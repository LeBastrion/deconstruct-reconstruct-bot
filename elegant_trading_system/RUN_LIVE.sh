#!/bin/bash
# LIVE TRADING LAUNCHER

echo "==================================="
echo "ELEGANT TRADING SYSTEM - LIVE MODE"
echo "==================================="
echo ""

# Check if credentials are set
if [ -z "$KUCOIN_API_KEY" ] || [ -z "$KUCOIN_API_SECRET" ] || [ -z "$KUCOIN_API_PASSPHRASE" ]; then
    echo "ERROR: Missing KuCoin API credentials!"
    echo ""
    echo "Please set these environment variables:"
    echo "  export KUCOIN_API_KEY='your-api-key'"
    echo "  export KUCOIN_API_SECRET='your-api-secret'"
    echo "  export KUCOIN_API_PASSPHRASE='your-api-passphrase'"
    echo ""
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements_live.txt

# Add current directory to Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run the live trading system
echo ""
echo "Starting LIVE trading system..."
echo "Trading pairs: BTC/USDT, ETH/USDT"
echo "Initial capital: $100 USDT"
echo "Risk per trade: 1% ($1)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python -m src.main_live