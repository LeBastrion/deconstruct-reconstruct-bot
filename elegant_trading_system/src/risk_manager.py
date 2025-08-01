"""
Risk Manager - Position sizing, stop loss, and portfolio risk management
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import numpy as np
import pandas as pd
import structlog
from enum import Enum

from .signal_engine import TradingSignal, SignalDirection

logger = structlog.get_logger()


class MarketRegime(Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


@dataclass
class RiskParameters:
    """Risk parameters for a position"""
    position_size: Decimal
    stop_loss_price: float
    take_profit_price: float
    max_loss_amount: Decimal
    risk_reward_ratio: float
    
    
@dataclass
class Position:
    """Active trading position"""
    symbol: str
    direction: SignalDirection
    entry_price: float
    position_size: Decimal
    stop_loss: float
    take_profit: float
    entry_time: datetime
    venue: str
    
    @property
    def current_pnl(self, current_price: float) -> Decimal:
        """Calculate current P&L"""
        if self.direction == SignalDirection.LONG:
            return self.position_size * Decimal(str(current_price - self.entry_price))
        else:
            return self.position_size * Decimal(str(self.entry_price - current_price))
    
    @property
    def risk_amount(self) -> Decimal:
        """Maximum risk for this position"""
        if self.direction == SignalDirection.LONG:
            return self.position_size * Decimal(str(self.entry_price - self.stop_loss))
        else:
            return self.position_size * Decimal(str(self.stop_loss - self.entry_price))


class RiskManager:
    """Manages position sizing, stops, and portfolio risk"""
    
    def __init__(self, config, initial_capital: Decimal):
        self.config = config
        self.capital = initial_capital
        self.positions: Dict[str, Position] = {}
        self.realized_pnl = Decimal('0')
        self.atr_calculator = ATRCalculator(period=config.trading.atr_period)
        self.regime_detector = RegimeDetector()
        self.drawdown_tracker = DrawdownTracker(initial_capital)
        
    def calculate_position_parameters(self, signal: TradingSignal, 
                                    current_price: float) -> Optional[RiskParameters]:
        """Calculate position size and risk parameters"""
        try:
            # Check if we can take new positions
            if not self._can_open_position(signal.symbol):
                logger.info(f"Cannot open position for {signal.symbol} - risk limits")
                return None
            
            # Get market regime and ATR
            atr = self.atr_calculator.get_atr(signal.symbol)
            if not atr:
                logger.warning(f"No ATR available for {signal.symbol}")
                return None
            
            regime = self.regime_detector.get_regime(signal.symbol)
            
            # Calculate volatility adjustment
            current_iv = self._estimate_implied_volatility(signal.symbol)
            historical_iv = self.atr_calculator.get_historical_volatility(signal.symbol)
            volatility_multiplier = current_iv / historical_iv if historical_iv > 0 else 1.0
            
            # Base position size calculation
            risk_amount = self.capital * self.config.trading.base_risk_percent
            
            # Adjust for regime
            if regime == MarketRegime.VOLATILE:
                risk_amount *= Decimal('0.5')  # Reduce risk in volatile markets
            elif regime == MarketRegime.RANGING:
                risk_amount *= Decimal('0.7')  # Slightly reduce in ranging markets
            
            # Calculate stop loss distance
            stop_distance = self._calculate_stop_distance(atr, regime)
            
            # Position size = Risk Amount / Stop Distance
            position_size = risk_amount / Decimal(str(stop_distance))
            
            # Apply volatility adjustment
            position_size = position_size / Decimal(str(volatility_multiplier))
            
            # Calculate stop and target prices
            if signal.direction == SignalDirection.LONG:
                stop_loss_price = current_price - stop_distance
                take_profit_price = current_price + self._calculate_target_distance(atr, regime)
            else:
                stop_loss_price = current_price + stop_distance
                take_profit_price = current_price - self._calculate_target_distance(atr, regime)
            
            # Ensure minimum risk/reward ratio
            risk = abs(current_price - stop_loss_price)
            reward = abs(take_profit_price - current_price)
            risk_reward_ratio = reward / risk if risk > 0 else 0
            
            if risk_reward_ratio < 1.5:
                logger.info(f"Skipping {signal.symbol} - insufficient risk/reward: {risk_reward_ratio:.2f}")
                return None
            
            return RiskParameters(
                position_size=position_size,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                max_loss_amount=risk_amount,
                risk_reward_ratio=risk_reward_ratio
            )
            
        except Exception as e:
            logger.error(f"Error calculating position parameters: {e}")
            return None
    
    def _can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position"""
        # Check max positions
        if len(self.positions) >= self.config.trading.max_concurrent_positions:
            return False
        
        # Check if already have position in symbol
        if symbol in self.positions:
            return False
        
        # Check drawdown limits
        if self.drawdown_tracker.get_current_drawdown() > self.config.trading.max_drawdown:
            logger.warning("Max drawdown reached - no new positions")
            return False
        
        # Check correlation limits
        correlated_count = self._count_correlated_positions(symbol)
        if correlated_count >= self.config.trading.max_correlated_positions:
            return False
        
        return True
    
    def _calculate_stop_distance(self, atr: float, regime: MarketRegime) -> float:
        """Calculate stop loss distance based on ATR and regime"""
        base_multiple = self.config.trading.base_stop_atr_multiple
        
        if regime == MarketRegime.TRENDING:
            # Wider stops in trends
            return atr * 1.0
        elif regime == MarketRegime.VOLATILE:
            # Tighter stops in volatile markets
            return atr * 0.5
        else:  # RANGING
            # Normal stops
            return atr * base_multiple
    
    def _calculate_target_distance(self, atr: float, regime: MarketRegime) -> float:
        """Calculate take profit distance based on ATR and regime"""
        base_multiple = self.config.trading.base_target_atr_multiple
        
        if regime == MarketRegime.TRENDING:
            # Larger targets in trends
            return atr * 3.0
        elif regime == MarketRegime.VOLATILE:
            # Smaller targets in volatile markets
            return atr * 1.5
        else:  # RANGING
            # Normal targets
            return atr * base_multiple
    
    def _estimate_implied_volatility(self, symbol: str) -> float:
        """Estimate current implied volatility from price action"""
        # Simplified IV estimation using recent price movements
        # In production, would use options data or more sophisticated models
        recent_atr = self.atr_calculator.get_atr(symbol)
        if recent_atr:
            return recent_atr * np.sqrt(252)  # Annualized
        return 0.5  # Default 50% IV
    
    def _count_correlated_positions(self, symbol: str) -> int:
        """Count positions in correlated assets"""
        # In production, would use actual correlation matrix
        # For now, use simple sector-based correlation
        correlated = 0
        
        for pos_symbol in self.positions:
            if self._are_correlated(symbol, pos_symbol):
                correlated += 1
        
        return correlated
    
    def _are_correlated(self, symbol1: str, symbol2: str) -> bool:
        """Check if two symbols are correlated"""
        # Simplified correlation check
        # In production, would use rolling correlation calculations
        
        # Same base currency = correlated
        base1 = symbol1.split('/')[0] if '/' in symbol1 else symbol1[:3]
        base2 = symbol2.split('/')[0] if '/' in symbol2 else symbol2[:3]
        
        return base1 == base2
    
    def open_position(self, symbol: str, signal: TradingSignal, 
                     risk_params: RiskParameters, fill_price: float,
                     venue: str) -> Position:
        """Open a new position"""
        position = Position(
            symbol=symbol,
            direction=signal.direction,
            entry_price=fill_price,
            position_size=risk_params.position_size,
            stop_loss=risk_params.stop_loss_price,
            take_profit=risk_params.take_profit_price,
            entry_time=datetime.now(),
            venue=venue
        )
        
        self.positions[symbol] = position
        logger.info(f"Opened {signal.direction.value} position in {symbol} at {fill_price}")
        
        return position
    
    def close_position(self, symbol: str, exit_price: float) -> Optional[Decimal]:
        """Close a position and return P&L"""
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        pnl = position.current_pnl(exit_price)
        
        self.realized_pnl += pnl
        self.capital += pnl
        
        del self.positions[symbol]
        
        logger.info(f"Closed {symbol} position at {exit_price}, P&L: {pnl}")
        
        # Update drawdown tracker
        self.drawdown_tracker.update(self.capital)
        
        return pnl
    
    def check_stops(self, current_prices: Dict[str, float]) -> List[str]:
        """Check if any positions hit their stops"""
        positions_to_close = []
        
        for symbol, position in self.positions.items():
            if symbol not in current_prices:
                continue
            
            current_price = current_prices[symbol]
            
            # Check stop loss
            if position.direction == SignalDirection.LONG:
                if current_price <= position.stop_loss:
                    positions_to_close.append(symbol)
                    logger.info(f"Stop loss hit for {symbol}")
            else:
                if current_price >= position.stop_loss:
                    positions_to_close.append(symbol)
                    logger.info(f"Stop loss hit for {symbol}")
            
            # Check take profit
            if position.direction == SignalDirection.LONG:
                if current_price >= position.take_profit:
                    positions_to_close.append(symbol)
                    logger.info(f"Take profit hit for {symbol}")
            else:
                if current_price <= position.take_profit:
                    positions_to_close.append(symbol)
                    logger.info(f"Take profit hit for {symbol}")
        
        return positions_to_close
    
    def get_portfolio_stats(self) -> Dict:
        """Get current portfolio statistics"""
        total_risk = Decimal('0')
        unrealized_pnl = Decimal('0')
        
        for position in self.positions.values():
            total_risk += position.risk_amount
            # Would need current prices for unrealized P&L
        
        return {
            'capital': self.capital,
            'positions': len(self.positions),
            'total_risk': total_risk,
            'risk_percentage': (total_risk / self.capital * 100) if self.capital > 0 else 0,
            'realized_pnl': self.realized_pnl,
            'current_drawdown': self.drawdown_tracker.get_current_drawdown(),
            'max_drawdown': self.drawdown_tracker.max_drawdown
        }


