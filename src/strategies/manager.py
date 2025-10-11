from typing import Dict, List, Optional, Any
from src.strategies.base import BaseStrategy
from src.strategies.two_hunters import TwoHuntersStrategy
from src.core.models.budget import Budget
from src.core.models.bar import Bar
from src.core.models.signal import Signal
from src.core.utils.logger import TradingLogger


class StrategyManager:
    """Manages multiple trading strategies"""
    
    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.logger = TradingLogger.get_trading_logger()
    
    def add_strategy(self, strategy: BaseStrategy) -> bool:
        """Add a strategy to the manager"""
        strategy_key = f"{strategy.name}_{strategy.symbol}"
        
        if strategy_key in self.strategies:
            self.logger.warning(f"Strategy {strategy_key} already exists")
            return False
        
        self.strategies[strategy_key] = strategy
        self.logger.info(f"Added strategy: {strategy_key}")
        return True
    
    def remove_strategy(self, name: str, symbol: str) -> bool:
        """Remove a strategy from the manager"""
        strategy_key = f"{name}_{symbol}"
        
        if strategy_key in self.strategies:
            del self.strategies[strategy_key]
            self.logger.info(f"Removed strategy: {strategy_key}")
            return True
        
        return False
    
    def get_strategy(self, name: str, symbol: str) -> Optional[BaseStrategy]:
        """Get a specific strategy"""
        strategy_key = f"{name}_{symbol}"
        return self.strategies.get(strategy_key)
    
    def create_two_hunters_strategy(self) -> TwoHuntersStrategy:
        """Create and add a Two Hunters strategy"""
        strategy = TwoHuntersStrategy()
        self.add_strategy(strategy)
        return strategy
    
    def get_active_strategies(self) -> List[BaseStrategy]:
        """Get all active strategies"""
        return [s for s in self.strategies.values() if s.is_active]
    
    def add_bars_to_all(self, bars: List[Bar]):
        """Add bars to all active strategies"""
        for strategy in self.get_active_strategies():
            try:
                # Filter bars for this strategy's symbol
                strategy_bars = [b for b in bars if hasattr(b, 'symbol') and b.symbol == strategy.symbol]
                if strategy_bars:
                    strategy.add_bars(strategy_bars)
            except Exception as e:
                self.logger.error(f"Error adding bars to {strategy.name}: {e}")
    
    def reset_all_daily_states(self):
        """Reset daily state for all strategies"""
        for strategy in self.strategies.values():
            try:
                strategy.reset_daily_state()
            except Exception as e:
                self.logger.error(f"Error resetting daily state for {strategy.name}: {e}")
    
    def get_all_signals(self) -> List[Signal]:
        """Get all signals from all strategies"""
        all_signals = []
        for strategy in self.strategies.values():
            all_signals.extend(strategy.signals_generated)
        return all_signals
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get overall performance summary"""
        all_signals = self.get_all_signals()
        completed_signals = [s for s in all_signals if s.is_completed]
        
        if not completed_signals:
            return {
                'total_strategies': len(self.strategies),
                'total_signals': 0,
                'overall_win_rate': 0.0,
                'total_profit': 0.0
            }
        
        wins = sum(1 for s in completed_signals if s.outcome.value == 'win')
        total_profit = sum(s.gain for s in completed_signals if s.gain)
        
        return {
            'total_strategies': len(self.strategies),
            'active_strategies': len(self.get_active_strategies()),
            'total_signals': len(completed_signals),
            'overall_win_rate': (wins / len(completed_signals)) * 100,
            'total_profit': total_profit,
            'strategy_breakdown': {
                name: strategy.get_performance_summary() 
                for name, strategy in self.strategies.items()
            }
        }
