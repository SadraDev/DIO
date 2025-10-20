from typing import List, Optional, Union, Dict, Any
from src.core.models.budget import Budget
from src.core.models.bar import Bar
from src.indicators.base import BaseIndicator


class FakeCHoCHDetector(BaseIndicator):
    """
    Fake CHoCH (Change of Character) pattern detector for identifying market structure breaks and reversals.
    Adapted from original code with enhancements.
    """

    def __init__(
        self,
        window: int = 15,
        tolerance: int = 5,
        buffer: float = 0.0000001,
        intensity: float = 3.0,
        use_volume: bool = False,
        detailed: bool = False,
        single_hit: bool = True,
        volume_factor: float = 1.2,
        budget: Budget = None
    ):
        super().__init__("FakeCHoCHDetector")
        
        self.window = window
        self.tolerance = tolerance
        self.buffer = buffer
        self.intensity = intensity
        self.use_volume = use_volume
        self.detailed = detailed
        self.single_hit = single_hit
        self.volume_factor = volume_factor
        self.budget = budget

    def is_swing_high(self, bars: List[Bar], i: int) -> bool:
        """Identify swing high using 5-bar fractal pattern."""
        if i < 2 or i >= len(bars) - 2:
            return False
        return all(bars[i].high > bars[i + offset].high for offset in [-2, -1, 1, 2])

    def is_swing_low(self, bars: List[Bar], i: int) -> bool:
        """Identify swing low using 5-bar fractal pattern."""
        if i < 2 or i >= len(bars) - 2:
            return False
        return all(bars[i].low < bars[i + offset].low for offset in [-2, -1, 1, 2])

    def calculate(self, bars: List[Bar]) -> Any:
        """Implementation of base class method"""
        return self.detect(bars)

    def detect(self, bars: List[Bar]) -> Union[bool, List[Dict[str, Any]]]:
        """
        Detect fake CHoCH patterns in the price series.
        Returns a list of matches or True/False depending on `detailed`.
        """
        n = len(bars)
        if n < self.window + self.tolerance:
            return [] if self.detailed else False

        detections = []
        swing_points = []

        # Step 1: Identify swing highs and lows
        for i in range(2, n - 2):
            if self.is_swing_high(bars, i):
                swing_points.append(('high', i, bars[i].high))
            elif self.is_swing_low(bars, i):
                swing_points.append(('low', i, bars[i].low))

        # Step 2: For each swing point, detect a break followed by a reversal
        for direction, idx, price in swing_points:
            for j in range(idx + 1, min(idx + self.tolerance + 1, n)):
                bar = bars[j]
                broke = (
                    bar.high > price + self.buffer if direction == 'high'
                    else bar.low < price - self.buffer
                )

                if broke:
                    k = j + 1
                    max_k = k + self.tolerance
                    last_bar = bars[k - 1] if k > 0 else bars[0]

                    # Get local extrema around the swing point
                    window_start = max(0, idx - 2)
                    window_end = min(len(bars), idx + 3)
                    window_bars = bars[window_start:window_end]
                    
                    local_min = min(b.low for b in window_bars)
                    local_max = max(b.high for b in window_bars)

                    # Step 3: Look for reversal after the break
                    while k < n:
                        test_bar = bars[k]

                        # Check for reversal after break
                        reversed_condition = (
                            test_bar.low < local_min - self.buffer if direction == 'high'
                            else test_bar.high > local_max + self.buffer
                        )

                        if reversed_condition:
                            if not self.is_reversal_significant(local_min, local_max):
                                break  # Not significant enough to count

                            # Check for volume confirmation if enabled
                            if self.use_volume:
                                base_vol = bar.volume or 0
                                revert_vol = test_bar.volume or 0
                                if revert_vol < base_vol / self.volume_factor:
                                    k += 1
                                    continue  # Not enough volume for reversal

                            # Store detection
                            detections.append({
                                "swing_index": idx,
                                "break_index": j,
                                "revert_index": k,
                                "direction": "down" if direction == 'high' else "up",
                                "swing_level": price,
                                "break_bar": bar,
                                "swing_bar": bars[idx],
                                "revert_bar": test_bar,
                                "local_max": max(window_bars, key=lambda b: b.high),
                                "local_min": min(window_bars, key=lambda b: b.low),
                            })

                            if self.single_hit:
                                break  # Stop on first valid detection

                        else:
                            # Exit if the reversal hasn't happened within tolerance range
                            if k > max_k:
                                if test_bar.close == test_bar.open:
                                    break  # Doji / neutral bar

                                same_color = (
                                    (last_bar.close > last_bar.open and test_bar.close > test_bar.open) or
                                    (last_bar.close < last_bar.open and test_bar.close < test_bar.open)
                                )
                                if not same_color:
                                    break  # Candle color switched — possible trend shift

                        last_bar = test_bar
                        k += 1

                    break  # Stop scanning forward once break is detected

        return detections if self.detailed else bool(detections)

    def is_reversal_significant(self, local_min: float, local_max: float) -> bool:
        """
        Determine if a reversal is significant enough based on pip difference.
        """
        diff = abs(local_max - local_min)
        pips = self.budget.pips_from_diff(diff)
        return pips > self.intensity
