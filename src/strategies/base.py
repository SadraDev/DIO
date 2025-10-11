from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.core.models.signal import Signal
from src.core.models.bar import Bar
from src.core.models.budget import Budget


class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, name: str):
        self.name = name
        self.created_at = datetime.now()
        self.signals_generated = []
        self._active = True
    
    @abstractmethod
    def add_bars(self, bars: List[Bar]):
        """Add new price bars to the strategy"""
        pass
    
    @abstractmethod
    def reset_daily_state(self):
        """Reset daily state for new trading day"""
        pass
    
    def activate(self):
        """Activate the strategy"""
        self._active = True
    
    def deactivate(self):
        """Deactivate the strategy"""
        self._active = False
    
    @property
    def is_active(self) -> bool:
        """Check if strategy is active"""
        return self._active
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get strategy performance summary"""
        completed_signals = [s for s in self.signals_generated if s.is_completed]
        
        if not completed_signals:
            return {
                'total_signals': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'avg_profit_per_trade': 0.0
            }
        
        wins = sum(1 for s in completed_signals if s.outcome.value == 'win')
        total_profit = sum(s.gain for s in completed_signals if s.gain)
        
        return {
            'total_signals': len(completed_signals),
            'win_rate': (wins / len(completed_signals)) * 100,
            'total_profit': total_profit,
            'avg_profit_per_trade': total_profit / len(completed_signals)
        }
    
    def __repr__(self):
        return f"{self.name}(symbol={self.symbol}, signals={len(self.signals_generated)})"
