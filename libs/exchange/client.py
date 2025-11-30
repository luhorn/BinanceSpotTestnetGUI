"""
Binance Exchange Client Module

This module provides a wrapper around the Binance Spot API for testnet operations.
"""

import json
from decimal import Decimal
from binance.spot import Spot
from binance.error import ClientError


def load_secrets(path: str = 'resources/secrets.json') -> dict:
    """Load API secrets from JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


class BinanceClient:
    BASE_URL = 'https://testnet.binance.vision'
    
    def __init__(self, api_key: str = None, api_secret: str = None, secrets_path: str = 'resources/secrets.json'):
        if api_key is None or api_secret is None:
            secrets = load_secrets(secrets_path)
            api_key = secrets.get("api_key_binance_spot_testnet")
            api_secret = secrets.get("secret_key_binance_spot_testnet")
        
        self._client = Spot(
            api_key=api_key, 
            api_secret=api_secret, 
            base_url=self.BASE_URL
        )
        self._exchange_info_cache = None
    

    # ========== Account Operations ==========
    
    def get_account_info(self) -> dict | None:
        try:
            return self._client.account()
        except ClientError as e:
            raise BinanceClientError(f"Error fetching account info: {e}")
    

    def get_balances(self, non_zero_only: bool = True) -> list[dict]:
        account = self.get_account_info()
        if not account:
            return []
        
        balances = account.get('balances', [])
        if non_zero_only:
            balances = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        
        return balances
    

    # ========== Price Operations ==========
    
    def get_all_prices(self) -> dict[str, float]:
        try:
            ticker = self._client.ticker_price()
            return {t['symbol']: float(t['price']) for t in ticker}
        except ClientError as e:
            raise BinanceClientError(f"Error fetching prices: {e}")
    

    def get_price(self, symbol: str) -> float:
        prices = self.get_all_prices()
        return prices.get(symbol, 0.0)
    
    # ========== Exchange Info ==========
    
    def get_exchange_info(self, use_cache: bool = True) -> dict:
        if use_cache and self._exchange_info_cache:
            return self._exchange_info_cache
        
        try:
            self._exchange_info_cache = self._client.exchange_info()
            return self._exchange_info_cache
        except ClientError as e:
            raise BinanceClientError(f"Error fetching exchange info: {e}")
    

    def get_symbol_filters(self, symbol: str) -> dict | None:
        info = self.get_exchange_info()
        if not info:
            return None
        
        for s in info.get('symbols', []):
            if s['symbol'] == symbol:
                return {f['filterType']: f for f in s['filters']}
        
        return None
    

    def adjust_quantity(self, symbol: str, quantity: float, is_market_order: bool = False) -> float:
        filters = self.get_symbol_filters(symbol)
        if not filters:
            return quantity
        
        # For market orders, we need to respect BOTH:
        # - LOT_SIZE for step size (always applies)
        # - MARKET_LOT_SIZE for min/max (if available)
        
        # Get step size from LOT_SIZE (always required)
        lot_filter = filters.get('LOT_SIZE', {})
        step_size = float(lot_filter.get('stepSize', 0))
        
        # Get min/max from appropriate filter
        if is_market_order and 'MARKET_LOT_SIZE' in filters:
            market_filter = filters['MARKET_LOT_SIZE']
            min_qty = float(market_filter.get('minQty', 0))
            max_qty = float(market_filter.get('maxQty', 0))
            # If MARKET_LOT_SIZE max is 0, fall back to LOT_SIZE
            if max_qty == 0:
                max_qty = float(lot_filter.get('maxQty', float('inf')))
        else:
            min_qty = float(lot_filter.get('minQty', 0))
            max_qty = float(lot_filter.get('maxQty', float('inf')))
        
        result = quantity
        
        # First clamp to max (before step adjustment to avoid precision issues)
        if max_qty > 0 and result > max_qty:
            result = max_qty
        
        # Apply step size adjustment if step_size > 0
        if step_size > 0:
            # Use Decimal for precision
            q = Decimal(str(result))
            s = Decimal(str(step_size))
            
            # Floor division to nearest step
            adjusted_q = (q // s) * s
            
            # Determine precision from step_size
            s_str = f"{step_size:.8f}".rstrip('0')
            if '.' in s_str:
                precision = len(s_str.split('.')[1])
            else:
                precision = 0
            
            result = float(f"{adjusted_q:.{precision}f}")
        
        # Check min after step adjustment
        if result < min_qty:
            return 0.0  # Return 0 if below minimum (caller should handle this)
        
        return result
    

    def get_min_market_lot_size(self, symbol: str) -> float:
        """Get the minimum quantity for market orders."""
        filters = self.get_symbol_filters(symbol)
        if not filters:
            return 0.0
        
        if 'MARKET_LOT_SIZE' in filters:
            return float(filters['MARKET_LOT_SIZE'].get('minQty', 0))
        elif 'LOT_SIZE' in filters:
            return float(filters['LOT_SIZE'].get('minQty', 0))
        
        return 0.0
    

    def get_max_market_lot_size(self, symbol: str) -> float:
        """Get the maximum quantity for market orders."""
        filters = self.get_symbol_filters(symbol)
        if not filters:
            return float('inf')
        
        if 'MARKET_LOT_SIZE' in filters:
            max_qty = float(filters['MARKET_LOT_SIZE'].get('maxQty', 0))
            if max_qty > 0:
                return max_qty
        
        if 'LOT_SIZE' in filters:
            max_qty = float(filters['LOT_SIZE'].get('maxQty', 0))
            if max_qty > 0:
                return max_qty
        
        return float('inf')
    

    # ========== Order Operations ==========
    
    def get_open_orders(self, symbol: str = None) -> list[dict]:
        try:
            return self._client.get_open_orders(symbol=symbol)
        except ClientError as e:
            raise BinanceClientError(f"Error fetching open orders: {e}")
    

    def get_all_orders(self, symbol: str) -> list[dict]:
        try:
            return self._client.get_orders(symbol=symbol)
        except ClientError as e:
            # Return empty list on error (can be noisy for invalid symbols)
            return []
    

    def place_order(self, symbol: str, side: str, order_type: str, 
                    quantity: float = None, quote_order_qty: float = None,
                    price: float = None, time_in_force: str = "GTC") -> dict:
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        if quantity is not None:
            # Quantity should already be adjusted by caller
            params["quantity"] = quantity
        elif quote_order_qty is not None:
            params["quoteOrderQty"] = quote_order_qty
        
        if order_type == "LIMIT":
            params["timeInForce"] = time_in_force
            params["price"] = price
        
        try:
            return self._client.new_order(**params)
        except ClientError as e:
            raise BinanceClientError.from_client_error(e)
    

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        try:
            return self._client.cancel_order(symbol=symbol, orderId=order_id)
        except ClientError as e:
            raise BinanceClientError(f"Cancel failed: {e}")
    

    # ========== Utility Methods ==========
    
    def get_all_symbols(self) -> list[str]:
        prices = self.get_all_prices()
        return sorted(list(prices.keys()))
    

    def calculate_portfolio_value(self, balances: list[dict], prices: dict[str, float]) -> tuple[float, float, list[dict]]:
        usdt_balance = 0.0
        portfolio_value = 0.0
        asset_data = []
        
        for asset in balances:
            symbol = asset['asset']
            free = float(asset['free'])
            locked = float(asset['locked'])
            total = free + locked
            
            if symbol == 'USDT':
                usdt_balance = total
                val_in_usdt = total
            else:
                pair = f"{symbol}USDT"
                price = prices.get(pair, 0.0)
                val_in_usdt = total * price
            
            portfolio_value += val_in_usdt
            asset_data.append({
                "Asset": symbol,
                "Free": free,
                "Locked": locked,
                "Total": total,
                "Value (USDT)": val_in_usdt
            })
        
        return usdt_balance, portfolio_value, asset_data



class BinanceClientError(Exception):
    def __init__(self, message: str, error_code: int = None, error_message: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.error_message = error_message
    

    @classmethod
    def from_client_error(cls, error: ClientError) -> 'BinanceClientError':
        return cls(
            str(error),
            error_code=getattr(error, 'error_code', None),
            error_message=getattr(error, 'error_message', None)
        )
    

    def is_notional_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "NOTIONAL" in self.error_message
    
    
    def is_lot_size_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "LOT_SIZE" in self.error_message
    
    
    def is_market_lot_size_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "MARKET_LOT_SIZE" in self.error_message
    
    
    def is_liquidity_error(self) -> bool:
        return self.error_code == -2010 and self.error_message and "liquidity" in self.error_message.lower()
