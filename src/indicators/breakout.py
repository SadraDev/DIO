from typing import List, Optional, Tuple
from src.core.models.bar import Bar
from src.indicators.base import BaseIndicator


class BreakoutEngine(BaseIndicator):
    """
    Breakout detection engine for identifying trading opportunities.
    Adapted from original code.
    """
    
    def __init__(self, num_hunt: int = 2):
        super().__init__("BreakoutEngine")
        self.num_hunt = num_hunt

    def calculate(
        self, session_bars: List[Bar], mbox_result: dict, lookahead: int = 1
    ) -> Tuple[Optional[float], Optional[Bar], Optional[str], Optional[Bar], Optional[float]]:
        """
        Identify breakout signals within a session.

        :param session_bars: Candlestick data for the session.
        :param mbox_result: Dictionary containing min_val and max_val for breakout levels.
        :param lookahead: Number of bars to look ahead for confirming breakout.
        :return: Tuple of extrema, signal bar, direction ('BUY'/'SELL'), hunter bar, and next extrema.
        """
        if not session_bars or not mbox_result:
            return None, None, None, None, None

        min_val = mbox_result.get("min_val")
        max_val = mbox_result.get("max_val")
        
        if min_val is None or max_val is None:
            return None, None, None, None, None
            
        breakout_stage_up = 0
        breakout_stage_down = 0

        for i, bar in enumerate(session_bars):
            if i + lookahead >= len(session_bars):
                break

            current_max = bar.high
            current_min = bar.low

            # Confirm local breakout using lookahead window
            is_local_max = all(current_max > session_bars[j].high for j in range(i + 1, min(i + 1 + lookahead, len(session_bars))))
            is_local_min = all(current_min < session_bars[j].low for j in range(i + 1, min(i + 1 + lookahead, len(session_bars))))

            if is_local_max and current_max > max_val:
                breakout_stage_up += 1
                max_val = current_max

            elif is_local_min and current_min < min_val:
                breakout_stage_down += 1
                min_val = current_min

            # Check for enough breakout stages in either direction
            if breakout_stage_up >= self.num_hunt:
                signal_bar = self.find_signal_bar(session_bars, bar, 'SELL')
                if signal_bar:
                    extrema = max(max_val, self.find_extrema_bar(bar, signal_bar, session_bars, 'SELL'))
                    return extrema, signal_bar, 'SELL', bar, None

            elif breakout_stage_down >= self.num_hunt:
                signal_bar = self.find_signal_bar(session_bars, bar, 'BUY')
                if signal_bar:
                    extrema = min(min_val, self.find_extrema_bar(bar, signal_bar, session_bars, 'BUY'))
                    return extrema, signal_bar, 'BUY', bar, None

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
            if (this_bar.close < prev_bar.low and (this_bar.close - this_bar.open) < 0):
                return this_bar

        elif direction == 'BUY':
            # Bullish momentum confirmation
            if (this_bar.close > prev_bar.high and (this_bar.close - this_bar.open) >= 0):
                return this_bar

        return None

    def find_extrema_bar(self, hunter_bar: Bar, signal_bar: Bar, bars: List[Bar], action: str) -> float:
        """
        Find the most extreme high or low between hunter and signal bar.
        """
        extrema_bars = [bar for bar in bars 
                       if hunter_bar.timestamp <= bar.timestamp <= signal_bar.timestamp]
        
        if not extrema_bars:
            return hunter_bar.high if action == 'SELL' else hunter_bar.low

        if action == 'SELL':
            return max(extrema_bars, key=lambda bar: bar.high).high
        elif action == 'BUY':
            return min(extrema_bars, key=lambda bar: bar.low).low

        return 0.0
