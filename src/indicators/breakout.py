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

    def _get_threshold_time(self) -> time:
        """Get session hours from config"""
        mbox_time_config = settings.get("strategies.two_hunters.mbox_time", {})
        end_time = datetime.strptime(mbox_time_config["end"], "%H:%M")
        threshold = end_time + timedelta(minutes=60)
        return threshold.time()

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
            return self.custom(args["session_bars"], args["failed_signal"])
        
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
        _fvg_nearby_triggered = False

        m = len(_15_bars)
        for i, bar in enumerate(_15_bars):
            if i + lookahead >= m:
                break

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
            if _15_first_hunt_timestamp is None: return False
            if bar.timestamp > _15_first_hunt_timestamp: return True
            return False

        def fvg_nearby(bar, direction):
            return False
            fvg_results = self.fvg_detector.get_nearby_active_fvgs(bar=bar, symbol=self.symbol, pip_size=10.0)

            if fvg_results:
                bullishes = []
                bearishes = []
                for tf in fvg_results:
                    for fvg in fvg_results[tf]:
                        if fvg['type'] == 'bullish':
                            bullishes.append(fvg['high'])
                        if fvg['type'] == 'bearish':
                            bearishes.append(fvg['low'])
            
                bullishes.sort(reverse=True)
                bearishes.sort()
                
                if direction == "BUY" and bullishes:
                    return bullishes[0]

                if direction == "SELL" and bearishes:
                    return bearishes[0]

            return False

        n = len(session_bars)
        up_num_hunt = self.num_hunt
        down_num_hunt = self.num_hunt
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

                if breakout_stage_up >= up_num_hunt:
                    if bar.timestamp.time() < self._get_threshold_time():
                        up_num_hunt += 1

                    signal_bar = self.find_signal_bar(session_bars, bar, "SELL")
                    if signal_bar:
                        if not _15_triggered and not valid(bar):
                            up_num_hunt += 1
                            _15_triggered = True
                            signal_bar = None
                            continue
                        
                        if fvg_nearby(bar, "SELL") and not _fvg_nearby_triggered:
                            up_num_hunt += 1
                            max_val = fvg_nearby(bar, "SELL")
                            _fvg_nearby_triggered = True
                            signal_bar = None
                            continue

                        extrema = max(max_val, self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "SELL"))
                        return extrema, signal_bar, "SELL", bar, None
                    
                    else:
                        up_num_hunt += 1
                        continue

            elif is_local_min and current_min < min_val:
                
                breakout_stage_down += 1
                min_val = current_min

                if breakout_stage_down >= down_num_hunt:
                    if bar.timestamp.time() < self._get_threshold_time():
                        down_num_hunt += 1
                
                    signal_bar = self.find_signal_bar(session_bars, bar, "BUY")
                    if signal_bar:
                        if not _15_triggered and not valid(bar):
                            down_num_hunt += 1
                            _15_triggered = True
                            signal_bar = None
                            continue
                        
                        if fvg_nearby(bar, "BUY") and not _fvg_nearby_triggered:
                            down_num_hunt += 1
                            max_val = fvg_nearby(bar, "BUY")
                            _fvg_nearby_triggered = True
                            signal_bar = None
                            continue
                        
                        extrema = min(min_val, self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "BUY"))
                        return extrema, signal_bar, "BUY", bar, None

                    else:
                        down_num_hunt += 1
                        continue


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
                        extrema = max(max_val, self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "SELL"))
                        return extrema, signal_bar, "SELL", bar, None

                    else:
                        self.num_hunt += 1
                        continue

            elif is_local_min and current_min < min_val:
                breakout_stage_down += 1
                min_val = current_min

                if breakout_stage_down >= self.num_hunt:
                    signal_bar = self.find_signal_bar(session_bars, bar, "BUY")
                    if signal_bar:   
                        extrema = min(min_val, self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "BUY"))
                        return extrema, signal_bar, "BUY", bar, None

                    else:
                        self.num_hunt += 1
                        continue

        return None, None, None, None, None

    def custom(
        self,
        session_bars: list[Bar],
        signal: Signal,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[dict]]:

        if not session_bars:
            return None, None, None, None, None

        results: dict = {}
        num_hunt: int = 1
        fvgs = self.fvg_detector.get_nearby_active_fvgs(bar=session_bars[0], symbol=self.symbol, pip_size=5000.0)
        all_fvgs = fvgs.get("M15", []) + fvgs.get("H1", []) + fvgs.get("H4", []) + fvgs.get("H8", []) + fvgs.get("london", []) + fvgs.get("newyork", [])
        bellow_breakout_candidates = []
        above_breakout_candidates  = []

        results['take_profit'] = None
        results['stop_loss'] = None

        for fvg in all_fvgs:
            if session_bars[0].timestamp - datetime.fromisoformat(fvg.get("detection_time")) > timedelta(days=700):
                continue
            if fvg.get("type") == "bullish":
                bellow_breakout_candidates.append(fvg)

            elif fvg.get("type") == "bearish":
                above_breakout_candidates.append(fvg)

        bellow_breakout_candidates.sort(key=lambda l: l["high"], reverse=True)
        above_breakout_candidates.sort(key=lambda l: l["low"])

        to_remove = []
        for i in range(len(above_breakout_candidates)-1):
            this_fvg = above_breakout_candidates[i]
            above_fvg = above_breakout_candidates[i+1]

            # if the distance between fvgs are less that 5 pips, remove the one in the bottom.
            if abs(above_fvg['low'] - this_fvg['high']) / 0.0001 <= 5: 
                to_remove.append(this_fvg)

        for fvg in to_remove:
            above_breakout_candidates.remove(fvg)

        to_remove = []
        for i in range(len(bellow_breakout_candidates)-1):
            this_fvg = bellow_breakout_candidates[i]
            above_fvg = bellow_breakout_candidates[i+1]

            # if the distance between fvgs are less that 10 pips, remove the one at the top.
            if abs(above_fvg['low'] - this_fvg['high']) / 0.0001 <= 5: 
                to_remove.append(this_fvg)

        for fvg in to_remove:
            bellow_breakout_candidates.remove(fvg)
        
        # min_val = (bellow_breakout_candidates[0]["high"] + bellow_breakout_candidates[0]["low"]) / 2 if bellow_breakout_candidates else float("-inf")
        # max_val = (above_breakout_candidates[0]["high"] + above_breakout_candidates[0]["low"]) / 2 if above_breakout_candidates  else float("inf")

        min_val = bellow_breakout_candidates[0]["high"] if bellow_breakout_candidates else float("-inf")
        max_val = above_breakout_candidates[0]["low"]   if above_breakout_candidates  else float("inf")

        n = len(session_bars)
        lookahead: int = 1
        breakout_up = 0
        breakout_down = 0
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

            if bellow_breakout_candidates and is_local_min and current_min < min_val:

                breakout_down += 1
                min_val = current_min

                if breakout_down >= num_hunt and signal.is_buy:
                    if False: signal_bar = bar
                    
                    else:
                        signal_bar = self.find_signal_bar(session_bars, bar, "BUY")
                    
                    if signal_bar:
                        extrema = self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "BUY")
                        return extrema, signal_bar, "BUY", bar, results

                    else:
                        num_hunt += 1
                        continue

            if above_breakout_candidates and is_local_max and current_max > max_val:

                breakout_up += 1
                max_val = current_max

                if breakout_up >= num_hunt and signal.is_sell:
                    if False: signal_bar = bar
                    
                    else:
                        signal_bar = self.find_signal_bar(session_bars, bar, "SELL")
                    
                    if signal_bar:
                        extrema = self.find_extrema_between_two_bars(bar, signal_bar, session_bars, "SELL")
                        return extrema, signal_bar, "SELL", bar, results

                    else:
                        num_hunt += 1
                        continue


        return None, None, None, None, None

    def find_signal_bar(self, bars: List[Bar], hunter_bar: Bar, direction: str, look_ahead: int = 3) -> Optional[Bar]:
        """
        Find the actual order signal bar that follows a breakout (hunter bar).
        """
        try:
            idx = bars.index(hunter_bar)
        except ValueError:
            return None

        cond = True if direction == "BUY" else False

        counter = 0
        for i in range(idx, len(bars)):
            this_bar: Bar = bars[i]

            if counter == look_ahead:
                break

            if (this_bar.is_weak and idx != i):
                counter += 1
                continue

            if this_bar == hunter_bar:
                search_idx = idx-1
                while search_idx >= 0 and (bars[search_idx].is_bullish == cond or bars[search_idx].is_weak):
                    search_idx -= 1

                if search_idx >= 0:
                    to_engulf_bar = bars[search_idx]
                else:
                    to_engulf_bar = bars[0]

                if self._is_order_bar(to_engulf_bar, this_bar, direction):
                    return this_bar

            # Skip weak bars going backwards until a strong one is found
            if this_bar != hunter_bar: 
                counter += 1
                search_idx = idx
                while search_idx >= 0 and (bars[search_idx].is_bullish == cond or bars[search_idx].is_weak):
                    search_idx -= 1

                if search_idx >= 0:
                    to_engulf_bar = bars[search_idx]
                else:
                    to_engulf_bar = bars[0]

                signal = self._is_order_bar(to_engulf_bar, this_bar, direction)
                if signal:
                    return signal

        return None

    def _is_order_bar(self, prev_bar: Bar, this_bar: Bar, direction: str) -> Optional[Bar]:
        """
        Check if this_bar is valid for order placement based on previous bar and direction.
        """

        _m = settings.get("strategies.two_hunters.flags.order_block_significance")

        if direction == 'SELL':
            if this_bar.close < prev_bar.low - (prev_bar.range*_m) and this_bar.is_bearish:
                return this_bar
            # if this_bar.upper_wick / this_bar.range >= 0.9: return this_bar

        elif direction == 'BUY':
            if this_bar.close > prev_bar.high + (prev_bar.range*_m) and this_bar.is_bullish:
                return this_bar
            # if this_bar.lower_wick / this_bar.range >= 0.9: return this_bar

        return None

    def find_extrema_between_two_bars(self, hunter_bar: Bar, signal_bar: Bar, bars: List[Bar], action: str) -> float:
        """
        Find the most extreme high or low between hunter and signal bar.
        """
        extrema_bars = [bar for bar in bars if hunter_bar.timestamp <= bar.timestamp <= signal_bar.timestamp]

        if not extrema_bars:
            return hunter_bar.high if action == 'SELL' else hunter_bar.low

        # We SELL at bid and BUY at ask 
        if action == 'SELL':
            return max(extrema_bars, key=lambda bar: bar.bid_high).bid_high
        elif action == 'BUY':
            return min(extrema_bars, key=lambda bar: bar.ask_low).ask_low

        # if action == 'SELL':
        #     return max(extrema_bars, key=lambda bar: bar.ask_high).ask_high
        # elif action == 'BUY':
        #     return min(extrema_bars, key=lambda bar: bar.bid_low).bid_low

        return 0.0
