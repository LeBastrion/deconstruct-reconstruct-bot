"""
Signal Engine - Order flow momentum signal generation
"""
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
import pandas as pd
import structlog
from enum import Enum

from .market_data import MarketDataAggregator, OrderBookSnapshot

logger = structlog.get_logger()


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class TradingSignal:
    """Trading signal with all relevant metrics"""
    timestamp: datetime
    symbol: str
    direction: SignalDirection
    strength: float
    
    # Components
    orderbook_imbalance: float
    volume_velocity: float
    spread_tightness: float
    distance_from_vwap: float
    
    # Confidence metrics
    confidence: float  # 0-1 score
    venues_agreeing: int  # Number of venues showing same signal
    
    def is_actionable(self, config) -> bool:
        """Check if signal meets all entry criteria"""
        return (
            self.strength > config.trading.signal_strength_threshold and
            self.volume_velocity > config.trading.volume_velocity_threshold and
            abs(self.distance_from_vwap) < config.trading.vwap_distance_threshold
        )


class SignalEngine:
    """Generates trading signals from order flow momentum"""
    
    def __init__(self, market_data: MarketDataAggregator, config):
        self.market_data = market_data
        self.config = config
        self.vwap_calculator = VWAPCalculator()
        self.signal_history = {}  # {symbol: [signals]}
        
    def generate_signal(self, symbol: str) -> Optional[TradingSignal]:
        """Generate trading signal for a symbol"""
        try:
            # Get aggregated orderbook
            orderbook = self.market_data.get_aggregated_orderbook(symbol)
            if not orderbook:
                return None
            
            # Calculate signal components
            imbalance = orderbook.imbalance
            velocity = self.market_data.get_volume_velocity(symbol)
            tightness = self.market_data.get_spread_tightness(symbol)
            
            # Get VWAP
            vwap = self.vwap_calculator.get_vwap(symbol)
            if vwap:
                distance_from_vwap = (orderbook.mid_price - vwap) / vwap
            else:
                distance_from_vwap = 0.0
            
            # Calculate signal strength
            signal_strength = imbalance * velocity * tightness
            
            # Determine direction
            if signal_strength > self.config.trading.signal_strength_threshold:
                if imbalance > 1.5:  # More bids than asks
                    direction = SignalDirection.LONG
                elif imbalance < 0.67:  # More asks than bids (1/1.5)
                    direction = SignalDirection.SHORT
                else:
                    direction = SignalDirection.NEUTRAL
            else:
                direction = SignalDirection.NEUTRAL
            
            # Calculate confidence based on venue agreement
            venues_agreeing = self._count_agreeing_venues(symbol, direction)
            total_venues = len(self.market_data.orderbook_cache[symbol])
            confidence = venues_agreeing / total_venues if total_venues > 0 else 0
            
            signal = TradingSignal(
                timestamp=datetime.now(),
                symbol=symbol,
                direction=direction,
                strength=signal_strength,
                orderbook_imbalance=imbalance,
                volume_velocity=velocity,
                spread_tightness=tightness,
                distance_from_vwap=distance_from_vwap,
                confidence=confidence,
                venues_agreeing=venues_agreeing
            )
            
            # Store in history
            if symbol not in self.signal_history:
                self.signal_history[symbol] = []
            self.signal_history[symbol].append(signal)
            
            # Keep only recent history (last hour)
            cutoff = datetime.now().timestamp() - 3600
            self.signal_history[symbol] = [
                s for s in self.signal_history[symbol] 
                if s.timestamp.timestamp() > cutoff
            ]
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return None
    
    def _count_agreeing_venues(self, symbol: str, direction: SignalDirection) -> int:
        """Count how many venues show the same signal direction"""
        agreeing = 0
        
        for venue, snapshot in self.market_data.orderbook_cache[symbol].items():
            venue_imbalance = snapshot.imbalance
            
            if direction == SignalDirection.LONG and venue_imbalance > 1.5:
                agreeing += 1
            elif direction == SignalDirection.SHORT and venue_imbalance < 0.67:
                agreeing += 1
            elif direction == SignalDirection.NEUTRAL:
                agreeing += 1
        
        return agreeing
    
    def get_signal_quality_score(self, signal: TradingSignal) -> float:
        """Calculate signal quality score for ranking multiple signals"""
        # Weight different components
        strength_weight = 0.4
        confidence_weight = 0.3
        vwap_weight = 0.2
        spread_weight = 0.1
        
        # Normalize components
        strength_score = min(signal.strength / 5.0, 1.0)  # Cap at 5.0
        vwap_score = 1.0 - min(abs(signal.distance_from_vwap) / 0.01, 1.0)  # Better if closer to VWAP
        spread_score = min(signal.spread_tightness / 2.0, 1.0)  # Higher is better
        
        quality = (
            strength_score * strength_weight +
            signal.confidence * confidence_weight +
            vwap_score * vwap_weight +
            spread_score * spread_weight
        )
        
        return quality
    
    def filter_correlated_signals(self, signals: List[TradingSignal], 
                                correlation_matrix: pd.DataFrame) -> List[TradingSignal]:
        """Filter out highly correlated signals to avoid concentration risk"""
        if len(signals) <= 1:
            return signals
        
        # Sort by quality
        sorted_signals = sorted(
            signals, 
            key=lambda s: self.get_signal_quality_score(s),
            reverse=True
        )
        
        selected = []
        
        for signal in sorted_signals:
            # Check correlation with already selected signals
            is_correlated = False
            
            for selected_signal in selected:
                if signal.symbol in correlation_matrix.index and \
                   selected_signal.symbol in correlation_matrix.columns:
                    
                    correlation = correlation_matrix.loc[signal.symbol, selected_signal.symbol]
                    if abs(correlation) > self.config.trading.correlation_threshold:
                        is_correlated = True
                        break
            
            if not is_correlated:
                selected.append(signal)
                
                # Stop if we have enough uncorrelated positions
                if len(selected) >= self.config.trading.max_concurrent_positions:
                    break
        
        return selected


