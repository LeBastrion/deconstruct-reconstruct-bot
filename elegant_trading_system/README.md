# Elegant Trading System

A microstructure momentum trading system that exploits order flow imbalances with ruthless risk management.

## Philosophy

Markets exhibit persistent microstructure patterns driven by order flow mechanics. This system trades those patterns with precision timing and disciplined risk management.

## Core Components

### 1. **Market Data Aggregator** (`market_data.py`)
- Real-time order book aggregation across venues
- Volume velocity tracking
- Spread analysis

### 2. **Signal Engine** (`signal_engine.py`)
- Order flow momentum signals
- Multi-venue confirmation
- VWAP-relative positioning

### 3. **Risk Manager** (`risk_manager.py`)
- Dynamic position sizing based on ATR and volatility
- Regime-adaptive stop losses
- Portfolio concentration limits

### 4. **Execution Engine** (`execution_engine.py`)
- Smart order routing across venues
- IOC orders to avoid adverse selection
- Slippage minimization

### 5. **Portfolio Monitor** (`portfolio_monitor.py`)
- Real-time correlation tracking
- Performance analytics
- Risk exposure monitoring

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BINANCE_API_KEY="your_key"
export BINANCE_SECRET="your_secret"
export COINBASE_API_KEY="your_key"
export COINBASE_SECRET="your_secret"

# Run the system
python -m elegant_trading_system.src.main
```

## Configuration

Edit `src/config.py` to adjust:
- Risk parameters (position sizing, max positions)
- Signal thresholds
- Execution settings
- Market regimes

## Performance Targets

- **Annual Return**: 15-25%
- **Max Drawdown**: 8-10%
- **Sharpe Ratio**: 1.5-2.0
- **Win Rate**: 55-60%

## Risk Management

The system implements multiple layers of risk control:
1. Position-level stops (0.75 ATR)
2. Portfolio-level exposure limits
3. Correlation-based position filtering
4. Regime-adaptive sizing

## Why It Works

Unlike the garbage systems analyzed, this strategy:
- Has a clear edge (order flow momentum)
- Implements proper risk management
- Executes with precision
- Scales elegantly
- Keeps it simple

No tokens. No governance. No AI buzzwords. Just mechanical edge execution.