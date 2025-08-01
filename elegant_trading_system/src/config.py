"""
Configuration for the Elegant Trading System
"""
from dataclasses import dataclass
from typing import List, Dict
import os
from decimal import Decimal


@dataclass
class TradingConfig:
    """Core trading parameters"""
    # Risk parameters
    base_risk_percent: Decimal = Decimal("0.0025")  # 0.25% per trade
    max_concurrent_positions: int = 10
    max_correlated_positions: int = 3
    correlation_threshold: float = 0.7
    
    # Signal parameters
    signal_strength_threshold: float = 2.5
    volume_velocity_threshold: float = 1.5
    vwap_distance_threshold: float = 0.005  # 0.5%
    
    # Risk management
    base_stop_atr_multiple: float = 0.75
    base_target_atr_multiple: float = 2.0
    
    # Regime-specific adjustments
    trending_adx_threshold: float = 25.0
    ranging_adx_threshold: float = 20.0
    high_volatility_atr_multiple: float = 2.0
    
    # Position sizing
    volatility_lookback_days: int = 30
    atr_period: int = 14
    
    # Execution
    primary_venue_allocation: float = 0.6
    secondary_venue_allocation: float = 0.3
    dark_pool_allocation: float = 0.1
    
    # Performance targets
    target_annual_return: float = 0.20  # 20%
    max_drawdown: float = 0.10  # 10%
    target_sharpe: float = 1.75


@dataclass
class MarketDataConfig:
    """Market data configuration"""
    orderbook_depth: int = 20
    update_frequency_ms: int = 100
    data_retention_hours: int = 24
    
    # Venues to monitor
    primary_venues: List[str] = None
    secondary_venues: List[str] = None
    
    def __post_init__(self):
        if self.primary_venues is None:
            self.primary_venues = ["binance", "coinbase"]
        if self.secondary_venues is None:
            self.secondary_venues = ["kraken", "bitstamp"]


@dataclass
class ExecutionConfig:
    """Execution configuration"""
    order_timeout_seconds: int = 5
    max_slippage_percent: float = 0.001  # 0.1%
    use_ioc_orders: bool = True
    
    # Smart routing
    enable_smart_routing: bool = True
    venue_latency_map: Dict[str, int] = None
    
    def __post_init__(self):
        if self.venue_latency_map is None:
            self.venue_latency_map = {
                "binance": 10,
                "coinbase": 15,
                "kraken": 20,
                "bitstamp": 25
            }


@dataclass
class SystemConfig:
    """Overall system configuration"""
    trading: TradingConfig
    market_data: MarketDataConfig
    execution: ExecutionConfig
    
    # System settings
    environment: str = os.getenv("TRADING_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Database
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    postgres_url: str = os.getenv("DATABASE_URL", "postgresql://localhost/trading")
    
    # API keys (loaded from environment)
    api_keys: Dict[str, Dict[str, str]] = None
    
    def __post_init__(self):
        if self.api_keys is None:
            self.api_keys = {
                "binance": {
                    "api_key": os.getenv("BINANCE_API_KEY", ""),
                    "secret": os.getenv("BINANCE_SECRET", "")
                },
                "coinbase": {
                    "api_key": os.getenv("COINBASE_API_KEY", ""),
                    "secret": os.getenv("COINBASE_SECRET", "")
                }
            }
    
    @classmethod
    def load_default(cls) -> "SystemConfig":
        """Load default configuration"""
        return cls(
            trading=TradingConfig(),
            market_data=MarketDataConfig(),
            execution=ExecutionConfig()
        )
    
    def validate(self) -> bool:
        """Validate configuration"""
        # Check risk parameters
        assert 0 < self.trading.base_risk_percent < Decimal("0.01"), "Base risk must be between 0-1%"
        assert self.trading.max_concurrent_positions > 0, "Must allow at least 1 position"
        
        # Check signal parameters
        assert self.trading.signal_strength_threshold > 1, "Signal threshold must be > 1"
        
        # Check execution
        assert 0 < self.execution.max_slippage_percent < 0.01, "Slippage limit must be reasonable"
        
        return True


# Global config instance
config = SystemConfig.load_default()