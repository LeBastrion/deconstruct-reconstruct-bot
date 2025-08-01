"""
Market Data Aggregator - Real-time order book aggregation across venues
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
import pandas as pd
from collections import defaultdict
import ccxt.async_support as ccxt
import structlog
from decimal import Decimal

logger = structlog.get_logger()


@dataclass
class OrderBookSnapshot:
    """Point-in-time order book data"""
    timestamp: datetime
    venue: str
    symbol: str
    bids: List[Tuple[float, float]]  # [(price, volume), ...]
    asks: List[Tuple[float, float]]
    mid_price: float
    spread: float
    bid_volume: float
    ask_volume: float
    
    @property
    def imbalance(self) -> float:
        """Calculate order book imbalance"""
        if self.ask_volume == 0:
            return float('inf')
        return self.bid_volume / self.ask_volume
    
    @property
    def weighted_mid_price(self) -> float:
        """Volume-weighted mid price"""
        if not self.bids or not self.asks:
            return self.mid_price
        
        best_bid_price, best_bid_vol = self.bids[0]
        best_ask_price, best_ask_vol = self.asks[0]
        
        total_vol = best_bid_vol + best_ask_vol
        if total_vol == 0:
            return self.mid_price
            
        return (best_bid_price * best_ask_vol + best_ask_price * best_bid_vol) / total_vol


class MarketDataAggregator:
    """Aggregates real-time order book data from multiple venues"""
    
    def __init__(self, config):
        self.config = config
        self.exchanges = {}
        self.orderbook_cache = defaultdict(dict)  # {symbol: {venue: snapshot}}
        self.volume_history = defaultdict(list)  # {symbol: [(timestamp, volume), ...]}
        self._running = False
        
    async def initialize(self):
        """Initialize exchange connections"""
        for venue in self.config.market_data.primary_venues + self.config.market_data.secondary_venues:
            try:
                if venue == "binance":
                    exchange = ccxt.binance({
                        'apiKey': self.config.api_keys[venue]['api_key'],
                        'secret': self.config.api_keys[venue]['secret'],
                        'enableRateLimit': True,
                        'options': {'defaultType': 'spot'}
                    })
                elif venue == "coinbase":
                    exchange = ccxt.coinbase({
                        'apiKey': self.config.api_keys[venue]['api_key'],
                        'secret': self.config.api_keys[venue]['secret'],
                        'enableRateLimit': True
                    })
                else:
                    logger.warning(f"Unsupported venue: {venue}")
                    continue
                    
                await exchange.load_markets()
                self.exchanges[venue] = exchange
                logger.info(f"Initialized {venue}")
                
            except Exception as e:
                logger.error(f"Failed to initialize {venue}: {e}")
    
    async def start(self, symbols: List[str]):
        """Start market data collection"""
        self._running = True
        tasks = []
        
        for symbol in symbols:
            for venue in self.exchanges:
                task = asyncio.create_task(
                    self._collect_orderbook_data(venue, symbol)
                )
                tasks.append(task)
        
        # Also start volume tracking
        tasks.append(asyncio.create_task(self._track_volume_velocity()))
        
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """Stop market data collection"""
        self._running = False
        
        for exchange in self.exchanges.values():
            await exchange.close()
    
    async def _collect_orderbook_data(self, venue: str, symbol: str):
        """Collect order book data for a specific venue/symbol"""
        exchange = self.exchanges[venue]
        
        while self._running:
            try:
                orderbook = await exchange.fetch_order_book(
                    symbol, 
                    limit=self.config.market_data.orderbook_depth
                )
                
                snapshot = self._process_orderbook(venue, symbol, orderbook)
                self.orderbook_cache[symbol][venue] = snapshot
                
                # Update volume history
                total_volume = snapshot.bid_volume + snapshot.ask_volume
                self.volume_history[symbol].append((datetime.now(), total_volume))
                
                # Keep only recent history
                cutoff_time = datetime.now().timestamp() - (20 * 60)  # 20 minutes
                self.volume_history[symbol] = [
                    (ts, vol) for ts, vol in self.volume_history[symbol]
                    if ts.timestamp() > cutoff_time
                ]
                
                await asyncio.sleep(self.config.market_data.update_frequency_ms / 1000)
                
            except Exception as e:
                logger.error(f"Error collecting {venue} {symbol}: {e}")
                await asyncio.sleep(1)
    
    def _process_orderbook(self, venue: str, symbol: str, orderbook: dict) -> OrderBookSnapshot:
        """Process raw orderbook into snapshot"""
        bids = [(float(price), float(volume)) for price, volume in orderbook['bids']]
        asks = [(float(price), float(volume)) for price, volume in orderbook['asks']]
        
        if not bids or not asks:
            raise ValueError("Empty orderbook")
        
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        
        bid_volume = sum(volume for _, volume in bids[:10])  # Top 10 levels
        ask_volume = sum(volume for _, volume in asks[:10])
        
        return OrderBookSnapshot(
            timestamp=datetime.now(),
            venue=venue,
            symbol=symbol,
            bids=bids,
            asks=asks,
            mid_price=(best_bid + best_ask) / 2,
            spread=best_ask - best_bid,
            bid_volume=bid_volume,
            ask_volume=ask_volume
        )
    
    async def _track_volume_velocity(self):
        """Track volume velocity across time windows"""
        while self._running:
            await asyncio.sleep(60)  # Update every minute
            
            for symbol in self.volume_history:
                volumes = self.volume_history[symbol]
                if len(volumes) > 1:
                    recent_vol = np.mean([vol for _, vol in volumes[-1:]])  # Last minute
                    avg_vol = np.mean([vol for _, vol in volumes])  # 20 min average
                    
                    if avg_vol > 0:
                        velocity = recent_vol / avg_vol
                        logger.debug(f"{symbol} volume velocity: {velocity:.2f}")
    
    def get_aggregated_orderbook(self, symbol: str) -> Optional[OrderBookSnapshot]:
        """Get aggregated orderbook across all venues"""
        if symbol not in self.orderbook_cache:
            return None
        
        snapshots = list(self.orderbook_cache[symbol].values())
        if not snapshots:
            return None
        
        # Aggregate all bids and asks
        all_bids = []
        all_asks = []
        
        for snapshot in snapshots:
            all_bids.extend(snapshot.bids)
            all_asks.extend(snapshot.asks)
        
        # Sort and aggregate by price level
        bid_levels = defaultdict(float)
        ask_levels = defaultdict(float)
        
        for price, volume in all_bids:
            bid_levels[price] += volume
            
        for price, volume in all_asks:
            ask_levels[price] += volume
        
        # Convert back to sorted lists
        sorted_bids = sorted(bid_levels.items(), reverse=True)[:self.config.market_data.orderbook_depth]
        sorted_asks = sorted(ask_levels.items())[:self.config.market_data.orderbook_depth]
        
        if not sorted_bids or not sorted_asks:
            return None
        
        best_bid = sorted_bids[0][0]
        best_ask = sorted_asks[0][0]
        
        bid_volume = sum(volume for _, volume in sorted_bids[:10])
        ask_volume = sum(volume for _, volume in sorted_asks[:10])
        
        return OrderBookSnapshot(
            timestamp=datetime.now(),
            venue="aggregated",
            symbol=symbol,
            bids=sorted_bids,
            asks=sorted_asks,
            mid_price=(best_bid + best_ask) / 2,
            spread=best_ask - best_bid,
            bid_volume=bid_volume,
            ask_volume=ask_volume
        )
    
    def get_volume_velocity(self, symbol: str) -> float:
        """Calculate current volume velocity"""
        if symbol not in self.volume_history:
            return 0.0
        
        volumes = self.volume_history[symbol]
        if len(volumes) < 2:
            return 1.0
        
        # Last 1 minute vs 20 minute average
        now = datetime.now().timestamp()
        recent_vols = [vol for ts, vol in volumes if now - ts.timestamp() < 60]
        all_vols = [vol for _, vol in volumes]
        
        if not recent_vols or not all_vols:
            return 1.0
        
        recent_avg = np.mean(recent_vols)
        total_avg = np.mean(all_vols)
        
        if total_avg == 0:
            return 1.0
            
        return recent_avg / total_avg
    
    def get_spread_tightness(self, symbol: str) -> float:
        """Calculate spread tightness metric"""
        orderbook = self.get_aggregated_orderbook(symbol)
        if not orderbook:
            return 0.0
        
        # Get historical spreads
        historical_spreads = []
        for snapshot in self.orderbook_cache[symbol].values():
            historical_spreads.append(snapshot.spread)
        
        if not historical_spreads:
            return 1.0
        
        avg_spread = np.mean(historical_spreads)
        if avg_spread == 0:
            return 1.0
        
        # Tighter spread = higher value
        return avg_spread / orderbook.spread if orderbook.spread > 0 else 1.0