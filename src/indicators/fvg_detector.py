import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, time
from pathlib import Path
from src.core.models.bar import Bar
from src.core.data.fetcher import DataFetcher
from src.indicators.base import BaseIndicator


class FVGDetector(BaseIndicator):
    """
    Detects Fair Value Gaps (FVGs) in price data across multiple symbols and timeframes.
    
    FVG Definition:
    - Bullish FVG: low(bar[3]) > high(bar[1]) - gap exists between bar 1 high and bar 3 low
    - Bearish FVG: high(bar[3]) < low(bar[1]) - gap exists between bar 1 low and bar 3 high
    
    FVGs are stored in reports/fvgs and updated as they get filled/violated.
    JSON structure: {SYMBOL: {TIMEFRAME: [fvg_dict, ...], ...}, ...}
    Internal storage structure: self.fvgs[symbol][timeframe] = [fvg_dict, ...]
    """
    
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        min_gap_pips: float = 3.5,
        max_gap_pips: float = 20.0,
        timeframes: Optional[List[str]] = None,
    ):
        """
        Initialize FVG Detector.
        
        Args:
            symbols: List of trading symbols (e.g., 'EURUSD', 'GBPUSD')
            fetcher: DataFetcher instance; creates new if None
            min_gap_pips: Minimum gap size in pips to consider as valid FVG
            max_gap_pips: Maximum gap size in pips to filter out large gaps
            timeframes: List of timeframes to analyze (e.g., 'M1', 'M15', 'H1')
        """
        super().__init__("FVGDetector")
        self.symbols = symbols or ["GBPUSD.", "EURUSD."]
        self.fetcher = DataFetcher()
        self.min_gap_pips = min_gap_pips
        self.max_gap_pips = max_gap_pips
        self.timeframes = timeframes or ["M15", "H1"]
        
        # Get pip size from config (standard FX)
        self.pip_size = 0.0001
        
        # Directory for storing FVG data
        self.fvg_dir = Path("reports") / "fvgs"
        
        # Internal storage structure: {symbol: {timeframe: [fvg_dict, ...]}}
        self.fvgs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self.load_fvgs_from_cache()

    def _generate_fvg_id(self, fvg: Dict[str, Any]) -> str:
        """
        Generate a unique ID for an FVG based on its key attributes.
        This helps detect duplicate FVGs.
        
        Format: {fvg_type}_{bar_open_time}_{high}_{low}_{size_pips}
        """
        fvg_type = fvg.get("type", "unknown")
        bar_time = fvg.get("bar_open_time", "")
        high = fvg.get("high", 0)
        low = fvg.get("low", 0)
        size = fvg.get("size_pips", 0)
        
        return f"{fvg_type}_{bar_time}_{high:.5f}_{low:.5f}_{size:.2f}"
    
    def _fvg_exists(self, new_fvg: Dict[str, Any], existing_fvgs: List[Dict[str, Any]]) -> bool:
        """
        Check if an FVG already exists in the list.
        Compares by: type, bar_open_time, high, low, and size_pips.
        
        Returns:
            True if identical FVG found, False otherwise
        """
        new_id = self._generate_fvg_id(new_fvg)
        
        for existing_fvg in existing_fvgs:
            existing_id = self._generate_fvg_id(existing_fvg)
            if new_id == existing_id:
                return True
        
        return False
    
    def _merge_fvg_list(
        self, 
        existing: List[Dict[str, Any]], 
        new_fvgs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Merge new FVGs with existing ones, filtering out duplicates.
        
        Args:
            existing: List of existing FVGs
            new_fvgs: List of new FVGs to add
        
        Returns:
            Merged list with duplicates removed
        """
        for fvg in new_fvgs:
            if not self._fvg_exists(fvg, existing):
                existing.append(fvg)
        
        return existing

    def ensure_symbol_storage(self, symbol: str) -> None:
        """Ensure fvgs dict has an entry for symbol."""
        if symbol not in self.fvgs:
            self.fvgs[symbol] = {tf: [] for tf in self.timeframes}

    def detect_fvgs_in_bars(self, bars: List[Bar]) -> List[Dict[str, Any]]:
        """
        Detect FVGs in a given list of bars.
        
        Returns:
            list of FVG dicts with structure:
            {
                'type': 'bullish' or 'bearish',
                'high': float,
                'low': float,
                'size_pips': float,
                'bar_open_time': str (ISO format),
                'detection_time': str (ISO format),
                'filled_timestamp': None or str (ISO format when filled),
            }
        """
        fvg_list: List[Dict[str, Any]] = []
        
        for i in range(2, len(bars)):
            bar1, bar3 = bars[i - 2], bars[i]
            
            # Bullish FVG: low of bar3 > high of bar1
            if bar3.low > bar1.high:
                gap_pips = self.get_pip_diff(bar3.low, bar1.high)
                if self.min_gap_pips <= gap_pips <= self.max_gap_pips:
                    fvg_list.append({
                        "type": "bullish",
                        "high": bar3.low,
                        "low": bar1.high,
                        "size_pips": gap_pips,
                        "bar_open_time": bar1.timestamp.isoformat(),
                        "detection_time": bar3.timestamp.isoformat(),
                        "filled_timestamp": None,
                    })
            
            # Bearish FVG: high of bar3 < low of bar1
            if bar3.high < bar1.low:
                gap_pips = self.get_pip_diff(bar3.high, bar1.low)
                if self.min_gap_pips <= gap_pips <= self.max_gap_pips:
                    fvg_list.append({
                        "type": "bearish",
                        "high": bar1.low,
                        "low": bar3.high,
                        "size_pips": gap_pips,
                        "bar_open_time": bar1.timestamp.isoformat(),
                        "detection_time": bar3.timestamp.isoformat(),
                        "filled_timestamp": None,
                    })
        
        return fvg_list

    def clean_filled_fvgs(self) -> None:
        """
        Remove FVGs that have been filled or violated by the latest bars.
        Mark filled FVGs with their fill timestamp.
        """

        for symbol, tf_results in self.fvgs.items():
            self.ensure_symbol_storage(symbol)
            
            for tf, current_fvgs in tf_results.items():
                if tf not in self.fvgs[symbol]:
                    self.fvgs[symbol][tf] = []
                
                try:
                    # Determine oldest FVG time for this symbol/timeframe
                    if self.fvgs[symbol][tf]:
                        oldest_fvg_time = min(
                            datetime.fromisoformat(fvg["bar_open_time"])
                            for fvg in self.fvgs[symbol][tf]
                        )
                        check_bars = self.fetcher.fetch_bars_from_mt5(
                            oldest_fvg_time,
                            datetime.now(),
                            symbol,
                            "M1",
                        )
                    else:
                        check_bars = []
                    
                    # Mark filled FVGs and filter out violated ones
                    active_fvgs: List[Dict[str, Any]] = []
                    
                    for fvg in self.fvgs[symbol][tf]:
                        # Skip if already marked as filled
                        if fvg.get("filled_timestamp") is not None:
                            active_fvgs.append(fvg)
                            continue
                        
                        is_filled, filled_time = self.is_fvg_filled(fvg, check_bars)
                        if is_filled:
                            # Mark with fill timestamp
                            fvg["filled_timestamp"] = filled_time
                        
                        active_fvgs.append(fvg)
                    
                    # Add newly detected FVGs (with duplicate check)
                    active_fvgs = self._merge_fvg_list(active_fvgs, current_fvgs)
                    self.fvgs[symbol][tf] = active_fvgs
                
                except Exception as e:
                    # In case of error, keep existing + add new (with duplicate check)
                    self.fvgs[symbol][tf] = self._merge_fvg_list(
                        self.fvgs[symbol][tf], 
                        current_fvgs
                    )

    def is_fvg_filled(self, fvg: Dict[str, Any], bars: List[Bar]) -> bool | None:
        """
        Check if an FVG has been filled (touched/penetrated) by price.
        
        - Bullish FVG is filled when bar.low <= fvg['low']
        - Bearish FVG is filled when bar.high >= fvg['high']
        """
        fvg_type = fvg["type"]
        fvg_high = fvg["high"]
        fvg_low = fvg["low"]
        detection_time = datetime.fromisoformat(fvg["detection_time"]) + timedelta(minutes=15)
        
        # Only check bars after detection
        bars_after = [bar for bar in bars if bar.timestamp > detection_time]
        
        for bar in bars_after:
            if fvg_type == "bullish":
                # Bullish FVG filled when low penetrates into gap
                if bar.low <= fvg_high:
                    return True, bar.timestamp.isoformat()
            elif fvg_type == "bearish":
                # Bearish FVG filled when high penetrates into gap
                if bar.high >= fvg_low:
                    return True, bar.timestamp.isoformat()
        
        return False, None

    def get_fvg_cache_path(self, symbol: str) -> Path:
        """Get path to FVG cache JSON file for a symbol."""
        return self.fvg_dir / f"{symbol}_fvgs.json"

    def save_fvgs_to_cache(self) -> None:
        """
        Save current FVGs to JSON cache (one file per symbol).
        Uses filled_timestamp instead of status field.
        """
        try:
            self.fvg_dir.mkdir(parents=True, exist_ok=True)
            
            for symbol, tf_dict in self.fvgs.items():
                cache_path = self.get_fvg_cache_path(symbol)
                
                # Build serializable dict
                serializable_fvgs: Dict[str, List[Dict[str, Any]]] = {}
                
                for tf, fvg_list in tf_dict.items():
                    serializable_fvgs[tf] = []
                    
                    for fvg in fvg_list:
                        # Ensure timestamps are ISO strings
                        fvg_copy = fvg.copy()
                        
                        if not isinstance(fvg_copy.get("bar_open_time"), str):
                            fvg_copy["bar_open_time"] = fvg_copy["bar_open_time"].isoformat()
                        
                        if not isinstance(fvg_copy.get("detection_time"), str):
                            fvg_copy["detection_time"] = fvg_copy["detection_time"].isoformat()
                        
                        serializable_fvgs[tf].append(fvg_copy)
                
                # Write to cache
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(serializable_fvgs, f, indent=2)
        
        except Exception as e:
            # Silently fail if cache write fails
            print(e)
            pass

    def load_fvgs_from_cache(self) -> None:
        """Load FVGs from JSON cache for all configured symbols."""
        self.fvgs = {}
        
        try:
            for symbol in self.symbols:
                cache_path = self.get_fvg_cache_path(symbol)
                
                if cache_path.exists():
                    with open(cache_path, "r", encoding="utf-8") as f:
                        self.fvgs[symbol] = json.load(f)
                else:
                    self.fvgs[symbol] = {tf: [] for tf in self.timeframes}
        
        except Exception:
            # Initialize empty if load fails
            for symbol in self.symbols:
                self.fvgs[symbol] = {tf: [] for tf in self.timeframes}

    def get_active_fvgs(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Get active (unfilled) FVGs.
        
        Args:
            symbol: Filter by symbol, or None for all
            timeframe: Filter by specific timeframe, or None for all
        
        Returns:
            Dict[symbol][timeframe] = list of active FVGs (filled_timestamp is None)
        """
        symbols = [symbol] if symbol else list(self.fvgs.keys())
        result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        
        for sym in symbols:
            if sym not in self.fvgs:
                continue
            
            tf_dict = self.fvgs[sym]
            
            if timeframe:
                active = [
                    fvg for fvg in tf_dict.get(timeframe, [])
                    if fvg.get("filled_timestamp") is None
                ]
                if active:
                    result.setdefault(sym, {})[timeframe] = active
            else:
                for tf, fvg_list in tf_dict.items():
                    active = [
                        fvg for fvg in fvg_list
                        if fvg.get("filled_timestamp") is None
                    ]
                    if active:
                        result.setdefault(sym, {})[tf] = active
        
        return result

    def get_filled_fvgs(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Get filled (touched/penetrated) FVGs.
        
        Args:
            symbol: Filter by symbol, or None for all
            timeframe: Filter by specific timeframe, or None for all
        
        Returns:
            Dict[symbol][timeframe] = list of filled FVGs (filled_timestamp is not None)
        """
        symbols = [symbol] if symbol else list(self.fvgs.keys())
        result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        
        for sym in symbols:
            if sym not in self.fvgs:
                continue
            
            tf_dict = self.fvgs[sym]
            
            if timeframe:
                filled = [
                    fvg for fvg in tf_dict.get(timeframe, [])
                    if fvg.get("filled_timestamp") is not None
                ]
                if filled:
                    result.setdefault(sym, {})[timeframe] = filled
            else:
                for tf, fvg_list in tf_dict.items():
                    filled = [
                        fvg for fvg in fvg_list
                        if fvg.get("filled_timestamp") is not None
                    ]
                    if filled:
                        result.setdefault(sym, {})[tf] = filled
        
        return result

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """
        Clear cache files.
        
        Args:
            symbol: If provided, clear only this symbol; otherwise all symbols.
        """
        try:
            target_symbols = [symbol] if symbol else self.symbols
            
            for sym in target_symbols:
                cache_path = self.get_fvg_cache_path(sym)
                
                if cache_path.exists():
                    cache_path.unlink()
                
                if sym in self.fvgs:
                    self.fvgs[sym] = {tf: [] for tf in self.timeframes}
        
        except Exception:
            pass

    def get_pip_diff(self, price1: float, price2: float) -> float:
        """Calculate price difference in pips."""
        return abs(price1 - price2) / self.pip_size

    def pips_to_price(self, pips: float) -> float:
        """Convert pips to price value."""
        return pips * self.pip_size

    def detect(
        self,
        start_dt: datetime,
        end_dt: datetime,
        timeframes: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Detect FVGs across multiple symbols and timeframes within a datetime range.
        
        Args:
            start_dt: Start datetime
            end_dt: End datetime
            timeframes: Override default timeframes
            symbols: Override default symbols
        
        Returns:
            Dict[symbol][timeframe] = list of detected FVG dicts
        """
        tf_list = timeframes or self.timeframes
        symbol_list = symbols or self.symbols
        
        results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        
        for symbol in symbol_list:
            symbol_results: Dict[str, List[Dict[str, Any]]] = {}
            
            for tf in tf_list:
                try:
                    bars = self.fetcher.fetch_bars_from_mt5(
                        start_dt,
                        end_dt,
                        symbol,
                        tf,
                    )
                    
                    if bars:
                        fvgs = self.detect_fvgs_in_bars(bars)
                        symbol_results[tf] = fvgs
                        self.ensure_symbol_storage(symbol)
                        # Use merge instead of extend
                        self.fvgs[symbol][tf] = self._merge_fvg_list(
                            self.fvgs[symbol][tf],
                            fvgs
                        )
                    else:
                        symbol_results[tf] = []
                
                except Exception:
                    symbol_results[tf] = []
            
            results[symbol] = symbol_results
        
        # Clean up filled/violated FVGs
        self.clean_filled_fvgs()
        
        # Save to cache
        self.save_fvgs_to_cache()
        
        return results

    def get_nearby_active_fvgs(
        self,
        bar: Bar,
        symbol: str,
        pip_size: float,
        timeframes: List[str] = ["H1", "M15"],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all active FVGs for a given symbol where the distance from the bar
        is less than the given pip_size, organized by timeframe.
        
        An FVG is considered active for the bar if:
        - bar.timestamp < fvg['filled_timestamp'] (bar is before fill time), OR
        - fvg['filled_timestamp'] is None (FVG never filled)
        
        Distance calculation:
            - Bullish FVG: distance = abs(bar.low  - fvg['high']) / pip_size
            - Bearish FVG: distance = abs(bar.high - fvg['low']) / pip_size
        
        Args:
            bar: Bar object to check against
            symbol: Symbol to query FVGs for
            pip_size: Maximum distance in pips from bar to FVG
            timeframes: List of timeframes to query (default ["H1", "M15"])
        
        Returns:
            Dict[timeframe] = list of active FVG dicts within pip_size distance
            Example: {"H1": [fvg1, fvg2], "M15": [fvg3, fvg4]}
        """
        results: Dict[str, List[Dict[str, Any]]] = {tf: [] for tf in timeframes}
        
        if bar is None:
            return results
        
        if symbol not in self.fvgs:
            return results
        
        for tf in timeframes:
            if tf not in self.fvgs[symbol]:
                continue
            
            for fvg in self.fvgs[symbol][tf]:
                # Check if FVG is active at bar's timestamp
                filled_ts = fvg.get("filled_timestamp")
                
                if filled_ts is None:
                    is_active = True
                else:
                    # Convert filled_timestamp to datetime if it's a string
                    if isinstance(filled_ts, str):
                        filled_dt = datetime.fromisoformat(filled_ts)
                    else:
                        filled_dt = filled_ts
                    
                    # FVG is active if bar is before fill time
                    is_active = bar.timestamp < filled_dt
                
                if not is_active:
                    continue
                
                # Compute distance based on FVG type
                if fvg["type"] == "bullish":
                    # Distance from bar.low to fvg's high boundary
                    distance = abs(bar.low - fvg["high"]) / pip_size
                elif fvg["type"] == "bearish":
                    # Distance from bar.high to fvg's low boundary
                    distance = abs(bar.high - fvg["low"]) / pip_size
                else:
                    continue
                
                # Include if distance is within pip_size
                if distance <= pip_size:
                    results[tf].append(fvg)
        
        return results