"""
Free Market Data - Binance public WebSocket (no auth required)
"""
import asyncio
import json
import websockets
from typing import Dict, List, Optional, Callable
from datetime import datetime
import numpy as np
from collections import defaultdict
import structlog

from .market_data import OrderBookSnapshot

logger = structlog.get_logger()


class FreeMarketData:
    """Free market data from Binance public WebSocket"""
    
    def __init__(self):
        self.orderbook_cache = {}  # {symbol: OrderBookSnapshot}
        self.volume_history = defaultdict(list)
        self.ws_connections = {}
        self._running = False
        
    async def start(self, symbols: List[str]):
        """Start free market data collection"""
        self._running = True
        
        # Convert symbols to Binance format
        binance_symbols = [self._convert_symbol(s) for s in symbols]
        
        tasks = []
        for symbol, binance_symbol in zip(symbols, binance_symbols):
            task = asyncio.create_task(
                self._connect_orderbook_stream(symbol, binance_symbol)
            )
            tasks.append(task)
            
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """Stop market data collection"""
        self._running = False
        
        for ws in self.ws_connections.values():
            await ws.close()
    
    def _convert_symbol(self, symbol: str) -> str:
        """Convert from standard to Binance format"""
        # BTC/USDT -> btcusdt
        return symbol.replace('/', '').lower()
    
    async def _connect_orderbook_stream(self, symbol: str, binance_symbol: str):
        """Connect to Binance order book stream"""
        url = f"wss://stream.binance.com:9443/ws/{binance_symbol}@depth20@100ms"
        
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    self.ws_connections[symbol] = ws
                    logger.info(f"Connected to Binance stream for {symbol}")
                    
                    async for message in ws:
                        if not self._running:
                            break
                            
                        data = json.loads(message)
                        self._process_orderbook_update(symbol, data)
                        
            except Exception as e:
                logger.error(f"WebSocket error for {symbol}: {e}")
                await asyncio.sleep(5)  # Reconnect after 5 seconds
    
    def _process_orderbook_update(self, symbol: str, data: dict):
        """Process order book update from Binance"""
        try:
            bids = [(float(price), float(qty)) for price, qty in data['bids']]
            asks = [(float(price), float(qty)) for price, qty in data['asks']]
            
            if not bids or not asks:
                return
            
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            
            # Calculate volumes (top 10 levels)
            bid_volume = sum(qty for _, qty in bids[:10])
            ask_volume = sum(qty for _, qty in asks[:10])
            
            snapshot = OrderBookSnapshot(
                timestamp=datetime.now(),
                venue="binance",
                symbol=symbol,
                bids=bids,
                asks=asks,
                mid_price=(best_bid + best_ask) / 2,
                spread=best_ask - best_bid,
                bid_volume=bid_volume,
                ask_volume=ask_volume
            )
            
            self.orderbook_cache[symbol] = snapshot
            
            # Update volume history
            total_volume = bid_volume + ask_volume
            self.volume_history[symbol].append((datetime.now(), total_volume))
            
            # Keep only last 20 minutes
            cutoff = datetime.now().timestamp() - (20 * 60)
            self.volume_history[symbol] = [
                (ts, vol) for ts, vol in self.volume_history[symbol]
                if ts.timestamp() > cutoff
            ]
            
        except Exception as e:
            logger.error(f"Error processing orderbook for {symbol}: {e}")
    
    def get_orderbook(self, symbol: str) -> Optional[OrderBookSnapshot]:
        """Get latest order book for symbol"""
        return self.orderbook_cache.get(symbol)
    
    def get_volume_velocity(self, symbol: str) -> float:
        """Calculate volume velocity"""
        if symbol not in self.volume_history or len(self.volume_history[symbol]) < 2:
            return 1.0
        
        volumes = self.volume_history[symbol]
        now = datetime.now().timestamp()
        
        # Last 1 minute
        recent_vols = [vol for ts, vol in volumes if now - ts.timestamp() < 60]
        # 20 minute average
        all_vols = [vol for _, vol in volumes]
        
        if not recent_vols or not all_vols:
            return 1.0
        
        recent_avg = np.mean(recent_vols)
        total_avg = np.mean(all_vols)
        
        return recent_avg / total_avg if total_avg > 0 else 1.0
    
    def get_spread_tightness(self, symbol: str) -> float:
        """Calculate spread tightness"""
        current = self.get_orderbook(symbol)
        if not current:
            return 1.0
        
        # Get historical spreads from last 5 minutes
        historical_spreads = []
        
        # Since we only have current snapshot, use a rolling average
        # In production, would store historical snapshots
        avg_spread = current.spread * 1.2  # Assume 20% wider on average
        
        if current.spread > 0:
            return avg_spread / current.spread
        
        return 1.0