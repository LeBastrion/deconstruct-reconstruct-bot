"""
Elegant Trading System - Microstructure Momentum Trading
"""
from .main import ElegantTradingSystem, main
from .config import SystemConfig, TradingConfig
from .signal_engine import TradingSignal, SignalDirection
from .risk_manager import RiskManager, Position
from .market_data import MarketDataAggregator
from .execution_engine import ExecutionEngine, ExecutionResult
from .portfolio_monitor import PortfolioMonitor, PerformanceMetrics

__version__ = "1.0.0"
__all__ = [
    "ElegantTradingSystem",
    "SystemConfig",
    "TradingConfig",
    "TradingSignal",
    "SignalDirection",
    "RiskManager",
    "Position",
    "MarketDataAggregator",
    "ExecutionEngine",
    "ExecutionResult",
    "PortfolioMonitor",
    "PerformanceMetrics",
    "main"
]