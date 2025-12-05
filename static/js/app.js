/**
 * Binance Spot Testnet GUI - Main JavaScript
 */

// ========== State Management ==========

let currentSymbol = 'BTCUSDT';
let currentPrice = 0;
let availableBalance = 0;
let autoRefreshInterval = null;

// ========== Initialization ==========

document.addEventListener('DOMContentLoaded', function() {
    // Initialize symbol selector
    const symbolSelect = document.getElementById('symbol-select');
    if (symbolSelect) {
        symbolSelect.addEventListener('change', onSymbolChange);
        // Trigger initial load
        onSymbolChange();
    }
    
    // Initialize filter checkboxes
    document.querySelectorAll('[id^="filter-"]').forEach(cb => {
        cb.addEventListener('change', filterSymbols);
    });
    
    // Initialize order type toggles
    document.querySelectorAll('input[name="buy-type"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const priceGroup = document.getElementById('buy-price-group');
            const priceInput = document.getElementById('buy-price');
            if (this.value === 'MARKET') {
                priceGroup.style.display = 'none';
                priceInput.disabled = true;
                priceInput.removeAttribute('required');
            } else {
                priceGroup.style.display = 'block';
                priceInput.disabled = false;
            }
        });
    });
    
    document.querySelectorAll('input[name="sell-type"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const priceGroup = document.getElementById('sell-price-group');
            const priceInput = document.getElementById('sell-price');
            if (this.value === 'MARKET') {
                priceGroup.style.display = 'none';
                priceInput.disabled = true;
                priceInput.removeAttribute('required');
            } else {
                priceGroup.style.display = 'block';
                priceInput.disabled = false;
            }
        });
    });
    
    // Initialize danger zone confirmation
    const confirmReset = document.getElementById('confirm-reset');
    if (confirmReset) {
        confirmReset.addEventListener('change', function() {
            document.getElementById('reset-btn').disabled = !this.checked;
        });
    }
    
    // Initialize hide small assets checkbox
    const hideSmall = document.getElementById('hide-small-assets');
    if (hideSmall) {
        hideSmall.addEventListener('change', filterAssetTable);
    }
    
    // Load initial data
    refreshOpenOrders();
    refreshActivityLog();
    
    // Start auto-refresh (every 30 seconds)
    startAutoRefresh();
});

// ========== Auto Refresh ==========

function startAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    autoRefreshInterval = setInterval(function() {
        refreshPrice();
        refreshOpenOrders();
    }, 30000);
}

// ========== Symbol Management ==========

function onSymbolChange() {
    const symbolSelect = document.getElementById('symbol-select');
    currentSymbol = symbolSelect.value;
    
    // Update history dropdown
    const historySymbol = document.getElementById('history-symbol');
    if (historySymbol) {
        historySymbol.value = currentSymbol;
    }
    
    refreshPrice();
    updateAvailableBalance();
}

function filterSymbols() {
    const filters = [];
    if (document.getElementById('filter-usdt').checked) filters.push('USDT');
    if (document.getElementById('filter-btc').checked) filters.push('BTC');
    if (document.getElementById('filter-bnb').checked) filters.push('BNB');
    if (document.getElementById('filter-eth').checked) filters.push('ETH');
    
    const symbolSelect = document.getElementById('symbol-select');
    const currentValue = symbolSelect.value;
    
    // Clear and repopulate
    symbolSelect.innerHTML = '';
    
    const filteredSymbols = window.allSymbols.filter(s => {
        if (filters.length === 0) return true;
        return filters.some(f => s.endsWith(f));
    });
    
    filteredSymbols.forEach(symbol => {
        const option = document.createElement('option');
        option.value = symbol;
        option.textContent = symbol;
        if (symbol === currentValue) {
            option.selected = true;
        }
        symbolSelect.appendChild(option);
    });
    
    // If current selection no longer valid, select first option
    if (!filteredSymbols.includes(currentValue) && filteredSymbols.length > 0) {
        symbolSelect.value = filteredSymbols[0];
        onSymbolChange();
    }
}

function selectAsset(asset) {
    const pair = asset + 'USDT';
    if (window.allSymbols.includes(pair)) {
        // Make sure USDT filter is on
        document.getElementById('filter-usdt').checked = true;
        filterSymbols();
        
        const symbolSelect = document.getElementById('symbol-select');
        symbolSelect.value = pair;
        onSymbolChange();
        
        // Scroll to trading panel on mobile
        document.querySelector('.card-header h5').scrollIntoView({ behavior: 'smooth' });
    }
}

