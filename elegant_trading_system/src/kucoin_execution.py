"""
KuCoin Execution Engine - Free API trading
"""
import asyncio
import hmac
import hashlib
import base64
import time
import json
from typing import Dict, Optional
from decimal import Decimal
import aiohttp
import structlog

from .execution_engine import Order, OrderStatus, OrderType, ExecutionResult
from .signal_engine import SignalDirection

logger = structlog.get_logger()


class KuCoinExecution:
    """KuCoin API execution engine"""
    
    def __init__(self, api_key: str, api_secret: str, api_passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.base_url = "https://api.kucoin.com"
        self.session = None
        
    async def initialize(self):
        """Initialize connection"""
        self.session = aiohttp.ClientSession()
        
        # Test connection
        try:
            account = await self._get_account_info()
            logger.info(f"Connected to KuCoin. Account: {account}")
        except Exception as e:
            logger.error(f"Failed to connect to KuCoin: {e}")
            raise
    
    async def close(self):
        """Close connection"""
        if self.session:
            await self.session.close()
    
    async def execute_order(self, symbol: str, direction: SignalDirection,
                          size: Decimal, order_type: str = "market") -> Optional[Order]:
        """Execute order on KuCoin"""
        try:
            # Convert symbol format: BTC/USDT -> BTC-USDT
            kucoin_symbol = symbol.replace('/', '-')
            
            # Prepare order data
            side = "buy" if direction == SignalDirection.LONG else "sell"
            
            order_data = {
                "clientOid": str(int(time.time() * 1000)),
                "side": side,
                "symbol": kucoin_symbol,
                "type": order_type
            }
            
            if order_type == "market":
                order_data["size"] = str(size)
            else:  # limit order
                # Get current price for limit order
                ticker = await self._get_ticker(kucoin_symbol)
                if direction == SignalDirection.LONG:
                    price = float(ticker['bestAsk']) * 1.0001  # Slightly above ask
                else:
                    price = float(ticker['bestBid']) * 0.9999  # Slightly below bid
                
                order_data["price"] = str(price)
                order_data["size"] = str(size)
                order_data["timeInForce"] = "IOC"  # Immediate or cancel
            
            # Place order
            response = await self._place_order(order_data)
            
            if response and 'orderId' in response:
                # Get order details
                order_details = await self._get_order(response['orderId'])
                
                return Order(
                    order_id=response['orderId'],
                    symbol=symbol,
                    direction=direction,
                    order_type=OrderType.MARKET if order_type == "market" else OrderType.IOC,
                    quantity=size,
                    price=float(order_details.get('price', 0)),
                    venue="kucoin",
                    status=self._parse_status(order_details.get('isActive')),
                    created_at=datetime.now(),
                    filled_quantity=Decimal(str(order_details.get('dealSize', 0))),
                    average_fill_price=float(order_details.get('dealFunds', 0)) / float(order_details.get('dealSize', 1))
                )
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return None
    
    async def get_balance(self, currency: str = "USDT") -> Dict:
        """Get account balance"""
        endpoint = "/api/v1/accounts"
        params = {"currency": currency, "type": "trade"}
        
        response = await self._request("GET", endpoint, params=params)
        
        if response and 'data' in response:
            for account in response['data']:
                if account['currency'] == currency:
                    return {
                        'currency': currency,
                        'available': float(account['available']),
                        'balance': float(account['balance'])
                    }
        
        return {'currency': currency, 'available': 0.0, 'balance': 0.0}
    
    async def _get_ticker(self, symbol: str) -> Dict:
        """Get ticker data"""
        endpoint = f"/api/v1/market/orderbook/level1"
        params = {"symbol": symbol}
        
        response = await self._request("GET", endpoint, params=params, auth=False)
        return response.get('data', {})
    
    async def _get_account_info(self) -> Dict:
        """Get account information"""
        endpoint = "/api/v1/accounts"
        response = await self._request("GET", endpoint)
        return response
    
    async def _place_order(self, order_data: Dict) -> Dict:
        """Place order via API"""
        endpoint = "/api/v1/orders"
        response = await self._request("POST", endpoint, data=order_data)
        return response.get('data', {})
    
    async def _get_order(self, order_id: str) -> Dict:
        """Get order details"""
        endpoint = f"/api/v1/orders/{order_id}"
        response = await self._request("GET", endpoint)
        return response.get('data', {})
    
    def _parse_status(self, is_active: bool) -> OrderStatus:
        """Parse order status"""
        return OrderStatus.PENDING if is_active else OrderStatus.FILLED
    
    def _generate_signature(self, timestamp: str, method: str, 
                          endpoint: str, body: str = "") -> str:
        """Generate request signature"""
        message = timestamp + method + endpoint + body
        mac = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _generate_passphrase(self) -> str:
        """Generate passphrase signature"""
        mac = hmac.new(
            self.api_secret.encode('utf-8'),
            self.api_passphrase.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    async def _request(self, method: str, endpoint: str, 
                      params: Dict = None, data: Dict = None, auth: bool = True) -> Dict:
        """Make API request"""
        url = self.base_url + endpoint
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        if auth:
            timestamp = str(int(time.time() * 1000))
            body = json.dumps(data) if data else ""
            
            headers.update({
                'KC-API-KEY': self.api_key,
                'KC-API-SIGN': self._generate_signature(timestamp, method, endpoint, body),
                'KC-API-TIMESTAMP': timestamp,
                'KC-API-PASSPHRASE': self._generate_passphrase(),
                'KC-API-KEY-VERSION': '2'
            })
        
        async with self.session.request(
            method, url, params=params, json=data, headers=headers
        ) as response:
            result = await response.json()
            
            if result.get('code') != '200000':
                raise Exception(f"API Error: {result}")
            
            return result