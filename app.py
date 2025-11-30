"""
Binance Spot Testnet GUI

Main application entry point. Handles initialization and orchestrates
the GUI components with their handlers.
"""

import streamlit as st
from libs.exchange import BinanceClient
from libs.exchange.client import BinanceClientError
from libs.gui import GUIComponents, GUIHandlers


# ========== Cached Data Functions ==========
# These use Streamlit's caching to avoid repeated API calls

@st.cache_data(ttl=2)
def get_account_info(_client: BinanceClient):
    """Cached account info fetch."""
    try:
        return _client.get_account_info()
    except BinanceClientError as e:
        st.error(str(e))
        return None


@st.cache_data(ttl=5)
def get_prices(_client: BinanceClient):
    """Cached price data fetch."""
    try:
        return _client.get_all_prices()
    except BinanceClientError as e:
        st.error(str(e))
        return {}


def get_open_orders(client: BinanceClient, symbol=None):
    """Fetch open orders."""
    try:
        return client.get_open_orders(symbol=symbol)
    except BinanceClientError as e:
        st.error(str(e))
        return []


def get_all_orders(client: BinanceClient, symbol: str):
    """Fetch order history for a symbol."""
    return client.get_all_orders(symbol)


# ========== Main Application ==========

def main():
    # Initialize session state
    if "activity_log" not in st.session_state:
        st.session_state.activity_log = []
    
    # Initialize client
    client = BinanceClient()
    
    # Initialize handlers and components
    handlers = GUIHandlers(client)
    gui = GUIComponents(handlers)
    
    # Setup page
    gui.setup_page()
    
    # Sidebar header
    st.sidebar.header("Actions")
    
    # Fetch data
    account = get_account_info(client)
    prices = get_prices(client)
    all_symbols = sorted(list(prices.keys()))
    assets = []
    
    if account:
        # Get non-zero balances
        balances = account['balances']
        assets = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        
        # Calculate portfolio value
        usdt_balance, portfolio_value, asset_data = client.calculate_portfolio_value(assets, prices)
        
        # Render dashboard
        gui.render_portfolio_summary(usdt_balance, portfolio_value)
        gui.render_assets_table(asset_data, all_symbols)
        
        # Render trading sidebar
        symbol_input, current_price = gui.render_symbol_selector(all_symbols, prices)
        gui.render_trading_tabs(symbol_input, current_price, account)
        
        # Render open orders
        open_orders = get_open_orders(client)
        gui.render_open_orders(open_orders)
        
        # Render order history
        gui.render_order_history(
            symbol_input, 
            assets, 
            all_symbols, 
            lambda sym: get_all_orders(client, sym)
        )
        
        # Render danger zone
        gui.render_danger_zone()
    
    # Render activity log (always visible)
    gui.render_activity_log()


if __name__ == "__main__":
    main()