// ========== Price and Balance ==========

function refreshPrice() {
    if (!currentSymbol) return;
    
    fetch(`/api/price/${currentSymbol}`)
        .then(response => response.json())
        .then(data => {
            currentPrice = data.price;
            document.getElementById('current-price').value = data.formatted;
            
            // Update buy/sell price inputs
            document.getElementById('buy-price').value = data.price;
            document.getElementById('sell-price').value = data.price;
            
            // Also update local cache
            if (window.prices) {
                window.prices[currentSymbol] = data.price;
            }
        })
        .catch(err => {
            console.error('Failed to fetch price:', err);
            showToast('Failed to fetch price', 'error');
        });
}

function updateAvailableBalance() {
    // Extract base asset from symbol
    const baseAsset = getBaseAsset(currentSymbol);
    if (!baseAsset) return;
    
    fetch(`/api/balance/${baseAsset}`)
        .then(response => response.json())
        .then(data => {
            availableBalance = data.free;
            document.getElementById('available-balance').textContent = 
                `Available: ${data.free.toFixed(8)} ${baseAsset}`;
        })
        .catch(err => console.error('Failed to fetch balance:', err));
}

function getBaseAsset(symbol) {
    // Common quote assets
    const quotes = ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB', 'EUR'];
    for (const quote of quotes) {
        if (symbol.endsWith(quote)) {
            return symbol.slice(0, -quote.length);
        }
    }
    return null;
}

function setMaxSellQuantity() {
    document.getElementById('sell-quantity').value = availableBalance;
}

// ========== Data Refresh ==========

function refreshAll() {
    showToast('Refreshing data...', 'info');
    
    fetch('/api/refresh')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showToast(data.error, 'error');
                return;
            }
            
            // Update portfolio summary
            document.getElementById('usdt-balance').textContent = data.usdt_balance;
            document.getElementById('portfolio-value').textContent = data.portfolio_value;
            
            // Update assets table
            updateAssetsTable(data.assets);
            
            // Update symbols list
            window.allSymbols = data.all_symbols;
            filterSymbols();
            
            // Refresh other components
            refreshOpenOrders();
            refreshActivityLog();
            
            showToast('Data refreshed', 'success');
        })
        .catch(err => {
            console.error('Refresh failed:', err);
            showToast('Failed to refresh data', 'error');
        });
}

function updateAssetsTable(assets) {
    const tbody = document.querySelector('#assets-table tbody');
    tbody.innerHTML = '';
    
    assets.forEach(asset => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-asset', asset.Asset);
        tr.setAttribute('data-value', asset.RawValue);
        
        tr.innerHTML = `
            <td><strong>${asset.Asset}</strong></td>
            <td>${asset.Free}</td>
            <td>${asset.Locked}</td>
            <td>${asset.Total}</td>
            <td>${asset.Value}</td>
            <td>
                ${asset.Asset !== 'USDT' ? 
                    `<button class="btn btn-sm btn-outline-primary" onclick="selectAsset('${asset.Asset}')">Trade</button>` 
                    : ''}
            </td>
        `;
        tbody.appendChild(tr);
    });
    
    // Apply filter if needed
    filterAssetTable();
}

function filterAssetTable() {
    const hideSmall = document.getElementById('hide-small-assets').checked;
    const rows = document.querySelectorAll('#assets-table tbody tr');
    
    rows.forEach(row => {
        const value = parseFloat(row.getAttribute('data-value'));
        row.style.display = (hideSmall && value < 10) ? 'none' : '';
    });
}

// ========== Open Orders ==========

