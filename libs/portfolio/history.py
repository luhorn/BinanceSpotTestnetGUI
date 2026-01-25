"""
Portfolio History Module

Handles storage and retrieval of portfolio value snapshots over time.
Supports on-demand snapshots and historical backfilling using Binance klines.
"""

import json
import os
import time
from datetime import datetime
from typing import Optional


class PortfolioHistory:
    """Manages portfolio history data storage and backfilling."""
    
    # Interval mappings in seconds
    INTERVALS = {
        '1m': 60,
        '5m': 300,
        '15m': 900,
        '1h': 3600,
        '4h': 14400,
        '1d': 86400,
    }
    
    # Smart interval selection based on time range
    RANGE_INTERVALS = {
        '1d': '15m',    # 1 day: 15-minute intervals (96 points)
        '1w': '1h',     # 1 week: hourly intervals (168 points)
        '1m': '4h',     # 1 month: 4-hour intervals (180 points)
        '6m': '1d',     # 6 months: daily intervals (180 points)
        '1y': '1d',     # 1 year: daily intervals (365 points)
        'ytd': '1d',    # Year to date: daily intervals
        'all': '1d',    # All time: daily intervals
    }
    
    # Time range mappings in seconds
    RANGE_SECONDS = {
        '1d': 86400,
        '1w': 604800,
        '1m': 2592000,
        '6m': 15552000,
        '1y': 31536000,
    }
    
    def __init__(self, data_file: str = 'resources/portfolio_history.json', client=None):
        """
        Initialize portfolio history.
        
        Args:
            data_file: Path to JSON storage file
            client: BinanceClient instance for fetching historical prices
        """
        self.data_file = data_file
        self.client = client
        self.data = self._load_data()
        self._last_snapshot_time = 0
        self._min_snapshot_interval = 60  # Minimum 60 seconds between snapshots
    
    def _load_data(self) -> dict:
        """Load history data from file."""
        default_data = {
            'snapshots': [],
            'current_holdings': {},
            'metadata': {
                'first_snapshot': None,
                'last_snapshot': None,
                'total_snapshots': 0,
                'backfilled_snapshots': 0
            }
        }
        
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    return {**default_data, **data}
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading portfolio history: {e}")
        
        return default_data
    
    def _save_data(self) -> bool:
        """Save history data to file."""
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            return True
        except IOError as e:
            print(f"Error saving portfolio history: {e}")
            return False
    
    def _update_metadata(self):
        """Update metadata based on current snapshots."""
        snapshots = self.data['snapshots']
        if snapshots:
            timestamps = [s['timestamp'] for s in snapshots]
            self.data['metadata']['first_snapshot'] = min(timestamps)
            self.data['metadata']['last_snapshot'] = max(timestamps)
            self.data['metadata']['total_snapshots'] = len(snapshots)
            self.data['metadata']['backfilled_snapshots'] = sum(
                1 for s in snapshots if s.get('is_backfilled', False)
            )
    
    def add_snapshot(self, timestamp: float, total_value: float, usdt_balance: float,
                     asset_count: int, assets_detail: dict = None, 
                     is_backfilled: bool = False) -> bool:
        """
        Add a portfolio snapshot.
        
        Args:
            timestamp: Unix timestamp
            total_value: Total portfolio value in USDT
            usdt_balance: USDT balance
            asset_count: Number of assets
            assets_detail: Detailed asset breakdown (required for backfilling)
            is_backfilled: Whether this is a backfilled snapshot
        
        Returns:
            True if snapshot was added, False if skipped (too recent)
        """
        # Check if we should skip (too recent and not backfilled)
        if not is_backfilled:
            current_time = time.time()
            if current_time - self._last_snapshot_time < self._min_snapshot_interval:
                return False
            self._last_snapshot_time = current_time
        
        # Check for duplicate timestamp (within 30 seconds tolerance)
        existing_times = {s['timestamp'] for s in self.data['snapshots']}
        for existing_time in existing_times:
            if abs(existing_time - timestamp) < 30:
                # Skip duplicate
                return False
        
        snapshot = {
            'timestamp': int(timestamp),
            'datetime': datetime.utcfromtimestamp(timestamp).isoformat() + 'Z',
            'total_value': round(total_value, 2),
            'usdt_balance': round(usdt_balance, 2),
            'asset_count': asset_count,
            'is_backfilled': is_backfilled
        }
        
        if assets_detail:
            snapshot['assets'] = assets_detail
        
        self.data['snapshots'].append(snapshot)
        
        # Sort snapshots by timestamp
        self.data['snapshots'].sort(key=lambda x: x['timestamp'])
        
        self._update_metadata()
        self._save_data()
        
        return True
    
    def update_current_holdings(self, assets_detail: dict):
        """
        Update current holdings for backfilling.
        
        Args:
            assets_detail: Dict of asset -> {'quantity': x, 'value_usdt': y}
        """
        holdings = {}
        for asset, details in assets_detail.items():
            if isinstance(details, dict):
                holdings[asset] = details.get('quantity', 0)
            else:
                holdings[asset] = details
        
        self.data['current_holdings'] = {
            **holdings,
            'last_updated': int(time.time())
        }
        self._save_data()
    
    def get_history(self, start_time: float = None, end_time: float = None) -> list:
        """
        Get portfolio history for a time range.
        
        Args:
            start_time: Start timestamp (optional)
            end_time: End timestamp (optional)
        
        Returns:
            List of snapshot dictionaries
        """
        snapshots = self.data['snapshots']
        
        if start_time is not None:
            snapshots = [s for s in snapshots if s['timestamp'] >= start_time]
        
        if end_time is not None:
            snapshots = [s for s in snapshots if s['timestamp'] <= end_time]
        
        return snapshots
    
    def get_latest_snapshot(self) -> Optional[dict]:
        """Get the most recent snapshot."""
        if self.data['snapshots']:
            return max(self.data['snapshots'], key=lambda x: x['timestamp'])
        return None
    
    def get_first_snapshot_time(self) -> Optional[float]:
        """Get timestamp of earliest snapshot."""
        return self.data['metadata'].get('first_snapshot')
    
    def get_range_start_time(self, time_range: str) -> float:
        """
        Calculate start time based on range parameter.
        
        Args:
            time_range: One of '1d', '1w', '1m', '6m', '1y', 'ytd', 'all'
        
        Returns:
            Unix timestamp for start of range
        """
        now = time.time()
        
        if time_range == 'ytd':
            year_start = datetime(datetime.now().year, 1, 1)
            return year_start.timestamp()
        
        if time_range == 'all':
            first = self.get_first_snapshot_time()
            if first:
                return first
            # Default to 1 year if no data
            return now - self.RANGE_SECONDS.get('1y', 31536000)
        
        return now - self.RANGE_SECONDS.get(time_range, 604800)  # Default 1 week
    
    def get_interval_for_range(self, time_range: str) -> str:
        """Get appropriate interval for a time range."""
        return self.RANGE_INTERVALS.get(time_range, '1h')
    
    def should_backfill(self, time_range: str) -> bool:
        """
        Check if backfilling is needed for the requested range.
        
        Returns True if there are significant gaps in the data.
        """
        if not self.client:
            return False
        
        start_time = self.get_range_start_time(time_range)
        end_time = time.time()
        
        existing_snapshots = self.get_history(start_time, end_time)
        
        # If we have very few snapshots, definitely need backfill
        interval_str = self.get_interval_for_range(time_range)
        interval_seconds = self.INTERVALS.get(interval_str, 3600)
        
        expected_count = (end_time - start_time) / interval_seconds
        actual_count = len(existing_snapshots)
        
        # Backfill if we have less than 20% of expected data points
        return actual_count < expected_count * 0.2
    
    def backfill_history(self, current_assets: dict, start_time: float, 
                        end_time: float, interval: str = '1h') -> int:
        """
        Backfill missing historical data using Binance klines.
        
        Args:
            current_assets: Dict of asset -> quantity
            start_time: Start timestamp
            end_time: End timestamp
            interval: Kline interval ('1h', '4h', '1d', etc.)
        
        Returns:
            Number of snapshots added
        """
        if not self.client:
            return 0
        
        # Get interval in seconds
        interval_seconds = self.INTERVALS.get(interval, 3600)
        
        # Get existing snapshot timestamps
        existing_times = {s['timestamp'] for s in self.data['snapshots']}
        
        # Generate expected timestamps
        expected_times = []
        current = int(start_time)
        while current <= int(end_time):
            # Check if this timestamp is not already covered
            is_covered = any(abs(current - et) < interval_seconds / 2 for et in existing_times)
            if not is_covered:
                expected_times.append(current)
            current += interval_seconds
        
        if not expected_times:
            return 0
        
        # Limit the number of backfill points to avoid API overload
        max_backfill = 500
        if len(expected_times) > max_backfill:
            # Sample evenly across the range
            step = len(expected_times) // max_backfill
            expected_times = expected_times[::step][:max_backfill]
        
        # Get list of non-USDT assets to fetch prices for
        symbols = [f"{asset}USDT" for asset in current_assets.keys() if asset != 'USDT']
        
        # Fetch historical prices for each timestamp
        added_count = 0
        
        for timestamp in expected_times:
            try:
                # Calculate portfolio value at this timestamp
                total_value = current_assets.get('USDT', 0.0)
                
                # Get historical prices
                prices = self.client.get_historical_prices(symbols, timestamp)
                
                for asset, quantity in current_assets.items():
                    if asset == 'USDT':
                        continue
                    symbol = f"{asset}USDT"
                    price = prices.get(symbol, 0.0)
                    total_value += quantity * price
                
                # Only add if we got valid prices
                if total_value > 0:
                    success = self.add_snapshot(
                        timestamp=timestamp,
                        total_value=total_value,
                        usdt_balance=current_assets.get('USDT', 0.0),
                        asset_count=len(current_assets),
                        is_backfilled=True
                    )
                    if success:
                        added_count += 1
                
            except Exception as e:
                print(f"Failed to backfill timestamp {timestamp}: {e}")
                continue
        
        return added_count
    
    def calculate_stats(self, snapshots: list) -> dict:
        """
        Calculate statistics for a list of snapshots.
        
        Args:
            snapshots: List of snapshot dictionaries
        
        Returns:
            Dict with start_value, end_value, change_percent, min_value, max_value
        """
        if not snapshots:
            return {
                'start_value': 0,
                'end_value': 0,
                'change_percent': 0,
                'min_value': 0,
                'max_value': 0
            }
        
        # Sort by timestamp
        sorted_snapshots = sorted(snapshots, key=lambda x: x['timestamp'])
        
        values = [s['total_value'] for s in sorted_snapshots]
        start_value = values[0]
        end_value = values[-1]
        
        if start_value > 0:
            change_percent = ((end_value - start_value) / start_value) * 100
        else:
            change_percent = 0
        
        return {
            'start_value': round(start_value, 2),
            'end_value': round(end_value, 2),
            'change_percent': round(change_percent, 2),
            'min_value': round(min(values), 2),
            'max_value': round(max(values), 2)
        }
    
    def prune_old_data(self, days_to_keep: int = 365) -> int:
        """
        Remove snapshots older than specified days.
        
        Args:
            days_to_keep: Number of days of history to retain
        
        Returns:
            Number of snapshots removed
        """
        cutoff_time = time.time() - (days_to_keep * 86400)
        
        original_count = len(self.data['snapshots'])
        self.data['snapshots'] = [
            s for s in self.data['snapshots'] 
            if s['timestamp'] >= cutoff_time
        ]
        
        removed_count = original_count - len(self.data['snapshots'])
        
        if removed_count > 0:
            self._update_metadata()
            self._save_data()
        
        return removed_count
    
    def set_client(self, client):
        """Set the Binance client for historical price fetching."""
        self.client = client
