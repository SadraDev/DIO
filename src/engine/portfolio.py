from typing import Dict, List
from src.core.models.budget import Budget
from src.core.models.signal import Signal

class PortfolioManager:
    """Manages portfolio across multiple symbols in live trading"""
    
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.symbol_budgets: Dict[str, Budget] = {}
        self.active_positions: Dict[str, List[Signal]] = {}
    
    def add_symbol(self, symbol: str, allocation_percent: float):
        """Add symbol with specific allocation"""
        allocated_balance = self.initial_balance * allocation_percent
        self.symbol_budgets[symbol] = Budget(allocated_balance)
        self.active_positions[symbol] = []
    
    def get_total_exposure(self) -> float:
        """Calculate total portfolio exposure"""
        total_exposure = 0.0
        for positions in self.active_positions.values():
            for position in positions:
                if position.entry_lot:
                    total_exposure += position.entry_lot * 100000  # Standard lot size
        return total_exposure
    
    def get_portfolio_summary(self) -> Dict:
        """Get comprehensive portfolio summary"""
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'total_pnl': self.current_balance - self.initial_balance,
            'active_positions': sum(len(pos) for pos in self.active_positions.values()),
            'symbols': list(self.symbol_budgets.keys())
        }
