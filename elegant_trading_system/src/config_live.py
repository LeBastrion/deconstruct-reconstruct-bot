"""
Live Trading Configuration - Minimal for immediate deployment
"""
from decimal import Decimal
import os


class LiveConfig:
    """Minimal config for live trading"""
    
    # KuCoin API credentials (to be set via environment)
    KUCOIN_API_KEY = os.getenv('KUCOIN_API_KEY', '')
    KUCOIN_API_SECRET = os.getenv('KUCOIN_API_SECRET', '')
    KUCOIN_API_PASSPHRASE = os.getenv('KUCOIN_API_PASSPHRASE', '')
    
    # Trading parameters - AGGRESSIVE for quick results
    SYMBOLS = ['BTC/USDT', 'ETH/USDT']  # Most liquid pairs
    
    # Risk - Start conservative
    INITIAL_CAPITAL = Decimal('100')  # $100 USDT
    RISK_PER_TRADE = Decimal('0.01')  # 1% per trade = $1 risk
    MAX_POSITIONS = 2  # One per symbol max
    
    # Signals - More aggressive for action
    SIGNAL_STRENGTH_THRESHOLD = 2.0  # Lower threshold for more signals
    VOLUME_VELOCITY_THRESHOLD = 1.3  # Lower for more signals
    VWAP_DISTANCE_THRESHOLD = 0.01  # 1% from VWAP
    
    # Execution
    USE_MARKET_ORDERS = True  # Immediate fills
    
    # Stop/Target - Tighter for quick trades
    STOP_ATR_MULTIPLE = 0.5  # Tight stop
    TARGET_ATR_MULTIPLE = 1.5  # Quick profit target
    
    # Monitoring
    LOG_LEVEL = "INFO"
    REPORT_INTERVAL_SECONDS = 60  # Report every minute