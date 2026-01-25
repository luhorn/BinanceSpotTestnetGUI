/**
 * Portfolio Value Chart Module
 * 
 * Handles the portfolio value over time chart with time range selection
 * and logarithmic scale toggle.
 */

// ========== Chart State ==========

let portfolioChart = null;
let currentTimeRange = '1w';
let useLogScale = false;
let chartData = [];

// ========== Chart Initialization ==========

/**
 * Initialize the portfolio chart.
 */
function initPortfolioChart() {
    const canvas = document.getElementById('portfolio-chart');
    if (!canvas) {
        console.warn('Portfolio chart canvas not found');
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    portfolioChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Portfolio Value (USDT)',
                data: [],
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.1,
                pointRadius: 0,
                pointHitRadius: 10,
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: true,
                    callbacks: {
                        title: function(context) {
                            const date = new Date(context[0].parsed.x);
                            return date.toLocaleString();
                        },
                        label: function(context) {
                            const value = context.parsed.y;
                            return `Value: $${formatChartValue(value)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day',
                        displayFormats: {
                            hour: 'MMM d, HH:mm',
                            day: 'MMM d',
                            week: 'MMM d',
                            month: 'MMM yyyy'
                        }
                    },
                    title: {
                        display: false
                    },
                    grid: {
                        display: false
                    }
                },
                y: {
                    type: 'linear',
                    title: {
                        display: true,
                        text: 'Value (USDT)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '$' + formatChartValue(value);
                        }
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                }
            }
        }
    });
}

// ========== Data Loading ==========

/**
 * Load portfolio history data from the API.
 * @param {string} range - Time range (1d, 1w, 1m, 6m, 1y, ytd, all)
 */
function loadPortfolioHistory(range = '1w') {
    currentTimeRange = range;
    showChartLoading(true);
    
    fetch(`/api/portfolio_history?range=${range}&backfill=true`)
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                chartData = result.data;
                updatePortfolioChart(chartData);
                updateChartStats(result.stats);
            } else {
                showChartError(result.error || 'Failed to load chart data');
            }
        })
        .catch(err => {
            console.error('Failed to load portfolio history:', err);
            showChartError('Failed to load chart data');
        })
        .finally(() => {
            showChartLoading(false);
        });
}

/**
 * Update the chart with new data.
 * @param {Array} data - Array of {timestamp, value} objects
 */
function updatePortfolioChart(data) {
    if (!portfolioChart) {
        console.warn('Chart not initialized');
        return;
    }
    
    if (!data || data.length === 0) {
        showChartEmpty();
        return;
    }
    
    // Transform data for Chart.js
    const chartPoints = data.map(point => ({
        x: point.timestamp * 1000,  // Convert to milliseconds
        y: point.value
    }));
    
    // Update dataset
    portfolioChart.data.datasets[0].data = chartPoints;
    
    // Update time unit based on range
    const timeUnit = getTimeUnitForRange(currentTimeRange);
    portfolioChart.options.scales.x.time.unit = timeUnit;
    
    // Apply log scale if enabled
    applyLogScale(useLogScale);
    
    // Update chart
    portfolioChart.update();
}

/**
 * Get appropriate time unit for the selected range.
 * @param {string} range - Time range
 * @returns {string} Chart.js time unit
 */
function getTimeUnitForRange(range) {
    switch (range) {
        case '1d':
            return 'hour';
        case '1w':
            return 'day';
        case '1m':
            return 'day';
        case '6m':
        case '1y':
        case 'ytd':
        case 'all':
            return 'month';
        default:
            return 'day';
    }
}

// ========== Log Scale ==========

/**
 * Apply or remove logarithmic scale.
 * @param {boolean} enabled - Whether to use log scale
 */
function applyLogScale(enabled) {
    if (!portfolioChart) return;
    
    useLogScale = enabled;
    
    if (enabled) {
        portfolioChart.options.scales.y.type = 'logarithmic';
        portfolioChart.options.scales.y.title.text = 'Value (USDT) - Log Scale';
    } else {
        portfolioChart.options.scales.y.type = 'linear';
        portfolioChart.options.scales.y.title.text = 'Value (USDT)';
    }
    
    portfolioChart.update();
}

/**
 * Handle log scale toggle.
 * @param {boolean} enabled - Whether log scale is enabled
 */
function onLogScaleToggle(enabled) {
    applyLogScale(enabled);
}

// ========== Time Range ==========

/**
 * Handle time range change.
 * @param {string} range - New time range
 */
function onTimeRangeChange(range) {
    loadPortfolioHistory(range);
}

// ========== Statistics Display ==========

/**
 * Update the chart statistics display.
 * @param {Object} stats - Statistics object from API
 */
function updateChartStats(stats) {
    const statsDiv = document.getElementById('chart-stats');
    if (!statsDiv) return;
    
    if (!stats || stats.start_value === 0) {
        statsDiv.innerHTML = '<span class="text-muted small">No data available for statistics</span>';
        return;
    }
    
    const changeClass = stats.change_percent >= 0 ? 'text-success' : 'text-danger';
    const changeIcon = stats.change_percent >= 0 ? '↑' : '↓';
    
    statsDiv.innerHTML = `
        <div class="d-flex justify-content-center flex-wrap gap-3">
            <span class="badge bg-light text-dark">
                Start: $${formatChartValue(stats.start_value)}
            </span>
            <span class="badge bg-light text-dark">
                End: $${formatChartValue(stats.end_value)}
            </span>
            <span class="badge ${changeClass === 'text-success' ? 'bg-success' : 'bg-danger'} text-white">
                ${changeIcon} ${Math.abs(stats.change_percent).toFixed(2)}%
            </span>
            <span class="badge bg-secondary">
                Min: $${formatChartValue(stats.min_value)}
            </span>
            <span class="badge bg-secondary">
                Max: $${formatChartValue(stats.max_value)}
            </span>
        </div>
    `;
}

// ========== UI Helpers ==========

/**
 * Show/hide loading state.
 * @param {boolean} loading - Whether chart is loading
 */
function showChartLoading(loading) {
    const loadingEl = document.getElementById('chart-loading');
    const statsDiv = document.getElementById('chart-stats');
    
    if (loading) {
        if (loadingEl) loadingEl.style.display = 'inline';
        if (statsDiv) statsDiv.innerHTML = '<span class="text-muted small" id="chart-loading">Loading chart data...</span>';
    } else {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

/**
 * Show empty chart message.
 */
function showChartEmpty() {
    const statsDiv = document.getElementById('chart-stats');
    if (statsDiv) {
        statsDiv.innerHTML = `
            <span class="text-muted small">
                <i class="bi bi-info-circle"></i> 
                No historical data yet. Data will appear as you use the app.
            </span>
        `;
    }
    
    // Clear chart data
    if (portfolioChart) {
        portfolioChart.data.datasets[0].data = [];
        portfolioChart.update();
    }
}

/**
 * Show chart error message.
 * @param {string} message - Error message
 */
function showChartError(message) {
    const statsDiv = document.getElementById('chart-stats');
    if (statsDiv) {
        statsDiv.innerHTML = `
            <span class="text-danger small">
                <i class="bi bi-exclamation-triangle"></i> ${message}
            </span>
        `;
    }
}

/**
 * Format value for display in chart.
 * @param {number} value - Value to format
 * @returns {string} Formatted value
 */
function formatChartValue(value) {
    if (value >= 1000000) {
        return (value / 1000000).toFixed(2) + 'M';
    } else if (value >= 1000) {
        return (value / 1000).toFixed(2) + 'K';
    } else {
        return value.toFixed(2);
    }
}

// ========== Refresh Integration ==========

/**
 * Refresh the portfolio chart with current time range.
 */
function refreshPortfolioChart() {
    loadPortfolioHistory(currentTimeRange);
}

// ========== Event Listener Setup ==========

/**
 * Set up event listeners for chart controls.
 * Called from app.js on DOMContentLoaded.
 */
function setupChartEventListeners() {
    // Time range buttons
    document.querySelectorAll('input[name="time-range"]').forEach(radio => {
        radio.addEventListener('change', function() {
            onTimeRangeChange(this.value);
        });
    });
    
    // Log scale toggle
    const logToggle = document.getElementById('log-scale-toggle');
    if (logToggle) {
        logToggle.addEventListener('change', function() {
            onLogScaleToggle(this.checked);
        });
    }
}