class ATRCalculator:
    """Calculate Average True Range for volatility measurement"""
    
    def __init__(self, period: int = 14):
        self.period = period
        self.price_history = {}  # {symbol: [(high, low, close, timestamp), ...]}
        self.atr_values = {}  # {symbol: [atr_values]}
        
    def update(self, symbol: str, high: float, low: float, close: float):
        """Update ATR calculation with new price data"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []
            self.atr_values[symbol] = []
        
        self.price_history[symbol].append((high, low, close, datetime.now()))
        
        # Keep only recent data
        max_periods = self.period * 10
        if len(self.price_history[symbol]) > max_periods:
            self.price_history[symbol] = self.price_history[symbol][-max_periods:]
        
        # Calculate ATR if we have enough data
        if len(self.price_history[symbol]) >= 2:
            atr = self._calculate_atr(symbol)
            if atr:
                self.atr_values[symbol].append(atr)
                if len(self.atr_values[symbol]) > max_periods:
                    self.atr_values[symbol] = self.atr_values[symbol][-max_periods:]
    
    def _calculate_atr(self, symbol: str) -> Optional[float]:
        """Calculate current ATR value"""
        history = self.price_history[symbol]
        if len(history) < self.period:
            return None
        
        true_ranges = []
        
        for i in range(1, len(history)):
            high = history[i][0]
            low = history[i][1]
            prev_close = history[i-1][2]
            
            true_range = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(true_range)
        
        if len(true_ranges) >= self.period:
            return np.mean(true_ranges[-self.period:])
        
        return None
    
    def get_atr(self, symbol: str) -> Optional[float]:
        """Get current ATR value"""
        if symbol in self.atr_values and self.atr_values[symbol]:
            return self.atr_values[symbol][-1]
        return None
    
    def get_historical_volatility(self, symbol: str, periods: int = 30) -> float:
        """Calculate historical volatility"""
        if symbol not in self.price_history:
            return 0.5
        
        closes = [data[2] for data in self.price_history[symbol][-periods:]]
        
        if len(closes) < 2:
            return 0.5
        
        returns = np.diff(np.log(closes))
        return np.std(returns) * np.sqrt(252)  # Annualized


class RegimeDetector:
    """Detect market regime (trending, ranging, volatile)"""
    
    def __init__(self):
        self.adx_calculator = ADXCalculator()
        self.regime_history = {}
        
    def get_regime(self, symbol: str) -> MarketRegime:
        """Determine current market regime"""
        adx = self.adx_calculator.get_adx(symbol)
        atr_spike = self._check_volatility_spike(symbol)
        
        if atr_spike:
            return MarketRegime.VOLATILE
        elif adx and adx > 25:
            return MarketRegime.TRENDING
        elif adx and adx < 20:
            return MarketRegime.RANGING
        else:
            return MarketRegime.RANGING  # Default
    
    def _check_volatility_spike(self, symbol: str) -> bool:
        """Check if volatility has spiked recently"""
        # Simplified check - in production would use more sophisticated methods
        return False


class ADXCalculator:
    """Calculate Average Directional Index for trend strength"""
    
    def __init__(self, period: int = 14):
        self.period = period
        self.adx_values = {}
        
    def get_adx(self, symbol: str) -> Optional[float]:
        """Get current ADX value"""
        # Simplified - returns mock values
        # In production, would calculate from price data
        return 22.0  # Default moderate trend strength


class DrawdownTracker:
    """Track portfolio drawdowns"""
    
    def __init__(self, initial_capital: Decimal):
        self.initial_capital = initial_capital
        self.peak_capital = initial_capital
        self.max_drawdown = 0.0
        
    def update(self, current_capital: Decimal):
        """Update drawdown calculations"""
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
        
        current_drawdown = float((self.peak_capital - current_capital) / self.peak_capital)
        
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
    
    def get_current_drawdown(self) -> float:
        """Get current drawdown percentage"""
        return self.max_drawdown