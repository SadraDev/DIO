from typing import List, Optional, Dict, Any
from collections import defaultdict
from src.core.models.signal import Signal
from config.settings import settings

class PropStatus:
    """Represents prop trading evaluation status"""
    def __init__(self):
        self.passed: Optional[bool] = None
        self.max_daily_fail_percent: Optional[float] = None
        self.max_daily_win_percent: Optional[float] = None
        self.max_total_fail_percent: Optional[float] = None
        self.max_total_win_percent: Optional[float] = None

class Budget:
    """
    Manages account balance, risk, and position sizing with CORRECTED financial calculations
    Now properly accounts for risk_amount in all position sizing and P&L calculations
    """
    
    def __init__(self, initial_balance: Optional[float] = None, initial_risk_percent: Optional[float] = None):
        # Core account parameters
        self.initial_balance = initial_balance or settings.get('account.initial_balance', 10000)
        self.current_balance = self.initial_balance
        
        # Risk management
        self.initial_risk_percent = initial_risk_percent or settings.get('account.default_risk_percent', 0.01)
        self.current_risk_percent = self.initial_risk_percent
        
        # Market parameters from config
        self.standard_pip_size = settings.get('market.standard_pip_size', 0.0001)
        self.standard_lot_size = settings.get('market.standard_lot_size', 100000)
        self.min_lot_size = settings.get('market.min_lot_size', 0.01)

        # Prop trading thresholds from config
        self.daily_fail_threshold = settings.get('account.prop_trading.daily_fail_percent', 0.05)
        self.total_fail_threshold = settings.get('account.prop_trading.total_fail_percent', 0.08) 
        self.win_target = settings.get('account.prop_trading.win_target_percent', 0.15)
        
        # Prop evaluation state
        self.prop_status = PropStatus()
        
        # Risk adjustment flags and modifiers from config
        self.load_risk_modifiers()
    
    def load_risk_modifiers(self):
        """Load risk modification settings from config"""
        risk_config = settings.get('trading.risk', {})
        
        self.use_all_flags = False
        self.use_trend_flag = False
        self.use_time_flag = False
        self.use_choch_flag = False
        
        modifiers = risk_config.get('modifiers', {})
        self.trend_cut = modifiers.get('trend_cut', 2.0)
        self.time_cut = modifiers.get('time_cut', 2.0)
        self.choch_cut = modifiers.get('choch_cut', 2.0)
        self.recovery_cut = modifiers.get('recovery_cut', 2.0)
    
    def reset(self, balance: Optional[float] = None):
        """Reset budget to initial state"""
        self.current_balance = balance if balance is not None else self.initial_balance
        self.current_risk_percent = self.initial_risk_percent
        self.prop_status = PropStatus()
        
        from src.core.utils.logger import log_system_event
        log_system_event("budget_reset", balance=self.current_balance, risk_percent=self.current_risk_percent)
    
    def update_balance(self, new_balance: float):
        """Update current account balance"""
        old_balance = self.current_balance
        self.current_balance = new_balance
        
        from src.core.utils.logger import log_system_event
        log_system_event("balance_updated", old_balance=old_balance, 
                         new_balance=new_balance, change=new_balance - old_balance)
    
    def apply_signal_gain(self, signal: Signal):
        """Apply signal gain/loss to current balance"""
        self.current_balance += signal.gain
    
    def pips_from_diff(self, price_diff: float) -> float:
        """Convert price difference to pips"""
        return abs(price_diff) / self.standard_pip_size
    
    def diff_from_pips(self, pips: float) -> float:
        """Convert pips to price difference"""
        return abs(pips) * self.standard_pip_size
    
    def value_from_percent(self, percent: float) -> float:
        """Convert percentage of balance to monetary value"""
        if not -1.0 <= percent <= 1.0:
            raise ValueError("Percentage should be between -1.0 and 1.0")
        return percent * self.current_balance
    
    def risk_amount(self) -> float:
        """
        CORE PROPERTY: Calculate exact dollar amount to risk per trade
        This is THE method that determines position sizing
        
        Returns:
            Dollar amount to risk (e.g., $200 for $10,000 account at 2% risk)
        """
        return self.current_risk_percent * self.current_balance
    
    def reward_amount(self, reward_ratio: float) -> float:
        """Calculate potential reward based on risk and reward ratio"""
        if reward_ratio <= 0:
            raise ValueError("Reward ratio must be non-negative")
        return self.risk_amount() * reward_ratio
    
    # ENHANCED POSITION SIZING - NOW USES RISK_AMOUNT DIRECTLY
    def calculate_pip_value(self, symbol: str) -> float:
        """
        Calculate pip value for ONE standard lot (100,000 units)
        COMPREHENSIVE symbol support with proper pip sizes
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD", "USDJPY") 
            entry_price: Current market price
            
        Returns:
            Pip value in USD for 1.0 standard lot
        """
        # Clean symbol
        if symbol is None:
            return 0        # TODO: trace back to the issue
        

        clean_symbol = symbol.rstrip('.').upper()
        
        # Symbol pip sizes - comprehensive list
        pip_sizes = {
            # Major forex pairs (0.0001 pip)
            'EURUSD': 0.0001, 'GBPUSD': 0.0001, 'AUDUSD': 0.0001, 'NZDUSD': 0.0001,
            'USDCAD': 0.0001, 'USDCHF': 0.0001, 'EURGBP': 0.0001, 'EURAUD': 0.0001,
            'EURNZD': 0.0001, 'EURCHF': 0.0001, 'EURCAD': 0.0001, 'GBPAUD': 0.0001,
            'GBPNZD': 0.0001, 'GBPCAD': 0.0001, 'GBPCHF': 0.0001, 'AUDNZD': 0.0001,
            'AUDCAD': 0.0001, 'AUDCHF': 0.0001, 'NZDCAD': 0.0001, 'NZDCHF': 0.0001, 
            'CADCHF': 0.0001,
            
            # JPY pairs (0.01 pip) 
            'USDJPY': 0.01, 'EURJPY': 0.01, 'GBPJPY': 0.01, 'AUDJPY': 0.01,
            'NZDJPY': 0.01, 'CADJPY': 0.01, 'CHFJPY': 0.01,
            
            # Commodities 
            'XAUUSD': 0.01,   # Gold
            'XAGUSD': 0.001,  # Silver  
            'WTIUSD': 0.01,   # Oil
            'UKOIL': 0.01,    # Brent Oil
            
            # Indices
            'US30': 1.0,      # Dow Jones
            'US500': 0.1,     # S&P 500
            'NAS100': 0.1,    # Nasdaq
            'GER30': 1.0,     # DAX
            'UK100': 1.0,     # FTSE
            'JPN225': 1.0,    # Nikkei
            
            # Crypto
            'BTCUSD': 1.0,
            'ETHUSD': 0.01,
            'LTCUSD': 0.01,
            'ADAUSD': 0.0001,
            'DOTUSD': 0.001,
        }
        
        # Get pip size
        pip_size = pip_sizes.get(clean_symbol, 0.0001)  # Default 0.0001
        
        # Standard lot size
        lot_size = self.standard_lot_size  # 100,000
        
        return pip_size * lot_size
    
    def lots_from_diff(self, symbol: str, sl_distance: float) -> float:
        """
        Calculate position size based on RISK_AMOUNT - THE CORE METHOD
        This ensures risk_amount() directly determines lot size
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price  
            stop_loss_price: Stop loss price
            
        Returns:
            Position size in lots that risks exactly self.risk_amount dollars
            
        Example:
            Account: $10,000
            Risk: 2% = $200 
            EUR/USD: Entry 1.0500, SL 1.0450 (50 pips)
            Pip value: $10 per lot
            Position size: $200 / (50 pips × $10) = 0.4 lots
        """
        
        # Calculate stop loss distance in pips
        sl_distance_pips = self.pips_from_diff(sl_distance)
        
        if sl_distance_pips < 0:
            raise ValueError("Stop loss distance must be greater than 0")
        
        # Get pip value for 1 lot
        pip_value_per_lot = self.calculate_pip_value(symbol)
        
        # CORE CALCULATION: Risk Amount / (SL Pips × Pip Value) = Lot Size
        risk_dollars = self.risk_amount()
        lot_size = risk_dollars / (sl_distance_pips * pip_value_per_lot) if sl_distance_pips != 0 else 0
        
        # Round to minimum lot size and apply limits
        lot_size = max(round(lot_size, 2), self.min_lot_size)
        lot_size = min(lot_size, 10.0)  # Max 10 lots
        
        return lot_size
    
    def calculate_gain_loss(self, symbol: str, entry_price: float, exit_price: float, 
                           lot_size: float, action: str) -> float:
        """
        Calculate exact gain/loss for a position
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            exit_price: Exit price
            lot_size: Position size in lots
            action: "BUY" or "SELL"
            
        Returns:
            Gain/loss in USD (positive = profit, negative = loss)
        """
        
        # Calculate pips moved
        if action.upper() == "BUY":
            pips_moved = self.pips_from_diff(exit_price - entry_price)
            if exit_price < entry_price:
                pips_moved = -pips_moved
        else:
            pips_moved = self.pips_from_diff(entry_price - exit_price) 
            if entry_price < exit_price:
                pips_moved = -pips_moved
        
        # Get pip value for the position
        pip_value_per_lot = self.calculate_pip_value(symbol)
        
        # Calculate P&L: Pips × Pip Value × Lot Size
        gain_loss = pips_moved * pip_value_per_lot * lot_size
        
        return gain_loss
    
    def update_risk_percent(self, signal: Signal):
        """Dynamically adjust risk percentage based on signal flags"""
        # Start with base risk
        self.current_risk_percent = self.initial_risk_percent
        
        # Apply global flag setting
        if self.use_all_flags:
            self.use_trend_flag = True
            self.use_time_flag = True
            self.use_choch_flag = True

        if self.use_time_flag and getattr(signal, 'time_flag', False):
            self.current_risk_percent = min(self.current_risk_percent, self.initial_risk_percent / self.time_cut)
            
        if self.use_choch_flag and not getattr(signal, 'fake_CHoCH', True):
            self.current_risk_percent = min(self.current_risk_percent, self.initial_risk_percent / self.choch_cut)
            
        if self.use_trend_flag and getattr(signal, 'trend', False):
            self.current_risk_percent = min(self.current_risk_percent, self.initial_risk_percent / self.trend_cut)
        
        # Ensure risk doesn't exceed maximum
        max_risk = settings.get('trading.risk.max_risk_percent', 0.05)
        self.current_risk_percent = min(self.current_risk_percent, max_risk)
        
        from src.core.utils.logger import TradingLogger
        logger = TradingLogger.get_trading_logger()
        logger.debug(f"Risk adjusted: {self.initial_risk_percent:.3f} -> {self.current_risk_percent:.3f}")
    
    # VALIDATION METHODS
    def validate_trade(self, symbol: str, entry_price: float, stop_loss_price: float, lot_size: float) -> dict:
        """Validate a trade setup"""
        sl_pips = self.pips_from_diff(abs(entry_price - stop_loss_price))
        pip_value = self.calculate_pip_value(symbol)
        max_loss = sl_pips * pip_value * lot_size
        risk_percent_actual = (max_loss / self.current_balance) * 100
        
        return {
            'valid': max_loss <= self.risk_amount() * 1.1,  # Allow 10% tolerance
            'sl_pips': sl_pips,
            'max_loss_usd': max_loss,
            'risk_percent_actual': risk_percent_actual,
            'risk_amount_target': self.risk_amount(),
            'pip_value_per_lot': pip_value,
            'lot_size': lot_size
        }
    
    def evaluate_prop_status(self, signals: List[Signal]):
        """Evaluate prop trading performance based on completed signals"""
        if not signals:
            return
        
        starting_balance = self.current_balance
        from src.core.utils.logger import log_system_event
        
        # Group signals by day for daily evaluation
        daily_groups = defaultdict(list)
        for signal in signals:
            if signal.outcome_timestamp:
                day = signal.outcome_timestamp.date()
                daily_groups[day].append(signal)
        
        # Evaluate daily performance
        running_balance = starting_balance
        for day, day_signals in daily_groups.items():
            daily_gain = sum(s.gain for s in day_signals if s.gain is not None)
            day_end_balance = running_balance + daily_gain
            
            # Check daily loss limit
            if day_end_balance < running_balance:
                fail_percent = (running_balance - day_end_balance) / running_balance * 100
                self.prop_status.max_daily_fail_percent = max(self.prop_status.max_daily_fail_percent or 0, fail_percent)
                
                if fail_percent >= self.daily_fail_threshold * 100:
                    if self.prop_status.passed is None:
                        self.prop_status.passed = False
                        log_system_event("prop_evaluation", status="failed", reason="daily_loss_limit", 
                                        loss_percent=fail_percent, day=day.isoformat())
            
            # Check daily profit
            elif day_end_balance > running_balance:
                win_percent = (day_end_balance - running_balance) / running_balance * 100
                self.prop_status.max_daily_win_percent = max(self.prop_status.max_daily_win_percent or 0, win_percent)
                
                if win_percent >= self.win_target * 100:
                    if self.prop_status.passed is None:
                        self.prop_status.passed = True
                        log_system_event("prop_evaluation", status="passed", reason="daily_profit_target",
                                        win_percent=win_percent, day=day.isoformat())
            
            running_balance = day_end_balance
        
        # Evaluate overall performance if no daily decision made
        if self.prop_status.passed is None:
            final_balance = starting_balance + sum(s.gain for s in signals if s.gain is not None)
            
            if final_balance < starting_balance:
                total_fail_percent = (starting_balance - final_balance) / starting_balance * 100
                self.prop_status.max_total_fail_percent = total_fail_percent
                
                if total_fail_percent >= self.total_fail_threshold * 100:
                    self.prop_status.passed = False
                    log_system_event("prop_evaluation", status="failed", reason="total_loss_limit",
                                   loss_percent=total_fail_percent)
            
            elif final_balance > starting_balance:
                total_win_percent = (final_balance - starting_balance) / starting_balance * 100
                self.prop_status.max_total_win_percent = total_win_percent
                
                if total_win_percent >= self.win_target * 100:
                    self.prop_status.passed = True
                    log_system_event("prop_evaluation", status="passed", reason="total_profit_target",
                                   win_percent=total_win_percent)
    
    def get_prop_status_string(self) -> str:
        """Get human-readable prop status"""
        if self.prop_status.passed is None:
            return "Pending"
        elif self.prop_status.passed:
            return "Passed"
        else:
            return "Failed"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive budget summary"""
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'net_change': self.current_balance - self.initial_balance,
            'net_change_percent': (self.current_balance - self.initial_balance) / self.initial_balance * 100,
            'initial_risk_percent': self.initial_risk_percent,
            'current_risk_percent': self.current_risk_percent,
            'current_risk_amount': self.risk_amount(),
            'prop_status': {
                'passed': self.prop_status.passed,
                'status_string': self.get_prop_status_string(),
                'max_daily_fail_percent': self.prop_status.max_daily_fail_percent,
                'max_daily_win_percent': self.prop_status.max_daily_win_percent,
                'max_total_fail_percent': self.prop_status.max_total_fail_percent,
                'max_total_win_percent': self.prop_status.max_total_win_percent
            }
        }
    
    def __repr__(self):
        balance_change = self.current_balance - self.initial_balance
        change_sign = "+" if balance_change >= 0 else ""
        return (f"Budget(Balance: ${self.current_balance:.2f} {change_sign}${balance_change:.2f}, "
                f"Risk: {self.current_risk_percent:.1%}, Prop: {self.get_prop_status_string()})")
    
    def __str__(self):
        return self.__repr__()
