from typing import List, Optional, Tuple, Dict, Any
from src.indicators.fvg_detector import FVGDetector
from src.core.models.bar import Bar
from src.core.models.signal import Signal
from src.core.data.fetcher import DataFetcher
from src.indicators.base import BaseIndicator
from config.settings import settings
from datetime import datetime, time, timedelta
from enum import Enum

class BreakoutType(Enum):
    DEFAULT = "default"
    RECOVERY = "recovery"
    CUSTOM = "custom"

class BreakoutEngine(BaseIndicator):
    """
    Breakout detection engine for identifying trading opportunities.
    No higher timeframe validation.
    """

    def __init__(self, num_hunt: int = 2, symbol: str = ""):
        super().__init__("BreakoutEngine")
        self.num_hunt = num_hunt
        self.type = BreakoutType.DEFAULT
        self.fetcher = DataFetcher()
        self.fvg_detector = FVGDetector()
        self.symbol = symbol

    def _get_mbox_end_time(self) -> time:
        """Get session hours from config"""
        mbox_time_config = settings.get("strategies.two_hunters.mbox_time", {})
        
        end_time = datetime.strptime(mbox_time_config["end"], "%H:%M").time()
        return end_time

    def breakout(
        self,
        **args,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Dispatcher method to select the calculation logic based on breakout_type enum.
        """
        if self.type == BreakoutType.DEFAULT:
            self.num_hunt = 2
            return self.default(args["session_bars"], args["mbox_result"])
        
        elif self.type == BreakoutType.RECOVERY:
            self.num_hunt = 1
            return self.recovery(args["recovery_bars"], args["extended_mbox_results"])
        
        elif self.type == BreakoutType.CUSTOM:
            return self.custom(args["session_bars"], args["mbox_result"], args["london_results"], 
                               args["newyork_results"], args["fvg_results"])
        
        else:
            raise ValueError(f"Unknown BreakoutType: {self.type}")

    def default(
        self,
        session_bars: List[Bar],
        box: dict,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals on the main timeframe using `session_bars`.
        """
        lookahead: int = 1
        if not session_bars or not box:
            return None, None, None, None, None

        min_val = box.get("min_val")
        max_val = box.get("max_val")
        if min_val is None or max_val is None:
            return None, None, None, None, None

        breakout_stage_up = 0
        breakout_stage_down = 0
        
        start = session_bars[0].timestamp
        end = session_bars[-1].timestamp
        _15_bars = self.fetcher.fetch_bars_from_mt5(start, end, self.symbol, "M15")        
        _15_first_hunt_timestamp = None
        _15_triggered = False

        m = len(_15_bars)
        for i, bar in enumerate(_15_bars):
            if i + lookahead >= m:
                break

            if bar.timestamp.time() < self._get_mbox_end_time() + timedelta(hours=1):
                continue

            current_max = bar.high
            current_min = bar.low

            is_local_max = all(
                current_max > _15_bars[j].high for j in range(i + 1, min(i + 1 + lookahead, m))
            )
            is_local_min = all(
                current_min < _15_bars[j].low for j in range(i + 1, min(i + 1 + lookahead, m))
            )

            if is_local_max and current_max > max_val:
                _15_first_hunt_timestamp = bar.timestamp
                break
            elif is_local_min and current_min < min_val:
                _15_first_hunt_timestamp = bar.timestamp
                break
        
        def valid(bar: Bar) -> bool:
            # return True
            if _15_first_hunt_timestamp is None: return False
            if bar.timestamp > _15_first_hunt_timestamp: return True
            return False

        n = len(session_bars)
        for i, bar in enumerate(session_bars):
            if i + lookahead >= n:
                break

            current_max = bar.high
            current_min = bar.low

            is_local_max = all(
                current_max > session_bars[j].high for j in range(i + 1, min(i + 1 + lookahead, n))
            )
            is_local_min = all(
                current_min < session_bars[j].low for j in range(i + 1, min(i + 1 + lookahead, n))
            )

            if is_local_max and current_max > max_val:
                breakout_stage_up += 1
                max_val = current_max

                if bar.timestamp.time() < self._get_mbox_end_time() + timedelta(hours=1):
                    self.num_hunt += 1

                if breakout_stage_up >= self.num_hunt:
                    signal_bar = self.find_signal_bar(session_bars, bar, "SELL")
                    if signal_bar:
                        if not _15_triggered and not valid(bar):
                            self.num_hunt += 1
                            _15_triggered = True
                            continue
                        
                        extrema = max(max_val, self.find_extrema_bar(bar, signal_bar, session_bars, "SELL"))
                        return extrema, signal_bar, "SELL", bar, None

            elif is_local_min and current_min < min_val:
                breakout_stage_down += 1
                min_val = current_min

                if bar.timestamp.time() < self._get_mbox_end_time() + timedelta(hours=1):
                    self.num_hunt += 1

                if breakout_stage_down >= self.num_hunt:
                    signal_bar = self.find_signal_bar(session_bars, bar, "BUY")
                    if signal_bar:
                        if not _15_triggered and not valid(bar):
                            self.num_hunt += 1
                            _15_triggered = True
                            continue

                        extrema = min(min_val, self.find_extrema_bar(bar, signal_bar, session_bars, "BUY"))
                        return extrema, signal_bar, "BUY", bar, None

        return None, None, None, None, None

    def recovery(
        self,
        session_bars: List[Bar],
        box: dict,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals on the main timeframe using `session_bars`.
        """
        lookahead: int = 1
        if not session_bars or not box:
            return None, None, None, None, None

        min_val = box.get("min_val")
        max_val = box.get("max_val")
        if min_val is None or max_val is None:
            return None, None, None, None, None

        breakout_stage_up = 0
        breakout_stage_down = 0
    
        n = len(session_bars)
        for i, bar in enumerate(session_bars):
            if i + lookahead >= n:
                break

            current_max = bar.high
            current_min = bar.low

            is_local_max = all(
                current_max > session_bars[j].high for j in range(i + 1, min(i + 1 + lookahead, n))
            )
            is_local_min = all(
                current_min < session_bars[j].low for j in range(i + 1, min(i + 1 + lookahead, n))
            )

            if is_local_max and current_max > max_val:
                breakout_stage_up += 1
                max_val = current_max

                if breakout_stage_up >= self.num_hunt:
                    signal_bar = self.find_signal_bar(session_bars, bar, "SELL")
                    if signal_bar:
                        extrema = max(max_val, self.find_extrema_bar(bar, signal_bar, session_bars, "SELL"))
                        return extrema, signal_bar, "SELL", bar, None

            elif is_local_min and current_min < min_val:
                breakout_stage_down += 1
                min_val = current_min

                if breakout_stage_down >= self.num_hunt:
                    signal_bar = self.find_signal_bar(session_bars, bar, "BUY")
                    if signal_bar:   
                        extrema = min(min_val, self.find_extrema_bar(bar, signal_bar, session_bars, "BUY"))
                        return extrema, signal_bar, "BUY", bar, None

        return None, None, None, None, None

    def custom(
        self,
        session_bars: List[Bar],
        mbox_result: dict,
        london_results: dict,
        newyork_results: dict,
        fvgs: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[dict]]:
        """
        Custom recovery strategy that uses FVGs and session extrema as breakout lines.
        """
        lookahead = 1
        
        # ===== Step 1: Determine current position relative to MBox =====
        if not session_bars or not mbox_result:
            return None, None, None, None, None
        
        mbox_min = mbox_result.get('min_val')
        mbox_max = mbox_result.get('max_val')
        
        if mbox_min is None or mbox_max is None:
            return None, None, None, None, None
        
        if not session_bars:
            return None, None, None, None, None
        
        # Current price reference
        current_bar = session_bars[0]

        # Determine if we're below or above MBox
        if current_bar.close < mbox_min:
            is_bullish_side = True
            breakout_direction = "BUY"

        elif current_bar.close > mbox_max:
            is_bullish_side = False
            breakout_direction = "SELL"

        else:
            return None, None, None, None, None
        
        # ===== Step 2: Get breakout line from FVGs and session extrema =====
        breakout_line = None
        breakout_line_source = None  # Track source for logging
        
        # Extract all FVGs from both timeframes
        all_fvgs = fvgs.get("M15", []) + fvgs.get("H1", [])
        
        if is_bullish_side:
            # Bullish: Get bullish FVGs, London min, AND New York min as backup
            bullish_fvgs = [fvg for fvg in all_fvgs if fvg['type'] == 'bullish']
            
            london_min = london_results.get('min_val')
            newyork_min = newyork_results.get('min_val')
            
            # Collect candidate breakout lines
            candidates = []

            # Add FVG midpoints
            for fvg in bullish_fvgs:
                fvg_mid = (fvg['high'] + fvg['low']) / 2
                candidates.append((fvg_mid, 'bullish_fvg_mid'))
            
            # Add London min
            if london_min is not None:
                candidates.append((london_min, 'london_min'))
            
            # Add New York min
            if newyork_min is not None:
                candidates.append((newyork_min, 'newyork_min'))
            
            # Add MBox min as final fallback
            candidates.append((mbox_min, 'mbox_min'))
            
            # Choose closest candidate below current price
            below_candidates = [(price, source) for price, source in candidates if price < current_bar.low]
            
            if below_candidates:
                breakout_line = min(below_candidates, key=lambda x: abs(x[0] - current_bar.low))
            
            else:
                return None, None, None, None, None
        
        else:  # Bearish side
            # Bearish: Get bearish FVGs, New York max, AND London max as backup
            bearish_fvgs = [fvg for fvg in all_fvgs if fvg['type'] == 'bearish']
            
            newyork_max = newyork_results.get('max_val')
            london_max = london_results.get('max_val')
            
            # Collect candidate breakout lines
            candidates = []
            
            # Add FVG midpoints
            for fvg in bearish_fvgs:
                fvg_mid = (fvg['high'] + fvg['low']) / 2
                candidates.append((fvg_mid, 'bearish_fvg_mid'))
            
            # Add New York max
            if newyork_max is not None:
                candidates.append((newyork_max, 'newyork_max'))
            
            # Add London max
            if london_max is not None:
                candidates.append((london_max, 'london_max'))
            
            # Add MBox max as final fallback
            candidates.append((mbox_max, 'mbox_max'))
            
            # Choose closest candidate above current price
            above_candidates = [(price, source) for price, source in candidates if price > current_bar.high]
            
            if above_candidates:
                breakout_line = max(above_candidates, key=lambda x: abs(current_bar.high - x[0]))
            
            else:
                return None, None, None, None, None
        
        # ===== Step 3: Loop through session bars and wait for breakout =====
        breakout_bar = None
        breakout_index = None
        for i, bar in enumerate(session_bars):
            if i < lookahead:
                continue
            
            if is_bullish_side:
                if bar.low < breakout_line[0]:
                    breakout_bar = bar
                    breakout_index = i
                    break
            else:
                if bar.high > breakout_line[0]:
                    breakout_bar = bar
                    breakout_index = i
                    break
        
        if breakout_bar is None or breakout_index is None:
            # No breakout occurred
            return None, None, None, None, None
        
        # ===== Step 4: Wait for local extrema to form =====
        # Extrema must be higher/lower than before and after bar (at least 1 pip)
        extrema_bar = None
        extrema_price = None
        extrema_index = None
        
        for i in range(breakout_index, len(session_bars)):
            bar = session_bars[i]
            prev_bar = session_bars[i - 1]
            next_bar = session_bars[i + 1] if i + 1 < len(session_bars) else None
            
            if next_bar is None:
                # Can't form complete extrema without next bar
                continue
            
            if is_bullish_side:
                # Look for local minimum (lower low than before and after)
                is_local_min = (
                    bar.low < prev_bar.low - 0.00001 and  # At least 1 pip lower than previous
                    bar.low < next_bar.low - 0.00001  # At least 1 pip lower than next
                )
                
                if is_local_min:
                    extrema_bar = bar
                    extrema_price = bar.low
                    extrema_index = i
                    break
            
            else:  # Bearish
                # Look for local maximum (higher high than before and after)
                is_local_max = (
                    bar.high > prev_bar.high + 0.00001 and  # At least 1 pip higher than previous
                    bar.high > next_bar.high + 0.00001  # At least 1 pip higher than next
                )
                
                if is_local_max:
                    extrema_bar = bar
                    extrema_price = bar.high
                    extrema_index = i
                    break
        
        if extrema_bar is None:
            # No extrema formed, can't proceed
            return None, None, None, None, None
        
        # ===== Step 5: Look for order bar after extrema =====
        signal_bar = None
        
        for i in range(extrema_index + 1, len(session_bars)):
            this_bar = session_bars[i]
            prev_bar = session_bars[i - 1]
            
            signal_bar = self._is_order_bar(prev_bar, this_bar, breakout_direction, True)
            if signal_bar:
                break
        
        if signal_bar is None:
            return None, None, None, None, None
        
        # ===== Step 6: Determine S/L and T/P levels =====
        results = {}
        
        # Get session levels once for reuse
        london_min = london_results.get('min_val')
        london_max = london_results.get('max_val')
        newyork_min = newyork_results.get('min_val')
        newyork_max = newyork_results.get('max_val')
        
        # Separate FVGs by type for easier access
        bullish_fvgs = [fvg for fvg in all_fvgs if fvg['type'] == 'bullish']
        bearish_fvgs = [fvg for fvg in all_fvgs if fvg['type'] == 'bearish']
        
        if is_bullish_side:

            # Stop Loss
            sl_candidates = []
            for fvg in bullish_fvgs:
                # sl_candidates.append((fvg['high'], 'bullish_fvg_high')) if fvg['high'] < extrema_price else None
                # sl_candidates.append((fvg['low'],  'bullish_fvg_low'))  if fvg['low']  < extrema_price else None
                _mid = (fvg['low'] + fvg['high']) / 2
                sl_candidates.append((_mid,  'bullish_fvg_mid'))  if _mid < extrema_price else None

            if london_min is not None:
                sl_candidates.append((london_min, 'london_min')) if london_min < extrema_price else None
            
            if newyork_min is not None:
                sl_candidates.append((newyork_min, 'newyork_min')) if newyork_min < extrema_price else None
            
            # Sort by distance from extrema price and get second nearest
            sl_candidates_sorted = sorted(sl_candidates, key=lambda x: abs(x[0] - extrema_price))

            _r = max(abs(extrema_price - signal_bar.close), 0.00001)
            _to_remove = []

            for sl_candidate in sl_candidates_sorted:
                _xr = abs(sl_candidate[0] - signal_bar.close) / _r
                if _xr < 1.1:
                    _to_remove.append(sl_candidate)

            for sl_candidate in _to_remove:
                sl_candidates_sorted.remove(sl_candidate)

            if sl_candidates_sorted:
                results['stop_loss'] = sl_candidates_sorted[0][0]
            
            else:
                results['stop_loss'] = None  # Fallback
            
            # Take Profit
            tp_candidates = []
            for fvg in bearish_fvgs:
                tp_candidates.append((fvg['low'],  'bearish_fvg_low'))  if fvg['low'] > extrema_price else None
                tp_candidates.append((fvg['high'], 'bearish_fvg_high')) if fvg['high'] > extrema_price else None
                # _fvg_mid = (fvg['high'] + fvg['low']) / 2
                # tp_candidates.append((_fvg_mid, 'bearish_fvg_mid')) if _fvg_mid > extrema_price else None

            if mbox_max is not None:
                tp_candidates.append((mbox_max, 'mbox_max')) if mbox_max > extrema_price else None

            if mbox_min is not None:
                tp_candidates.append((mbox_min, 'mbox_min')) if mbox_min > extrema_price else None

            if newyork_max is not None:
                tp_candidates.append((newyork_max, 'newyork_max')) if newyork_max > extrema_price else None
            
            if london_max is not None:
                tp_candidates.append((london_max, 'london_max')) if london_max > extrema_price else None
            
            # Choose nearest T/P above the entry
            tp_candidates_sorted = sorted(tp_candidates, key=lambda x: abs(x[0] - extrema_price))

            to_remove = []
            for tp_candidate in tp_candidates_sorted:
                if results["stop_loss"]:
                    _r = abs(results["stop_loss"] - signal_bar.close)
                    _xr = abs(signal_bar.close - tp_candidate[0]) / _r
                    if _xr < 2:
                        to_remove.append(tp_candidate)
                
                else:
                    _r = abs(extrema_price - signal_bar.close)
                    _xr = abs(signal_bar.close - tp_candidate[0]) / _r
                    if _xr < 3 or _xr > 6:
                        to_remove.append(tp_candidate)

            for tp_candidate in to_remove:
                tp_candidates_sorted.remove(tp_candidate)

            if len(tp_candidates_sorted) >= 2:
                if (tp_candidates_sorted[0][0] - tp_candidates_sorted[1][0]) / 0.0001 < 5:
                    tp_candidates_sorted.pop(0)

            if tp_candidates_sorted:
                results['take_profit'] = tp_candidates_sorted[0][0]
            
            else:
                results['take_profit'] = None  # Fallback
        

        else: # is_bearish_side
                
            # Stop Loss
            sl_candidates = []
            for fvg in bearish_fvgs:
                # sl_candidates.append((fvg['low'],  'bearish_fvg_low'))  if fvg['low']  > extrema_price else None
                # sl_candidates.append((fvg['high'], 'bearish_fvg_high')) if fvg['high'] > extrema_price else None
                _mid = (fvg['low'] + fvg['high']) / 2
                sl_candidates.append((_mid, 'bearish_fvg_mid')) if _mid > extrema_price else None

            if london_max is not None:
                sl_candidates.append((london_max, 'london_max')) if london_max > extrema_price else None
            
            if newyork_max is not None:
                sl_candidates.append((newyork_max, 'newyork_max')) if newyork_max > extrema_price else None
            
            # Sort by distance from extrema price and get second nearest
            sl_candidates_sorted = sorted(sl_candidates, key=lambda x: abs(x[0] - extrema_price))

            _r = abs(extrema_price - signal_bar.close)
            _to_remove = []

            for sl_candidate in sl_candidates_sorted:
                _xr = abs(sl_candidate[0] - signal_bar.close) / _r
                if _xr < 1.1:
                    _to_remove.append(sl_candidate)

            for sl_candidate in _to_remove:
                sl_candidates_sorted.remove(sl_candidate)

            if sl_candidates_sorted:
                results['stop_loss'] = sl_candidates_sorted[0][0]
            
            else:
                results['stop_loss'] = None  # Fallback
            

            # Take Profit
            tp_candidates = []
            for fvg in bullish_fvgs:
                tp_candidates.append((fvg['low'],  'bullish_fvg_low'))  if fvg['low'] < extrema_price else None
                tp_candidates.append((fvg['high'], 'bullish_fvg_high')) if fvg['high'] < extrema_price else None
                # _fvg_mid = (fvg['high'] + fvg['low']) / 2
                # tp_candidates.append((_fvg_mid, 'bullish_fvg_mid')) if _fvg_mid < extrema_price else None

            if mbox_max is not None:
                tp_candidates.append((mbox_max, 'mbox_max')) if mbox_max < extrema_price else None

            if mbox_min is not None:
                tp_candidates.append((mbox_min, 'mbox_min')) if mbox_min < extrema_price else None

            if newyork_min is not None:
                tp_candidates.append((newyork_min, 'newyork_min')) if newyork_min < extrema_price else None
            
            if london_min is not None:
                tp_candidates.append((london_min, 'london_min')) if london_min < extrema_price else None
            
            # Choose nearest T/P above the entry
            tp_candidates_sorted = sorted(tp_candidates, key=lambda x: abs(x[0] - extrema_price))

            to_remove = []
            for tp_candidate in tp_candidates_sorted:
                
                if results["stop_loss"]:
                    _r = abs(results["stop_loss"] - signal_bar.close)
                    _xr = abs(signal_bar.close - tp_candidate[0]) / _r
                    if _xr < 2:
                        to_remove.append(tp_candidate)
                
                else:
                    _r = abs(extrema_price - signal_bar.close)
                    _xr = abs(signal_bar.close - tp_candidate[0]) / _r
                    if _xr < 3 or _xr > 6:
                        to_remove.append(tp_candidate)

            for tp_candidate in to_remove:
                tp_candidates_sorted.remove(tp_candidate)

            if len(tp_candidates_sorted) >= 2:
                if (tp_candidates_sorted[0][0] - tp_candidates_sorted[1][0]) / 0.0001 < 5:
                    tp_candidates_sorted.pop(0)

            if tp_candidates_sorted:
                results['take_profit'] = tp_candidates_sorted[0][0]
            
            else:
                results['take_profit'] = None  # Fallback

        # ===== Return results =====
        results['take_profit'] = None
        results['stop_loss'] = None
        return extrema_price, signal_bar, breakout_direction, breakout_bar, results

    def find_signal_bar(self, bars: List[Bar], hunter_bar: Bar, direction: str) -> Optional[Bar]:
        """
        Find the actual order signal bar that follows a breakout (hunter bar).
        """
        try:
            idx = bars.index(hunter_bar)
        except ValueError:
            return None

        for i in range(idx + 1, len(bars)):
            this_bar = bars[i]
            prev_bar = bars[i - 1] if i > 0 else bars[0]

            if self._is_order_bar(prev_bar, this_bar, direction, False):

                # Skip weak bars going backwards until a strong one is found
                search_idx = i - 1
                while search_idx >= 0 and bars[search_idx].is_weak:
                    search_idx -= 1

                if search_idx >= 0:
                    prev_bar = bars[search_idx]

                signal = self._is_order_bar(prev_bar, this_bar, direction, False)
                if signal:
                    return signal

        return None

    def _is_order_bar(self, prev_bar: Bar, this_bar: Bar, direction: str, cunt: bool) -> Optional[Bar]:
        """
        Check if this_bar is valid for order placement based on previous bar and direction.
        """
        if this_bar.is_weak:
            return None
        
        _m = settings.get("strategies.two_hunters.flags.order_block_significance")

        if direction == 'SELL':
            # Bearish momentum confirmation
            if this_bar.close < prev_bar.low - (prev_bar.range*_m) and this_bar.is_bearish:
                return this_bar

        elif direction == 'BUY':
            # Bullish momentum confirmation
            if this_bar.close > prev_bar.high + (prev_bar.range*_m) and this_bar.is_bullish:
                return this_bar

        return None

    def find_extrema_bar(self, hunter_bar: Bar, signal_bar: Bar, bars: List[Bar], action: str) -> float:
        """
        Find the most extreme high or low between hunter and signal bar.
        """
        extrema_bars = [bar for bar in bars if hunter_bar.timestamp <= bar.timestamp <= signal_bar.timestamp]

        if not extrema_bars:
            return hunter_bar.high if action == 'SELL' else hunter_bar.low

        if action == 'SELL':
            return max(extrema_bars, key=lambda bar: bar.high).high
        elif action == 'BUY':
            return min(extrema_bars, key=lambda bar: bar.low).low

        return 0.0
