"""
Binance Spot Testnet GUI - Flask Version

Main application entry point using Flask with AJAX-based refreshing.
"""

from flask import Flask, render_template, jsonify, request
import time
import os
import json
from datetime import datetime

from libs.exchange import BinanceClient
from libs.exchange.client import BinanceClientError
from libs.portfolio import PortfolioHistory

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ========== Configuration ==========

CONFIG_PATH = 'resources/config.json'

def load_config() -> dict:
    """Load configuration from file."""
    default_config = {
        'hide_small_assets': False,
        'hidden_assets': []
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                return {**default_config, **config}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading config: {e}")
    return default_config


def save_config(config: dict) -> bool:
    """Save configuration to file."""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except IOError as e:
        print(f"Error saving config: {e}")
        return False

# Global client instance
_client = None

def get_client() -> BinanceClient:
    """Get or create the Binance client instance."""
    global _client
    if _client is None:
        _client = BinanceClient()
    return _client


# ========== Portfolio History ==========

PORTFOLIO_HISTORY_PATH = 'resources/portfolio_history.json'
portfolio_history = PortfolioHistory(data_file=PORTFOLIO_HISTORY_PATH)


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


def save_portfolio_snapshot(force: bool = False) -> bool:
    """
    Save current portfolio state to history.
    
    Args:
        force: Force save even if recent snapshot exists
    
    Returns:
        True if snapshot was saved
    """
    data = calculate_portfolio_data()
    if not data or data['portfolio_value'] <= 0:
        return False
    
    # Extract asset details for backfilling
    asset_details = {}
    for asset in data['assets']:
        symbol = asset['Asset']
        asset_details[symbol] = {
            'quantity': asset['Total'],
            'value_usdt': asset['Value (USDT)']
        }
    
    success = portfolio_history.add_snapshot(
        timestamp=time.time(),
        total_value=data['portfolio_value'],
        usdt_balance=data['usdt_balance'],
        asset_count=len(data['assets']),
        assets_detail=asset_details
    )
    
    if success:
        # Update current holdings for future backfilling
        holdings = {asset['Asset']: asset['Total'] for asset in data['assets']}
        portfolio_history.update_current_holdings(holdings)
    
    return success


def backfill_portfolio_history(time_range: str) -> int:
    """
    Backfill missing historical data for the requested time range.
    
    Args:
        time_range: One of '1d', '1w', '1m', '6m', '1y', 'ytd', 'all'
    
    Returns:
        Number of snapshots added
    """
    # Ensure portfolio_history has the client
    portfolio_history.set_client(get_client())
    
    # Get current asset holdings
    data = calculate_portfolio_data()
    if not data:
        return 0
    
    current_assets = {asset['Asset']: asset['Total'] for asset in data['assets']}
    
    # Calculate time range
    now = time.time()
    start_time = portfolio_history.get_range_start_time(time_range)
    
    # Get appropriate interval for the range
    interval = portfolio_history.get_interval_for_range(time_range)
    
    # Backfill
    return portfolio_history.backfill_history(
        current_assets=current_assets,
        start_time=start_time,
        end_time=now,
        interval=interval
    )


# ========== Page Routes ==========

@app.route('/')
def index():
    """Main dashboard page."""
    data = calculate_portfolio_data()
    if data is None:
        return render_template('error.html', message="Failed to connect to Binance API")
    
    config = load_config()
    hidden_assets = config.get('hidden_assets', [])
    
    # Filter out hidden assets from the display
    filtered_assets = [a for a in data['assets'] if a['Asset'] not in hidden_assets]
    
    return render_template('index.html',
        usdt_balance=format_number(data['usdt_balance']),
        portfolio_value=format_number(data['portfolio_value']),
        assets=filtered_assets,
        all_symbols=data['all_symbols'],
        prices=data['prices'],
        format_number=format_number,
        config=config
    )


# ========== API Routes ==========

@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get current configuration."""
    return jsonify(load_config())


@app.route('/api/config', methods=['POST'])
def api_save_config():
    """Save configuration."""
    data = request.get_json()
    config = load_config()
    
    # Update only the fields that are provided
    if 'hide_small_assets' in data:
        config['hide_small_assets'] = bool(data['hide_small_assets'])
    if 'hidden_assets' in data:
        config['hidden_assets'] = list(data['hidden_assets'])
    
    if save_config(config):
        add_log("Configuration saved", "success")
        return jsonify({'success': True, 'config': config})
    else:
        return jsonify({'success': False, 'error': 'Failed to save config'}), 500


@app.route('/api/config/hide_asset', methods=['POST'])
def api_hide_asset():
    """Add an asset to the hidden list."""
    data = request.get_json()
    asset = data.get('asset')
    
    if not asset:
        return jsonify({'success': False, 'error': 'Asset name required'}), 400
    
    config = load_config()
    if asset not in config['hidden_assets']:
        config['hidden_assets'].append(asset)
        save_config(config)
        add_log(f"Asset {asset} hidden from overview", "info")
    
    return jsonify({'success': True, 'hidden_assets': config['hidden_assets']})


@app.route('/api/config/unhide_asset', methods=['POST'])
def api_unhide_asset():
    """Remove an asset from the hidden list."""
    data = request.get_json()
    asset = data.get('asset')
    
    if not asset:
        return jsonify({'success': False, 'error': 'Asset name required'}), 400
    
    config = load_config()
    if asset in config['hidden_assets']:
        config['hidden_assets'].remove(asset)
        save_config(config)
        add_log(f"Asset {asset} restored to overview", "info")
    
    return jsonify({'success': True, 'hidden_assets': config['hidden_assets']})


@app.route('/api/refresh')
def api_refresh():
    """Refresh all data and return updated dashboard info."""
    cache.clear()
    data = calculate_portfolio_data()
    
    if data is None:
        return jsonify({'error': 'Failed to fetch data'}), 500
    
    # Save portfolio snapshot on refresh
    try:
        save_portfolio_snapshot()
    except Exception as e:
        print(f"Warning: Failed to save portfolio snapshot: {e}")
    
    config = load_config()
    hidden_assets = config.get('hidden_assets', [])
    
    # Format asset data for JSON, excluding hidden assets
    formatted_assets = []
    for asset in data['assets']:
        if asset['Asset'] in hidden_assets:
            continue
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
        'all_symbols': data['all_symbols'],
        'config': config
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
    
    # Format timestamps and price
    for order in orders:
        if 'time' in order:
            order['time_formatted'] = time.strftime('%Y-%m-%d %H:%M:%S', 
                time.localtime(order['time'] / 1000))
        
        # Format price - convert from string to float with 4 decimal places
        # For market orders that filled, price may be "0", so calculate from fills
        price = float(order.get('price', 0))
        if price == 0 and order.get('executedQty', 0) and float(order.get('executedQty', 0)) > 0:
            # For filled orders with price 0, try to get average price from cummulativeQuoteQty
            cumulative_quote = float(order.get('cummulativeQuoteQty', 0))
            executed_qty = float(order.get('executedQty', 0))
            if executed_qty > 0:
                price = cumulative_quote / executed_qty
        
        order['price'] = f"{price:.4f}"
    
    return jsonify({'orders': orders})


@app.route('/api/activity_log')
def api_activity_log():
    """Get activity log entries."""
    return jsonify({'log': activity_log})


@app.route('/api/portfolio_history')
def api_portfolio_history():
    """
    Get portfolio history for a time range.
    
    Query params:
        range: Time range (1d, 1w, 1m, 6m, 1y, ytd, all). Default: 1w
        backfill: Enable historical backfilling (true/false). Default: true
    """
    time_range = request.args.get('range', '1w')
    enable_backfill = request.args.get('backfill', 'true').lower() == 'true'
    
    # Ensure the client is set for backfilling
    portfolio_history.set_client(get_client())
    
    # Backfill missing data if requested and needed
    if enable_backfill and portfolio_history.should_backfill(time_range):
        try:
            added = backfill_portfolio_history(time_range)
            if added > 0:
                add_log(f"Backfilled {added} historical data points", "info")
        except Exception as e:
            add_log(f"Backfill failed: {e}", "warning")
    
    # Get data for the requested range
    start_time = portfolio_history.get_range_start_time(time_range)
    end_time = time.time()
    
    snapshots = portfolio_history.get_history(start_time, end_time)
    
    # Calculate statistics
    stats = portfolio_history.calculate_stats(snapshots)
    
    # Format data for chart (timestamp, value pairs)
    chart_data = [
        {'timestamp': s['timestamp'], 'value': s['total_value']}
        for s in snapshots
    ]
    
    return jsonify({
        'success': True,
        'range': time_range,
        'data': chart_data,
        'stats': stats,
        'total_points': len(chart_data)
    })


@app.route('/api/portfolio_snapshot', methods=['POST'])
def api_save_snapshot():
    """Manually trigger a portfolio snapshot save."""
    try:
        success = save_portfolio_snapshot(force=True)
        if success:
            add_log("Portfolio snapshot saved", "success")
            return jsonify({'success': True, 'message': 'Snapshot saved'})
        else:
            return jsonify({'success': False, 'message': 'Snapshot skipped (too recent)'})
    except Exception as e:
        add_log(f"Failed to save snapshot: {e}", "error")
        return jsonify({'success': False, 'error': str(e)}), 500


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
            error_msg = "Order value too small (min ~10 USDT)"
        elif e.is_insufficient_balance():
            error_msg = "Insufficient balance for this order"
        elif e.is_lot_size_error():
            error_msg = "Invalid quantity for this symbol"
        else:
            error_msg = e.get_user_message()
        add_log(f"Buy Failed: {error_msg}", "error")
        return jsonify({'success': False, 'error': error_msg}), 400


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
        
        # Check market lot size constraints for market orders
        if is_market:
            max_market_qty = client.get_max_market_lot_size(symbol)
            if max_market_qty > 0 and quantity > max_market_qty:
                add_log(f"Sell Warning: Quantity {quantity} exceeds max market lot size {max_market_qty} for {symbol}. Order will be reduced.", "warning")
        
        adjusted_qty = client.adjust_quantity(symbol, quantity, is_market_order=is_market)
        
        if adjusted_qty <= 0:
            min_qty = client.get_min_market_lot_size(symbol) if is_market else 0
            add_log(f"Sell Failed: Quantity too small after adjustment (min: {min_qty}).", "error")
            return jsonify({'success': False, 'error': 'Quantity too small'}), 400
        
        # Log if quantity was significantly reduced
        if adjusted_qty < quantity * 0.99:  # More than 1% reduction
            add_log(f"Sell Info: Quantity adjusted from {quantity} to {adjusted_qty} for {symbol}", "info")
        
        result = client.place_order(
            symbol=symbol,
            side="SELL",
            order_type=order_type,
            quantity=adjusted_qty,
            price=price if order_type == "LIMIT" else None
        )
        
        # Check order status from response
        order_status = result.get('status', 'UNKNOWN')
        if order_status == 'FILLED':
            add_log(f"Sell Order Filled: {symbol}, Qty: {adjusted_qty}", "success")
        elif order_status == 'NEW':
            add_log(f"Sell Order Placed (Open): {symbol}, Qty: {adjusted_qty}, Price: {price}", "success")
        elif order_status == 'PARTIALLY_FILLED':
            filled_qty = result.get('executedQty', 'unknown')
            add_log(f"Sell Order Partially Filled: {symbol}, Filled: {filled_qty}/{adjusted_qty}", "success")
        elif order_status == 'EXPIRED' or order_status == 'EXPIRED_IN_MATCH':
            add_log(f"Sell Order Expired: {symbol}, Qty: {adjusted_qty} - No matching liquidity", "warning")
        elif order_status == 'CANCELED':
            add_log(f"Sell Order Cancelled: {symbol}, Qty: {adjusted_qty}", "warning")
        else:
            add_log(f"Sell Order {order_status}: {symbol}, Qty: {adjusted_qty}", "success")
        
        cache.clear()
        return jsonify({'success': True, 'status': order_status})
        
    except BinanceClientError as e:
        if e.is_notional_error():
            error_msg = "Order value too small (min ~10 USDT)"
        elif e.is_insufficient_balance():
            error_msg = "Insufficient balance for this order"
        elif e.is_market_lot_size_error():
            max_qty = client.get_max_market_lot_size(symbol)
            error_msg = f"Quantity exceeds max market lot size ({max_qty})"
        elif e.is_lot_size_error():
            error_msg = "Invalid quantity for this symbol"
        elif e.is_liquidity_error():
            error_msg = "No liquidity available for this order"
        else:
            error_msg = e.get_user_message()
        add_log(f"Sell Failed: {error_msg}", "error")
        return jsonify({'success': False, 'error': error_msg}), 400


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

