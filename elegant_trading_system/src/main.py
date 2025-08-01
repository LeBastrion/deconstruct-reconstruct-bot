"""
Main Trading System - Orchestrates all components
"""
import asyncio
import signal
import sys
from decimal import Decimal
from datetime import datetime
import structlog
from typing import List, Dict, Optional

from .config import SystemConfig
from .market_data import MarketDataAggregator
from .signal_engine import SignalEngine
from .risk_manager import RiskManager
from .execution_engine import ExecutionEngine
from .portfolio_monitor import PortfolioMonitor

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class ElegantTradingSystem:
    """Main trading system orchestrator"""
    
    def __init__(self, config: SystemConfig, initial_capital: Decimal):
        self.config = config
        self.running = False
        
        # Initialize components
        self.market_data = MarketDataAggregator(config)
        self.signal_engine = SignalEngine(self.market_data, config)
        self.risk_manager = RiskManager(config, initial_capital)
        self.execution_engine = None  # Initialized after market data
        self.portfolio_monitor = PortfolioMonitor(initial_capital)
        
        # Trading state
        self.symbols = []
        self.last_signal_time = {}
        self.min_signal_interval = 60  # Seconds between signals per symbol
        
    async def initialize(self, symbols: List[str]):
        """Initialize the trading system"""
        logger.info("Initializing Elegant Trading System...")
        
        self.symbols = symbols
        
        # Initialize market data connections
        await self.market_data.initialize()
        
        # Initialize execution engine with exchanges
        self.execution_engine = ExecutionEngine(
            self.market_data.exchanges,
            self.config
        )
        
        # Validate configuration
        self.config.validate()
        
        logger.info(f"System initialized. Trading symbols: {symbols}")
    
    async def start(self):
        """Start the trading system"""
        logger.info("Starting trading system...")
        self.running = True
        
        # Start market data collection
        market_data_task = asyncio.create_task(
            self.market_data.start(self.symbols)
        )
        
        # Start main trading loop
        trading_task = asyncio.create_task(self._trading_loop())
        
        # Start monitoring loop
        monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Wait for all tasks
        try:
            await asyncio.gather(
                market_data_task,
                trading_task,
                monitoring_task
            )
        except asyncio.CancelledError:
            logger.info("System shutdown requested")
    
    async def stop(self):
        """Stop the trading system"""
        logger.info("Stopping trading system...")
        self.running = False
        
        # Cancel all open orders
        await self.execution_engine.cancel_all_orders()
        
        # Close all positions at market
        await self._close_all_positions()
        
        # Stop market data
        await self.market_data.stop()
        
        # Generate final report
        report = self.portfolio_monitor.generate_report()
        logger.info(f"Final Report:\n{report}")
    
    async def _trading_loop(self):
        """Main trading loop"""
        await asyncio.sleep(5)  # Wait for initial market data
        
        while self.running:
            try:
                # Check for stop conditions
                current_prices = await self._get_current_prices()
                positions_to_close = self.risk_manager.check_stops(current_prices)
                
                for symbol in positions_to_close:
                    await self._close_position(symbol, current_prices.get(symbol))
                
                # Generate signals for all symbols
                signals = []
                for symbol in self.symbols:
                    # Rate limit signals
                    if symbol in self.last_signal_time:
                        time_since_last = (datetime.now() - self.last_signal_time[symbol]).seconds
                        if time_since_last < self.min_signal_interval:
                            continue
                    
                    signal = self.signal_engine.generate_signal(symbol)
                    if signal and signal.is_actionable(self.config):
                        signals.append(signal)
                
                # Filter correlated signals
                if signals:
                    correlation_matrix = self.portfolio_monitor.get_correlation_matrix(
                        [s.symbol for s in signals]
                    )
                    filtered_signals = self.signal_engine.filter_correlated_signals(
                        signals, correlation_matrix
                    )
                    
                    # Process signals
                    for signal in filtered_signals:
                        await self._process_signal(signal)
                
                # Update portfolio monitoring
                for symbol, position in self.risk_manager.positions.items():
                    if symbol in current_prices:
                        self.portfolio_monitor.update_position(
                            position, current_prices[symbol]
                        )
                
                # Sleep before next iteration
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _monitoring_loop(self):
        """Monitoring and reporting loop"""
        report_interval = 300  # 5 minutes
        last_report_time = datetime.now()
        
        while self.running:
            try:
                current_time = datetime.now()
                
                # Generate periodic reports
                if (current_time - last_report_time).seconds >= report_interval:
                    # Portfolio health check
                    current_prices = await self._get_current_prices()
                    health = self.portfolio_monitor.get_position_health(
                        self.risk_manager.positions,
                        current_prices
                    )
                    
                    # Risk metrics
                    risk_stats = self.risk_manager.get_portfolio_stats()
                    
                    # Performance metrics
                    perf_metrics = self.portfolio_monitor.get_performance_metrics()
                    
                    # Execution stats
                    exec_stats = self.execution_engine.get_execution_stats()
                    
                    logger.info(
                        "System Status",
                        portfolio_health=health,
                        risk_stats=risk_stats,
                        performance=f"Return: {perf_metrics.total_return:.2%}, "
                                  f"Sharpe: {perf_metrics.sharpe_ratio:.2f}",
                        execution=exec_stats
                    )
                    
                    last_report_time = current_time
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)
    
    async def _process_signal(self, signal):
        """Process a trading signal"""
        try:
            # Get current price
            orderbook = self.market_data.get_aggregated_orderbook(signal.symbol)
            if not orderbook:
                return
            
            current_price = orderbook.mid_price
            
            # Calculate position parameters
            risk_params = self.risk_manager.calculate_position_parameters(
                signal, current_price
            )
            
            if not risk_params:
                return
            
            # Execute order
            logger.info(
                f"Executing {signal.direction.value} signal for {signal.symbol}, "
                f"size: {risk_params.position_size:.2f}"
            )
            
            execution_result = await self.execution_engine.execute_signal(
                signal.symbol,
                signal.direction,
                risk_params.position_size,
                urgency=signal.strength / 3.0  # Higher strength = more urgent
            )
            
            if execution_result.success and execution_result.total_filled > 0:
                # Record position
                position = self.risk_manager.open_position(
                    signal.symbol,
                    signal,
                    risk_params,
                    execution_result.average_price,
                    list(execution_result.venue_fills.keys())[0]  # Primary venue
                )
                
                # Update signal time
                self.last_signal_time[signal.symbol] = datetime.now()
                
                logger.info(
                    f"Position opened: {signal.symbol} {signal.direction.value} "
                    f"@ {execution_result.average_price:.4f}, "
                    f"slippage: {execution_result.total_slippage:.2%}"
                )
            else:
                logger.warning(
                    f"Failed to execute signal for {signal.symbol}: "
                    f"filled {execution_result.total_filled}/{risk_params.position_size}"
                )
                
        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
    
    async def _close_position(self, symbol: str, current_price: Optional[float]):
        """Close a position"""
        try:
            position = self.risk_manager.positions.get(symbol)
            if not position:
                return
            
            # Execute close order
            close_direction = "SHORT" if position.direction.value == "LONG" else "LONG"
            
            execution_result = await self.execution_engine.execute_signal(
                symbol,
                close_direction,
                position.position_size,
                urgency=2.0  # High urgency for exits
            )
            
            if execution_result.success:
                exit_price = execution_result.average_price
            else:
                # Use current price as fallback
                exit_price = current_price or position.entry_price
            
            # Record trade
            self.portfolio_monitor.record_trade(
                symbol=symbol,
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.position_size,
                direction=position.direction.value,
                entry_time=position.entry_time,
                exit_time=datetime.now()
            )
            
            # Close position in risk manager
            pnl = self.risk_manager.close_position(symbol, exit_price)
            
            logger.info(f"Position closed: {symbol} @ {exit_price:.4f}, P&L: {pnl:.2f}")
            
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}", exc_info=True)
    
    async def _close_all_positions(self):
        """Emergency close all positions"""
        current_prices = await self._get_current_prices()
        
        for symbol in list(self.risk_manager.positions.keys()):
            await self._close_position(symbol, current_prices.get(symbol))
    
    async def _get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all symbols"""
        prices = {}
        
        for symbol in self.symbols:
            orderbook = self.market_data.get_aggregated_orderbook(symbol)
            if orderbook:
                prices[symbol] = orderbook.mid_price
        
        return prices


async def main():
    """Main entry point"""
    # Load configuration
    config = SystemConfig.load_default()
    
    # Set initial capital
    initial_capital = Decimal('100000')  # $100K
    
    # Define symbols to trade
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    
    # Create trading system
    system = ElegantTradingSystem(config, initial_capital)
    
    # Initialize
    await system.initialize(symbols)
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        asyncio.create_task(system.stop())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start trading
    await system.start()


if __name__ == "__main__":
    asyncio.run(main())