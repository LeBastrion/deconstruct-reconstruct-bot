#!/usr/bin/env python3
"""
LIVE TRADING SYSTEM - Immediate deployment
"""
import asyncio
import signal
import sys
import os
from decimal import Decimal
from datetime import datetime
import structlog

from .config_live import LiveConfig
from .market_data_free import FreeMarketData
from .signal_engine import SignalEngine, VWAPCalculator
from .kucoin_execution import KuCoinExecution

# Simple logger
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ]
)
logger = structlog.get_logger()


class LiveTradingSystem:
    """Minimal live trading system"""
    
    def __init__(self):
        self.config = LiveConfig()
        self.market_data = FreeMarketData()
        self.signal_engine = None
        self.execution = None
        self.positions = {}  # {symbol: position_data}
        self.capital = self.config.INITIAL_CAPITAL
        self.running = False
        
    async def initialize(self):
        """Initialize system"""
        logger.info("Initializing LIVE trading system...")
        
        # Validate credentials
        if not all([self.config.KUCOIN_API_KEY, 
                   self.config.KUCOIN_API_SECRET,
                   self.config.KUCOIN_API_PASSPHRASE]):
            raise ValueError("Missing KuCoin API credentials! Set environment variables.")
        
        # Initialize execution
        self.execution = KuCoinExecution(
            self.config.KUCOIN_API_KEY,
            self.config.KUCOIN_API_SECRET,
            self.config.KUCOIN_API_PASSPHRASE
        )
        await self.execution.initialize()
        
        # Check balance
        balance = await self.execution.get_balance("USDT")
        logger.info(f"Account balance: {balance['available']} USDT")
        
        if balance['available'] < float(self.config.INITIAL_CAPITAL):
            raise ValueError(f"Insufficient balance. Need {self.config.INITIAL_CAPITAL} USDT")
        
        # Create signal engine with market data
        self.signal_engine = SignalEngine(self.market_data, self.config)
        
        logger.info("System initialized successfully!")
    
    async def start(self):
        """Start trading"""
        self.running = True
        logger.info("Starting LIVE trading...")
        
        # Start market data
        market_task = asyncio.create_task(
            self.market_data.start(self.config.SYMBOLS)
        )
        
        # Start trading loop
        trading_task = asyncio.create_task(self._trading_loop())
        
        # Start monitoring
        monitor_task = asyncio.create_task(self._monitor_loop())
        
        await asyncio.gather(market_task, trading_task, monitor_task)
    
    async def stop(self):
        """Stop trading"""
        logger.info("Stopping trading system...")
        self.running = False
        
        # Close all positions
        for symbol in list(self.positions.keys()):
            await self._close_position(symbol)
        
        await self.market_data.stop()
        await self.execution.close()
        
        logger.info("System stopped")
    
    async def _trading_loop(self):
        """Main trading loop"""
        await asyncio.sleep(10)  # Wait for market data
        
        while self.running:
            try:
                for symbol in self.config.SYMBOLS:
                    # Skip if already have position
                    if symbol in self.positions:
                        await self._check_exit(symbol)
                        continue
                    
                    # Check if can open new position
                    if len(self.positions) >= self.config.MAX_POSITIONS:
                        continue
                    
                    # Generate signal
                    signal = self._generate_simple_signal(symbol)
                    
                    if signal and signal['strength'] > self.config.SIGNAL_STRENGTH_THRESHOLD:
                        await self._open_position(symbol, signal)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Trading error: {e}")
                await asyncio.sleep(5)
    
    def _generate_simple_signal(self, symbol: str) -> Optional[Dict]:
        """Generate simplified signal"""
        orderbook = self.market_data.get_orderbook(symbol)
        if not orderbook:
            return None
        
        # Simple momentum signal
        imbalance = orderbook.imbalance
        velocity = self.market_data.get_volume_velocity(symbol)
        tightness = self.market_data.get_spread_tightness(symbol)
        
        strength = imbalance * velocity * tightness
        
        if imbalance > 1.5:  # More bids
            direction = "LONG"
        elif imbalance < 0.67:  # More asks
            direction = "SHORT"
        else:
            return None
        
        return {
            'direction': direction,
            'strength': strength,
            'price': orderbook.mid_price
        }
    
    async def _open_position(self, symbol: str, signal: Dict):
        """Open position"""
        try:
            # Calculate position size (fixed risk)
            risk_amount = self.capital * self.config.RISK_PER_TRADE
            stop_distance = signal['price'] * 0.005  # 0.5% stop
            position_size = float(risk_amount / Decimal(str(stop_distance)))
            
            # Round to valid precision
            if symbol == "BTC/USDT":
                position_size = round(position_size, 4)  # 0.0001 BTC min
            else:
                position_size = round(position_size, 3)  # 0.001 ETH min
            
            # Execute order
            logger.info(f"Opening {signal['direction']} position: {symbol} size={position_size}")
            
            from .signal_engine import SignalDirection
            direction = SignalDirection.LONG if signal['direction'] == "LONG" else SignalDirection.SHORT
            
            order = await self.execution.execute_order(
                symbol, 
                direction,
                Decimal(str(position_size)),
                "market" if self.config.USE_MARKET_ORDERS else "limit"
            )
            
            if order and order.filled_quantity > 0:
                # Record position
                self.positions[symbol] = {
                    'direction': signal['direction'],
                    'entry_price': order.average_fill_price,
                    'size': float(order.filled_quantity),
                    'stop_loss': order.average_fill_price * (0.995 if signal['direction'] == "LONG" else 1.005),
                    'take_profit': order.average_fill_price * (1.015 if signal['direction'] == "LONG" else 0.985),
                    'entry_time': datetime.now()
                }
                
                logger.info(f"Position opened: {symbol} @ {order.average_fill_price}")
            
        except Exception as e:
            logger.error(f"Failed to open position: {e}")
    
    async def _check_exit(self, symbol: str):
        """Check if should exit position"""
        position = self.positions[symbol]
        orderbook = self.market_data.get_orderbook(symbol)
        
        if not orderbook:
            return
        
        current_price = orderbook.mid_price
        
        # Check stop loss or take profit
        should_exit = False
        reason = ""
        
        if position['direction'] == "LONG":
            if current_price <= position['stop_loss']:
                should_exit = True
                reason = "stop_loss"
            elif current_price >= position['take_profit']:
                should_exit = True
                reason = "take_profit"
        else:
            if current_price >= position['stop_loss']:
                should_exit = True
                reason = "stop_loss"
            elif current_price <= position['take_profit']:
                should_exit = True
                reason = "take_profit"
        
        if should_exit:
            logger.info(f"Exiting {symbol} - {reason}")
            await self._close_position(symbol)
    
    async def _close_position(self, symbol: str):
        """Close position"""
        try:
            position = self.positions[symbol]
            
            # Reverse direction to close
            from .signal_engine import SignalDirection
            close_direction = SignalDirection.SHORT if position['direction'] == "LONG" else SignalDirection.LONG
            
            order = await self.execution.execute_order(
                symbol,
                close_direction,
                Decimal(str(position['size'])),
                "market"
            )
            
            if order:
                # Calculate P&L
                if position['direction'] == "LONG":
                    pnl = (order.average_fill_price - position['entry_price']) * position['size']
                else:
                    pnl = (position['entry_price'] - order.average_fill_price) * position['size']
                
                self.capital += Decimal(str(pnl))
                
                logger.info(f"Position closed: {symbol} P&L: ${pnl:.2f}")
                
                del self.positions[symbol]
                
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
    
    async def _monitor_loop(self):
        """Monitor and report"""
        while self.running:
            try:
                # Get account balance
                balance = await self.execution.get_balance("USDT")
                
                # Calculate stats
                open_positions = len(self.positions)
                current_balance = balance['available']
                pnl = float(current_balance) - float(self.config.INITIAL_CAPITAL)
                pnl_percent = (pnl / float(self.config.INITIAL_CAPITAL)) * 100
                
                logger.info(
                    f"STATUS: Balance=${current_balance:.2f} | "
                    f"P&L=${pnl:.2f} ({pnl_percent:+.1f}%) | "
                    f"Positions={open_positions}"
                )
                
                await asyncio.sleep(self.config.REPORT_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(60)


async def main():
    """Main entry point"""
    # Check for API credentials
    if not os.getenv('KUCOIN_API_KEY'):
        print("\n!!! MISSING API CREDENTIALS !!!")
        print("\nSet these environment variables:")
        print("export KUCOIN_API_KEY='your-key'")
        print("export KUCOIN_API_SECRET='your-secret'")
        print("export KUCOIN_API_PASSPHRASE='your-passphrase'")
        sys.exit(1)
    
    system = LiveTradingSystem()
    
    try:
        await system.initialize()
        
        # Handle shutdown
        def shutdown(sig, frame):
            asyncio.create_task(system.stop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        
        await system.start()
        
    except Exception as e:
        logger.error(f"System error: {e}")
        await system.stop()


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════╗
    ║   ELEGANT TRADING SYSTEM - LIVE MODE  ║
    ╚═══════════════════════════════════════╝
    
    WARNING: This will trade with REAL MONEY!
    Starting in 5 seconds... (Ctrl+C to cancel)
    """)
    
    import time
    time.sleep(5)
    
    asyncio.run(main())