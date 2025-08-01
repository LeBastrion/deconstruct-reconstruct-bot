"""
Portfolio Monitor - Correlation tracking and performance analytics
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import numpy as np
import pandas as pd
import structlog
from collections import defaultdict

from .risk_manager import Position

logger = structlog.get_logger()


@dataclass
class PerformanceMetrics:
    """Portfolio performance metrics"""
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    average_win: Decimal
    average_loss: Decimal
    total_trades: int
    

class PortfolioMonitor:
    """Monitor portfolio performance and correlations"""
    
    def __init__(self, initial_capital: Decimal):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.correlation_calculator = CorrelationCalculator()
        self.performance_tracker = PerformanceTracker(initial_capital)
        self.trade_history = []
        self.daily_returns = []
        
    def update_position(self, position: Position, current_price: float):
        """Update portfolio with position changes"""
        # Track unrealized P&L
        unrealized_pnl = position.current_pnl(current_price)
        
        # Update correlation data
        self.correlation_calculator.update_price(
            position.symbol, 
            current_price,
            datetime.now()
        )
        
    def record_trade(self, symbol: str, entry_price: float, exit_price: float,
                    quantity: Decimal, direction: str, entry_time: datetime,
                    exit_time: datetime):
        """Record completed trade"""
        if direction == "LONG":
            pnl = quantity * Decimal(str(exit_price - entry_price))
        else:
            pnl = quantity * Decimal(str(entry_price - exit_price))
        
        trade = {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'quantity': quantity,
            'direction': direction,
            'pnl': pnl,
            'return': float(pnl / (quantity * Decimal(str(entry_price)))),
            'entry_time': entry_time,
            'exit_time': exit_time,
            'duration': (exit_time - entry_time).total_seconds()
        }
        
        self.trade_history.append(trade)
        self.current_capital += pnl
        
        # Update performance tracker
        self.performance_tracker.add_trade(trade)
        
        logger.info(
            f"Trade recorded: {symbol} {direction} "
            f"P&L: {pnl:.2f} ({trade['return']:.2%})"
        )
    
    def get_correlation_matrix(self, symbols: List[str]) -> pd.DataFrame:
        """Get correlation matrix for given symbols"""
        return self.correlation_calculator.get_correlation_matrix(symbols)
    
    def get_performance_metrics(self) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics"""
        if not self.trade_history:
            return PerformanceMetrics(
                total_return=0.0,
                annualized_return=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                average_win=Decimal('0'),
                average_loss=Decimal('0'),
                total_trades=0
            )
        
        # Calculate returns
        total_return = float((self.current_capital - self.initial_capital) / self.initial_capital)
        
        # Annualized return (assuming 252 trading days)
        days_active = (datetime.now() - self.trade_history[0]['entry_time']).days
        if days_active > 0:
            annualized_return = (1 + total_return) ** (365 / days_active) - 1
        else:
            annualized_return = 0.0
        
        # Win rate and profit factor
        winning_trades = [t for t in self.trade_history if t['pnl'] > 0]
        losing_trades = [t for t in self.trade_history if t['pnl'] < 0]
        
        win_rate = len(winning_trades) / len(self.trade_history) if self.trade_history else 0
        
        total_wins = sum(t['pnl'] for t in winning_trades)
        total_losses = abs(sum(t['pnl'] for t in losing_trades))
        profit_factor = float(total_wins / total_losses) if total_losses > 0 else float('inf')
        
        average_win = total_wins / len(winning_trades) if winning_trades else Decimal('0')
        average_loss = total_losses / len(losing_trades) if losing_trades else Decimal('0')
        
        # Sharpe ratio
        sharpe = self._calculate_sharpe_ratio()
        
        # Max drawdown
        max_dd = self.performance_tracker.get_max_drawdown()
        
        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_win=average_win,
            average_loss=average_loss,
            total_trades=len(self.trade_history)
        )
    
    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio from trade history"""
        if len(self.trade_history) < 2:
            return 0.0
        
        # Group trades by day and calculate daily returns
        daily_pnl = defaultdict(Decimal)
        daily_capital = defaultdict(Decimal)
        
        for trade in self.trade_history:
            trade_date = trade['exit_time'].date()
            daily_pnl[trade_date] += trade['pnl']
        
        # Calculate daily returns
        dates = sorted(daily_pnl.keys())
        returns = []
        
        running_capital = self.initial_capital
        for date in dates:
            daily_return = float(daily_pnl[date] / running_capital)
            returns.append(daily_return)
            running_capital += daily_pnl[date]
        
        if not returns:
            return 0.0
        
        # Calculate Sharpe
        returns_array = np.array(returns)
        avg_return = np.mean(returns_array) * 252  # Annualized
        std_return = np.std(returns_array) * np.sqrt(252)  # Annualized
        
        if std_return == 0:
            return 0.0
        
        return (avg_return - risk_free_rate) / std_return
    
    def get_position_health(self, positions: Dict[str, Position],
                          current_prices: Dict[str, float]) -> Dict:
        """Analyze health of current positions"""
        if not positions:
            return {
                'healthy_positions': 0,
                'at_risk_positions': 0,
                'correlation_risk': 'LOW',
                'concentration_risk': 'LOW'
            }
        
        healthy = 0
        at_risk = 0
        
        for symbol, position in positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                pnl_percent = float(position.current_pnl(current_price) / 
                                  (position.position_size * Decimal(str(position.entry_price))))
                
                if pnl_percent > 0:
                    healthy += 1
                elif pnl_percent < -0.5:  # Down more than 50% of risk
                    at_risk += 1
        
        # Check correlation risk
        symbols = list(positions.keys())
        if len(symbols) > 1:
            corr_matrix = self.get_correlation_matrix(symbols)
            high_correlations = (corr_matrix > 0.7).sum().sum() - len(symbols)  # Exclude diagonal
            
            if high_correlations > len(symbols):
                correlation_risk = 'HIGH'
            elif high_correlations > len(symbols) // 2:
                correlation_risk = 'MEDIUM'
            else:
                correlation_risk = 'LOW'
        else:
            correlation_risk = 'LOW'
        
        # Check concentration risk
        position_values = [
            float(pos.position_size * Decimal(str(current_prices.get(sym, pos.entry_price))))
            for sym, pos in positions.items()
        ]
        
        if position_values:
            max_position = max(position_values)
            total_value = sum(position_values)
            max_concentration = max_position / total_value if total_value > 0 else 0
            
            if max_concentration > 0.3:  # Single position > 30%
                concentration_risk = 'HIGH'
            elif max_concentration > 0.2:
                concentration_risk = 'MEDIUM'
            else:
                concentration_risk = 'LOW'
        else:
            concentration_risk = 'LOW'
        
        return {
            'healthy_positions': healthy,
            'at_risk_positions': at_risk,
            'correlation_risk': correlation_risk,
            'concentration_risk': concentration_risk,
            'total_positions': len(positions)
        }
    
    def generate_report(self) -> str:
        """Generate performance report"""
        metrics = self.get_performance_metrics()
        
        report = f"""
