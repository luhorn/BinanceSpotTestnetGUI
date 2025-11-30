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
    """
    Wrapper class for Binance Spot Testnet API operations.
    
    Handles all exchange-related functionality including:
    - Account information
    - Price data
    - Order management
    - Exchange info and filters
    """
    
    BASE_URL = 'https://testnet.binance.vision'
    
    def __init__(self, api_key: str = None, api_secret: str = None, secrets_path: str = 'resources/secrets.json'):
        """
        Initialize the Binance client.
        
        Args:
            api_key: Binance API key (optional, will load from secrets if not provided)
            api_secret: Binance API secret (optional, will load from secrets if not provided)
            secrets_path: Path to secrets.json file
        """
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
        """
        Get account information including balances.
        
        Returns:
            Account info dict or None on error
        """
        try:
            return self._client.account()
        except ClientError as e:
            raise BinanceClientError(f"Error fetching account info: {e}")
    
    def get_balances(self, non_zero_only: bool = True) -> list[dict]:
        """
        Get account balances.
        
        Args:
            non_zero_only: If True, only return assets with non-zero balance
            
        Returns:
            List of balance dictionaries
        """
        account = self.get_account_info()
        if not account:
            return []
        
        balances = account.get('balances', [])
        if non_zero_only:
            balances = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        
        return balances
    
    # ========== Price Operations ==========
    
    def get_all_prices(self) -> dict[str, float]:
        """
        Get current prices for all trading pairs.
        
        Returns:
            Dictionary mapping symbol to price
        """
        try:
            ticker = self._client.ticker_price()
            return {t['symbol']: float(t['price']) for t in ticker}
        except ClientError as e:
            raise BinanceClientError(f"Error fetching prices: {e}")
    
    def get_price(self, symbol: str) -> float:
        """
        Get current price for a specific symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            
        Returns:
            Current price
        """
        prices = self.get_all_prices()
        return prices.get(symbol, 0.0)
    
    # ========== Exchange Info ==========
    
    def get_exchange_info(self, use_cache: bool = True) -> dict:
        """
        Get exchange information including trading rules.
        
        Args:
            use_cache: If True, use cached data if available
            
        Returns:
            Exchange info dictionary
        """
        if use_cache and self._exchange_info_cache:
            return self._exchange_info_cache
        
        try:
            self._exchange_info_cache = self._client.exchange_info()
            return self._exchange_info_cache
        except ClientError as e:
            raise BinanceClientError(f"Error fetching exchange info: {e}")
    
    def get_symbol_filters(self, symbol: str) -> dict | None:
        """
        Get trading filters for a specific symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Dictionary of filters by filter type, or None if not found
        """
        info = self.get_exchange_info()
        if not info:
            return None
        
        for s in info.get('symbols', []):
            if s['symbol'] == symbol:
                return {f['filterType']: f for f in s['filters']}
        
        return None
    
    def adjust_quantity(self, symbol: str, quantity: float) -> float:
        """
        Adjust quantity to match LOT_SIZE filter requirements.
        
        Args:
            symbol: Trading pair symbol
            quantity: Desired quantity
            
        Returns:
            Adjusted quantity that meets LOT_SIZE requirements
        """
        filters = self.get_symbol_filters(symbol)
        if not filters:
            return quantity
        
        if 'LOT_SIZE' not in filters:
            return quantity
        
        step_size = float(filters['LOT_SIZE']['stepSize'])
        if step_size <= 0:
            return quantity
        
        # Use Decimal for precision
        q = Decimal(str(quantity))
        s = Decimal(str(step_size))
        
        # Floor division to nearest step
        adjusted_q = (q // s) * s
        
        # Determine precision from step_size
        s_str = f"{step_size:.8f}".rstrip('0')
        if '.' in s_str:
            precision = len(s_str.split('.')[1])
        else:
            precision = 0
        
        return float(f"{adjusted_q:.{precision}f}")
    
    # ========== Order Operations ==========
    
    def get_open_orders(self, symbol: str = None) -> list[dict]:
        """
        Get open orders.
        
        Args:
            symbol: Optional symbol to filter by
            
        Returns:
            List of open orders
        """
        try:
            return self._client.get_open_orders(symbol=symbol)
        except ClientError as e:
            raise BinanceClientError(f"Error fetching open orders: {e}")
    
    def get_all_orders(self, symbol: str) -> list[dict]:
        """
        Get order history for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            List of orders
        """
        try:
            return self._client.get_orders(symbol=symbol)
        except ClientError as e:
            # Return empty list on error (can be noisy for invalid symbols)
            return []
    
    def place_order(self, symbol: str, side: str, order_type: str, 
                    quantity: float = None, quote_order_qty: float = None,
                    price: float = None, time_in_force: str = "GTC") -> dict:
        """
        Place a new order.
        
        Args:
            symbol: Trading pair symbol
            side: 'BUY' or 'SELL'
            order_type: 'LIMIT' or 'MARKET'
            quantity: Order quantity in base asset
            quote_order_qty: Order quantity in quote asset (for MARKET orders)
            price: Order price (required for LIMIT orders)
            time_in_force: Time in force (default: GTC)
            
        Returns:
            Order response dictionary
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        if quantity is not None:
            # Adjust quantity for LOT_SIZE
            params["quantity"] = self.adjust_quantity(symbol, quantity)
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
        """
        Cancel an order.
        
        Args:
            symbol: Trading pair symbol
            order_id: Order ID to cancel
            
        Returns:
            Cancel response dictionary
        """
        try:
            return self._client.cancel_order(symbol=symbol, orderId=order_id)
        except ClientError as e:
            raise BinanceClientError(f"Cancel failed: {e}")
    
    # ========== Utility Methods ==========
    
    def get_all_symbols(self) -> list[str]:
        """Get sorted list of all trading symbols."""
        prices = self.get_all_prices()
        return sorted(list(prices.keys()))
    
    def calculate_portfolio_value(self, balances: list[dict], prices: dict[str, float]) -> tuple[float, float, list[dict]]:
        """
        Calculate total portfolio value.
        
        Args:
            balances: List of balance dictionaries
            prices: Dictionary of symbol prices
            
        Returns:
            Tuple of (usdt_balance, total_portfolio_value, asset_data_list)
        """
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
    """Custom exception for Binance client errors."""
    
    def __init__(self, message: str, error_code: int = None, error_message: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.error_message = error_message
    
    @classmethod
    def from_client_error(cls, error: ClientError) -> 'BinanceClientError':
        """Create from a Binance ClientError."""
        return cls(
            str(error),
            error_code=getattr(error, 'error_code', None),
            error_message=getattr(error, 'error_message', None)
        )
    
    def is_notional_error(self) -> bool:
        """Check if this is a minimum notional error."""
        return self.error_code == -1013 and self.error_message and "NOTIONAL" in self.error_message
    
    def is_lot_size_error(self) -> bool:
        """Check if this is a LOT_SIZE error."""
        return self.error_code == -1013 and self.error_message and "LOT_SIZE" in self.error_message
