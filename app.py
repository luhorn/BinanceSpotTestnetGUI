"""
Binance Spot Testnet GUI - Flask Version

Main application entry point using Flask with AJAX-based refreshing.
"""

from flask import Flask, render_template, jsonify, request
import time
import os

from libs.exchange import BinanceClient
from libs.exchange.client import BinanceClientError

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Global client instance
_client = None

def get_client() -> BinanceClient:
    """Get or create the Binance client instance."""
    global _client
    if _client is None:
        _client = BinanceClient()
    return _client


# ========== Cache with TTL ==========

class TTLCache:
    """Simple TTL cache for API data."""
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
    
    def get(self, key: str, ttl: int = 5):
        """Get cached value if not expired."""
        if key in self._cache:
            if time.time() - self._timestamps.get(key, 0) < ttl:
                return self._cache[key]
        return None
    
    def set(self, key: str, value):
        """Set cache value with current timestamp."""
        self._cache[key] = value
        self._timestamps[key] = time.time()
    
    def clear(self):
        """Clear all cached data."""
        self._cache.clear()
        self._timestamps.clear()

cache = TTLCache()


# ========== Activity Log ==========

activity_log = []

def add_log(message: str, level: str = "info"):
    """Add entry to activity log."""
    global activity_log
    activity_log.insert(0, {
        "msg": message,
        "level": level,
        "time": time.strftime("%H:%M:%S")
    })
    # Keep only last 50 entries
    if len(activity_log) > 50:
        activity_log = activity_log[:50]


# ========== Data Fetching ==========

def get_account_info(force_refresh: bool = False):
    """Get account info with caching."""
    if not force_refresh:
        cached = cache.get('account_info', ttl=2)
        if cached is not None:
            return cached
    
    try:
        client = get_client()
        data = client.get_account_info()
        cache.set('account_info', data)
        return data
    except BinanceClientError as e:
        add_log(f"Error fetching account: {e}", "error")
        return None


def get_prices(force_refresh: bool = False):
    """Get all prices with caching."""
    if not force_refresh:
        cached = cache.get('prices', ttl=5)
        if cached is not None:
            return cached
    
    try:
        client = get_client()
        data = client.get_all_prices()
        cache.set('prices', data)
        return data
    except BinanceClientError as e:
        add_log(f"Error fetching prices: {e}", "error")
        return {}


def get_open_orders(symbol=None):
    """Fetch open orders."""
    try:
        client = get_client()
        return client.get_open_orders(symbol=symbol)
    except BinanceClientError as e:
        add_log(f"Error fetching orders: {e}", "error")
        return []


def get_all_orders(symbol: str):
    """Fetch order history for a symbol."""
    try:
        client = get_client()
        return client.get_all_orders(symbol)
    except BinanceClientError:
        return []


# ========== Helper Functions ==========

def format_number(value: float) -> str:
    """Format number with European style (comma as decimal separator)."""
    if value is None:
        return "0,00"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calculate_portfolio_data():
    """Calculate all portfolio data for the dashboard."""
    account = get_account_info()
    prices = get_prices()
    
    if not account:
        return None
    
    client = get_client()
    balances = account.get('balances', [])
    
    # Filter non-zero balances
    assets = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
    
    # Calculate portfolio value
    usdt_balance, portfolio_value, asset_data = client.calculate_portfolio_value(assets, prices)
    
    return {
        'usdt_balance': usdt_balance,
        'portfolio_value': portfolio_value,
        'assets': asset_data,
        'all_symbols': sorted(list(prices.keys())),
        'prices': prices
    }


# ========== Page Routes ==========

@app.route('/')
def index():
    """Main dashboard page."""
    data = calculate_portfolio_data()
    if data is None:
        return render_template('error.html', message="Failed to connect to Binance API")
    
    return render_template('index.html',
        usdt_balance=format_number(data['usdt_balance']),
        portfolio_value=format_number(data['portfolio_value']),
        assets=data['assets'],
        all_symbols=data['all_symbols'],
        prices=data['prices'],
        format_number=format_number
    )


