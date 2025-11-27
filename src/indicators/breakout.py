from typing import List, Optional, Tuple
from collections import defaultdict
from src.core.models.bar import Bar
from src.core.data.fetcher import DataFetcher
from src.indicators.base import BaseIndicator
from datetime import datetime, time
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
        self.symbol = symbol

    def breakout(
        self,
        session_bars: List[Bar],
        box: dict,
        lookahead: int = 1,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Dispatcher method to select the calculation logic based on breakout_type enum.
        """
        if self.type == BreakoutType.DEFAULT:
            self.num_hunt = 2
            return self.default(session_bars, box, lookahead)
        
        elif self.type == BreakoutType.RECOVERY:
            self.num_hunt = 1
            return self.recovery(session_bars, box, lookahead)
        
        elif self.type == BreakoutType.CUSTOM:
            return self.custom(session_bars, box, lookahead)
        else:
            raise ValueError(f"Unknown BreakoutType: {self.type}")

    def default(
        self,
        session_bars: List[Bar],
        box: dict,
        lookahead: int = 1,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals on the main timeframe using `session_bars`.
        """
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

            if bar.timestamp.time() < time(hour=13, minute=29):
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

                if bar.timestamp.time() < time(hour=13, minute=29):
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

                if bar.timestamp.time() < time(hour=13, minute=29):
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
        lookahead: int = 1,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals on the main timeframe using `session_bars`.
        """
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
        box: dict,
        lookahead: int = 1,
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals on the main timeframe using `session_bars`.
        """
        return None, None, None, None, None

        min_val = box.get("min_val")
        max_val = box.get("max_val")
        if min_val is None or max_val is None:
            return None, None, None, None, None

        breakout_stage_up = 0
        breakout_stage_down = 0
        
        start = datetime.combine(session_bars[0].timestamp.date(), time(12, 30))
        end = session_bars[-1].timestamp
        _15_bars = self.fetcher.fetch_bars_from_mt5(start, end, self.symbol, "M15")        
        _15_first_hunt_timestamp = None
        _15_triggered = False

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
            if bar.timestamp > _15_first_hunt_timestamp:
                return True
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

                if bar.timestamp.time() < time(hour=13, minute=29):
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

                if bar.timestamp.time() < time(hour=13, minute=29):
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

            if self._is_order_bar(prev_bar, this_bar, direction):

                # Skip weak bars going backwards until a strong one is found
                search_idx = i - 1
                while search_idx >= 0 and bars[search_idx].is_weak:
                    search_idx -= 1

                if search_idx >= 0:
                    prev_bar = bars[search_idx]

                signal = self._is_order_bar(prev_bar, this_bar, direction)
                if signal:
                    return signal

        return None

    def _is_order_bar(self, prev_bar: Bar, this_bar: Bar, direction: str) -> Optional[Bar]:
        """
        Check if this_bar is valid for order placement based on previous bar and direction.
        """
        if this_bar.is_weak:
            return None

        if direction == 'SELL':
            # Bearish momentum confirmation
            if this_bar.close < prev_bar.low and this_bar.is_bearish:
                return this_bar

        elif direction == 'BUY':
            # Bullish momentum confirmation
            if this_bar.close > prev_bar.high and this_bar.is_bullish:
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
