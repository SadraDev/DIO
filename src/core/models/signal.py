from datetime import datetime, timedelta
from typing import Optional, List, TYPE_CHECKING
from enum import Enum
from config.settings import settings

if TYPE_CHECKING:
    from src.core.models.bar import Bar

class SignalAction(Enum):
    """Signal action types"""
    BUY = "BUY"
    SELL = "SELL"

class SignalOutcome(Enum):
    """Signal outcome types"""
    WIN = "win"
    LOSS = "loss"
    PENDING = "pending"
    FORCE_STOPED = "force_stoped"

class SignalType(Enum):
    """Signal type classification"""
    MAIN = "main"
    RECOVERY = "recovery"

class Signal:
    """
    Represents a trading signal with all relevant data
    UPDATED: Uses Budget class for all financial calculations
    """
    
    def __init__(self, action: SignalAction, entry_price: float, stop_loss: float, 
                 take_profit: float, symbol: str, timestamp: datetime,
                 signal_type: SignalType = SignalType.MAIN, take_profit_pips: Optional[float] = None,
                 stop_loss_pips: Optional[float] = None, entry_lot: Optional[float] = None,
                 gain: Optional[float] = None, ticket: Optional[int] = None):
        
        # Core signal data
        self.action = action if isinstance(action, SignalAction) else SignalAction(action)
        self.symbol = symbol
        self.timestamp = timestamp
        self.signal_type = signal_type
        
        # Price levels
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        
        # Store initial values for risk-free adjustments
        self.initial_entry_price = entry_price
        self.initial_stop_loss = stop_loss
        self.initial_take_profit = take_profit
        
        # Position sizing and metrics
        self.entry_lot = entry_lot
        self.stop_loss_pips = stop_loss_pips
        self.take_profit_pips = take_profit_pips
        
        # Outcome tracking
        self.outcome: Optional[SignalOutcome] = SignalOutcome.PENDING
        self.outcome_timestamp: Optional[datetime] = None
        self.exit_pips: Optional[float] = None
        self.exit_price: Optional[float] = None
        self.gain = gain
        
        # Order execution details
        self.ticket = ticket  # Broker order ticket ID
        self.commission = None
        
        # Strategy flags and metadata
        self.trend = None
        self.fake_CHoCH = None
        self.time_flag = None

        # Toggle if any flag is use not to generate signal
        self.used_flag = False
        
        # Risk management tracking
        self.sl_adjusted_count = 0
    
    @property
    def is_main(self) -> bool:
        """Check if this is a main signal"""
        return self.signal_type == SignalType.MAIN
    
    @property
    def is_buy(self) -> bool:
        """Check if this is a buy signal"""
        return self.action == SignalAction.BUY
    
    @property
    def is_sell(self) -> bool:
        """Check if this is a sell signal"""
        return self.action == SignalAction.SELL
    
    @property
    def is_pending(self) -> bool:
        """Check if signal outcome is still pending"""
        return self.outcome is None or self.outcome == SignalOutcome.PENDING
    
    @property
    def is_completed(self) -> bool:
        """Check if signal is completed (win or loss)"""
        return self.outcome in [SignalOutcome.WIN, SignalOutcome.LOSS, SignalOutcome.FORCE_STOPED]

    @property
    def has_flag(self) -> bool:
        return self.trend or self.time_flag or self.fake_CHoCH

    def reward_ratio(self) -> float:
        """Calculate reward to risk ratio (TP pips / SL pips)"""
        if self.stop_loss_pips is None or self.stop_loss_pips <= 0:
            return 0.0
        if self.take_profit_pips is None:
            return 0.0
        return abs(self.take_profit_pips) / abs(self.stop_loss_pips)
    
    # OUTCOME AND ADJUSTMENT METHODS
    def update_outcome(self, outcome: SignalOutcome, gain: float, timestamp: Optional[datetime] = None):
        """Update signal outcome"""
        self.outcome = outcome
        self.gain = gain
        self.outcome_timestamp = timestamp or datetime.now()
    
    def adjust_stop_loss(self, new_stop_loss: float, reason: str):
        """Adjust stop loss level"""
        old_sl = self.stop_loss
        self.stop_loss = new_stop_loss
        self.sl_adjusted_count += 1
        
        from src.core.utils.logger import log_signal_event
        log_signal_event("stop_loss_adjusted", self.symbol, self.action.value,
                        old_sl=old_sl, new_sl=new_stop_loss, reason=reason,
                        adjustment_count=self.sl_adjusted_count)
        
        from src.core.utils.logger import log_signal_event
        log_signal_event("risk_free_activated", self.symbol, self.action.value,
                        entry_price=self.entry_price, current_sl=self.stop_loss)
    
    # MAIN EVALUATION METHOD - COMPLETELY REWRITTEN WITH SINGLE LOOP
    def evaluate_signal(self, budget = None, force_stop_dt: datetime = None, max_fetch_attempts: int = 5) -> Optional['Bar']:
        """
        Evaluate signal outcome with SINGLE-LOOP processing and automatic bar fetching
        COMPLETELY REWRITTEN: Uses Budget for all calculations, eliminates double-looping
        """
        from src.core.utils.logger import log_signal_event
        from src.core.data.fetcher import DataFetcher

        fetcher = DataFetcher()

        # Calculate position size using Budget's ratio_amount if not set
        fetch_attempts = 1
        commission_value = settings.get("trading.commission")

        # MAIN EVALUATION LOOP WITH AUTOMATIC BAR FETCHING
        while not self.is_completed and fetch_attempts <= max_fetch_attempts:
            # Filter bars after signal timestamp
            evaluation_bars = fetcher.fetch_bars_from_mt5(
                start_dt=self.timestamp + timedelta(minutes=1), 
                end_dt=self.timestamp + timedelta(hours=24*(fetch_attempts)),
                symbol=self.symbol)

            # Check if we have any bars to evaluate
            if not evaluation_bars:
                log_signal_event("no_bars_for_evaluation", self.symbol, self.action.value,
                               signal_time=self.timestamp, available_bars=len(evaluation_bars),
                               fetch_attempt=fetch_attempts)
                
                # Try to fetch more bars if we haven't reached max attempts
                if fetch_attempts < max_fetch_attempts:
                    fetch_attempts += 1
                    continue
            
            # SINGLE LOOP: Process bars chronologically  
            for bar in evaluation_bars:

                # === STEP 1: APPLY ORDER MANAGEMENT (if any enabled) ===
                # if self.signal_type == SignalType.RECOVERY:
                self.online_order_manager(bar, budget)

                if force_stop_dt and bar.timestamp >= force_stop_dt:
                    action = "SELL" if self.action == SignalAction.SELL else "BUY"
                    self.exit_price = bar.open
                    actual_gain = budget.calculate_gain_loss(
                        self.symbol, self.initial_entry_price, self.exit_price,
                        self.entry_lot, action
                    )
                    
                    self.update_outcome(SignalOutcome.FORCE_STOPED, actual_gain, bar.timestamp)
                    self.commission = self.entry_lot * commission_value
                    self.gain -= self.commission

                    log_signal_event("signal_force_stoped", self.symbol, self.action.value,
                                    gain=actual_gain, exit_price=self.exit_price,
                                    pips=budget.pips_from_diff(abs(self.initial_entry_price - self.exit_price)),
                                    lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                    fetch_attempts=fetch_attempts)
                    break

                # === STEP 2: CHECK FOR TP/SL HITS ===
                if self.action == SignalAction.SELL:
                    # Take Profit hit (price going down)
                    if bar.low <= self.take_profit:
                        self.exit_price = self.take_profit
                        actual_gain = budget.calculate_gain_loss(
                            self.symbol, self.initial_entry_price, self.exit_price, 
                            self.entry_lot, "SELL"
                        )
                        
                        self.update_outcome(SignalOutcome.WIN, actual_gain, bar.timestamp)
                        log_signal_event("signal_win", self.symbol, self.action.value,
                                        gain=actual_gain, exit_price=self.exit_price,
                                        pips=budget.pips_from_diff(abs(self.initial_entry_price - self.exit_price)),
                                        lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                        fetch_attempts=fetch_attempts)
                    
                    # Stop Loss hit (price going up)
                    if bar.high >= self.stop_loss:
                        self.exit_price = self.stop_loss
                        actual_loss = budget.calculate_gain_loss(
                            self.symbol, self.initial_entry_price, self.stop_loss,
                            self.entry_lot, "SELL"
                        )

                        if self.initial_entry_price <= self.stop_loss:
                            self.update_outcome(SignalOutcome.LOSS, actual_loss, bar.timestamp)
                            log_signal_event("signal_loss", self.symbol, self.action.value,
                                            loss=actual_loss, exit_price=self.stop_loss,
                                            pips=budget.pips_from_diff(abs(self.stop_loss - self.initial_entry_price)),
                                            lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                            fetch_attempts=fetch_attempts)
                        else:
                            self.update_outcome(SignalOutcome.WIN, actual_loss, bar.timestamp)
                            log_signal_event("signal_win", self.symbol, self.action.value,
                                            gain=actual_loss, exit_price=self.stop_loss,
                                            pips=budget.pips_from_diff(abs(self.initial_entry_price - self.stop_loss)),
                                            lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                            fetch_attempts=fetch_attempts)
                        
                elif self.action == SignalAction.BUY:
                    # Take Profit hit (price going up)
                    if bar.high >= self.take_profit:
                        self.exit_price = self.take_profit
                        actual_gain = budget.calculate_gain_loss(
                            self.symbol, self.initial_entry_price, self.take_profit,
                            self.entry_lot, "BUY"
                        )
                        
                        self.update_outcome(SignalOutcome.WIN, actual_gain, bar.timestamp)
                        log_signal_event("signal_win", self.symbol, self.action.value,
                                        gain=actual_gain, exit_price=self.exit_price,
                                        pips=budget.pips_from_diff(abs(self.exit_price - self.initial_entry_price)),
                                        lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                        fetch_attempts=fetch_attempts)
                    
                    # Stop Loss hit (price going down)
                    elif bar.low <= self.stop_loss:
                        self.exit_price = self.stop_loss
                        actual_loss = budget.calculate_gain_loss(
                            self.symbol, self.initial_entry_price, self.stop_loss,
                            self.entry_lot, "BUY"
                        )
                        
                        if self.initial_entry_price >= self.stop_loss:
                            self.update_outcome(SignalOutcome.LOSS, actual_loss, bar.timestamp)
                            log_signal_event("signal_loss", self.symbol, self.action.value,
                                            loss=actual_loss, exit_price=self.stop_loss,
                                            pips=budget.pips_from_diff(abs(self.initial_entry_price - self.stop_loss)),
                                            lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                            fetch_attempts=fetch_attempts)
                        else:
                            self.update_outcome(SignalOutcome.WIN, actual_loss, bar.timestamp)
                            log_signal_event("signal_win", self.symbol, self.action.value,
                                            gain=actual_loss, exit_price=self.stop_loss,
                                            pips=budget.pips_from_diff(abs(self.stop_loss - self.initial_entry_price)),
                                            lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                            fetch_attempts=fetch_attempts)
            
                if self.is_completed:
                    self.commission = self.entry_lot * commission_value
                    self.gain -= self.commission
                    break

            # If we've processed all current bars without an outcome, try to fetch more
            if fetch_attempts < max_fetch_attempts and not self.is_completed:
                log_signal_event("signal_not_resolved", self.symbol, self.action.value,
                            bars_processed=len(evaluation_bars),
                            last_bar_time=evaluation_bars[-1].timestamp if evaluation_bars else None,
                            attempting_fetch=fetch_attempts + 1)
                fetch_attempts += 1
            else:
                # Max attempts reached
                break
        
        # Signal was not resolved - remains pending
        log_signal_event("signal_remains_pending", self.symbol, self.action.value,
                       total_bars_processed=len([bar for bar in evaluation_bars if bar.timestamp > self.timestamp]),
                       total_fetch_attempts=fetch_attempts)

    def online_order_manager(self, bar, budget):
        risk_manager = settings.get("strategies.two_hunters.flags.use_risk_manager")
        use_online_commission_manager = settings.get("strategies.two_hunters.flags.use_online_commission_manager")
        use_offline_commission_manager = settings.get("strategies.two_hunters.flags.use_offline_commission_manager")
        commission_diff = 0 #budget.calculate_commission_diff()
        ratio_amount = round(abs(self.initial_entry_price - self.initial_stop_loss), 5)

        if risk_manager and bar is not None:
            # Risk-free management setup
            risk_free_1r_applied = False
            risk_free_2r_applied = False
            risk_free_3r_applied = False

            if self.action == SignalAction.SELL:

                # Cover Commission amount
                if not risk_free_1r_applied and bar.low <= self.initial_entry_price - commission_diff:
                    new_sl = self.initial_stop_loss - commission_diff

                    if self.stop_loss > new_sl:
                        self.adjust_stop_loss(new_sl, "Reached commission amount")

                # 1R favorable movement (price going down)
                if not risk_free_1r_applied and bar.low <= self.initial_entry_price - ratio_amount:
                    new_sl = (self.initial_stop_loss - ratio_amount / 2) - commission_diff

                    if self.stop_loss > new_sl:
                        # self.adjust_stop_loss(new_sl, "1R_favorable")
                        risk_free_1r_applied = True
                
                # 2R breakeven
                if not risk_free_2r_applied and bar.low <= round(self.initial_entry_price - 2 * ratio_amount, 5):
                    new_sl = self.initial_entry_price - commission_diff

                    if self.stop_loss > new_sl:
                        self.adjust_stop_loss(new_sl, "2R_breakeven")
                        risk_free_2r_applied = True
                
                # Near 3R lock
                if abs(bar.low - self.initial_take_profit) <= 0.10*ratio_amount and not risk_free_3r_applied:
                    new_sl = self.initial_entry_price - 0.90*(3*ratio_amount) - commission_diff
                    new_tp = bar.low - 0.25*ratio_amount - commission_diff
                    self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss > new_sl else self.stop_loss
                    risk_free_3r_applied = True

                # Post 3R movement
                if abs(bar.low - self.take_profit) <= 0.10*ratio_amount and risk_free_3r_applied:
                    new_sl = bar.high + 0.10*ratio_amount - commission_diff
                    new_tp = bar.low - 0.25*ratio_amount - commission_diff
                    self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "Post 3R movement") if self.stop_loss > new_sl else self.stop_loss

            elif self.action == SignalAction.BUY:

                # Cover Commission amount
                if not risk_free_1r_applied and bar.high >= self.initial_entry_price + commission_diff:
                    new_sl = self.initial_stop_loss + commission_diff

                    if self.stop_loss < new_sl:
                        self.adjust_stop_loss(new_sl, "Reached commission amount")

                # 1R favorable movement (price going up)
                if not risk_free_1r_applied and bar.high >= self.initial_entry_price + ratio_amount:
                    new_sl = (self.initial_stop_loss + ratio_amount / 2) + commission_diff
                        
                    if self.stop_loss <= new_sl:
                        self.adjust_stop_loss(new_sl, "1R_favorable") 
                        risk_free_1r_applied = True
                
                # 2R breakeven
                if not risk_free_2r_applied and bar.high >= self.initial_entry_price + 2 * ratio_amount:
                    new_sl = self.initial_entry_price + commission_diff

                    if self.stop_loss <= new_sl:
                        self.adjust_stop_loss(new_sl, "2R_breakeven")
                        risk_free_2r_applied = True

                # Near 3R lock
                if abs(bar.high - self.take_profit) <= 0.10*ratio_amount:
                    new_sl = self.initial_entry_price + 0.95*(3*ratio_amount) + commission_diff
                    new_tp = bar.high + 0.25*ratio_amount + commission_diff
                    self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss
                    risk_free_3r_applied = True

                # Post 3R movement
                if abs(bar.high - self.take_profit) <= 0.10*ratio_amount and not risk_free_3r_applied:
                    new_sl = bar.low - 0.10*ratio_amount + commission_diff
                    new_tp = bar.high + 0.25*ratio_amount + commission_diff
                    self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss

        elif use_online_commission_manager and bar is not None:
            # Cover Commission amount
            if self.action == SignalAction.SELL:
                if bar.low <= self.initial_entry_price - commission_diff*2:
                    new_sl = self.initial_stop_loss - commission_diff
                    new_tp = self.initial_take_profit - commission_diff
                    self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "Covered commission amount") if self.stop_loss > new_sl else self.stop_loss

            # Cover Commission amount
            elif self.action == SignalAction.BUY:
                if bar.high >= self.initial_entry_price + commission_diff*2:
                    new_sl = self.initial_stop_loss + commission_diff
                    new_tp = self.initial_take_profit + commission_diff
                    self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "Covered commission amount") if self.stop_loss < new_sl else self.stop_loss

        elif use_offline_commission_manager and bar is not None:
            # Cover Commission amount
            commission_per_lot = settings.get("trading.commission")
            commission_amount = budget.lots_from_diff(self.symbol, abs(self.initial_entry_price - self.initial_stop_loss)) * commission_per_lot
            diff = (3*commission_amount / budget.calculate_pip_value(self.symbol)) * budget.pip_size

            if self.action == SignalAction.SELL:
                if abs(bar.low - self.initial_take_profit) <= 0.50*ratio_amount:
                    new_sl = self.initial_entry_price - 0.95*(3*ratio_amount)
                    new_tp = self.initial_take_profit - diff
                    self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "near_tp_commission_adjustment") if self.stop_loss > new_sl else self.stop_loss

            # Cover Commission amount
            elif self.action == SignalAction.BUY:
                if abs(bar.high - self.initial_take_profit) <= 0.10*ratio_amount:
                    new_sl = self.initial_entry_price + 0.95*(3*ratio_amount) + commission_diff
                    new_tp = self.initial_take_profit + diff
                    self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                    self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss


    # BINARY OPTION ANALYSIS (Preserved)
    def binary_option(signals: List, length: int = 60) -> List[int]:
        """Binary option success rate analysis"""
        from src.core.data.fetcher import DataFetcher
        from datetime import timedelta
        
        result = [0] * length
        fetcher = DataFetcher()
        
        for signal in signals:
            start_time = signal.timestamp + timedelta(minutes=1)
            end_time = start_time + timedelta(minutes=length)
            
            try:
                bars = fetcher.fetch_bars_from_mt5(start_time, end_time, signal.symbol)
                bars = bars[:length]
                
                for idx, bar in enumerate(bars):
                    if signal.action == SignalAction.BUY:
                        result[idx] += 1 if bar.high > signal.initial_entry_price else -1
                    elif signal.action == SignalAction.SELL:
                        result[idx] += 1 if bar.low < signal.initial_entry_price else -1
            except:
                continue
        
        return [round(x * 100 / len(signals)) for x in result] if signals else result
    
    # SERIALIZATION METHODS (Unchanged)
    def to_dict(self) -> dict:
        """Convert signal to dictionary representation"""
        return {
            # Core signal data
            "action": self.action.value,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal_type": self.signal_type.value,
            
            # Price levels
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            
            # Initial values (for risk-free tracking)
            "initial_entry_price": self.initial_entry_price,
            "initial_stop_loss": self.initial_stop_loss,
            "initial_take_profit": self.initial_take_profit,
            
            # Position sizing and metrics
            "entry_lot": self.entry_lot,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
            
            # Outcome tracking
            "outcome": self.outcome.value if self.outcome else None,
            "outcome_timestamp": self.outcome_timestamp.isoformat() if self.outcome_timestamp else None,
            "exit_pips": self.exit_pips,
            "exit_price": self.exit_price,
            "gain": self.gain,
            
            # Order execution details
            "ticket": self.ticket,
            "commission": self.commission,
            
            # Strategy flags and metadata
            "trend": self.trend,
            "fake_CHoCH": self.fake_CHoCH,
            "time_flag": self.time_flag,
            "used_flag": self.used_flag,
            
            # Risk management tracking
            "sl_adjusted_count": self.sl_adjusted_count,
            
            # Computed properties (for convenience)
            "is_complete": self.is_completed,
            "is_pending": self.is_pending,
            "risk_free_activated": True if self.sl_adjusted_count > 0 else False,
        }

    
    def __repr__(self):
        outcome_str = f" {self.outcome.value.upper()}" if self.outcome else " PENDING"
        gain_str = f" Gain: ${self.gain:.2f}" if self.gain is not None else ""
        return (f"Signal({self.symbol} {self.action.value} @ {self.entry_price:.5f} "
                f"SL:{self.stop_loss:.5f} TP:{self.take_profit:.5f} "
                f"{self.timestamp.strftime('%Y-%m-%d %H:%M')}{outcome_str}{gain_str})")
    
    def __str__(self):
        return self.__repr__()
