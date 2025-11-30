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
                is_market = order_type == "MARKET"
                adjusted_qty = self.client.adjust_quantity(symbol, quantity, is_market_order=is_market)
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
            is_market = order_type == "MARKET"
            adjusted_qty = self.client.adjust_quantity(symbol, quantity, is_market_order=is_market)
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
    
    def handle_portfolio_reset(self, status_callback=None) -> bool:
        def update_status(msg):
            if status_callback:
                status_callback(msg)
        
        self.add_log("Starting Portfolio Reset...", "warning")
        
        try:
            # 1. Cancel all open orders
            update_status("Cancelling open orders...")
            open_orders = self.client.get_open_orders()
            if open_orders:
                for order in open_orders:
                    self.client.cancel_order(symbol=order['symbol'], order_id=order['orderId'])
                self.add_log(f"Cancelled {len(open_orders)} open orders.", "success")
            else:
                self.add_log("No open orders to cancel.", "info")
            
            # 2. Analyze and sell assets
            update_status("Analyzing assets...")
            prices = self.client.get_all_prices()
            balances = self.client.get_balances(non_zero_only=True)
            
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
                        # No USDT trading pair available
                        no_pair_assets.append(asset_name)
            
            # Log assets without trading pairs
            if no_pair_assets:
                self.add_log(f"Skipping {len(no_pair_assets)} assets without USDT pairs: {', '.join(no_pair_assets)}", "info")
            
            # Pass 1: Sell Sellable Assets
            if sellable_assets:
                update_status(f"Selling {len(sellable_assets)} major assets...")
                for asset_name, free_amt, pair in sellable_assets:
                    try:
                        min_qty = self.client.get_min_market_lot_size(pair)
                        max_qty = self.client.get_max_market_lot_size(pair)
                        
                        remaining = free_amt
                        total_sold = 0.0
                        
                        # Sell in batches if quantity exceeds max
                        while remaining > 0:
                            qty_to_sell = self.client.adjust_quantity(pair, remaining, is_market_order=True)
                            
                            if qty_to_sell <= 0 or qty_to_sell < min_qty:
                                # Remaining quantity below minimum - treat as dust
                                if total_sold == 0:
                                    self.add_log(f"Cannot sell {asset_name}: qty {free_amt} below min {min_qty}. Moving to dust.", "warning")
                                    dust_assets.append((asset_name, remaining, pair))
                                else:
                                    self.add_log(f"Remaining {remaining} {asset_name} is dust.", "info")
                                    dust_assets.append((asset_name, remaining, pair))
                                break
                            
                            result = self.client.place_order(
                                symbol=pair, 
                                side='SELL', 
                                order_type='MARKET', 
                                quantity=qty_to_sell
                            )
                            
                            # Check if order was filled or expired (no liquidity)
                            status = result.get('status', '')
                            executed_qty = float(result.get('executedQty', 0))
                            
                            if status == 'EXPIRED' or executed_qty == 0:
                                self.add_log(f"Cannot sell {asset_name}: No liquidity on testnet.", "warning")
                                break  # No point retrying, no buyers
                            
                            total_sold += executed_qty
                            remaining -= executed_qty
                            self.add_log(f"Sold {executed_qty} {asset_name}", "success")
                            
                            # Small delay between batch sells
                            if remaining > 0 and remaining >= min_qty:
                                time.sleep(0.3)
                            else:
                                if remaining > 0:
                                    dust_assets.append((asset_name, remaining, pair))
                                break
                        
                    except BinanceClientError as e:
                        if e.is_market_lot_size_error() or e.is_lot_size_error():
                            self.add_log(f"Cannot sell {asset_name}: lot size error. Moving to dust.", "warning")
                            dust_assets.append((asset_name, free_amt, pair))
                        else:
                            self.add_log(f"Failed to sell {asset_name}: {e}", "error")
            
            # Pass 2: Sweep Dust
            if dust_assets:
                update_status(f"Sweeping {len(dust_assets)} dust assets...")
                self.add_log(f"Found {len(dust_assets)} dust assets. Attempting to sweep...", "info")
                
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
                        self.add_log(f"Skipping dust sweep for {asset_name}: Insufficient USDT ({usdt_balance:.2f} < 11.0)", "warning")
                        continue
                    
                    try:
                        # Buy 11 USDT worth
                        buy_result = self.client.place_order(
                            symbol=pair, 
                            side='BUY', 
                            order_type='MARKET', 
                            quote_order_qty=11.0
                        )
                        
                        # Check if buy was filled
                        if buy_result.get('status') == 'EXPIRED' or float(buy_result.get('executedQty', 0)) == 0:
                            self.add_log(f"Skipping {asset_name}: No liquidity on testnet.", "warning")
                            continue
                        
                        self.add_log(f"Bought ~11 USDT of {asset_name} to enable sell.", "info")
                        
                        time.sleep(0.5)
                        
                        # Get new balance
                        sub_acc = self.client.get_account_info()
                        new_bal = 0.0
                        for b in sub_acc['balances']:
                            if b['asset'] == asset_name:
                                new_bal = float(b['free'])
                                break
                        
                        # Sell everything
                        qty_to_sell = self.client.adjust_quantity(pair, new_bal, is_market_order=True)
                        if qty_to_sell > 0:
                            sell_result = self.client.place_order(
                                symbol=pair, 
                                side='SELL', 
                                order_type='MARKET', 
                                quantity=qty_to_sell
                            )
                            
                            if sell_result.get('status') == 'EXPIRED' or float(sell_result.get('executedQty', 0)) == 0:
                                self.add_log(f"Failed to sell {asset_name}: No liquidity for sell.", "warning")
                            else:
                                executed = float(sell_result.get('executedQty', 0))
                                self.add_log(f"Swept dust: Sold {executed} {asset_name}", "success")
                        else:
                            self.add_log(f"Failed to sweep {asset_name}: Adjusted quantity is 0.", "error")
                    
                    except BinanceClientError as e:
                        if e.is_liquidity_error():
                            self.add_log(f"Skipping {asset_name}: Testnet has insufficient liquidity.", "warning")
                        elif e.is_market_lot_size_error() or e.is_lot_size_error():
                            self.add_log(f"Skipping {asset_name}: Quantity below minimum lot size.", "warning")
                        else:
                            self.add_log(f"Failed to sweep {asset_name}: {e}", "error")
            
            self.add_log("Portfolio Reset Complete.", "success")
            return True
            
        except BinanceClientError as e:
            self.add_log(f"Error during reset: {e}", "error")
            return False
    

    # ========== Asset Selection Handler ==========
    
    def handle_asset_selection(self, selected_asset: str, all_symbols: list[str]):
        potential_pair = f"{selected_asset}USDT"
        if potential_pair in all_symbols:
            st.session_state["symbol_select"] = potential_pair
            st.rerun()
