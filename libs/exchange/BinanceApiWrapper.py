import json
from decimal import Decimal
import math
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *
import logging
from dataclasses import dataclass, field
from enum import Enum, auto



# --- Global Defines ---
class cErrors(Enum):
    NOT_TRADING     = auto()
    MIN_QTY         = auto()
    MAX_QTY         = auto()
    MIN_PRICE       = auto()
    MAX_PRICE       = auto()
    MIN_NOTIONAL    = auto()
    MAX_NOTIONAL    = auto()


# --- Data storage classes ---

'''
Data class to hold asset information needed for trading
'''
@dataclass
class SymbolLimits():
    symbol: str
    min_qty: float
    max_qty: float
    step_size: float
    min_price: float
    max_price: float
    tick_size: float
    min_notional: float | None
    max_notional: float | None
    status: str


# --- Helper functions ---

'''
Round to the Binance Step
'''
def round_step(f: float, step: float) -> float:
    digits = math.log10(step ** (-1))
    return truncate_float(f, digits)
        
    
'''
Truncate float to a specified number of decimal digits
'''
def truncate_float(f: float, digits: int) -> float:
    factor = 10 ** digits
    return math.floor(f * factor) / factor


def load_secrets(path: str = 'resources/secrets.json') -> dict:
    """Load API secrets from JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


# --- Exception Class ---

class BinanceClientError(Exception):
    """Custom exception for Binance API errors with structured error info."""
    def __init__(self, message: str, error_code: int = None, error_message: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.error_message = error_message

    @classmethod
    def from_api_exception(cls, error: BinanceAPIException) -> 'BinanceClientError':
        return cls(
            str(error),
            error_code=getattr(error, 'code', None),
            error_message=getattr(error, 'message', None)
        )

    def get_user_message(self) -> str:
        """Get a clean, user-friendly error message."""
        if self.error_message:
            return self.error_message
        msg = str(self.args[0]) if self.args else "Unknown error"
        if len(msg) > 200:
            return msg[:200] + "..."
        return msg

    def is_notional_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "NOTIONAL" in self.error_message

    def is_lot_size_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "LOT_SIZE" in self.error_message

    def is_market_lot_size_error(self) -> bool:
        return self.error_code == -1013 and self.error_message and "MARKET_LOT_SIZE" in self.error_message

    def is_liquidity_error(self) -> bool:
        return self.error_code == -2010 and self.error_message and "liquidity" in self.error_message.lower()

    def is_insufficient_balance(self) -> bool:
        return self.error_code == -2010 and self.error_message and "insufficient balance" in self.error_message.lower()


# --- API Wrapper Class ---

class BinanceClient:    
    def __init__(self, api_key=None, api_secret=None, testnet=True, communicator=None, secrets_path='resources/secrets.json'):        
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')     # Configure logging
        
        if api_key is None or api_secret is None:
            secrets = load_secrets(secrets_path)
            api_key = secrets.get("api_key_binance_spot_testnet")
            api_secret = secrets.get("secret_key_binance_spot_testnet")
        
        self.client = Client(api_key, api_secret, testnet=testnet)     # Configure Client
        self.com = communicator

        self.symbol_limits: dict[str, SymbolLimits] = {}
        self.load_symbol_limits()


    # -------------------------
    # --- GENERAL FUNCTIONS ---
    # -------------------------

    '''
    Print a message to the Terminal if no communicator present, else send via communicator
    '''
    def write_msg(self, msg):
        if(self.com):
            self.com.send_message(msg)
        else:
            print(msg)


    '''
    Test if binance can be reached and API keys are correct 
    '''
    def test_connection(self) -> bool:
        try:
            self.client.get_account()
            return True
        except BinanceAPIException as e:
            self.write_msg(f"ERROR: Binance connection test failed: {e}\n")
            return False
        

    # -------------------------
    # --- ASSET INFORMATION ---
    # -------------------------

    def get_all_prices(self):
        try:
            tickers = self.client.get_all_tickers()
            return {t['symbol']: float(t['price']) for t in tickers}
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)


    def get_symbol_price(self, symbol):
        try:
            prices = self.get_all_prices()
            symbol_price = prices[symbol]
            return symbol_price
        except Exception as e:
            self.write_msg(e)
            return 0.0
        

    def load_symbol_limits(self):
        try:
            info = self.client.get_exchange_info()
            for s in info["symbols"]:
                symbol = s["symbol"]
                filters = {f["filterType"]: f for f in s["filters"]}

                lot = filters["LOT_SIZE"]
                price = filters["PRICE_FILTER"]
                notional = filters.get("MIN_NOTIONAL")
                max_notional = filters.get("NOTIONAL")  # may not exist

                self.symbol_limits[symbol] = SymbolLimits(
                    symbol=symbol,

                    min_qty=float(lot["minQty"]),
                    max_qty=float(lot["maxQty"]),
                    step_size=float(lot["stepSize"]),

                    min_price=float(price["minPrice"]),
                    max_price=float(price["maxPrice"]),
                    tick_size=float(price["tickSize"]),

                    min_notional=float(notional["minNotional"]) if notional else None,
                    max_notional=float(max_notional["maxNotional"]) if max_notional else None,

                    status=s["status"]
                )
        except BinanceAPIException as e:
            self.write_msg(e)
        except Exception as e:
            self.write_msg(e)


    # ---------------------------
    # --- ACCOUNT INFORMATION ---
    # ---------------------------

    '''
    Get current cash balance
    '''
    def get_cash_balance(self) -> float:
        try:
            usdt_balance = self.client.get_asset_balance(asset='USDT')
            return float(usdt_balance['free']) if usdt_balance else 0.0
        except BinanceAPIException as e:
            self.write_msg(e)
            return None

    '''
    Get current locked cash balance
    '''
    def get_locked_cash_balance(self) -> float:
        try:
            usdt_balance = self.client.get_asset_balance(asset='USDT')
            return float(usdt_balance['locked']) if usdt_balance else 0.0
        except BinanceAPIException as e:
            self.write_msg(e)
            return None


    '''
    Get all assets ina ccoutn with their USDT values where USDT value is over threshold
    '''
    def get_filtered_holdings(self, filter_threshold_usdt):
        holdings = self.get_holdings()
        filtered_holdings = [h for h in holdings if h['usdt_value'] > filter_threshold_usdt]
        return filtered_holdings


    '''
    Get all assets in account with their USDT values
    '''
    def get_holdings(self):
        try:
            account = self.client.get_account()
            balances = account.get('balances', [])
            active_balances = [b for b in balances if float(b['free']) > 0.0 or float(b['locked']) > 0.0]   # Filter out assets with 0 free and 0 locked (only actual positions)
            prices = self.get_all_prices()  # Get all prices
            
            # Calculate USDT value for each asset
            holdings = []
            for balance in active_balances:
                asset = balance['asset']
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked
                
                # Get price for this asset paired with USDT
                symbol = asset + 'USDT'
                price = prices.get(symbol, 0.0)
                usdt_value = total * price
                
                holdings.append({
                    'asset': asset,
                    'free': free,
                    'locked': locked,
                    'total': total,
                    'price': price,
                    'usdt_value': usdt_value
                })
            
            return holdings
        except BinanceAPIException as e:
            self.write_msg(e)
            return None
        

    '''
    Get open orders (optionally filtered by symbol)
    '''
    def get_open_orders(self, symbol: str = None):
        try:
            if symbol:
                return self.client.get_open_orders(symbol=symbol)
            return self.client.get_open_orders()
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)
        

    # ---------------------
    # --- HANDLE ORDERS ---
    # ---------------------

    '''
    Validate order to match all the asset specific limits
    '''
    def validate_order(self, symbol: str, qty: float, price: float):
        s = self.symbol_limits[symbol]
        is_valid = True     # Set to false if order was changed
        is_fatal_error = False    # Set to true if order cannot be executed (FatalError) 
        errors = []

        if s.status != "TRADING":
            is_valid = False
            errors.append(cErrors.NOT_TRADING)

        # round to allowed precision
        new_price   = round_step(price, s.tick_size)
        new_qty     = round_step(qty, s.step_size)

        if new_qty < s.min_qty:
            is_valid = False
            is_fatal_error = True
            errors.append(cErrors.MIN_QTY)

        if new_qty > s.max_qty:
            is_valid = False
            new_qty = round_step(s.max_qty, s.step_size)
            errors.append(cErrors.MAX_QTY)

        if new_price < s.min_price:
            is_valid = False
            is_fatal_error = True
            errors.append(cErrors.MIN_PRICE)

        if new_price > s.max_price:
            is_valid = False
            new_price = round_step(s.max_price, s.tick_size)
            errors.append(cErrors.MAX_PRICE)

        notional = new_price * new_qty

        if s.min_notional and notional < s.min_notional:
            is_valid = False
            is_fatal_error = True
            errors.append(cErrors.MIN_NOTIONAL)

        if s.max_notional and notional > s.max_notional:
            is_valid = False
            is_fatal_error = True
            errors.append(cErrors.MAX_NOTIONAL)

        result = {
            "is_valid": is_valid,
            "is_fatal_error": is_fatal_error,
            "errors": errors,
            "price": new_price,
            "qty": new_qty
        }
        return result


    '''
    Place a direct market order
    '''
    def place_market_order(self, symbol: str, side: str, qty: float):
        try:
            s = self.symbol_limits[symbol]
            type = "MARKET"

            # round to allowed precision
            qty = round_step(qty, s.step_size)

            # Validate if the order is valid
            current_price = self.get_symbol_price(symbol)
            result = self.validate_order(symbol, qty, current_price)

            if not result["is_valid"]:
                if result["is_fatal_error"]:
                    error_msgs = [str(e) for e in result["errors"]]
                    raise BinanceClientError(
                        f"Market order validation failed for '{symbol}' {side}, qty {qty}: {', '.join(error_msgs)}"
                    )
                else:
                    self.write_msg(f"Warning: Quantity changed in Market Order for symbol '{symbol}': qty {qty} -> {result['qty']}")

            qty = result["qty"]  # Update qty after validation

            result = self.client.create_order(symbol=symbol, side=side, type=type, quantity=qty)
            return result
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)

    
    '''
    Place a limit order
    '''
    def place_limit_order(self, symbol: str, side: str, qty: float, price: float):
        try:
            s = self.symbol_limits[symbol]
            type = "LIMIT"
            timeInForce = "GTC" # Good Till Cancel – stays open until you cancel it manually

            # round to allowed precision
            price   = round_step(price, s.tick_size)
            qty     = round_step(qty, s.step_size)

            # Validate if the order is valid
            result = self.validate_order(symbol, qty, price)

            if not result["is_valid"]:
                if result["is_fatal_error"]:
                    error_msgs = [str(e) for e in result["errors"]]
                    raise BinanceClientError(
                        f"Limit order validation failed for '{symbol}' {side}, price {price}, qty {qty}: {', '.join(error_msgs)}"
                    )
                else:
                    self.write_msg(f"Warning: Values changed in Limit Order for symbol '{symbol}': price {price} -> {result['price']}, qty {qty} -> {result['qty']}")
            
            price   = result["price"]  # Update price after validation
            qty     = result["qty"]    # Update qty after validation

            result = self.client.create_order(symbol=symbol, side=side, type=type, timeInForce=timeInForce, quantity=qty, price=price)
            return result
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)

    
    '''
    Cancel an active order
    '''
    def cancel_order(self, symbol: str, order_id: int):
        try:
            canceled = self.client.cancel_order(symbol=symbol, orderId=order_id)
            return canceled
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)


    '''
    Get order detailes for a specific order (Do Not use for price information!)
    '''
    def get_order(self, symbol: str, order_id: int):
        try:
            order = self.client.get_order(symbol=symbol, orderId=order_id)
            return self.normalize_order(order)
        except BinanceAPIException as e:
            self.write_msg(f"get_order failed: {e}")
            return None

    
    '''
    Get details for all open orders (Use if information about open orders is needed. Do Not use for price information!)
    '''
    def get_all_orders(self, symbol: str, limit=100):
        """Get all orders for a symbol. Returns raw API dicts for compatibility."""
        try:
            orders = self.client.get_all_orders(symbol=symbol, limit=limit)
            return orders
        except BinanceAPIException as e:
            self.write_msg(f"get_all_orders failed: {e}")
            return []

    def get_all_orders_normalized(self, symbol: str, limit=100):
        """Get all orders for a symbol with normalized field names."""
        orders = self.get_all_orders(symbol=symbol, limit=limit)
        return [self.normalize_order(o) for o in orders]
        

    '''
    Get details for all trades (Use if information about filled trades is needed)
    '''
    def get_all_trades(self, symbol: str, limit=100):
        try:
            trades = self.client.get_my_trades(symbol=symbol, limit=limit)
            trades_list = [self.normalize_trades(t) for t in trades]
            return trades_list
        except BinanceAPIException as e:
            self.write_msg(f"get_all_trades failed: {e}")
            return []

    
    '''
    Get all trades for a specific order ID as list
    '''
    def get_trades_by_order_id(self, symbol: str, order_id: int):
        try:
            trades = self.get_all_trades(symbol=symbol, limit=100)
            trades.sort(key=lambda x: x['time'], reverse=True)

            trade_list = []
            for trade in trades:
                if trade["order_id"] == order_id:
                    trade_list.append(trade)
            
            return trade_list
        except BinanceAPIException as e:
            self.write_msg(f"get_trades_by_order_id failed: {e}")
            return []
        

    # ----------------------------
    # --- NORMALIZER FUNCTIONS ---
    # ----------------------------

    '''
    Convert Binance order response into consistent structure
    '''
    def normalize_order(self, order_dict: dict) -> dict:
        return {
            "symbol": order_dict["symbol"],
            "order_id": int(order_dict["orderId"]),
            "order_list_id": int(order_dict["orderListId"]),
            "client_order_id": order_dict["clientOrderId"],
            "type": order_dict["type"],
            "side": order_dict["side"],
            "status": order_dict["status"],
            "orig_qty": float(order_dict["origQty"]),
            "executed_qty": float(order_dict["executedQty"]),
            "limit_price": float(order_dict["price"]) if float(order_dict["price"]) > 0 else None,
            "avg_price": float(order_dict.get("avgPrice", 0)) if float(order_dict.get("avgPrice", 0)) > 0 else None,
            "create_time": int(order_dict["time"]),
            "update_time": int(order_dict["updateTime"]),
            "working_time": int(order_dict["workingTime"]),
            "time_in_force": order_dict["timeInForce"]
        }


    '''
    Convert Binance trade response into consistent structure
    '''
    def normalize_trades(self, trade_dict: dict) -> dict:
        return {
            "symbol": trade_dict["symbol"],
            "trade_id": int(trade_dict["id"]),
            "order_id": int(trade_dict["orderId"]),
            "order_list_id": int(trade_dict.get("orderListId", -1)),
            "price": float(trade_dict["price"]),
            "qty": float(trade_dict["qty"]),
            "quote_qty": float(trade_dict["quoteQty"]),
            "commission": float(trade_dict["commission"]),
            "commission_asset": trade_dict["commissionAsset"],
            "time": int(trade_dict["time"]),
            "is_buyer": trade_dict["isBuyer"],
            "is_maker": trade_dict["isMaker"],
            "is_best_match": trade_dict["isBestMatch"]
        }


    # ----------------------------------------
    # --- APP COMPATIBILITY METHODS ---
    # ----------------------------------------

    '''
    Get raw account info dict from Binance API
    '''
    def get_account_info(self) -> dict:
        try:
            return self.client.get_account()
        except BinanceAPIException as e:
            raise BinanceClientError.from_api_exception(e)

    '''
    Get balance list, optionally filtered to non-zero balances
    '''
    def get_balances(self, non_zero_only: bool = True) -> list[dict]:
        account = self.get_account_info()
        balances = account.get('balances', [])
        if non_zero_only:
            balances = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        return balances

    '''
    Get sorted list of all trading symbols
    '''
    def get_all_symbols(self) -> list[str]:
        prices = self.get_all_prices()
        return sorted(list(prices.keys()))

    '''
    Calculate portfolio value from balances and prices.
    Returns (usdt_balance, portfolio_value, asset_data_list).
    '''
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

    '''
    Adjust quantity to match symbol step size and min/max constraints.
    Returns 0.0 if quantity is below minimum.
    '''
    def adjust_quantity(self, symbol: str, quantity: float, is_market_order: bool = False) -> float:
        if symbol not in self.symbol_limits:
            return quantity

        s = self.symbol_limits[symbol]
        qty = round_step(quantity, s.step_size)

        if qty > s.max_qty:
            qty = round_step(s.max_qty, s.step_size)

        if qty < s.min_qty:
            return 0.0

        return qty

    '''
    Get minimum lot size for market orders
    '''
    def get_min_market_lot_size(self, symbol: str) -> float:
        if symbol in self.symbol_limits:
            return self.symbol_limits[symbol].min_qty
        return 0.0

    '''
    Get maximum lot size for market orders
    '''
    def get_max_market_lot_size(self, symbol: str) -> float:
        if symbol in self.symbol_limits:
            return self.symbol_limits[symbol].max_qty
        return float('inf')

    '''
    Unified order placement. Routes to market or limit order with validation.
    Supports quote_order_qty for market buy orders (buy with USDT amount).
    '''
    def place_order(self, symbol: str, side: str, order_type: str,
                    quantity: float = None, quote_order_qty: float = None,
                    price: float = None, time_in_force: str = "GTC") -> dict:
        if order_type == "MARKET":
            if quote_order_qty is not None:
                # Buy/Sell with quote asset amount (e.g. spend X USDT)
                try:
                    return self.client.create_order(
                        symbol=symbol, side=side, type="MARKET",
                        quoteOrderQty=quote_order_qty
                    )
                except BinanceAPIException as e:
                    raise BinanceClientError.from_api_exception(e)
            else:
                return self.place_market_order(symbol, side, quantity)
        elif order_type == "LIMIT":
            return self.place_limit_order(symbol, side, quantity, price)
        else:
            raise BinanceClientError(f"Unsupported order type: {order_type}")

    '''
    Get symbol filter information (compatibility method)
    '''
    def get_symbol_filters(self, symbol: str) -> dict | None:
        if symbol in self.symbol_limits:
            return self.symbol_limits[symbol]
        return None

