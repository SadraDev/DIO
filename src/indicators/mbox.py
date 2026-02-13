from typing import List, Dict, Any, Tuple
from datetime import time
from src.core.models.budget import Budget
from src.core.models.bar import Bar
from src.indicators.base import BaseIndicator
from src.indicators.trend_detector import create_trend_detector
from config.settings import settings
from datetime import datetime

class MBoxAnalyzer(BaseIndicator):
    """
    Analyzes a set of market bars (MBox) to detect extrema, timing, and trend strength.
    Adapted from original code.
    """

    def __init__(self):
        super().__init__("MBoxAnalyzer")
        self.results = None

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
        if len(bars) < 20:
            return False, 0.0
        detector = create_trend_detector('consensus')
        trend_detected, direction, confidence = detector.detect(bars)

        time_flag_hour_str = settings.get("strategies.two_hunters.flags.time_flag_hour")
        time_flag_hour = datetime.strptime(time_flag_hour_str, "%H:%M").time()

        # Time of extrema in relation to 07:00 UTC
        max_time_flag = False if ts_max.time() < time_flag_hour else True
        min_time_flag = False if ts_min.time() < time_flag_hour else True
        extrema_time_flag = max_time_flag or min_time_flag

        self.results = {
            "max_val": max_val,
            "min_val": min_val,
            "trend": trend_detected,
            "trend_confidence": confidence,
            "trend_direction": direction,
            "extrema_flag": extrema_time_flag,
        }
        return self.results
