from typing import Dict, List
from datetime import datetime, timedelta
from src.core.models.signal import Signal
from src.core.models.budget import Budget
from src.core.utils.logger import TradingLogger

class LiveRiskManager:
    """
    Real-time risk management system
    """
    
    def __init__(self):
        self.logger = TradingLogger.get_trading_logger()
        self.daily_loss_limits: Dict[str, float] = {}
        self.position_limits: Dict[str, int] = {}
        self.emergency_stops: Dict[str, bool] = {}
        
    def check_position_risk(self, signal: Signal, current_balance: float) -> bool:
        """Check if position passes risk requirements"""
        
        # Check position size limit
        max_risk = current_balance * 0.02  # 2% max risk per trade
        position_risk = abs(signal.gain) if signal.gain else signal.entry_lot * 1000  # Estimate
        
        if position_risk > max_risk:
            self.logger.warning(f"Position risk {position_risk} exceeds limit {max_risk}")
            return False
        
        return True
    
    def check_daily_limits(self, symbol: str, current_loss: float) -> bool:
        """Check daily loss limits"""
        daily_limit = self.daily_loss_limits.get(symbol, 250.0)  # $500 default
        
        if current_loss > daily_limit:
            self.logger.error(f"Daily loss limit exceeded for {symbol}: ${current_loss}")
            self.emergency_stops[symbol] = True
            return False
        
        return True
    
    def should_stop_trading(self, symbol: str) -> bool:
        """Check if trading should be stopped for symbol"""
        return self.emergency_stops.get(symbol, False)
    
    def reset_daily_limits(self):
        """Reset daily limits for new trading day"""
        self.emergency_stops.clear()
        self.logger.info("Daily risk limits reset")
