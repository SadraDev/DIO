from typing import List, Dict, Any, Tuple
from datetime import time
from src.core.models.budget import Budget
from src.core.models.bar import Bar
from src.indicators.base import BaseIndicator
from config.settings import settings
from datetime import datetime

class MBoxAnalyzer(BaseIndicator):
    """
    Analyzes a set of market bars (MBox) to detect extrema, timing, and trend strength.
    Adapted from original code.
    """

    def __init__(self):
        super().__init__("MBoxAnalyzer")

    def calculate(self, bars: List[Bar]) -> Dict[str, Any]:
        """
        Analyze a set of bars to extract:
        - max/min price
        - trend direction and confidence
        - whether extrema occurred after 07:00 UTC
        """
        if not bars:
            return {}

        # Collect OHLC values for extrema detection
        all_ohlc = [(bar.open, bar.high, bar.low, bar.close) for bar in bars]
        min_val = min(min(ohlc) for ohlc in all_ohlc)
        max_val = max(max(ohlc) for ohlc in all_ohlc)

        # Get the timestamp of the bar where the extrema occurred
        idx_min = next(i for i, ohlc in enumerate(all_ohlc) if min_val in ohlc)
        idx_max = next(i for i, ohlc in enumerate(all_ohlc) if max_val in ohlc)
        ts_min = bars[idx_min].timestamp
        ts_max = bars[idx_max].timestamp

        # Analyze overall trend and confidence
        trend, trend_conf = self.detect_trend(bars)

        time_flag_hour_str = settings.get("strategies.two_hunters.time_flag_hour")
        time_flag_hour = datetime.strptime(time_flag_hour_str, "%H:%M").time()

        # Time of extrema in relation to 07:00 UTC
        max_time_flag = "before" if ts_max.time() < time_flag_hour else "after"
        min_time_flag = "before" if ts_min.time() < time_flag_hour else "after"
        extrema_time_flag = not (max_time_flag == "before" and min_time_flag == "before")

        return {
            "max_val": max_val,
            "min_val": min_val,
            "trend": trend,
            "trend_confidence": trend_conf,
            "extrema_flag": extrema_time_flag,
        }

    def detect_trend(self, bars: List[Bar]) -> Tuple[bool, float]:
        """
        Detects directional trend using average mid-values of the first and last 5 bars.
        Returns:
            - trend_present (bool): True if a trend is detected
            - trend_confidence (float): Normalized strength of the trend
        """
        if len(bars) < 10:
            return False, 0.0
            
        budget = Budget()

        def average_midval(subset: List[Bar]) -> float:
            return sum(bar.low + (bar.high - bar.low) / 2 for bar in subset) / len(subset)

        first_avg = average_midval(bars[:5])
        last_avg = average_midval(bars[-5:])

        all_ohlc = [(bar.open, bar.high, bar.low, bar.close) for bar in bars]
        min_val = min(min(ohlc) for ohlc in all_ohlc)
        max_val = max(max(ohlc) for ohlc in all_ohlc)

        mbox_pip_diff = budget.pips_from_diff(max_val - min_val)
        entry_exit_pip_diff = budget.pips_from_diff(first_avg - last_avg)
        
        if mbox_pip_diff == 0:
            return False, 0.0

        confidence = round(entry_exit_pip_diff / mbox_pip_diff, 2)
        return confidence > 0.3, confidence - 0.3