function refreshOpenOrders() {
    fetch('/api/open_orders')
        .then(response => response.json())
        .then(data => {
            const tbody = document.querySelector('#open-orders-table tbody');
            const noOrders = document.getElementById('no-open-orders');
            
            if (!data.orders || data.orders.length === 0) {
                tbody.innerHTML = '';
                noOrders.style.display = 'block';
                return;
            }
            
            noOrders.style.display = 'none';
            tbody.innerHTML = '';
            
            data.orders.forEach(order => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${order.symbol}</td>
                    <td>${order.orderId}</td>
                    <td class="${order.side === 'BUY' ? 'text-success' : 'text-danger'}">${order.side}</td>
                    <td>${order.type}</td>
                    <td>${order.price}</td>
                    <td>${order.origQty}</td>
                    <td>${order.executedQty}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-danger" 
                                onclick="cancelOrder('${order.symbol}', '${order.orderId}')">
                            Cancel
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(err => console.error('Failed to fetch open orders:', err));
}

function cancelOrder(symbol, orderId) {
    if (!confirm(`Cancel order ${orderId}?`)) return;
    
    fetch('/api/cancel_order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol, order_id: orderId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Order cancelled', 'success');
            refreshOpenOrders();
            refreshActivityLog();
        } else {
            showToast(data.error || 'Failed to cancel order', 'error');
        }
    })
    .catch(err => {
        showToast('Failed to cancel order', 'error');
    });
}

// ========== Order History ==========

function loadOrderHistory() {
    const symbol = document.getElementById('history-symbol').value;
    if (!symbol) {
        showToast('Please select a symbol', 'warning');
        return;
    }
    
    fetch(`/api/order_history/${symbol}`)
        .then(response => response.json())
        .then(data => {
            const tbody = document.querySelector('#order-history-table tbody');
            const noHistory = document.getElementById('no-order-history');
            
            if (!data.orders || data.orders.length === 0) {
                tbody.innerHTML = '';
                noHistory.textContent = 'No order history found.';
                noHistory.style.display = 'block';
                return;
            }
            
            noHistory.style.display = 'none';
            tbody.innerHTML = '';
            
            // Sort by time descending
            data.orders.sort((a, b) => b.time - a.time);
            
            data.orders.forEach(order => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${order.time_formatted || ''}</td>
                    <td>${order.symbol}</td>
                    <td class="${order.side === 'BUY' ? 'text-success' : 'text-danger'}">${order.side}</td>
                    <td>${order.type}</td>
                    <td><span class="badge ${getStatusBadgeClass(order.status)}">${order.status}</span></td>
                    <td>${order.price}</td>
                    <td>${order.origQty}</td>
                    <td>${order.executedQty}</td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(err => {
            console.error('Failed to fetch order history:', err);
            showToast('Failed to load order history', 'error');
        });
}

function getStatusBadgeClass(status) {
    switch (status) {
        case 'FILLED': return 'bg-success';
        case 'CANCELED': return 'bg-secondary';
        case 'NEW': return 'bg-primary';
        case 'PARTIALLY_FILLED': return 'bg-info';
        case 'EXPIRED': return 'bg-warning';
        default: return 'bg-secondary';
    }
}

// ========== Trading ==========

function placeBuyOrder(event) {
    event.preventDefault();
    console.log('placeBuyOrder called');
    
    const orderType = document.querySelector('input[name="buy-type"]:checked').value;
    const quantity = parseFloat(document.getElementById('buy-quantity').value) || 0;
    const totalUsdt = parseFloat(document.getElementById('buy-total').value) || 0;
    const price = parseFloat(document.getElementById('buy-price').value) || 0;
    
    console.log('Order data:', { orderType, quantity, totalUsdt, price, symbol: currentSymbol });
    
    if (quantity <= 0 && totalUsdt <= 0) {
        showToast('Please enter quantity or total', 'error');
        return;
    }
    
    const data = {
        symbol: currentSymbol,
        order_type: orderType,
        quantity: quantity,
        total_usdt: totalUsdt,
        price: price
    };
    
    // Show loading state
    const btn = document.querySelector('#buy-form button[type="submit"]');
    if (!btn) {
        console.error('Buy button not found!');
        showToast('Error: Buy button not found', 'error');
        return;
    }
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Placing...';
    
    console.log('Sending request to /api/buy');
    
    fetch('/api/buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(response => {
        console.log('Response received:', response.status, response.ok);
        // Parse JSON regardless of status code
        return response.json().then(data => {
            console.log('Response data:', data);
            return { ok: response.ok, data };
        });
    })
    .then(({ ok, data }) => {
        console.log('Processing response:', ok, data);
        if (ok && data.success) {
            console.log('Order successful, showing toast');
            showToast('Buy order placed successfully', 'success');
            // Clear form
            document.getElementById('buy-quantity').value = '';
            document.getElementById('buy-total').value = '';
            // Refresh data
            refreshAll();
        } else {
            console.log('Order failed, showing error toast');
            showToast(data.error || 'Failed to place order', 'error');
        }
    })
    .catch(err => {
        console.error('Buy order error:', err);
        showToast('Failed to place order: ' + err.message, 'error');
    })
    .finally(() => {
        console.log('Request complete, resetting button');
        btn.disabled = false;
        btn.innerHTML = originalText;
        refreshActivityLog();
    });
}

function placeSellOrder(event) {
    event.preventDefault();
    
    const orderType = document.querySelector('input[name="sell-type"]:checked').value;
    const quantity = parseFloat(document.getElementById('sell-quantity').value) || 0;
    const price = parseFloat(document.getElementById('sell-price').value) || 0;
    
    if (quantity <= 0) {
        showToast('Please enter quantity', 'error');
        return;
    }
    
    const data = {
        symbol: currentSymbol,
        order_type: orderType,
        quantity: quantity,
        price: price,
        current_price: currentPrice
    };
    
    // Show loading state
    const btn = document.querySelector('#sell-form button[type="submit"]');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Placing...';
    
    fetch('/api/sell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(response => {
        // Parse JSON regardless of status code
        return response.json().then(data => ({ ok: response.ok, data }));
    })
    .then(({ ok, data }) => {
        if (ok && data.success) {
            showToast('Sell order placed successfully', 'success');
            // Clear form
            document.getElementById('sell-quantity').value = '';
            // Refresh data
            refreshAll();
        } else {
            showToast(data.error || 'Failed to place order', 'error');
        }
    })
    .catch(err => {
        console.error('Sell order error:', err);
        showToast('Failed to place order: ' + err.message, 'error');
    })
    .finally(() => {
        btn.disabled = false;
        btn.innerHTML = originalText;
        refreshActivityLog();
    });
}

// ========== Portfolio Reset ==========

function resetPortfolio() {
    if (!confirm('Are you sure you want to reset your portfolio? This will cancel all orders and sell all assets.')) {
        return;
    }
    
    const btn = document.getElementById('reset-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Resetting...';
    
    fetch('/api/reset_portfolio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            showToast('Portfolio reset complete', 'success');
            refreshAll();
        } else {
            showToast(result.error || 'Reset failed', 'error');
        }
        refreshActivityLog();
    })
    .catch(err => {
        showToast('Reset failed', 'error');
    })
    .finally(() => {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-trash"></i> RESET PORTFOLIO';
        document.getElementById('confirm-reset').checked = false;
        btn.disabled = true;
    });
}

