import threading
import json
import time as goodtimes
import os
from datetime import datetime, timedelta, time, date, timezone
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from collections import defaultdict

from src.indicators.fvg_detector import FVGDetector
from src.core.models.signal import Signal, SignalAction, SignalType
from src.core.models.bar import Bar
from src.core.models.budget import Budget
from src.indicators.breakout import BreakoutEngine, BreakoutType
from src.indicators.mbox import MBoxAnalyzer
from src.indicators.choch import FakeCHoCHDetector
from src.core.execution.mt5_connection import MT5Connection
from src.core.data.fetcher import DataFetcher
from src.core.utils.logger import TradingLogger, log_signal_event, log_system_event
from config.settings import settings

class TwoHunters():
    """
    Two Hunters Strategy Implementation
    
    Strategy Logic:
    1. Analyze MBox session for market bias
    2. Hunt for breakouts in main session (2 hunts for main signal)  
    3. If main signal fails, hunt for recovery signal (1 hunt)
    4. Apply risk management and dynamic position sizing
    
    Updated with System Hours vs Session Hours Support:
    - System Hours: When the strategy engine can operate
    - Session Hours: When trading analysis and signal generation happens
    """
    
    def __init__(
            self, 
            name: str = "Two-Hunters",
            budget: Budget = None,
            use_all_flags: bool = False,
            use_trading_hours: bool = False,
            use_trend_flag: bool = False,
            use_time_flag: bool = False,
            use_choch_flag: bool = False
            ):
        # Load strategy configuration
        self.config = settings.get_strategy_config("two_hunters")

        # Initialize budget
        self.budget = Budget() if budget is None else budget
        self.name = name

        # Initialize MT5 connection
        self.mt5 = MT5Connection()

        # Initialize indicators
        self._init_indicators()

        # Feature flags (from config)  
        flags = self.config.get("flags", {})
        self.use_all_flags = True if use_all_flags else flags.get("use_all_flags", False)
        self.use_trading_hours = True if use_trading_hours else flags.get("use_trading_hours", False)
        self.use_trend_flag = True if use_trend_flag else flags.get("use_trend_flag", False)
        self.use_time_flag = True if use_time_flag else flags.get("use_time_flag", False)
        self.use_choch_flag = True if use_choch_flag else flags.get("use_choch_flag", False)
        
        # Symbol
        self.symbol: str = None

        # Strategy state
        self.signal_counter = defaultdict(int)
        self.all_bars = []
        self.fake_chochs = []
        
        # SESSION HOURS - When trading analysis happens
        self.mbox_time = self._get_mbox_time()
        self.session_time = self._get_session_time()
        
        self.mbox_result = {}

        # Strategy parameters (from config)
        self.max_signals_per_symbol = settings.max_signals_per_symbol
        self.margin_pips = self.config.get("margin_pips")
        self.fvg_range = (
            self.config.get("fvg", {}).get("min_size_pips"),
            self.config.get("fvg", {}).get("max_size_pips")
        )
        self.ratios = self.config.get("ratios", {"stop_loss": 1.0, "take_profit": 3.0})
        
        self.logger = TradingLogger.get_trading_logger()
        
        self.logger.info(f"TwoHunters strategy initialized:")
        self.logger.info(f"MBox Hours: {self.mbox_time[0]} - {self.mbox_time[1]}")
        self.logger.info(f"Session Hours: {len(self.session_time)}")
    
    def _init_indicators(self):
        """Initialize strategy indicators with configuration"""
        # Breakout Engine
        breakout_config = self.config.get("breakout", {})
        self.breakout_engine = BreakoutEngine(
            num_hunt=breakout_config.get("num_hunt_main", 2)
        )

        # MBox Analyzer
        self.mbox_analyzer = MBoxAnalyzer()
        
        # FVG Detector
        self.fvg_detector = FVGDetector()

        # Fake CHoCH Detector
        choch_config = self.config.get("choch", {})
        self.fake_choch_detector = FakeCHoCHDetector(
            window=choch_config.get("window", 15),
            tolerance=choch_config.get("tolerance", 5),
            buffer=choch_config.get("buffer", 0.0000001),
            intensity=choch_config.get("intensity", 3.0),
            use_volume=choch_config.get("use_volume", False),
            single_hit=choch_config.get("single_hit", True),
            volume_factor=choch_config.get("volume_factor", 1.2),
            budget=self.budget
        )
    
    def _get_mbox_time(self) -> Tuple[time, time]:
        """Get session hours from config"""
        mbox_time_config = settings.get("strategies.two_hunters.mbox_time", {})
        
        start_time = datetime.strptime(mbox_time_config["start"], "%H:%M").time()
        end_time = datetime.strptime(mbox_time_config["end"], "%H:%M").time()
        return (start_time, end_time)
    
    def _get_session_time(self) -> Tuple[time, time]:
        """Get trading session hours from config"""
        session_time_config = settings.get("strategies.two_hunters.sessions.main", {})

        start_time = datetime.strptime(session_time_config["start"], "%H:%M").time()
        end_time = datetime.strptime(session_time_config["end"], "%H:%M").time()

        return (start_time, end_time)

    def get_mbox_bars(self, target_date: datetime) -> List[Bar]:
        """Get MBox session bars for the target date"""
        mbox_start = datetime.combine(target_date.date(), self.mbox_time[0])
        mbox_end = datetime.combine(target_date.date(), self.mbox_time[1])
        mbox_bars = [
            bar for bar in self.all_bars 
            if mbox_start <= bar.timestamp <= mbox_end
        ]
        
        self.logger.debug(f"Found {len(mbox_bars)} MBox bars for {target_date.date()}")
        return mbox_bars
    
    def get_session_bars(self, target_date: datetime) -> List[Bar]:
        """Get main session bars for the target date"""
        session_start = datetime.combine(target_date.date(), self.session_time[0])
        session_end = datetime.combine(target_date.date(), self.session_time[1])

        session_bars = [
            bar for bar in self.all_bars
            if session_start <= bar.timestamp <= session_end
        ]
        
        self.logger.debug(f"Found {len(session_bars)} session bars for {target_date.date()}")
        return session_bars
    
    def add_bars(self, bars: List[Bar]):
        """Add new bars to strategy state"""
        self.all_bars = []
        self.all_bars.extend(bars)
        
        self.logger.debug(f"Added {len(bars)} bars for {self.symbol}, total: {len(self.all_bars)}")
    
    def detect_fake_choch(self, mbox_bars: List[Bar], session_bars: List[Bar], 
                         hunter_bar: Bar) -> bool:
        """Detect fake CHoCH patterns"""
        # Recent MBox bars (last 1h15m)
        cutoff_time = mbox_bars[-1].timestamp - timedelta(hours=1, minutes=15)
        recent_mbox = [bar for bar in mbox_bars if bar.timestamp > cutoff_time]
        
        # Session bars up to hunter bar
        session_slice = [bar for bar in session_bars if bar.timestamp <= hunter_bar.timestamp]
        
        # Combined analysis bars
        analysis_bars = recent_mbox + session_slice
        
        self.fake_choch_detector.detailed = True
        detections = self.fake_choch_detector.detect(analysis_bars)
        
        if detections:
            self.fake_chochs.extend(detections)
            self.logger.debug(f"Detected {len(detections)} fake CHoCH patterns")
            return True
        
        return False
    
    def calculate_entry_details(self, action: SignalAction, signal_bar: Bar, 
                              extrema: float) -> Tuple[float, float, float]:
        """Calculate entry price, stop loss, and take profit"""
        # Get surrounding bars for FVG analysis
        before_bar, after_bar = self._get_surrounding_bars(signal_bar)
        if not before_bar or not after_bar:
            before_bar = after_bar = signal_bar
        
        entry_price = signal_bar.close
        
        # Fair Value Gap (FVG) logic
        min_fvg, max_fvg = self.fvg_range
        
        def dynamic_fvg_scale(fvg_size_pips: float) -> float:
            """Calculate dynamic scale based on FVG size.
            
            Maps fvg_size_pips from [min_fvg, max_fvg] to [0.5, 0.3].
            Returns 0.5 when closer to min_fvg, 0.3 when closer to max_fvg.
            """
            if min_fvg <= fvg_size_pips <= max_fvg:
                # Linear interpolation from (min_fvg -> 0.6) to (max_fvg -> 0.4)
                t = (fvg_size_pips - min_fvg) / (max_fvg - min_fvg)  # t ranges 0 to 1
                return 0.6 - (t * 0.2)
            
            # Handle edge cases
            if fvg_size_pips <= min_fvg:
                return 1.0  # Below min, return max scale
            if fvg_size_pips >= max_fvg:
                return 0.4  # Above max, return min scale

        scale = 1.0
        if action == SignalAction.SELL:
            # Check for bullish FVG
            if before_bar.bid_low > signal_bar.close:
                fvg_size_pips = self.budget.pips_from_diff(extrema - signal_bar.bid_low)
                scale = dynamic_fvg_scale(fvg_size_pips)
                
                if scale == 1.0: entry_price = signal_bar.close  # Default is Bid
                # else: entry_price = signal_bar.bid_high - abs(signal_bar.bid_low - signal_bar.bid_high) * scale
                else: entry_price = extrema - abs(signal_bar.bid_low - extrema) * scale
                
                self.logger.debug(f"SELL FVG: size={fvg_size_pips:.1f} pips, scale={scale:.2f}")
            
            diff = self.budget.diff_from_pips(self.margin_pips)
            stop_loss = self.ratios["stop_loss"] * (extrema + diff)
            
            if scale == 1.0: take_profit = entry_price - self.ratios["take_profit"] * abs(entry_price - stop_loss)
            # else: take_profit = signal_bar.close - self.ratios["take_profit"] * abs(signal_bar.close - stop_loss)
            else: take_profit = entry_price - self.ratios["take_profit"] * abs(entry_price - stop_loss)

        elif action == SignalAction.BUY:
            # Check for bullish FVG
            if signal_bar.close + signal_bar.spread > before_bar.ask_high:
                fvg_size_pips = self.budget.pips_from_diff(signal_bar.ask_high - extrema)
                scale = dynamic_fvg_scale(fvg_size_pips)
                
                if scale == 1.0: entry_price = signal_bar.close + signal_bar.spread  # To get Ask close
                # else: entry_price = signal_bar.ask_low + abs(signal_bar.ask_low - signal_bar.ask_high) * scale
                else: entry_price = extrema + abs(extrema - signal_bar.ask_high) * scale
                
                self.logger.debug(f"BUY FVG: size={fvg_size_pips:.1f} pips, scale={scale:.2f}")
            
            diff = self.budget.diff_from_pips(self.margin_pips)
            stop_loss = self.ratios["stop_loss"] * (extrema - diff)

            if scale == 1.0: take_profit = entry_price + self.ratios["take_profit"] * abs(entry_price - stop_loss)
            # else: take_profit = signal_bar.close + self.ratios["take_profit"] * abs(signal_bar.close - stop_loss)
            else: take_profit = entry_price + self.ratios["take_profit"] * abs(entry_price - stop_loss)

        self.logger.debug(f"Entry calculation: EP={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
        return entry_price, stop_loss, take_profit, scale < 1.0
    
    def _get_surrounding_bars(self, bar: Bar) -> Tuple[Optional[Bar], Optional[Bar]]:
        """Get bars immediately before and after the given bar"""
        target_time = bar.timestamp
        
        surrounding = [
            b for b in self.all_bars
            if target_time - timedelta(minutes=1) <= b.timestamp <= target_time + timedelta(minutes=1)
        ]
        
        if len(surrounding) >= 3:
            # Return first and last (before and after)
            return surrounding[0], surrounding[-1]
        
        return None, None
    
    def create_signal(self, action: SignalAction, entry_price: float, stop_loss: float,
                     take_profit: float, timestamp: datetime, 
                     signal_type: SignalType = SignalType.MAIN) -> Optional[Signal]:

        signal = Signal(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            symbol=self.symbol,
            timestamp=timestamp,
            signal_type=signal_type
        )
        
        return signal
    
    def check_strategy_flags(self, signal: Signal) -> bool:
        """Check if signal passes strategy flag requirements"""
        if self.use_all_flags:
            self.use_trading_hours = True
            self.use_trend_flag = True
            self.use_time_flag = True
            self.use_choch_flag = True
        
        # Collect flag violations
        violations = []
        
        if self.use_trend_flag and signal.trend:
            violations.append("trend_flag")
        
        if self.use_time_flag and signal.time_flag:
            violations.append("time_flag")
        
        if self.use_choch_flag and not signal.fake_CHoCH:
            violations.append("choch_flag")

        if violations:
            signal.used_flag = True
            self.logger.debug(f"Signal rejected by flags: {violations}")
            return False
        
        return True
    
    def attempt_signal(self, target_date: datetime, failed_signal: Signal = None) -> Optional[Signal]:
        """Attempt to generate main signal for the given date"""

        # Get required bars
        mbox_bars = self.get_mbox_bars(target_date)
        session_bars = self.get_session_bars(target_date)

        if not mbox_bars or len(session_bars) < 5:
            self.logger.debug(f"Insufficient bars: MBox={len(mbox_bars)}, Session={len(session_bars)}")
            return None

        # Analyze MBox for market bias
        mbox_result = self.mbox_result if self.mbox_result else self.mbox_analyzer.calculate(mbox_bars)
        self.breakout_engine.symbol = self.symbol

        # Hunt for breakout
        if failed_signal is None:
            self.breakout_engine.type = BreakoutType.DEFAULT
            extrema, signal_bar, action, hunter_bar, _ = self.breakout_engine.breakout(
                session_bars=session_bars, mbox_result=mbox_result
            )
        
        else:
            self.breakout_engine.type = BreakoutType.CUSTOM

            bars_after_failed = [bar for bar in session_bars if bar.timestamp >= failed_signal.outcome_timestamp]
                        
            extrema, signal_bar, action, hunter_bar, _ = self.breakout_engine.breakout(
                session_bars=bars_after_failed, failed_signal=failed_signal
            )          
        
        if not signal_bar:
            self.logger.debug("No breakout signal found")
            return None
        
        # Convert string action to enum
        action_enum = SignalAction.SELL if action == "SELL" else SignalAction.BUY

        # Calculate entry details
        entry_price, stop_loss, take_profit, _is_order = self.calculate_entry_details(
            action_enum, signal_bar, extrema
        )
        
        # Create signal
        signal = self.create_signal(
            action_enum, entry_price, stop_loss, take_profit,
            signal_bar.timestamp, SignalType.MAIN if failed_signal is None else SignalType.RECOVERY
        )
        
        if not signal:
            return None

        # Set strategy flags
        if failed_signal is None:
            signal.trend = mbox_result.get("trend", False)
            signal.fake_CHoCH = self.detect_fake_choch(mbox_bars, session_bars, hunter_bar)
            signal.time_flag = mbox_result.get("extrema_flag", False)
        else:
            signal.trend = failed_signal.trend
            signal.fake_CHoCH = failed_signal.fake_CHoCH
            signal.time_flag = failed_signal.time_flag

        # Initialize trading parameters
        self.budget.update_risk_percent(signal)
        signal.stop_loss_pips = self.budget.pips_from_diff(abs(signal.entry_price - signal.stop_loss))
        signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))
        signal.is_order = _is_order

        # check if there is fvg close by
        if self.breakout_engine.type == BreakoutType.CUSTOM:
            _tp_moved = False
            lookahead_pips = 5000
            fvgs = self.fvg_detector.get_nearby_active_fvgs(bar=signal_bar, symbol=self.symbol, pip_size=lookahead_pips)

            clean_fvgs = []
            for tf in fvgs:
                for fvg in fvgs[tf]:
                    if ((tf == "london" or tf == "newyork") and 
                        datetime.fromisoformat(fvg["detection_time"]) > datetime.combine(signal.timestamp.date(), self.mbox_time[1])):
                        continue
                    clean_fvgs.append(fvg)

            if clean_fvgs:
                bearishes = []
                bullishes = []
                for fvg in clean_fvgs:
                    if fvg['type'] == "bearish": bearishes.append(fvg['low'])
                    if fvg['type'] == "bullish": bullishes.append(fvg['high'])

            bearishes.sort(reverse=True)
            bullishes.sort()

            if action == "SELL":
                for bullish in bullishes:
                    if self.budget.pips_from_diff(bullish - signal.entry_price) / signal.stop_loss_pips >= 5:
                        continue

                    if self.budget.pips_from_diff(bullish - signal.entry_price) / signal.stop_loss_pips < signal.take_profit_pips / signal.stop_loss_pips:
                        continue

                    signal.take_profit = bullish
                    _tp_moved = True
                    break

            if action == "BUY":
                for bearish in bearishes:
                    if self.budget.pips_from_diff(bearish - signal.entry_price) / signal.stop_loss_pips >= 5:
                        continue

                    if self.budget.pips_from_diff(bearish - signal.entry_price) / signal.stop_loss_pips < signal.take_profit_pips / signal.stop_loss_pips:
                        continue

                    signal.take_profit = bearish
                    _tp_moved = True
                    break
        
        # Commission amount
        commission = settings.get("trading.commission")
        use_offline_commission_manager = settings.get("strategies.two_hunters.flags.use_offline_commission_manager")
        use_large_slp_flag = settings.get("strategies.two_hunters.flags.use_large_slp_flag")
        use_2R_for_EUR = settings.get("strategies.two_hunters.flags.use_2r_for_eur")
        onhand_lot_size = self.budget.lots_from_diff(signal.symbol, abs(signal.entry_price - signal.stop_loss))

        if not use_offline_commission_manager:
            signal.entry_lot = onhand_lot_size
        else:
            commission_amount = onhand_lot_size * commission
            risk_dollars = self.budget.risk_amount() - commission_amount
            signal.entry_lot = self.budget.lots_from_diff_and_risk_amount(signal.symbol, abs(signal.entry_price - signal.stop_loss), risk_dollars)

        if use_2R_for_EUR and signal.symbol == "EURUSD.":
            if signal.is_buy:
                _2r_top = signal.entry_price + abs(signal.entry_price - signal.stop_loss) * 2
                signal.initial_take_profit = _2r_top
                signal.take_profit = _2r_top
                signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))
                
            if signal.is_sell:
                _2r_top = signal.entry_price - abs(signal.entry_price - signal.stop_loss) * 2
                signal.initial_take_profit = _2r_top
                signal.take_profit = _2r_top
                signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))

        if use_large_slp_flag and self.breakout_engine.type == BreakoutType.DEFAULT:
            magic_number = settings.get("strategies.two_hunters.flags.large_slp_magic_number")
            condition = signal.stop_loss_pips >= magic_number

            if condition:
                if signal.is_buy:
                    _2r_top = signal.entry_price + abs(signal.entry_price - signal.stop_loss) * 2
                    signal.initial_take_profit = _2r_top
                    signal.take_profit = _2r_top
                    signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))
                    
                if signal.is_sell:
                    _2r_top = signal.entry_price - abs(signal.entry_price - signal.stop_loss) * 2
                    signal.initial_take_profit = _2r_top
                    signal.take_profit = _2r_top
                    signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))

        _r = abs(signal.entry_price - signal.stop_loss)
        
        signal.entry_lot = self.budget.lots_from_diff(signal.symbol, _r)
        # signal.entry_lot = 1.0
        signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))
        signal.stop_loss_pips = self.budget.pips_from_diff(_r)

        commission_diff = 0
        # commission_amount = signal.entry_lot * commission
        # commission_diff = self.budget.diff_from_pips(commission_amount / 10)

        # while commission_diff / _r >= 0.3:
        #     commission_diff /= 2

        if self.breakout_engine.type == BreakoutType.CUSTOM:
            if action == "BUY":  signal.initial_take_profit = signal.entry_price + (abs(signal.entry_price - signal.stop_loss) * 1.0) + commission_diff
            if action == "SELL": signal.initial_take_profit = signal.entry_price - (abs(signal.entry_price - signal.stop_loss) * 1.0) - commission_diff

        # Log signal generation
        log_signal_event(
            "main_signal_generated", self.symbol, action_enum.value,
            entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit,
            lot_size=signal.entry_lot, timestamp=signal_bar.timestamp,
            system_hours_check=True, trading_session_check=True
        )
        
        # Update counter
        self.signal_counter[self.symbol] += 1

        return signal

    def backtest(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        output_dir: Optional[str] = None,
        **args
    ) -> Dict[str, Any]:
        """Run backtesting on historical data with integrated plotting"""
        logger = TradingLogger.get_backtest_logger()
        import click

        fetcher = DataFetcher()

        logger.info(f"Starting backtest: {symbols} from {start_date} to {end_date}")
        
        log_system_event("backtest_started", 
                        symbols=symbols, 
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        initial_balance=self.budget.initial_balance)
        
        results = {}
        for symbol in symbols:
            results[symbol] = []

        click.echo(f"Detecting FVGs...")
        # self.fvg_detector.clear_cache()
        # self.fvg_detector.symbols = symbols
        # self.fvg_detector.timeframes = ["H8", "M15"]
        # self.fvg_detector.detect(start_date - timedelta(days=60), end_date)  # TODO: move to config
        self.fvg_detector.load_fvgs_from_cache()
        click.echo(f"FVGs Detected.")

        try:
            # Fetch historical data
            self.logger.info(f"Fetching data for {symbols} from {start_date} to {end_date}")

            # Process day by day
            current_date = start_date
            signals = []
            days_processed = 0
            bars_processed = 0
            while current_date < end_date:
                if current_date.weekday() >= 5:
                    current_date += timedelta(days=1)
                    continue
                
                current_date_start = datetime.combine(current_date.date(), self.mbox_time[0])
                current_date_end = datetime.combine(current_date.date(), self.session_time[1])

                for symbol in symbols:
                    daily_bars = fetcher.fetch_bars_from_mt5(current_date_start, current_date_end, symbol)
                    bars_processed += len(daily_bars)

                    self.budget.calculate_pip_size(symbol)
                    self.budget.calculate_lot_size(symbol)

                    if daily_bars:
                        self.symbol = symbol
                        self.add_bars(daily_bars)
                        main_signal = self.attempt_signal(current_date)

                        if main_signal:
                            main_signal.evaluate_signal(budget=self.budget)
                            if main_signal.is_completed:
                                results[symbol].append(main_signal)
                                signals.append(main_signal)
                                if self.check_strategy_flags(main_signal):
                                    self.budget.apply_signal_gain(main_signal)

                                    self.logger.debug(f"Main signal completed: {main_signal.outcome.value}, "
                                                    f"Gain: {main_signal.gain}")
                                    
                                recovery_signal = self.attempt_signal(current_date, failed_signal=main_signal)
                                
                                if recovery_signal:
                                    recovery_signal.evaluate_signal(budget=self.budget)
                                    if recovery_signal.is_completed:
                                        results[symbol].append(recovery_signal)
                                        signals.append(recovery_signal)
                                        if self.check_strategy_flags(recovery_signal):
                                            self.budget.apply_signal_gain(recovery_signal)

                                            self.logger.debug(f"Recovery signal completed: "
                                                            f"{recovery_signal.outcome.value}, "
                                                            f"Gain: {recovery_signal.gain}")

                days_processed += 1
                current_date += timedelta(days=1)
                commission_loss = sum([s.commission for s in signals if not s.used_flag])
                click.echo(f"Date: {current_date.date()} --> Running Balance: {round(self.budget.current_balance)}$ - Commission paid: {round(commission_loss)}$ <--")
            
            # Evaluate prop status
            self.budget.evaluate_prop_status(signals)

            results["all"] = {
                    'signals': signals,
                    'budget': self.budget,
                    'bars_processed': bars_processed,
                    'days_processed': days_processed
                }
            
            log_system_event("backtest_completed", 
                            symbols=symbols,
                            total_signals=len(signals),
                            overall_profit=self.budget.current_balance)

            click.echo("Results gathered.")

            try:
                # Initialize plotter
                report_dir = output_dir or "reports"

                # Import ReportGenerator here to avoid circular imports
                from src.core.reporting.report_generator import ReportGenerator
                args['dispaly_timeframe'] = 'M1'
                args['display_range'] = 'monthly'
                
                report_gen = ReportGenerator(report_dir)
                report_gen.generate_reports(
                    symbols=symbols,
                    date_range=(start_date, end_date),
                    results=results,
                    flags=args
                )

            except Exception as e:
                import sys, traceback
                tb = traceback.extract_tb(sys.exc_info()[2])[-1]
                filename = tb.filename
                lineno = tb.lineno

                logger.error(f"Error generating reports: {e} (File: {filename}, line {lineno})")
            
            return results
        
        except Exception as e:
            log_system_event("backtest_error", error=str(e))
            raise


    def live_worker(self, stop_event: threading.Event, mt5_conn: MT5Connection, signals_file_lock: threading.Lock):

        import json, time
        from datetime import datetime, timedelta, timezone
        from src.core.data.fetcher import DataFetcher
        from src.core.models.signal import Signal, SignalType
        from src.core.utils.logger import TradingLogger

        logger    = TradingLogger.get_main_logger()
        BROKER_TZ = timezone(timedelta(hours=6, minutes=30))
        fetcher   = DataFetcher()

        signals_dir  = settings.get("paths.signals")
        signals_file = f"{signals_dir}/{datetime.now(BROKER_TZ).strftime('%Y-%m-%d')}.json"

        # ── JSON helpers ──────────────────────────────────────────────

        def _read_file():
            """Read raw JSON from disk – always called inside the lock."""
            try:
                with open(signals_file, "r") as f:
                    return json.load(f)
            except Exception:
                return {}

        def load_signals():
            with signals_file_lock:
                return _read_file()

        def save_signal(signal):
            with signals_file_lock:
                data = _read_file()           # read while already holding the lock
                existing = [
                    s for s in data.get(self.symbol, [])
                    if s.get("ticket") != signal.ticket
                ]
                existing.append(signal.to_dict())
                data[self.symbol] = existing
                with open(signals_file, "w") as f:
                    json.dump(data, f, indent=2)

        def signal_exists(signal):
            """True if a signal with matching levels is already on disk."""
            for s in load_signals().get(self.symbol, []):
                if (
                    s["entry_price"] == signal.entry_price and
                    s["stop_loss"]   == signal.stop_loss   and
                    s["take_profit"] == signal.take_profit
                ):
                    return True
            return False

        # ── bootstrap bars ────────────────────────────────────────────

        self.all_bars = fetcher.get_latest_bars(self.symbol, count=800)

        # ── restore today's signals from disk (restart guard) ─────────

        active_main_signal     = None
        active_recovery_signal = None

        for s in load_signals().get(self.symbol, []):
            sig = Signal.from_dict(s)
            if sig.signal_type == SignalType.MAIN and active_main_signal is None:
                active_main_signal = sig
                logger.info(f"{self.symbol} restored main signal (ticket {sig.ticket})")
            elif sig.signal_type == SignalType.RECOVERY and active_recovery_signal is None:
                active_recovery_signal = sig
                logger.info(f"{self.symbol} restored recovery signal (ticket {sig.ticket})")

        # ── small helpers ─────────────────────────────────────────────

        def fetch_and_append():
            latest = fetcher.get_latest_bars(self.symbol, count=2)
            if latest and len(latest) >= 2:
                completed_bar = latest[0]  # older bar = completed
                if completed_bar.timestamp > self.all_bars[-1].timestamp:
                    self.all_bars.append(completed_bar)
                    logger.info(f"{self.symbol} new bar {completed_bar.timestamp}")

        def place(signal):
            """Place a signal unless it is already on disk, return it or None.
            Retries placement for up to 60 seconds on failure."""
            if signal is None:
                return None
            if signal_exists(signal):
                logger.info(f"{self.symbol} duplicate signal – skipping placement")
                return signal          # already placed before restart

            deadline = (signal.timestamp + timedelta(seconds=60)).replace(tzinfo=BROKER_TZ)
            attempt  = 0
            while datetime.now(BROKER_TZ) < deadline and not stop_event.is_set():
                attempt += 1
                placed = (
                    mt5_conn.place_pending_order(signal)
                    if signal.is_order
                    else mt5_conn.place_market_order(signal)
                )
                if placed:
                    save_signal(signal)
                    if attempt > 1:
                        logger.info(f"{self.symbol} signal placed after {attempt} attempts")
                    return signal

                remaining = max(0, deadline - datetime.now(BROKER_TZ))
                logger.warning(
                    f"{self.symbol} placement attempt {attempt} failed – "
                    f"retrying ({remaining:.0f}s remaining)"
                )
                time.sleep(1)

            timeout = (datetime.now(BROKER_TZ) - deadline).total_seconds() // 60
            logger.error(f"{self.symbol} signal placement failed after {attempt} attempts ({timeout:.0f}-min timeout)")
            return None

        def print_signal_status(sig, label):
            """Print a one-line live status for the active signal."""
            order_data = mt5_conn.get_open_order(sig)
            ts = datetime.now(BROKER_TZ).strftime("%H:%M:%S")
            if order_data:
                profit_str = (
                    f"  Profit: ${order_data['profit']:.2f}"
                    if order_data.get("profit") is not None
                    else "  (pending order)"
                )
                print(
                    f"[{ts}] {self.symbol} {label} | "
                    f"Lots={sig.entry_lot} | "
                    f"{sig.action.value} @ {sig.entry_price:.5f} | "
                    f"SL={sig.stop_loss_pips:.1f}  TP={sig.take_profit_pips:.1f}"
                    f"{profit_str}"
                )

        def monitor_loop(sig, label):
            """
            Block here, printing status every second, until the signal
            closes or the stop_event fires.  Saves to disk each tick.
            """
            while not stop_event.is_set():
                fetch_and_append()
                sig = mt5_conn.monitor_signal(sig)
                if label == "RECOVERY" and sig.gain >= sig.entry_lot * sig.stop_loss_pips and sig.sl_adjusted_count == 0:
                    sig.sl_adjusted_count += 1
                    mt5_conn.update_order(sig, - sig.entry_lot / 2)
                save_signal(sig)
                print_signal_status(sig, label)
                if sig.is_completed:
                    ts = datetime.now(BROKER_TZ).strftime("%H:%M:%S")
                    print(
                        f"[{ts}] {self.symbol} {label} CLOSED | "
                        f"outcome={sig.outcome.value.upper()} | "
                        f"gain=${sig.gain:.2f}"
                    )
                    return
                time.sleep(1)


        # ── MAIN LOOP ─────────────────────────────────────────────────
        while not stop_event.is_set():
            try:
                fetch_and_append()

                # ── hunt for main signal ──────────────────────────────
                if active_main_signal is None:

                    signal = self.attempt_signal(target_date=datetime.now(BROKER_TZ))

                    if signal:
                        active_main_signal = place(signal)
                        if active_main_signal:
                            logger.info(f"{self.symbol} main signal placed")

                # ── monitor main until it closes ──────────────────────
                if active_main_signal:

                    monitor_loop(active_main_signal, label="MAIN")

                    if active_main_signal.is_completed:

                        rec = self.attempt_signal(
                            target_date=datetime.now(BROKER_TZ),
                            failed_signal=active_main_signal
                        )

                        active_recovery_signal = place(rec)
                        
                        if active_recovery_signal:
                            logger.info(f"{self.symbol} recovery signal placed")


                # ── monitor recovery until it closes ──────────────────
                if active_recovery_signal:

                    monitor_loop(active_recovery_signal, label="RECOVERY")

                    if active_recovery_signal.is_completed:
                        logger.info(
                            f"{self.symbol} recovery completed: "
                            f"{active_recovery_signal.outcome}"
                        )

                time.sleep(1)

            except Exception:
                import traceback
                logger.error(f"{self.symbol} worker error:\n{traceback.format_exc()}")
                time.sleep(5)

        logger.info(f"{self.symbol} worker stopped")