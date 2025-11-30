"""
GUI Components Module

This module contains all the UI component definitions for the Binance Spot Testnet GUI.
It focuses purely on layout and display, with handlers provided separately.
"""

import streamlit as st
import pandas as pd
from typing import Callable, Optional


class GUIComponents:
    def __init__(self, handlers):
        self.handlers = handlers
        self._log_placeholder = None
    

    # ========== Utility Functions ==========
    
    @staticmethod
    def format_number(value: float) -> str:
        if value is None:
            return "0,00"
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    

    # ========== Page Setup ==========
    
    @staticmethod
    def setup_page():
        st.set_page_config(page_title="Binance Spot Testnet GUI", layout="wide")
        st.title("Binance Spot Testnet GUI")
    

    # ========== Dashboard Components ==========
    
    def render_portfolio_summary(self, usdt_balance: float, portfolio_value: float):
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Cash (USDT)", self.format_number(usdt_balance))
        with col2:
            st.metric("Total Portfolio Value (USDT)", self.format_number(portfolio_value))
    
    def render_assets_table(self, asset_data: list[dict], all_symbols: list[str]) -> Optional[str]:
        col_head, col_btn = st.columns([6, 1])
        with col_head:
            st.subheader("Assets")
        with col_btn:
            if st.button("Refresh", key="refresh_assets"):
                self.handlers.refresh_data()
        
        if not asset_data:
            st.info("No assets found.")
            return None
        
        # Filter option for small value assets
        hide_small = st.checkbox("Hide assets < 10 USDT", value=False, key="hide_small_assets")
        
        df_assets = pd.DataFrame(asset_data)
        
        # Apply filter if checkbox is checked
        if hide_small:
            df_assets = df_assets[df_assets["Value (USDT)"] >= 10.0]
            if df_assets.empty:
                st.info("No assets with value >= 10 USDT found.")
                return None
        
        # Format columns for display
        df_display = df_assets.copy()
        for col in ["Free", "Locked", "Total", "Value (USDT)"]:
            df_display[col] = df_display[col].apply(self.format_number)
        
        event = st.dataframe(
            df_display, 
            on_select="rerun", 
            selection_mode="single-row",
            width="stretch"
        )
        
        if event.selection.rows:
            selected_index = event.selection.rows[0]
            selected_asset = df_assets.iloc[selected_index]["Asset"]
            self.handlers.handle_asset_selection(selected_asset, all_symbols)
        
        return None
    

    # ========== Trading Components ==========
    
    def render_symbol_selector(self, all_symbols: list[str], prices: dict[str, float]) -> tuple[str, float]:
        st.sidebar.header("Trade")
        st.sidebar.subheader("Filter Symbols")
        
        quote_assets = ["USDT", "BTC", "BNB", "ETH", "EUR"]
        selected_quotes = []
        filter_cols = st.sidebar.columns(3)
        
        for i, quote in enumerate(quote_assets):
            if filter_cols[i % 3].checkbox(quote, value=(quote == "USDT"), key=f"filter_{quote}"):
                selected_quotes.append(quote)
        
        filtered_symbols = all_symbols
        if selected_quotes:
            filtered_symbols = [s for s in all_symbols if any(s.endswith(q) for q in selected_quotes)]
        
        if not filtered_symbols:
            filtered_symbols = all_symbols
        
        # Ensure current selection is valid
        current_symbol = st.session_state.get("symbol_select", "BTCUSDT")
        if current_symbol not in filtered_symbols:
            current_symbol = filtered_symbols[0] if filtered_symbols else "BTCUSDT"
        
        try:
            index_to_use = filtered_symbols.index(current_symbol)
        except ValueError:
            index_to_use = 0
        
        symbol_input = st.sidebar.selectbox(
            "Symbol", 
            options=filtered_symbols, 
            index=index_to_use,
            key="symbol_select"
        )
        
        current_price = prices.get(symbol_input, 0.0) if symbol_input else 0.0
        if symbol_input:
            st.sidebar.write(f"Current Price: {self.format_number(current_price)}")
        
        return symbol_input, current_price
    

    def render_buy_form(self, symbol: str, current_price: float):
        st.write("Buy " + symbol)
        buy_type = st.radio("Order Type", ["LIMIT", "MARKET"], key="buy_type")
        
        with st.form("buy_form"):
            buy_quantity = st.number_input(
                "Quantity (Base Asset)", 
                min_value=0.0, 
                step=0.0001, 
                format="%.4f", 
                key="buy_qty"
            )
            buy_total = st.number_input(
                "Total (USDT)", 
                min_value=0.0, 
                step=1.0, 
                format="%.2f", 
                key="buy_total", 
                help="If Quantity is 0, this amount will be used to calculate quantity."
            )
            buy_price = st.number_input(
                "Price (USDT)", 
                min_value=0.0, 
                value=current_price, 
                step=0.01, 
                key="buy_price", 
                disabled=(buy_type == "MARKET")
            )
            submitted = st.form_submit_button("Buy")
        
        if submitted:
            success = self.handlers.handle_buy_order(
                symbol=symbol,
                order_type=buy_type,
                quantity=buy_quantity,
                total_usdt=buy_total,
                price=buy_price
            )
            if success:
                st.rerun()
    

    def render_sell_form(self, symbol: str, current_price: float, account: dict):
        st.write("Sell " + symbol)
        
        # Determine available balance for the base asset
        base_asset = None
        available_balance = 0.0
        
        if account:
            candidates = [b['asset'] for b in account['balances'] if symbol.startswith(b['asset'])]
            if candidates:
                base_asset = sorted(candidates, key=len, reverse=True)[0]
                for b in account['balances']:
                    if b['asset'] == base_asset:
                        available_balance = float(b['free'])
                        break
        
        if base_asset:
            col_bal, col_btn = st.columns([3, 1])
            with col_bal:
                st.caption(f"Available: {available_balance} {base_asset}")
            with col_btn:
                if st.button("Max", key="btn_max_sell"):
                    st.session_state.sell_qty = available_balance
                    st.rerun()
        
        sell_type = st.radio("Order Type", ["LIMIT", "MARKET"], key="sell_type")
        
        with st.form("sell_form"):
            sell_quantity = st.number_input(
                "Quantity", 
                min_value=0.0, 
                step=0.00000001, 
                format="%.8f", 
                key="sell_qty"
            )
            sell_price = st.number_input(
                "Price (USDT)", 
                min_value=0.0, 
                value=current_price, 
                step=0.01, 
                key="sell_price", 
                disabled=(sell_type == "MARKET")
            )
            submitted = st.form_submit_button("Sell")
        
        if submitted:
            success = self.handlers.handle_sell_order(
                symbol=symbol,
                order_type=sell_type,
                quantity=sell_quantity,
                price=sell_price,
                current_price=current_price
            )
            if success:
                st.rerun()
    

    def render_trading_tabs(self, symbol: str, current_price: float, account: dict):
        if not symbol:
            return
        
        tab1, tab2 = st.sidebar.tabs(["Buy", "Sell"])
        
        with tab1:
            self.render_buy_form(symbol, current_price)
        
        with tab2:
            self.render_sell_form(symbol, current_price, account)
    

    # ========== Order Components ==========
    
    def render_open_orders(self, open_orders: list[dict]):
        st.subheader("Open Orders")
        
        if not open_orders:
            st.write("No open orders.")
            return
        
        df_open = pd.DataFrame(open_orders)
        cols = ['symbol', 'orderId', 'price', 'origQty', 'executedQty', 'side', 'type', 'time']
        cols = [c for c in cols if c in df_open.columns]
        st.dataframe(df_open[cols])
        
        # Cancel Order
        cancel_id = st.text_input("Order ID to Cancel")
        cancel_symbol = st.text_input("Symbol for Cancel")
        
        if st.button("Cancel Order"):
            success = self.handlers.handle_cancel_order(cancel_symbol, cancel_id)
            if success:
                st.rerun()
    

    def render_order_history(self, symbol_input: str, assets: list[dict], 
                             all_symbols: list[str], get_all_orders_func: Callable):
        st.subheader("Order History")
        
        history_symbols = set()
        if symbol_input:
            history_symbols.add(symbol_input)
        
        if st.checkbox("Show history for all active assets (May be slow)"):
            if assets:
                for asset in assets:
                    s = asset['asset']
                    pair = f"{s}USDT"
                    if pair in all_symbols:
                        history_symbols.add(pair)
        
        all_history = []
        if len(history_symbols) > 3:
            st.caption(f"Fetching history for {len(history_symbols)} symbols...")
        
        for sym in history_symbols:
            orders = get_all_orders_func(sym)
            if orders:
                all_history.extend(orders)
        
        if all_history:
            df_hist = pd.DataFrame(all_history)
            cols = ['symbol', 'orderId', 'price', 'origQty', 'executedQty', 'side', 'type', 'status', 'time']
            cols = [c for c in cols if c in df_hist.columns]
            st.dataframe(df_hist[cols].sort_values(by='time', ascending=False))
        else:
            st.write("No order history found.")
    

    # ========== Danger Zone ==========
    
    def render_danger_zone(self):
        st.sidebar.markdown("---")
        st.sidebar.header("Danger Zone")
        
        confirm_reset = st.sidebar.checkbox(
            "I understand this will sell ALL assets and cancel ALL orders.", 
            key="danger_zone_confirm"
        )
        
        if st.sidebar.button("RESET PORTFOLIO (SELL ALL)", disabled=not confirm_reset):
            with st.sidebar.status("Resetting Portfolio...", expanded=True) as status:
                def status_callback(msg):
                    st.write(msg)
                
                success = self.handlers.handle_portfolio_reset(status_callback)
                
                if success:
                    status.update(label="Reset Complete!", state="complete", expanded=False)
                    import time
                    time.sleep(1)
                    self.handlers.refresh_data()
                else:
                    status.update(label="Reset Failed!", state="error")
    

    # ========== Activity Log ==========
    
    def render_activity_log(self):
        st.sidebar.markdown("---")
        st.sidebar.subheader("Activity Log")
        
        log_container = st.sidebar.container(height=300)
        with log_container:
            self._log_placeholder = st.empty()
        
        self._render_log_content()
    

    def _render_log_content(self):
        if self._log_placeholder is None:
            return
        
        if "activity_log" not in st.session_state:
            st.session_state.activity_log = []
        
        with self._log_placeholder.container():
            for log in st.session_state.activity_log:
                msg = f"[{log['time']}] {log['msg']}"
                if log['level'] == 'success':
                    st.success(msg)
                elif log['level'] == 'error':
                    st.error(msg)
                elif log['level'] == 'warning':
                    st.warning(msg)
                else:
                    st.info(msg)