// ========== Activity Log ==========

function refreshActivityLog() {
    fetch('/api/activity_log')
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById('activity-log');
            container.innerHTML = '';
            
            if (!data.log || data.log.length === 0) {
                container.innerHTML = '<div class="p-3 text-muted">No activity yet.</div>';
                return;
            }
            
            data.log.forEach(entry => {
                const div = document.createElement('div');
                div.className = `log-entry log-${entry.level}`;
                div.innerHTML = `
                    <span class="log-time">[${entry.time}]</span>
                    <span class="log-msg">${entry.msg}</span>
                `;
                container.appendChild(div);
            });
        })
        .catch(err => console.error('Failed to fetch activity log:', err));
}

// ========== Toast Notifications ==========

function showToast(message, type = 'info') {
    console.log('showToast called:', message, type);
    const container = document.getElementById('toast-container');
    console.log('Toast container:', container);
    
    if (!container) {
        console.error('Toast container not found!');
        alert(message);  // Fallback to alert
        return;
    }
    
    const toastId = 'toast-' + Date.now();
    const bgClass = {
        'success': 'bg-success',
        'error': 'bg-danger',
        'warning': 'bg-warning',
        'info': 'bg-info'
    }[type] || 'bg-info';
    
    const toastHtml = `
        <div id="${toastId}" class="toast ${bgClass} text-white" role="alert">
            <div class="toast-body d-flex justify-content-between align-items-center">
                ${message}
                <button type="button" class="btn-close btn-close-white ms-2" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', toastHtml);
    console.log('Toast HTML inserted');
    
    const toastEl = document.getElementById(toastId);
    console.log('Toast element:', toastEl);
    
    if (typeof bootstrap === 'undefined') {
        console.error('Bootstrap not loaded!');
        alert(message);  // Fallback to alert
        return;
    }
    
    const toast = new bootstrap.Toast(toastEl, { autohide: true, delay: 3000 });
    toast.show();
    console.log('Toast shown');
    
    // Remove from DOM after hiding
    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
}
