# Deconstruct-Reconstruct Trading Bot

An elegant trading system that ruthlessly analyzes trading strategies, extracts their best components, and reconstructs them into a beautiful, functional trading bot.

## Overview

This repository contains:
1. **Analysis of existing trading systems** - Deconstructed 6 systems, found mostly garbage
2. **The Elegant Strategy** - A microstructure momentum strategy built from first principles
3. **Live Trading System** - Ready-to-deploy bot using free APIs

## Quick Start - Live Trading

### Prerequisites
- KuCoin account with $100 USDT
- Python 3.8+

### Setup (5 minutes)

1. Clone the repository:
```bash
git clone https://github.com/LeBastrion/deconstruct-reconstruct-bot.git
cd deconstruct-reconstruct-bot/elegant_trading_system
```

2. Get KuCoin API credentials:
   - Login to KuCoin
   - Go to Account → API Management
   - Create API with "Trade" permission
   - Save your key, secret, and passphrase

3. Set environment variables:
```bash
export KUCOIN_API_KEY='your-api-key'
export KUCOIN_API_SECRET='your-api-secret'
export KUCOIN_API_PASSPHRASE='your-api-passphrase'
```

4. Run the bot:
```bash
./RUN_LIVE.sh
```

## The Strategy

**Core Philosophy**: Trade order flow momentum, not narratives.

- **Signal**: Order book imbalance × Volume velocity × Spread tightness
- **Risk**: 1% per trade with dynamic sizing
- **Execution**: Multi-venue smart routing (currently KuCoin only)
- **Data**: Free real-time from Binance WebSocket

## Project Structure

```
.
├── CLAUDE.md                    # AI assistant persona
├── ELEGANT_STRATEGY.md          # Complete strategy documentation
├── deconstructed_systems/       # Analysis of garbage systems
├── elegant_trading_system/      # The actual trading bot
│   ├── src/                     # Source code
│   ├── BUILD-DIARY.md          # Development log
│   ├── RUN_LIVE.sh             # Launch script
│   └── requirements_live.txt    # Dependencies
└── systems_to_deconstruct/      # Original whitepapers analyzed
```

## Performance Targets

- Annual Return: 15-25%
- Max Drawdown: 8-10%
- Sharpe Ratio: 1.5-2.0
- Win Rate: 55-60%

## Risk Warning

This bot trades with REAL MONEY. Start with only what you can afford to lose. The default configuration risks 1% ($1) per trade with $100 capital.

## Architecture

Unlike the analyzed systems full of buzzwords and fee extraction, this bot:
- Has a clear edge (order flow momentum)
- Implements proper risk management
- Executes with precision
- Works with free APIs
- No tokens, no governance, no BS

## Contributing

Feel free to submit PRs for:
- Additional free data sources
- More exchange integrations
- Risk management improvements
- Performance optimizations

## License

MIT License - Use at your own risk

---

Built by analyzing what doesn't work and creating what does.