class VWAPCalculator:
    """Calculate Volume Weighted Average Price"""
    
    def __init__(self):
        self.vwap_data = {}  # {symbol: {'prices': [], 'volumes': [], 'timestamps': []}}
        
    def update(self, symbol: str, price: float, volume: float):
        """Update VWAP calculation with new trade"""
        if symbol not in self.vwap_data:
            self.vwap_data[symbol] = {
                'prices': [],
                'volumes': [],
                'timestamps': []
            }
        
        data = self.vwap_data[symbol]
        now = datetime.now()
        
        data['prices'].append(price)
        data['volumes'].append(volume)
        data['timestamps'].append(now)
        
        # Keep only data from current trading session (last 8 hours)
        cutoff = now.timestamp() - (8 * 3600)
        
        valid_indices = [
            i for i, ts in enumerate(data['timestamps'])
            if ts.timestamp() > cutoff
        ]
        
        if valid_indices:
            data['prices'] = [data['prices'][i] for i in valid_indices]
            data['volumes'] = [data['volumes'][i] for i in valid_indices]
            data['timestamps'] = [data['timestamps'][i] for i in valid_indices]
    
    def get_vwap(self, symbol: str) -> Optional[float]:
        """Calculate current VWAP"""
        if symbol not in self.vwap_data:
            return None
        
        data = self.vwap_data[symbol]
        if not data['prices']:
            return None
        
        prices = np.array(data['prices'])
        volumes = np.array(data['volumes'])
        
        if volumes.sum() == 0:
            return None
        
        return (prices * volumes).sum() / volumes.sum()
    
    def get_vwap_bands(self, symbol: str, num_std: float = 2.0) -> Optional[Tuple[float, float, float]]:
        """Get VWAP with upper and lower bands"""
        vwap = self.get_vwap(symbol)
        if not vwap:
            return None
        
        data = self.vwap_data[symbol]
        prices = np.array(data['prices'])
        volumes = np.array(data['volumes'])
        
        # Calculate volume-weighted standard deviation
        deviations = prices - vwap
        weighted_var = (deviations ** 2 * volumes).sum() / volumes.sum()
        std_dev = np.sqrt(weighted_var)
        
        upper_band = vwap + (num_std * std_dev)
        lower_band = vwap - (num_std * std_dev)
        
        return lower_band, vwap, upper_band