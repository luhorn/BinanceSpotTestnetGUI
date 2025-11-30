"""
GUI Handlers Module

This module contains all the handler functions for GUI actions (button presses, form submissions).
These are separated from the GUI components to allow for clear separation of concerns.
"""

import time
import streamlit as st
from libs.exchange import BinanceClient
from libs.exchange.client import BinanceClientError


class GUIHandlers:
    def __init__(self, client: BinanceClient):
        self.client = client
    

    # ========== Logging ==========
    
    @staticmethod
    def add_log(message: str, level: str = "info"):
        if "activity_log" not in st.session_state:
            st.session_state.activity_log = []
        
        st.session_state.activity_log.insert(0, {
            "msg": message, 
            "level": level, 
            "time": time.strftime("%H:%M:%S")
        })
    

    # ========== Data Refresh ==========
    
    @staticmethod
    def refresh_data():
        # Clear streamlit cache for data functions
        st.cache_data.clear()
        st.rerun()
    

    # ========== Order Handlers ==========
    
    def handle_buy_order(self, symbol: str, order_type: str, quantity: float, 
                         total_usdt: float, price: float) -> bool:
        try:
            qty_to_log = 0
            
            if quantity > 0:
                adjusted_qty = self.client.adjust_quantity(symbol, quantity)
                self.client.place_order(
                    symbol=symbol,
                    side="BUY",
                    order_type=order_type,
                    quantity=adjusted_qty,
                    price=price if order_type == "LIMIT" else None
                )
                qty_to_log = adjusted_qty
                
            elif total_usdt > 0:
                if order_type == "MARKET":
                    self.client.place_order(
                        symbol=symbol,
                        side="BUY",
                        order_type=order_type,
                        quote_order_qty=total_usdt
                    )
                    qty_to_log = f"{total_usdt} USDT"
                else:
                    # LIMIT: Calculate quantity from total
                    if price <= 0:
                        self.add_log("Buy Failed: Price must be > 0 to calculate quantity from total.", "error")
                        return False
                    
                    calc_qty = total_usdt / price
                    adjusted_qty = self.client.adjust_quantity(symbol, calc_qty)
                    self.client.place_order(
                        symbol=symbol,
                        side="BUY",
                        order_type=order_type,
                        quantity=adjusted_qty,
                        price=price
                    )
                    qty_to_log = adjusted_qty
            else:
                self.add_log("Buy Failed: Please enter Quantity or Total (USDT).", "error")
                return False
            
            self.add_log(f"Buy Order Placed: {symbol}, Qty: {qty_to_log}", "success")
            return True
            
        except BinanceClientError as e:
            if e.is_notional_error():
                self.add_log("Buy Failed: Order value too small (min ~10 USDT).", "error")
            else:
                self.add_log(f"Buy Order Failed: {e}", "error")
            return False
    

    def handle_sell_order(self, symbol: str, order_type: str, quantity: float, 
                          price: float, current_price: float) -> bool:
        # Check estimated value
        if order_type == "LIMIT":
            estimated_value = quantity * price
        else:
            estimated_value = quantity * current_price
        
        if estimated_value < 10.0:
            self.add_log(f"Sell Failed: Order value {estimated_value:.2f} USDT is too small (min ~10 USDT).", "error")
            return False
        
        try:
            adjusted_qty = self.client.adjust_quantity(symbol, quantity)
            self.client.place_order(
                symbol=symbol,
                side="SELL",
                order_type=order_type,
                quantity=adjusted_qty,
                price=price if order_type == "LIMIT" else None
            )
            self.add_log(f"Sell Order Placed: {symbol}, Qty: {adjusted_qty}", "success")
            return True
            
        except BinanceClientError as e:
            if e.is_notional_error():
                self.add_log("Sell Failed: Order value too small (min ~10 USDT).", "error")
            elif e.is_lot_size_error():
                self.add_log(f"Sell Failed: Quantity {quantity} invalid for LOT_SIZE filter.", "error")
            else:
                self.add_log(f"Sell Order Failed: {e}", "error")
            return False
    
    def handle_cancel_order(self, symbol: str, order_id: str) -> bool:
        if not order_id or not symbol:
            self.add_log("Cancel Failed: Order ID and Symbol are required.", "error")
            return False
        
        try:
            self.client.cancel_order(symbol=symbol, order_id=order_id)
            self.add_log(f"Order {order_id} cancelled", "success")
            return True
        except BinanceClientError as e:
            self.add_log(f"Cancel Failed: {e}", "error")
            return False
    

    # ========== Portfolio Reset Handler ==========
    
    def handle_portfolio_reset(self, status_callback=None, log_callback=None) -> bool:
        def update_status(msg):
            if status_callback:
                status_callback(msg)
        
        def log_and_display(message: str, level: str = "info"):
            """Add to session log and display live if callback provided."""
            self.add_log(message, level)
            if log_callback:
                log_callback(message, level)
        
        log_and_display("Starting Portfolio Reset...", "warning")
        
        try:
            # 1. Cancel all open orders
            update_status("Cancelling open orders...")
            open_orders = self.client.get_open_orders()
            if open_orders:
                for order in open_orders:
                    self.client.cancel_order(symbol=order['symbol'], order_id=order['orderId'])
                log_and_display(f"Cancelled {len(open_orders)} open orders.", "success")
            else:
                log_and_display("No open orders to cancel.", "info")
            
            # 2. Analyze and sell assets
            update_status("Analyzing assets...")
            prices = self.client.get_all_prices()
            balances = self.client.get_balances(non_zero_only=True)
            
            sellable_assets = []
            dust_assets = []
            
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
            
            # Pass 1: Sell Sellable Assets
            if sellable_assets:
                update_status(f"Selling {len(sellable_assets)} major assets...")
                for asset_name, free_amt, pair in sellable_assets:
                    try:
                        qty_to_sell = self.client.adjust_quantity(pair, free_amt)
                        if qty_to_sell > 0:
                            self.client.place_order(
                                symbol=pair, 
                                side='SELL', 
                                order_type='MARKET', 
                                quantity=qty_to_sell
                            )
                            log_and_display(f"Sold {qty_to_sell} {asset_name}", "success")
                    except BinanceClientError as e:
                        log_and_display(f"Failed to sell {asset_name}: {e}", "error")
            
            # Pass 2: Sweep Dust
            if dust_assets:
                update_status(f"Sweeping {len(dust_assets)} dust assets...")
                log_and_display(f"Found {len(dust_assets)} dust assets. Attempting to sweep...", "info")
                
                # Get fresh USDT balance
                account = self.client.get_account_info()
                usdt_balance = 0.0
                for b in account['balances']:
                    if b['asset'] == 'USDT':
                        usdt_balance = float(b['free'])
                        break
                
                for i, (asset_name, free_amt, pair) in enumerate(dust_assets):
                    update_status(f"Sweeping {asset_name} ({i+1}/{len(dust_assets)})...")
                    
                    if usdt_balance < 11.0:
                        log_and_display(f"Skipping dust sweep for {asset_name}: Insufficient USDT ({usdt_balance:.2f} < 11.0)", "warning")
                        continue
                    
                    try:
                        # Buy 11 USDT worth
                        self.client.place_order(
                            symbol=pair, 
                            side='BUY', 
                            order_type='MARKET', 
                            quote_order_qty=11.0
                        )
                        log_and_display(f"Bought ~11 USDT of {asset_name} to enable sell.", "info")
                        
                        time.sleep(0.5)
                        
                        # Get new balance
                        sub_acc = self.client.get_account_info()
                        new_bal = 0.0
                        for b in sub_acc['balances']:
                            if b['asset'] == asset_name:
                                new_bal = float(b['free'])
                                break
                        
                        # Sell everything
                        qty_to_sell = self.client.adjust_quantity(pair, new_bal)
                        if qty_to_sell > 0:
                            self.client.place_order(
                                symbol=pair, 
                                side='SELL', 
                                order_type='MARKET', 
                                quantity=qty_to_sell
                            )
                            log_and_display(f"Swept dust: Sold {qty_to_sell} {asset_name}", "success")
                        else:
                            log_and_display(f"Failed to sweep {asset_name}: Adjusted quantity is 0.", "error")
                    
                    except BinanceClientError as e:
                        log_and_display(f"Failed to sweep {asset_name}: {e}", "error")
            
            log_and_display("Portfolio Reset Complete.", "success")
            return True
            
        except BinanceClientError as e:
            log_and_display(f"Error during reset: {e}", "error")
            return False
    

    # ========== Asset Selection Handler ==========
    
    def handle_asset_selection(self, selected_asset: str, all_symbols: list[str]):
        potential_pair = f"{selected_asset}USDT"
        if potential_pair in all_symbols:
            st.session_state["symbol_select"] = potential_pair
            st.rerun()
