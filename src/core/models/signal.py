from datetime import datetime, timedelta
from typing import Optional, List, TYPE_CHECKING
from enum import Enum
from config.settings import settings

if TYPE_CHECKING:
    from src.core.models.budget import Budget
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
    CANCELLED = "cancelled"

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
        self.emergency: bool = False
        
        # Outcome tracking
        self.outcome: Optional[SignalOutcome] = SignalOutcome.PENDING
        self.outcome_timestamp: Optional[datetime] = None
        self.exit_pips: Optional[float] = None
        self.exit_price: Optional[float] = None
        self.lil_boy: bool = False
        self.gain = gain
        
        # Order execution details
        self.ticket = ticket  # Broker order ticket ID
        self.commission = None
        
        # Strategy flags and metadata
        self.trend = None
        self.fake_CHoCH = None
        self.time_flag = None
        
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
        return self.outcome in [SignalOutcome.WIN, SignalOutcome.LOSS]
    
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
    def evaluate_signal(self, risk_manager: bool = True, max_fetch_attempts: int = 5) -> Optional['Bar']:
        """
        Evaluate signal outcome with SINGLE-LOOP processing and automatic bar fetching
        COMPLETELY REWRITTEN: Uses Budget for all calculations, eliminates double-looping
        """
        from src.core.utils.logger import log_signal_event
        from src.core.models.budget import Budget
        from src.core.data.fetcher import DataFetcher

        budget = Budget()
        fetcher = DataFetcher()

        # Calculate position size using Budget's ratio_amount if not set
        fetch_attempts = 1
        commission_amount = settings.get("trading.commission")
        
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

                # === STEP 1: CHECK FOR TP/SL HITS ===
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
                            self.update_outcome(SignalOutcome.WIN if not self.lil_boy else SignalOutcome.LOSS, actual_loss, bar.timestamp)
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
                            self.update_outcome(SignalOutcome.WIN if not self.lil_boy else SignalOutcome.LOSS, actual_loss, bar.timestamp)
                            log_signal_event("signal_win", self.symbol, self.action.value,
                                            gain=actual_loss, exit_price=self.stop_loss,
                                            pips=budget.pips_from_diff(abs(self.stop_loss - self.initial_entry_price)),
                                            lot_size=self.entry_lot, bars_evaluated=len(evaluation_bars),
                                            fetch_attempts=fetch_attempts)
            
                if self.is_completed:
                    self.commission = self.entry_lot * commission_amount * 100000
                    self.gain -= self.commission
                    break

                # === STEP 2: APPLY RISK-FREE MANAGEMENT (if enabled) ===
                if risk_manager and bar is not None and not self.emergency:
                    # Risk-free management setup
                    ratio_amount = round(abs(self.initial_entry_price - self.initial_stop_loss), 5)
                    risk_free_1r_applied = False
                    risk_free_2r_applied = False
                    lil_boy = False
                    
                    if self.action == SignalAction.SELL:

                        # # GET OUTs
                        # if abs(self.timestamp.minute - bar.timestamp.minute) <= 2 and not bar.is_head_down:
                        #     if bar.low <= self.initial_entry_price - ratio_amount * 1.5:
                        #         new_sl = bar.high
                        #         lil_boy = True
                        #         self.adjust_stop_loss(new_sl, "GOOD GET OUT") if self.stop_loss > new_sl else self.stop_loss
                            
                        #     elif(bar.high >= self.initial_entry_price + ratio_amount * 0.6):
                        #         if bar.is_bullish:
                        #             new_sl = bar.close
                                
                        #         elif bar.is_bearish or bar.is_doji:
                        #             new_sl = bar.low + bar.range/2
                                
                        #         lil_boy = True
                        #         self.adjust_stop_loss(new_sl, "BAD GET OUT") if self.stop_loss > new_sl else self.stop_loss
                        
                        if not risk_free_1r_applied and bar.low <= self.initial_entry_price - commission_amount and not lil_boy:
                            new_sl = self.initial_stop_loss - commission_amount

                            if self.stop_loss > new_sl:
                                self.adjust_stop_loss(new_sl, "Reached commission amount" if not lil_boy else "GET OUT")

                        # 1R favorable movement (price going down)
                        if not risk_free_1r_applied and bar.low <= self.initial_entry_price - ratio_amount and not lil_boy:
                            new_sl = (self.initial_stop_loss - ratio_amount / 2) - commission_amount

                            if self.stop_loss > new_sl:
                                self.adjust_stop_loss(new_sl, "1R_favorable" if not lil_boy else "GET OUT")
                                risk_free_1r_applied = True
                        
                        # 2R breakeven
                        if not risk_free_2r_applied and bar.low <= round(self.initial_entry_price - 2 * ratio_amount, 5):
                            new_sl = self.initial_entry_price - commission_amount

                            if self.stop_loss > new_sl:
                                self.adjust_stop_loss(new_sl, "2R_breakeven")
                                risk_free_2r_applied = True
                        
        
                        if abs(bar.low - self.take_profit) <= 0.20*ratio_amount:
                            new_sl = bar.low + commission_amount
                            new_tp = bar.low - 0.25*ratio_amount - commission_amount
                            self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                            self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss > new_sl else self.stop_loss
                        

                        # # Near TP profit locking        
                        # if abs(bar.low - self.take_profit) <= 0.1 * ratio_amount and bar.low < self.take_profit:
                        #     new_sl = bar.low + commission_amount
                        #     new_tp = bar.low - commission_amount*2
                        #     self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                        #     self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss > new_sl else self.stop_loss
                        
                        if lil_boy == True:
                            self.lil_boy = True

                    elif self.action == SignalAction.BUY:
                        
                        # # GET OUTs
                        # if abs(self.timestamp.minute - bar.timestamp.minute) <= 2 and not bar.is_head_down:
                        #     if bar.high >= self.initial_entry_price + ratio_amount * 1.5:
                        #         new_sl = bar.low
                        #         lil_boy = True
                        #         self.adjust_stop_loss(new_sl, "GOOD GET OUT") if self.stop_loss < new_sl else self.stop_loss
                            
                        #     elif(bar.low <= self.initial_entry_price - ratio_amount * 0.6):
                        #         if bar.is_bullish or bar.is_doji:
                        #             new_sl = bar.high - bar.range/2
                                
                        #         elif bar.is_bearish:
                        #             new_sl = bar.close
                                
                        #         lil_boy = True
                        #         self.adjust_stop_loss(new_sl, "BAD GET OUT") if self.stop_loss < new_sl else self.stop_loss
                        
                        # 1R favorable movement (price going up)
                        if not risk_free_1r_applied and bar.high >= self.initial_entry_price + ratio_amount and not lil_boy:
                            new_sl = (self.initial_stop_loss + ratio_amount / 2) + commission_amount
                                
                            if self.stop_loss <= new_sl:
                                self.adjust_stop_loss(new_sl, "1R_favorable") 
                                risk_free_1r_applied = True
                        
                        # 2R breakeven
                        if not risk_free_2r_applied and bar.high >= self.initial_entry_price + 2 * ratio_amount:
                            new_sl = self.initial_entry_price + commission_amount

                            if self.stop_loss <= new_sl:
                                self.adjust_stop_loss(new_sl, "2R_breakeven")
                                risk_free_2r_applied = True


                        if abs(bar.high - self.take_profit) <= 0.20*ratio_amount:
                            new_sl = bar.high - commission_amount
                            new_tp = bar.high + 0.25*ratio_amount + commission_amount
                            self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                            self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss

                        # # Near TP profit locking
                        # if abs(bar.high - self.take_profit) <= 0.1 * ratio_amount or bar.high > self.take_profit:
                        #     new_sl = bar.high - commission_amount
                        #     new_tp = bar.high + commission_amount*2
                        #     self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                        #     self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss


                        if lil_boy == True:
                            self.lil_boy = True

                elif self.emergency and bar is not None:
                    first_applied = False
                    second_applied = False

                    if self.is_sell:
                        is_65_percent_down = bar.low < self.initial_entry_price - abs(self.initial_entry_price - self.initial_take_profit) * 0.65
                        if not first_applied and is_65_percent_down:
                            new_sl = self.initial_stop_loss - commission_amount
                            self.adjust_stop_loss(new_sl, f"Passed 65% old tp") if self.stop_loss > new_sl else self.stop_loss
                        
                        if not second_applied and bar.low < self.initial_take_profit:
                            new_sl = bar.high - commission_amount
                            self.adjust_stop_loss(new_sl, "Passed old tp") if self.stop_loss > new_sl else self.stop_loss

                    if self.is_buy:
                        is_65_percent_down = bar.high > self.initial_entry_price + abs(self.initial_entry_price + self.initial_take_profit) * 0.65
                        if not first_applied and is_65_percent_down:
                            new_sl = self.initial_stop_loss + commission_amount
                            self.adjust_stop_loss(new_sl, "Passed old tp") if self.stop_loss < new_sl else self.stop_loss
                        
                        if not second_applied and bar.high > self.initial_take_profit:
                            new_sl = bar.low + commission_amount
                            self.adjust_stop_loss(new_sl, f"Passed 65% old tp") if self.stop_loss < new_sl else self.stop_loss

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

    
    # LEGACY RISK-FREE METHOD (Preserved for compatibility)
    def risk_manager(self, bars_till_now: List['Bar']) -> bool:

        if not bars_till_now:
            return False

        ratio_amount = round(abs(self.initial_entry_price - self.initial_stop_loss), 5)
        commission_amount = settings.get("trading.commission")
        risk_free_1r_applied = False
        risk_free_2r_applied = False
        lil_boy = False
        live_bar = bars_till_now.pop()

        for bar in bars_till_now:
            # === STEP 2: APPLY RISK-FREE MANAGEMENT (if enabled) ===
            if bar is not None and not self.emergency:
                # Risk-free management setup
                ratio_amount = round(abs(self.initial_entry_price - self.initial_stop_loss), 5)
                risk_free_1r_applied = False
                risk_free_2r_applied = False
                lil_boy = False
                
                if self.action == SignalAction.SELL:

                    # Adjust for commission
                    if not risk_free_1r_applied and bar.low <= self.initial_entry_price - commission_amount and not lil_boy:
                        new_sl = self.initial_stop_loss - commission_amount

                        if self.stop_loss > new_sl:
                            self.adjust_stop_loss(new_sl, "Reached commission amount" if not lil_boy else "GET OUT")

                    # 1R favorable
                    if not risk_free_1r_applied and bar.low <= self.initial_entry_price - ratio_amount and not lil_boy:
                        new_sl = (self.initial_stop_loss - ratio_amount / 2) - commission_amount

                        if self.stop_loss > new_sl:
                            self.adjust_stop_loss(new_sl, "1R_favorable" if not lil_boy else "GET OUT")
                            risk_free_1r_applied = True
                    
                    # 2R breakeven
                    if not risk_free_2r_applied and bar.low <= round(self.initial_entry_price - 2 * ratio_amount, 5):
                        new_sl = self.initial_entry_price - commission_amount

                        if self.stop_loss > new_sl:
                            self.adjust_stop_loss(new_sl, "2R_breakeven")
                            risk_free_2r_applied = True
                    
                    # Near 3R
                    if abs(bar.low - self.take_profit) <= 0.20*ratio_amount:
                        new_sl = bar.low + commission_amount
                        new_tp = bar.low - 0.25*ratio_amount - commission_amount
                        self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                        self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss > new_sl else self.stop_loss
                        
                    elif abs(live_bar.low - self.take_profit) <= 0.20*ratio_amount:
                        new_sl = live_bar.low + commission_amount
                        new_tp = live_bar.low - 0.25*ratio_amount - commission_amount
                        self.take_profit = new_tp if new_tp < self.take_profit else self.take_profit
                        self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss > new_sl else self.stop_loss

                    if lil_boy == True:
                        self.lil_boy = True

                elif self.action == SignalAction.BUY:

                    # Adjust for commission
                    if not risk_free_1r_applied and bar.high >= self.initial_entry_price + commission_amount and not lil_boy:
                        new_sl = self.initial_stop_loss + commission_amount

                        if self.stop_loss < new_sl:
                            self.adjust_stop_loss(new_sl, "Reached commission amount" if not lil_boy else "GET OUT")


                    # 1R favorable
                    if not risk_free_1r_applied and bar.high >= self.initial_entry_price + ratio_amount and not lil_boy:
                        new_sl = (self.initial_stop_loss + ratio_amount / 2) + commission_amount
                            
                        if self.stop_loss <= new_sl:
                            self.adjust_stop_loss(new_sl, "1R_favorable") 
                            risk_free_1r_applied = True
                    
                    # 2R breakeven
                    if not risk_free_2r_applied and bar.high >= self.initial_entry_price + 2 * ratio_amount:
                        new_sl = self.initial_entry_price + commission_amount

                        if self.stop_loss <= new_sl:
                            self.adjust_stop_loss(new_sl, "2R_breakeven")
                            risk_free_2r_applied = True


                    if abs(bar.high - self.take_profit) <= 0.20*ratio_amount:
                        new_sl = bar.high - commission_amount
                        new_tp = bar.high + 0.25*ratio_amount + commission_amount
                        self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                        self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss

                    if abs(live_bar.high - self.take_profit) <= 0.20*ratio_amount:
                        new_sl = live_bar.high - commission_amount
                        new_tp = live_bar.high + 0.25*ratio_amount + commission_amount
                        self.take_profit = new_tp if new_tp > self.take_profit else self.take_profit
                        self.adjust_stop_loss(new_sl, "near_tp_lock") if self.stop_loss < new_sl else self.stop_loss

            elif self.emergency and bar is not None:
                first_applied = False
                second_applied = False

                if self.is_sell:
                    is_65_percent_down = live_bar.low < self.initial_entry_price - abs(self.initial_entry_price - self.initial_take_profit) * 0.65
                    if not first_applied and is_65_percent_down:
                        new_sl = self.initial_stop_loss - commission_amount
                        self.adjust_stop_loss(new_sl, f"Passed 65% old tp") if self.stop_loss > new_sl else self.stop_loss
                    
                    if not second_applied and live_bar.low < self.initial_take_profit:
                        new_sl = live_bar.high - commission_amount
                        self.adjust_stop_loss(new_sl, "Passed old tp") if self.stop_loss > new_sl else self.stop_loss

                if self.is_buy:
                    is_65_percent_down = live_bar.high > self.initial_entry_price + abs(self.initial_entry_price + self.initial_take_profit) * 0.65
                    if not first_applied and is_65_percent_down:
                        new_sl = self.initial_stop_loss + commission_amount
                        self.adjust_stop_loss(new_sl, "Passed old tp") if self.stop_loss < new_sl else self.stop_loss
                    
                    if not second_applied and live_bar.high > self.initial_take_profit:
                        new_sl = live_bar.low + commission_amount
                        self.adjust_stop_loss(new_sl, f"Passed 65% old tp") if self.stop_loss < new_sl else self.stop_loss
    
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
            'action': self.action.value,
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'signal_type': self.signal_type.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'initial_entry_price': self.initial_entry_price,
            'initial_stop_loss': self.initial_stop_loss,
            'initial_take_profit': self.initial_take_profit,
            'entry_lot': self.entry_lot,
            'stop_loss_pips': self.stop_loss_pips,
            'take_profit_pips': self.take_profit_pips,
            'outcome': self.outcome.value if self.outcome else None,
            'outcome_timestamp': self.outcome_timestamp.isoformat() if self.outcome_timestamp else None,
            'is_complete': self.is_completed,
            'is_pending': self.is_pending,
            'gain': self.gain,
            'ticket': self.ticket,
            'trend': self.trend,
            'fake_CHoCH': self.fake_CHoCH,
            'time_flag': self.time_flag,
            'risk_free_activated': True if self.sl_adjusted_count > 0 else False,
            'sl_adjusted_count': self.sl_adjusted_count
        }
    
    def __repr__(self):
        outcome_str = f" {self.outcome.value.upper()}" if self.outcome else " PENDING"
        gain_str = f" Gain: ${self.gain:.2f}" if self.gain is not None else ""
        return (f"Signal({self.symbol} {self.action.value} @ {self.entry_price:.5f} "
                f"SL:{self.stop_loss:.5f} TP:{self.take_profit:.5f} "
                f"{self.timestamp.strftime('%Y-%m-%d %H:%M')}{outcome_str}{gain_str})")
    
    def __str__(self):
        return self.__repr__()
