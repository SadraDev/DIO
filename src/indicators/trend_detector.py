"""
Advanced trend detection algorithms for trading systems.
Each detector returns (trend_detected: bool, trend_direction: str, confidence: float)
- trend_detected: True if a clear trend exists
- trend_direction: "BULLISH", "BEARISH", or "NEUTRAL"  
- confidence: 0.0 to 1.0 (strength of the trend)
"""

from typing import List, Tuple
from src.core.models.bar import Bar
import numpy as np


class TrendDetectorBase:
    """Base class for trend detectors"""
    
    def detect(self, bars: List[Bar]) -> Tuple[bool, str, float]:
        """
        Detect trend in bars
        Returns: (trend_detected, trend_direction, confidence)
        """
        raise NotImplementedError


class LinearRegressionDetector(TrendDetectorBase):
    """
    Method 1: Linear Regression with R-squared
    Fits a line through price data and measures fit quality
    Excellent for measuring trend strength
    """
    
    def __init__(self, min_r_squared: float = 0.65):
        self.min_r_squared = min_r_squared
    
    def detect(self, bars: List[Bar]) -> Tuple[bool, str, float]:
        if len(bars) < 10:
            return False, "NEUTRAL", 0.0
        
        # Use closing prices
        closes = np.array([bar.close for bar in bars])
        x = np.arange(len(closes))
        
        # Calculate linear regression
        slope, intercept = np.polyfit(x, closes, 1)
        
        # Calculate R-squared
        y_pred = slope * x + intercept
        ss_res = np.sum((closes - y_pred) ** 2)
        ss_tot = np.sum((closes - np.mean(closes)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Normalize slope by price range for confidence
        price_range = max(closes) - min(closes)
        if price_range == 0:
            return False, "NEUTRAL", 0.0
        
        normalized_slope = abs(slope) * len(closes) / price_range
        
        # Combine R-squared and slope for confidence
        confidence = min(r_squared * 0.7 + 0.3 * min(normalized_slope, 1.0), 1.0)
        
        # Determine trend
        if r_squared >= self.min_r_squared:
            if slope > 0:
                return True, "BULLISH", confidence
            else:
                return True, "BEARISH", confidence
        else:
            return False, "NEUTRAL", confidence


class ADXBasedDetector(TrendDetectorBase):
    """
    Method 2: ADX (Average Directional Index) Implementation
    Industry-standard trend strength indicator
    Best for identifying strong vs weak trends
    """
    
    def __init__(self, period: int = 14, adx_threshold: float = 25.0):
        self.period = period
        self.adx_threshold = adx_threshold
    
    def detect(self, bars: List[Bar]) -> Tuple[bool, str, float]:
        if len(bars) < self.period + 1:
            return False, "NEUTRAL", 0.0
        
        # Calculate True Range (TR)
        tr_list = []
        for i in range(1, len(bars)):
            high = bars[i].high
            low = bars[i].low
            prev_close = bars[i-1].close
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_list.append(tr)
        
        # Calculate Directional Movement (+DM and -DM)
        plus_dm = []
        minus_dm = []
        for i in range(1, len(bars)):
            high_diff = bars[i].high - bars[i-1].high
            low_diff = bars[i-1].low - bars[i].low
            
            if high_diff > low_diff and high_diff > 0:
                plus_dm.append(high_diff)
            else:
                plus_dm.append(0)
                
            if low_diff > high_diff and low_diff > 0:
                minus_dm.append(low_diff)
            else:
                minus_dm.append(0)
        
        # Wilders smoothing function
        def wilders_smoothing(data, period):
            if len(data) < period:
                return []
            result = [sum(data[:period]) / period]
            for i in range(period, len(data)):
                smoothed = (result[-1] * (period - 1) + data[i]) / period
                result.append(smoothed)
            return result
        
        # Calculate smoothed values
        atr = wilders_smoothing(tr_list, self.period)
        plus_di_smooth = wilders_smoothing(plus_dm, self.period)
        minus_di_smooth = wilders_smoothing(minus_dm, self.period)
        
        if not atr or not plus_di_smooth or not minus_di_smooth:
            return False, "NEUTRAL", 0.0
        
        # Calculate DI+ and DI-
        plus_di = [(dm / atr[i]) * 100 for i, dm in enumerate(plus_di_smooth)]
        minus_di = [(dm / atr[i]) * 100 for i, dm in enumerate(minus_di_smooth)]
        
        # Calculate DX
        dx = []
        for i in range(len(plus_di)):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum != 0:
                dx_val = abs(plus_di[i] - minus_di[i]) / di_sum * 100
                dx.append(dx_val)
        
        # Calculate ADX (smoothed DX)
        if len(dx) < self.period:
            return False, "NEUTRAL", 0.0
        
        adx = wilders_smoothing(dx, self.period)
        
        # Get latest values
        current_adx = adx[-1]
        current_plus_di = plus_di[-1] 
        current_minus_di = minus_di[-1]
        
        # Normalize ADX to 0-1 confidence (ADX ranges 0-100)
        confidence = min(current_adx / 100.0, 1.0)
        
        # Determine trend
        if current_adx >= self.adx_threshold:
            if current_plus_di > current_minus_di:
                return True, "BULLISH", confidence
            else:
                return True, "BEARISH", confidence
        else:
            return False, "NEUTRAL", confidence


class MovingAverageConvergenceDetector(TrendDetectorBase):
    """
    Method 3: Multiple Moving Average Alignment
    Uses 3 EMAs to detect trend alignment
    Simple but effective for identifying established trends
    """
    
    def __init__(self, fast_period: int = 8, mid_period: int = 21, slow_period: int = 55):
        self.fast_period = fast_period
        self.mid_period = mid_period  
        self.slow_period = slow_period
    
    def calculate_ema(self, closes: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(closes) < period:
            return sum(closes) / len(closes)
        
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period  # Start with SMA
        
        for close in closes[period:]:
            ema = (close - ema) * multiplier + ema
        return ema
    
    def detect(self, bars: List[Bar]) -> Tuple[bool, str, float]:
        if len(bars) < self.slow_period:
            return False, "NEUTRAL", 0.0
        
        closes = [bar.close for bar in bars]
        
        # Calculate EMAs
        fast_ema = self.calculate_ema(closes, self.fast_period)
        mid_ema = self.calculate_ema(closes, self.mid_period)
        slow_ema = self.calculate_ema(closes, self.slow_period)
        
        # Check alignment
        bullish_aligned = fast_ema > mid_ema > slow_ema
        bearish_aligned = fast_ema < mid_ema < slow_ema
        
        # Calculate separation for confidence
        price_range = max(closes) - min(closes)
        if price_range == 0:
            return False, "NEUTRAL", 0.0
        
        # Measure EMA spread as percentage of range
        ema_spread = abs(fast_ema - slow_ema) / price_range
        confidence = min(ema_spread * 2, 1.0)  # Scale spread to 0-1
        
        # Determine trend
        if bullish_aligned:
            return True, "BULLISH", confidence
        elif bearish_aligned:
            return True, "BEARISH", confidence
        else:
            return False, "NEUTRAL", confidence


class ConsensusDetector(TrendDetectorBase):
    """
    Consensus Approach - Combines multiple detectors for robust detection
    Uses voting system with confidence-based weighting
    Most reliable detector using all available methods
    """
    
    def __init__(self, min_consensus: float = 0.5):
        self.min_consensus = min_consensus
        # Initialize all detectors (removed SwingStructureDetector)
        self.detectors = [
            LinearRegressionDetector(),
            ADXBasedDetector(), 
            MovingAverageConvergenceDetector()
        ]
    
    def detect(self, bars: List[Bar]) -> Tuple[bool, str, float]:
        if len(bars) < 20:
            return False, "NEUTRAL", 0.0
        
        # Get results from all detectors
        results = []
        for detector in self.detectors:
            try:
                trend_detected, direction, confidence = detector.detect(bars)
                results.append((trend_detected, direction, confidence))
            except Exception:
                # Skip detector if it fails
                continue
        
        if not results:
            return False, "NEUTRAL", 0.0
        
        # Count votes for each direction
        bullish_votes = sum(1 for _, direction, _ in results if direction == "BULLISH")
        bearish_votes = sum(1 for _, direction, _ in results if direction == "BEARISH")
        total_votes = len(results)
        
        # Calculate vote percentages
        bullish_ratio = bullish_votes / total_votes
        bearish_ratio = bearish_votes / total_votes
        
        # Calculate confidence as percentage of votes
        # 0 votes = 0%, 1 vote = 33%, 2 votes = 66%, 3 votes = 100%
        if bullish_votes > bearish_votes and bullish_ratio >= self.min_consensus:
            confidence = bullish_votes / 3.0  # Convert to percentage (max 3 detectors)
            return True, "BULLISH", confidence
        elif bearish_votes > bullish_votes and bearish_ratio >= self.min_consensus:
            confidence = bearish_votes / 3.0  # Convert to percentage (max 3 detectors)
            return True, "BEARISH", confidence
        else:
            # No consensus or tie
            confidence = max(bullish_votes, bearish_votes) / 3.0
            return False, "NEUTRAL", confidence


# Factory function for easy detector creation
def create_trend_detector(method: str) -> TrendDetectorBase:
    """
    Factory function to create trend detectors
    
    Args:
        method: One of "regression", "adx", "ema", "consensus"
    
    Returns:
        TrendDetectorBase instance
    """
    detectors = {
        "regression": LinearRegressionDetector,
        "adx": ADXBasedDetector, 
        "ema": MovingAverageConvergenceDetector,
        "consensus": ConsensusDetector
    }
    
    if method not in detectors:
        raise ValueError(f"Unknown method '{method}'. Choose from {list(detectors.keys())}")
    
    return detectors[method]()