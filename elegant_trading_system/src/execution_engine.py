"""
Execution Engine - Smart order routing and execution across venues
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import numpy as np
import structlog
from enum import Enum
import ccxt.async_support as ccxt

from .signal_engine import SignalDirection

logger = structlog.get_logger()


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    IOC = "IOC"  # Immediate or Cancel


class OrderStatus(Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """Order representation"""
    order_id: str
    symbol: str
    direction: SignalDirection
    order_type: OrderType
    quantity: Decimal
    price: Optional[float]
    venue: str
    status: OrderStatus
    created_at: datetime
    filled_quantity: Decimal = Decimal('0')
    average_fill_price: float = 0.0
    

@dataclass
class ExecutionResult:
    """Result of order execution"""
    success: bool
    orders: List[Order]
    total_filled: Decimal
    average_price: float
    total_slippage: float
    execution_time_ms: int
    venue_fills: Dict[str, Decimal]


class ExecutionEngine:
    """Smart order routing and execution"""
    
    def __init__(self, exchanges: Dict[str, ccxt.Exchange], config):
        self.exchanges = exchanges
        self.config = config
        self.pending_orders = {}
        self.order_history = []
        
    async def execute_signal(self, symbol: str, direction: SignalDirection,
                           quantity: Decimal, urgency: float = 1.0) -> ExecutionResult:
        """Execute a trading signal across venues"""
        start_time = datetime.now()
        
        try:
            # Get current market snapshot
            best_prices = await self._get_best_prices(symbol)
            if not best_prices:
                return ExecutionResult(
                    success=False,
                    orders=[],
                    total_filled=Decimal('0'),
                    average_price=0.0,
                    total_slippage=0.0,
                    execution_time_ms=0,
                    venue_fills={}
                )
            
            # Split order across venues
            venue_allocations = self._calculate_venue_split(
                symbol, quantity, direction, best_prices, urgency
            )
            
            # Execute orders in parallel
            orders = []
            tasks = []
            
            for venue, (allocation, limit_price) in venue_allocations.items():
                if allocation > 0:
                    task = asyncio.create_task(
                        self._execute_venue_order(
                            venue, symbol, direction, allocation, limit_price
                        )
                    )
                    tasks.append((venue, task))
            
            # Wait for all executions
            venue_results = []
            for venue, task in tasks:
                try:
                    order = await task
                    if order:
                        orders.append(order)
                        venue_results.append((venue, order))
                except Exception as e:
                    logger.error(f"Execution failed on {venue}: {e}")
            
            # Calculate results
            total_filled = sum(order.filled_quantity for order in orders)
            venue_fills = {
                venue: order.filled_quantity 
                for venue, order in venue_results
            }
            
            if total_filled > 0:
                weighted_price = sum(
                    float(order.filled_quantity) * order.average_fill_price 
                    for order in orders
                ) / float(total_filled)
                
                # Calculate slippage
                if direction == SignalDirection.LONG:
                    reference_price = best_prices['ask']
                else:
                    reference_price = best_prices['bid']
                
                slippage = abs(weighted_price - reference_price) / reference_price
            else:
                weighted_price = 0.0
                slippage = 0.0
            
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            result = ExecutionResult(
                success=total_filled > 0,
                orders=orders,
                total_filled=total_filled,
                average_price=weighted_price,
                total_slippage=slippage,
                execution_time_ms=execution_time,
                venue_fills=venue_fills
            )
            
            # Log execution
            logger.info(
                f"Executed {direction.value} {symbol}: "
                f"filled={total_filled}/{quantity} @ {weighted_price:.4f}, "
                f"slippage={slippage:.2%}, time={execution_time}ms"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return ExecutionResult(
                success=False,
                orders=[],
                total_filled=Decimal('0'),
                average_price=0.0,
                total_slippage=0.0,
                execution_time_ms=0,
                venue_fills={}
            )
    
    async def _get_best_prices(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get best bid/ask across all venues"""
        tasks = []
        
        for venue, exchange in self.exchanges.items():
            task = asyncio.create_task(self._fetch_ticker(exchange, symbol, venue))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        best_bid = 0
        best_ask = float('inf')
        
        for result in results:
            if isinstance(result, dict) and result:
                if result['bid'] > best_bid:
                    best_bid = result['bid']
                if result['ask'] < best_ask:
                    best_ask = result['ask']
        
        if best_bid > 0 and best_ask < float('inf'):
            return {
                'bid': best_bid,
                'ask': best_ask,
                'mid': (best_bid + best_ask) / 2
            }
        
        return None
    
    async def _fetch_ticker(self, exchange: ccxt.Exchange, symbol: str, venue: str) -> Dict:
        """Fetch ticker data from exchange"""
        try:
            ticker = await exchange.fetch_ticker(symbol)
            return {
                'venue': venue,
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'last': ticker['last']
            }
        except Exception as e:
            logger.error(f"Error fetching ticker from {venue}: {e}")
            return {}
    
    def _calculate_venue_split(self, symbol: str, quantity: Decimal,
                             direction: SignalDirection, best_prices: Dict,
                             urgency: float) -> Dict[str, Tuple[Decimal, float]]:
        """Calculate how to split order across venues"""
        allocations = {}
        
        # Get venue allocations from config
        primary_allocation = self.config.execution.primary_venue_allocation
        secondary_allocation = self.config.execution.secondary_venue_allocation
        dark_allocation = self.config.execution.dark_pool_allocation
        
        # Adjust for urgency (higher urgency = more aggressive pricing)
        if urgency > 1.5:
            # Very urgent - use market orders
            price_adjustment = 0.002  # 0.2% worse price for immediate fill
        else:
            # Normal - use limit orders at favorable prices
            price_adjustment = -0.0005  # 0.05% better price
        
        # Calculate limit prices
        if direction == SignalDirection.LONG:
            base_price = best_prices['ask']
            limit_price = base_price * (1 + price_adjustment)
        else:
            base_price = best_prices['bid']
            limit_price = base_price * (1 - price_adjustment)
        
        # Allocate to venues
        remaining_quantity = quantity
        
        # Primary venues get majority
        for venue in self.config.market_data.primary_venues:
            if venue in self.exchanges:
                allocation = quantity * Decimal(str(primary_allocation / len(self.config.market_data.primary_venues)))
                allocations[venue] = (allocation, limit_price)
                remaining_quantity -= allocation
        
        # Secondary venues
        for venue in self.config.market_data.secondary_venues:
            if venue in self.exchanges and remaining_quantity > 0:
                allocation = min(
                    remaining_quantity,
                    quantity * Decimal(str(secondary_allocation / len(self.config.market_data.secondary_venues)))
                )
                allocations[venue] = (allocation, limit_price)
                remaining_quantity -= allocation
        
        return allocations
    
    async def _execute_venue_order(self, venue: str, symbol: str,
                                 direction: SignalDirection, quantity: Decimal,
                                 limit_price: float) -> Optional[Order]:
        """Execute order on specific venue"""
        exchange = self.exchanges[venue]
        
        try:
            # Determine order type
            if self.config.execution.use_ioc_orders:
                order_type = 'limit'
                params = {'timeInForce': 'IOC'}
            else:
                order_type = 'limit'
                params = {}
            
            # Place order
            side = 'buy' if direction == SignalDirection.LONG else 'sell'
            
            response = await exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=float(quantity),
                price=limit_price,
                params=params
            )
            
            # Create order object
            order = Order(
                order_id=response['id'],
                symbol=symbol,
                direction=direction,
                order_type=OrderType.IOC if self.config.execution.use_ioc_orders else OrderType.LIMIT,
                quantity=quantity,
                price=limit_price,
                venue=venue,
                status=self._parse_order_status(response['status']),
                created_at=datetime.now(),
                filled_quantity=Decimal(str(response.get('filled', 0))),
                average_fill_price=float(response.get('average', limit_price))
            )
            
            self.order_history.append(order)
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to execute on {venue}: {e}")
            return None
    
    def _parse_order_status(self, status: str) -> OrderStatus:
        """Parse exchange order status"""
        status_map = {
            'open': OrderStatus.PENDING,
            'closed': OrderStatus.FILLED,
            'canceled': OrderStatus.CANCELLED,
            'expired': OrderStatus.CANCELLED,
            'rejected': OrderStatus.REJECTED
        }
        return status_map.get(status.lower(), OrderStatus.PENDING)
    
    async def cancel_all_orders(self, symbol: Optional[str] = None):
        """Cancel all pending orders"""
        tasks = []
        
        for venue, exchange in self.exchanges.items():
            try:
                if symbol:
                    orders = await exchange.fetch_open_orders(symbol)
                else:
                    orders = await exchange.fetch_open_orders()
                
                for order in orders:
                    task = asyncio.create_task(
                        exchange.cancel_order(order['id'], order['symbol'])
                    )
                    tasks.append(task)
                    
            except Exception as e:
                logger.error(f"Error fetching orders from {venue}: {e}")
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"Cancelled {len(tasks)} orders")
    
    def get_execution_stats(self) -> Dict:
        """Get execution statistics"""
        if not self.order_history:
            return {
                'total_orders': 0,
                'fill_rate': 0.0,
                'average_slippage': 0.0,
                'average_execution_time': 0
            }
        
        filled_orders = [o for o in self.order_history if o.status == OrderStatus.FILLED]
        
        fill_rate = len(filled_orders) / len(self.order_history) if self.order_history else 0
        
        # Calculate average slippage (would need to store reference prices)
        # For now, return placeholder
        avg_slippage = 0.001  # 0.1%
        
        return {
            'total_orders': len(self.order_history),
            'fill_rate': fill_rate,
            'average_slippage': avg_slippage,
            'venue_distribution': self._calculate_venue_distribution()
        }
    
    def _calculate_venue_distribution(self) -> Dict[str, float]:
        """Calculate volume distribution across venues"""
        venue_volumes = {}
        total_volume = Decimal('0')
        
        for order in self.order_history:
            if order.status == OrderStatus.FILLED:
                venue_volumes[order.venue] = venue_volumes.get(order.venue, Decimal('0')) + order.filled_quantity
                total_volume += order.filled_quantity
        
        if total_volume == 0:
            return {}
        
        return {
            venue: float(volume / total_volume)
            for venue, volume in venue_volumes.items()
        }