# ========== API Routes ==========

@app.route('/api/refresh')
def api_refresh():
    """Refresh all data and return updated dashboard info."""
    cache.clear()
    data = calculate_portfolio_data()
    
    if data is None:
        return jsonify({'error': 'Failed to fetch data'}), 500
    
    # Format asset data for JSON
    formatted_assets = []
    for asset in data['assets']:
        formatted_assets.append({
            'Asset': asset['Asset'],
            'Free': format_number(asset['Free']),
            'Locked': format_number(asset['Locked']),
            'Total': format_number(asset['Total']),
            'Value': format_number(asset['Value (USDT)']),
            'RawValue': asset['Value (USDT)']
        })
    
    return jsonify({
        'usdt_balance': format_number(data['usdt_balance']),
        'portfolio_value': format_number(data['portfolio_value']),
        'assets': formatted_assets,
        'all_symbols': data['all_symbols']
    })


@app.route('/api/price/<symbol>')
def api_get_price(symbol):
    """Get current price for a symbol."""
    prices = get_prices()
    price = prices.get(symbol, 0.0)
    return jsonify({
        'symbol': symbol,
        'price': price,
        'formatted': format_number(price)
    })


@app.route('/api/open_orders')
def api_open_orders():
    """Get all open orders."""
    orders = get_open_orders()
    return jsonify({'orders': orders})


@app.route('/api/order_history/<symbol>')
def api_order_history(symbol):
    """Get order history for a symbol."""
    orders = get_all_orders(symbol)
    
    # Format timestamps
    for order in orders:
        if 'time' in order:
            order['time_formatted'] = time.strftime('%Y-%m-%d %H:%M:%S', 
                time.localtime(order['time'] / 1000))
    
    return jsonify({'orders': orders})


@app.route('/api/activity_log')
def api_activity_log():
    """Get activity log entries."""
    return jsonify({'log': activity_log})


@app.route('/api/buy', methods=['POST'])
def api_buy():
    """Place a buy order."""
    data = request.get_json()
    
    symbol = data.get('symbol')
    order_type = data.get('order_type', 'LIMIT')
    quantity = float(data.get('quantity', 0))
    total_usdt = float(data.get('total_usdt', 0))
    price = float(data.get('price', 0))
    
    client = get_client()
    
    try:
        qty_to_log = 0
        
        if quantity > 0:
            is_market = order_type == "MARKET"
            adjusted_qty = client.adjust_quantity(symbol, quantity, is_market_order=is_market)
            
            if adjusted_qty <= 0:
                add_log("Buy Failed: Quantity too small after adjustment.", "error")
                return jsonify({'success': False, 'error': 'Quantity too small'}), 400
            
            client.place_order(
                symbol=symbol,
                side="BUY",
                order_type=order_type,
                quantity=adjusted_qty,
                price=price if order_type == "LIMIT" else None
            )
            qty_to_log = adjusted_qty
            
        elif total_usdt > 0:
            if order_type == "MARKET":
                client.place_order(
                    symbol=symbol,
                    side="BUY",
                    order_type=order_type,
                    quote_order_qty=total_usdt
                )
                qty_to_log = f"{total_usdt} USDT"
            else:
                # LIMIT: Calculate quantity from total
                if price <= 0:
                    add_log("Buy Failed: Price must be > 0 to calculate quantity from total.", "error")
                    return jsonify({'success': False, 'error': 'Price must be > 0'}), 400
                
                calc_qty = total_usdt / price
                adjusted_qty = client.adjust_quantity(symbol, calc_qty)
                
                if adjusted_qty <= 0:
                    add_log("Buy Failed: Calculated quantity too small.", "error")
                    return jsonify({'success': False, 'error': 'Quantity too small'}), 400
                
                client.place_order(
                    symbol=symbol,
                    side="BUY",
                    order_type=order_type,
                    quantity=adjusted_qty,
                    price=price
                )
                qty_to_log = adjusted_qty
        else:
            add_log("Buy Failed: Please enter Quantity or Total (USDT).", "error")
            return jsonify({'success': False, 'error': 'Enter quantity or total'}), 400
        
        add_log(f"Buy Order Placed: {symbol}, Qty: {qty_to_log}", "success")
        cache.clear()  # Clear cache to refresh data
        return jsonify({'success': True})
        
    except BinanceClientError as e:
        if e.is_notional_error():
            add_log("Buy Failed: Order value too small (min ~10 USDT).", "error")
            return jsonify({'success': False, 'error': 'Order value too small (min ~10 USDT)'}), 400
        else:
            add_log(f"Buy Order Failed: {e}", "error")
            return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/sell', methods=['POST'])
