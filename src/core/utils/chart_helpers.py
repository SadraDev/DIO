from typing import List, Dict, Any
from datetime import datetime, timedelta
import pandas as pd

from src.core.models.bar import Bar
from src.core.models.signal import Signal


def calculate_support_resistance(bars: List[Bar], window: int = 20) -> Dict[str, List[float]]:
    """Calculate support and resistance levels"""
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    
    # Simple support/resistance calculation
    resistance_levels = []
    support_levels = []
    
    for i in range(window, len(bars) - window):
        # Check if current high is a local maximum
        if all(highs[i] >= highs[j] for j in range(i-window, i+window+1)):
            resistance_levels.append(highs[i])
        
        # Check if current low is a local minimum  
        if all(lows[i] <= lows[j] for j in range(i-window, i+window+1)):
            support_levels.append(lows[i])
    
    return {
        'resistance': resistance_levels,
        'support': support_levels
    }


def prepare_signal_annotations(signals: List[Signal]) -> List[Dict[str, Any]]:
    """Prepare signal data for chart annotations"""
    annotations = []
    
    for i, signal in enumerate(signals):
        if not signal.timestamp:
            continue
            
        annotation = {
            'x': signal.timestamp,
            'y': signal.entry_price,
            'text': f"{signal.action.value}",
            'showarrow': True,
            'arrowcolor': '#00ff88' if signal.action.value == 'BUY' else '#ff4444',
            'arrowsize': 2,
            'arrowwidth': 2,
            'bgcolor': 'rgba(0,0,0,0.7)',
            'bordercolor': '#00ff88' if signal.action.value == 'BUY' else '#ff4444',
            'font': {'color': 'white', 'size': 12}
        }
        
        annotations.append(annotation)
    
    return annotations


def format_time_axis(start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Format time axis based on date range"""
    date_diff = (end_date - start_date).days
    
    if date_diff <= 1:
        # Intraday - show hours
        return {
            'dtick': 3600000,  # 1 hour in milliseconds
            'tickformat': '%H:%M'
        }
    elif date_diff <= 7:
        # Weekly - show days
        return {
            'dtick': 86400000,  # 1 day in milliseconds  
            'tickformat': '%d-%m'
        }
    else:
        # Monthly - show dates
        return {
            'dtick': 86400000 * 7,  # 1 week in milliseconds
            'tickformat': '%d-%m-%y'
        }