Portfolio Performance Report
============================
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Returns
-------
Total Return: {metrics.total_return:.2%}
Annualized Return: {metrics.annualized_return:.2%}
Sharpe Ratio: {metrics.sharpe_ratio:.2f}
Max Drawdown: {metrics.max_drawdown:.2%}

Trading Statistics
------------------
Total Trades: {metrics.total_trades}
Win Rate: {metrics.win_rate:.2%}
Profit Factor: {metrics.profit_factor:.2f}
Average Win: {metrics.average_win:.2f}
Average Loss: {metrics.average_loss:.2f}

Risk Metrics
------------
Current Capital: {self.current_capital:.2f}
Capital at Risk: {self._calculate_capital_at_risk():.2%}
"""
        return report
    
    def _calculate_capital_at_risk(self) -> float:
        """Calculate percentage of capital at risk"""
        # Placeholder - would calculate from open positions
        return 0.05  # 5%


class CorrelationCalculator:
    """Calculate rolling correlations between assets"""
    
    def __init__(self, lookback_periods: int = 60):
        self.lookback_periods = lookback_periods
        self.price_history = {}  # {symbol: [(timestamp, price), ...]}
        
    def update_price(self, symbol: str, price: float, timestamp: datetime):
        """Update price history for correlation calculation"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        
        self.price_history[symbol].append((timestamp, price))
        
        # Keep only recent history
        cutoff = datetime.now() - timedelta(days=self.lookback_periods)
        self.price_history[symbol] = [
            (ts, p) for ts, p in self.price_history[symbol]
            if ts > cutoff
        ]
    
    def get_correlation_matrix(self, symbols: List[str]) -> pd.DataFrame:
        """Calculate correlation matrix for given symbols"""
        # Create price dataframe
        price_data = {}
        
        for symbol in symbols:
            if symbol in self.price_history:
                prices = self.price_history[symbol]
                if prices:
                    price_data[symbol] = pd.Series(
                        [p for _, p in prices],
                        index=[ts for ts, _ in prices]
                    )
        
        if len(price_data) < 2:
            return pd.DataFrame()
        
        # Align series and calculate returns
        df = pd.DataFrame(price_data)
        returns = df.pct_change().dropna()
        
        # Calculate correlation
        if len(returns) > 5:
            return returns.corr()
        else:
            # Not enough data - return identity matrix
            n = len(symbols)
            return pd.DataFrame(
                np.eye(n),
                index=symbols,
                columns=symbols
            )


class PerformanceTracker:
    """Track detailed performance metrics"""
    
    def __init__(self, initial_capital: Decimal):
        self.initial_capital = initial_capital
        self.equity_curve = [(datetime.now(), float(initial_capital))]
        self.peak_equity = float(initial_capital)
        self.max_drawdown = 0.0
        self.trade_durations = []
        
    def add_trade(self, trade: Dict):
        """Add trade to performance tracking"""
        # Update equity curve
        current_equity = self.equity_curve[-1][1] + float(trade['pnl'])
        self.equity_curve.append((trade['exit_time'], current_equity))
        
        # Update peak and drawdown
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        current_drawdown = (self.peak_equity - current_equity) / self.peak_equity
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
        
        # Track trade duration
        self.trade_durations.append(trade['duration'])
    
    def get_max_drawdown(self) -> float:
        """Get maximum drawdown percentage"""
        return self.max_drawdown
    
    def get_average_trade_duration(self) -> float:
        """Get average trade duration in hours"""
        if not self.trade_durations:
            return 0.0
        
        avg_seconds = np.mean(self.trade_durations)
        return avg_seconds / 3600  # Convert to hours
    
    def get_equity_curve(self) -> List[Tuple[datetime, float]]:
        """Get equity curve data"""
        return self.equity_curve.copy()