def api_sell():
    """Place a sell order."""
    data = request.get_json()
    
    symbol = data.get('symbol')
    order_type = data.get('order_type', 'LIMIT')
    quantity = float(data.get('quantity', 0))
    price = float(data.get('price', 0))
    current_price = float(data.get('current_price', 0))
    
    # Check estimated value
    if order_type == "LIMIT":
        estimated_value = quantity * price
    else:
        estimated_value = quantity * current_price
    
    if estimated_value < 10.0:
        add_log(f"Sell Failed: Order value {estimated_value:.2f} USDT is too small (min ~10 USDT).", "error")
        return jsonify({'success': False, 'error': f'Order value {estimated_value:.2f} USDT too small'}), 400
    
    client = get_client()
    
    try:
        is_market = order_type == "MARKET"
        adjusted_qty = client.adjust_quantity(symbol, quantity, is_market_order=is_market)
        
        if adjusted_qty <= 0:
            add_log("Sell Failed: Quantity too small after adjustment.", "error")
            return jsonify({'success': False, 'error': 'Quantity too small'}), 400
        
        client.place_order(
            symbol=symbol,
            side="SELL",
            order_type=order_type,
            quantity=adjusted_qty,
            price=price if order_type == "LIMIT" else None
        )
        add_log(f"Sell Order Placed: {symbol}, Qty: {adjusted_qty}", "success")
        cache.clear()
        return jsonify({'success': True})
        
    except BinanceClientError as e:
        if e.is_notional_error():
            add_log("Sell Failed: Order value too small (min ~10 USDT).", "error")
        elif e.is_lot_size_error():
            add_log(f"Sell Failed: Quantity {quantity} invalid for LOT_SIZE filter.", "error")
        else:
            add_log(f"Sell Order Failed: {e}", "error")
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/cancel_order', methods=['POST'])
def api_cancel_order():
    """Cancel an order."""
    data = request.get_json()
    
    symbol = data.get('symbol')
    order_id = data.get('order_id')
    
    if not order_id or not symbol:
        add_log("Cancel Failed: Order ID and Symbol are required.", "error")
        return jsonify({'success': False, 'error': 'Order ID and Symbol required'}), 400
    
    client = get_client()
    
    try:
        client.cancel_order(symbol=symbol, order_id=order_id)
        add_log(f"Order {order_id} cancelled", "success")
        cache.clear()
        return jsonify({'success': True})
    except BinanceClientError as e:
        add_log(f"Cancel Failed: {e}", "error")
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reset_portfolio', methods=['POST'])
def api_reset_portfolio():
    """Reset portfolio - cancel all orders and sell all assets."""
    client = get_client()
    add_log("Starting Portfolio Reset...", "warning")
    
    try:
        # 1. Cancel all open orders
        open_orders = client.get_open_orders()
        if open_orders:
            for order in open_orders:
                client.cancel_order(symbol=order['symbol'], order_id=order['orderId'])
            add_log(f"Cancelled {len(open_orders)} open orders.", "success")
        else:
            add_log("No open orders to cancel.", "info")
        
        # 2. Analyze and sell assets
        prices = client.get_all_prices()
        balances = client.get_balances(non_zero_only=True)
        
        sellable_assets = []
        dust_assets = []
        no_pair_assets = []
        
        for b in balances:
            asset_name = b['asset']
            free_amt = float(b['free'])
            
            if asset_name != 'USDT' and free_amt > 0:
                pair = f"{asset_name}USDT"
                if pair in prices:
                    price = prices[pair]
                    value = free_amt * price
                    if value >= 10.0:
                        sellable_assets.append((asset_name, free_amt, pair))
                    else:
                        dust_assets.append((asset_name, free_amt, pair))
                else:
                    no_pair_assets.append(asset_name)
        
        if no_pair_assets:
            add_log(f"Skipping {len(no_pair_assets)} assets without USDT pairs", "info")
        
        # Sell sellable assets
        for asset_name, free_amt, pair in sellable_assets:
            try:
                min_qty = client.get_min_market_lot_size(pair)
                max_qty = client.get_max_market_lot_size(pair)
                
                remaining = free_amt
                total_sold = 0.0
                
                while remaining > 0:
                    qty_to_sell = client.adjust_quantity(pair, remaining, is_market_order=True)
                    
                    if qty_to_sell <= 0 or qty_to_sell < min_qty:
                        if total_sold == 0:
                            dust_assets.append((asset_name, remaining, pair))
                        break
                    
                    result = client.place_order(
                        symbol=pair,
                        side='SELL',
                        order_type='MARKET',
                        quantity=qty_to_sell
                    )
                    
                    status = result.get('status', '')
                    executed_qty = float(result.get('executedQty', 0))
                    
                    if status == 'EXPIRED' or executed_qty == 0:
                        add_log(f"Cannot sell {asset_name}: No liquidity on testnet.", "warning")
                        break
                    
                    total_sold += executed_qty
                    remaining -= executed_qty
                    add_log(f"Sold {executed_qty} {asset_name}", "success")
                    
                    if remaining > 0 and remaining >= min_qty:
                        time.sleep(0.3)
                    else:
                        break
                        
            except BinanceClientError as e:
                add_log(f"Failed to sell {asset_name}: {e}", "error")
        
        # Sweep dust assets
        if dust_assets:
            add_log(f"Found {len(dust_assets)} dust assets. Attempting to sweep...", "info")
            
            account = client.get_account_info()
            usdt_balance = 0.0
            for b in account['balances']:
                if b['asset'] == 'USDT':
                    usdt_balance = float(b['free'])
                    break
            
            for asset_name, free_amt, pair in dust_assets:
                if usdt_balance < 11.0:
                    add_log(f"Skipping dust sweep: Insufficient USDT", "warning")
                    break
                
                try:
                    buy_result = client.place_order(
                        symbol=pair,
                        side='BUY',
                        order_type='MARKET',
                        quote_order_qty=11.0
                    )
                    
                    if buy_result.get('status') == 'EXPIRED' or float(buy_result.get('executedQty', 0)) == 0:
                        continue
                    
                    time.sleep(0.5)
                    
                    sub_acc = client.get_account_info()
                    new_bal = 0.0
                    for b in sub_acc['balances']:
                        if b['asset'] == asset_name:
                            new_bal = float(b['free'])
                            break
                    
                    qty_to_sell = client.adjust_quantity(pair, new_bal, is_market_order=True)
                    if qty_to_sell > 0:
                        client.place_order(
                            symbol=pair,
                            side='SELL',
                            order_type='MARKET',
                            quantity=qty_to_sell
                        )
                        add_log(f"Swept dust: Sold {qty_to_sell} {asset_name}", "success")
                        
                except BinanceClientError as e:
                    add_log(f"Failed to sweep {asset_name}: {e}", "warning")
        
        add_log("Portfolio Reset Complete.", "success")
        cache.clear()
        return jsonify({'success': True})
        
    except BinanceClientError as e:
        add_log(f"Error during reset: {e}", "error")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/balance/<asset>')
def api_get_balance(asset):
    """Get balance for a specific asset."""
    account = get_account_info()
    if not account:
        return jsonify({'balance': 0.0})
    
    for b in account.get('balances', []):
        if b['asset'] == asset:
            return jsonify({
                'asset': asset,
                'free': float(b['free']),
                'locked': float(b['locked'])
            })
    
    return jsonify({'asset': asset, 'free': 0.0, 'locked': 0.0})


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)

