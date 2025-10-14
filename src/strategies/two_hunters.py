import asyncio
import threading
import json
import time as goodtimes
from datetime import datetime, timedelta, time, date
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import signal as os_signal
from collections import defaultdict

from src.core.models.signal import Signal, SignalAction, SignalType, SignalOutcome
from src.core.models.bar import Bar
from src.core.models.budget import Budget
from src.indicators.breakout import BreakoutEngine
from src.indicators.mbox import MBoxAnalyzer
from src.indicators.choch import FakeCHoCHDetector
from src.core.execution.mt5_connection import MT5Connection
from src.core.data.fetcher import DataFetcher
from src.core.utils.logger import TradingLogger, log_signal_event, log_system_event, log_order_event
from config.settings import settings

class TwoHuntersStrategy():
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
    
    def __init__(self, name: str = "Two-Hunters", budget: Budget = None):
        # Load strategy configuration
        self.config = settings.get_strategy_config("two_hunters")

        # Initialize indicators
        self._init_indicators()

        # Initialize budget
        self.budget = Budget() if budget is None else budget
        self.name = name

        # Symbol
        self.symbol: str = None

        # Strategy state
        self.signal_counter = defaultdict(int)  # Signals per symbol per day
        self.all_bars = []  # Store recent bars for analysis
        self.fake_chochs = []  # Store detected fake CHoCH patterns
        
        # SESSION HOURS - When trading analysis happens
        self.mbox_time = self._get_mbox_time()
        self.session_time = self._get_session_time()
        
        # Strategy parameters (from config)
        self.max_signals_per_symbol = settings.max_signals_per_symbol
        self.margin_pips = self.config.get("margin_pips", 0.05)
        self.fvg_range = (
            self.config.get("fvg", {}).get("min_size_pips", 1.0),
            self.config.get("fvg", {}).get("max_size_pips", 3.0)
        )
        self.ratios = self.config.get("ratios", {"stop_loss": 1.0, "take_profit": 3.0})
        
        # Feature flags (from config)  
        flags = self.config.get("flags", {})
        self.use_trading_hours = flags.get("use_trading_hours", False)
        self.use_all_flags = flags.get("use_all_flags", False)
        self.use_trend_flag = flags.get("use_trend_flag", False)
        self.use_time_flag = flags.get("use_time_flag", False)
        self.use_choch_flag = flags.get("use_choch_flag", False)
        
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
        
        # Fake CHoCH Detector
        choch_config = self.config.get("choch", {})
        self.fake_choch_detector = FakeCHoCHDetector(
            window=choch_config.get("window", 15),
            tolerance=choch_config.get("tolerance", 5),
            buffer=choch_config.get("buffer", 0.0000001),
            intensity=choch_config.get("intensity", 3.0),
            use_volume=choch_config.get("use_volume", False),
            single_hit=choch_config.get("single_hit", True),
            volume_factor=choch_config.get("volume_factor", 1.2)
        )
    
    def _get_mbox_time(self) -> Tuple[time, time]:
        """Get session hours from config"""
        mbox_time_config = settings.get("strategies.two_hunters.mbox_time", {})
        
        start_time = datetime.strptime(mbox_time_config["start"], "%H:%M").time()
        end_time = datetime.strptime(mbox_time_config["end"], "%H:%M").time()
        return (start_time, end_time)
    
    def _get_session_time(self) -> Tuple[time, time]:
        """Get trading session hours from config"""
        session_time_config = settings.get("strategies.two_hunters.session_time", {})

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
        loss_margin = self.budget.diff_from_pips(self.margin_pips)
        
        # Fair Value Gap (FVG) logic
        min_fvg, max_fvg = self.fvg_range
        
        def dynamic_fvg_scale(fvg_size_pips: float) -> float:
            """Calculate dynamic scale based on FVG size"""
            if fvg_size_pips <= min_fvg:
                return 1.0
            elif fvg_size_pips >= max_fvg:
                return 0.5
            return 1.0 - (fvg_size_pips * 0.5) / max_fvg
        
        if action == SignalAction.SELL:
            if before_bar.low > after_bar.high:
                fvg_size_pips = self.budget.pips_from_diff(before_bar.low - after_bar.high)
                scale = dynamic_fvg_scale(fvg_size_pips)
                entry_price = before_bar.low - (before_bar.low - after_bar.high)
                
                self.logger.debug(f"SELL FVG: size={fvg_size_pips:.1f} pips, scale={scale:.2f} -- NOT USED --")
            
            stop_loss = self.ratios["stop_loss"] * (extrema + loss_margin)
            take_profit = entry_price - self.ratios["take_profit"] * abs(entry_price - stop_loss)
        
        elif action == SignalAction.BUY:
            # Check for bullish FVG  
            if after_bar.low > before_bar.high:
                fvg_size_pips = self.budget.pips_from_diff(after_bar.low - before_bar.high)
                scale = dynamic_fvg_scale(fvg_size_pips)
                entry_price = before_bar.high + (after_bar.low - before_bar.high)
                
                self.logger.debug(f"BUY FVG: size={fvg_size_pips:.1f} pips, scale={scale:.2f} -- NOT USED --")
            
            stop_loss = self.ratios["stop_loss"] * (extrema - loss_margin)
            take_profit = entry_price + self.ratios["take_profit"] * abs(entry_price - stop_loss)
        
        self.logger.debug(f"Entry calculation: EP={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
        return entry_price, stop_loss, take_profit
    
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
            self.logger.debug(f"Signal rejected by flags: {violations}")
            return False
        
        return True
    
    def attempt_signal(self, target_date: datetime, faild_signal: Signal = None) -> Optional[Signal]:
        """Attempt to generate main signal for the given date"""

        # Get required bars
        mbox_bars = self.get_mbox_bars(target_date)
        session_bars = self.get_session_bars(target_date)
        
        if not mbox_bars or len(session_bars) < 5:
            self.logger.debug(f"Insufficient bars: MBox={len(mbox_bars)}, Session={len(session_bars)}")
            return None
        
        # Analyze MBox for market bias
        mbox_result = self.mbox_analyzer.calculate(mbox_bars)

        # Hunt for breakout
        if faild_signal is None:
            self.breakout_engine.num_hunt = self.config.get("breakout.num_hunt_main", 2)
            extrema, signal_bar, action, hunter_bar, _ = self.breakout_engine.calculate(
                session_bars, mbox_result
            )
        else:
            self.breakout_engine.num_hunt = self.config.get("breakout.num_hunt_recovery", 1)
            mbox_bars.extend([bar for bar in session_bars if bar.timestamp <= faild_signal.outcome_timestamp])
            mbox_result = self.mbox_analyzer.calculate(mbox_bars)
            
            recovery_bars = [bar for bar in session_bars if bar.timestamp > faild_signal.outcome_timestamp]

            extrema, signal_bar, action, hunter_bar, _ = self.breakout_engine.calculate(
                recovery_bars, mbox_result
            )


        if not signal_bar:
            self.logger.debug("No breakout signal found")
            return None
        
        # Convert string action to enum
        action_enum = SignalAction.SELL if action == "SELL" else SignalAction.BUY

        # Calculate entry details
        entry_price, stop_loss, take_profit = self.calculate_entry_details(
            action_enum, signal_bar, extrema
        )
        
        # Create signal
        signal = self.create_signal(
            action_enum, entry_price, stop_loss, take_profit,
            signal_bar.timestamp, SignalType.MAIN
        )
        
        if not signal:
            return None
        
        # Set strategy flags
        if faild_signal is None:
            signal.trend = mbox_result.get("trend", False)
            signal.fake_CHoCH = self.detect_fake_choch(mbox_bars, session_bars, hunter_bar)
            signal.time_flag = mbox_result.get("extrema_flag", False)
        else:
            signal.trend = faild_signal.trend
            signal.fake_CHoCH = faild_signal.fake_CHoCH
            signal.time_flag = faild_signal.time_flag
            signal.is_main = faild_signal.is_main

        # Check strategy flags
        if not self.check_strategy_flags(signal):
            return None
        
        # Initialize trading parameters
        self.budget.update_risk_percent(signal)
        signal.stop_loss_pips = self.budget.pips_from_diff(abs(signal.entry_price - signal.stop_loss))
        signal.take_profit_pips = self.budget.pips_from_diff(abs(signal.take_profit - signal.entry_price))
        signal.entry_lot = self.budget.lots_from_diff(signal.symbol, abs(signal.entry_price - signal.stop_loss))
        
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
    
    def reset_daily_state(self):
        """Reset daily state for new trading day"""
        self.signal_counter.clear()
        self.fake_chochs.clear()
        # Keep recent bars but clear old ones
        cutoff = datetime.now() - timedelta(days=2)
        self.all_bars = [bar for bar in self.all_bars if bar.timestamp > cutoff]
        
        self.logger.info(f"Daily state reset for {self.symbol}")
    
    def get_fake_chochs(self) -> List[Dict[str, Any]]:
        """Get detected fake CHoCH patterns"""
        return self.fake_chochs.copy()
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """Get strategy configuration and state information"""
        return {
            "name": "Two-Hunters",
            "symbol": self.symbol,
            "config": self.config,
            "system_hours": {
                "start": self.system_hours[0].strftime("%H:%M"),
                "end": self.system_hours[1].strftime("%H:%M")
            },
            "mbox_hours": {
                "start": self.mbox_time[0].strftime("%H:%M"),
                "end": self.mbox_time[1].strftime("%H:%M")
            },
            "trading_session_time": [
                {
                    "start": start.strftime("%H:%M"),
                    "end": end.strftime("%H:%M")
                }
                for start, end in self.session_time
            ],
            "signal_counts": dict(self.signal_counter),
            "bars_count": len(self.all_bars),
            "fake_chochs_count": len(self.fake_chochs),
            "flags": {
                "use_trading_hours": self.use_trading_hours,
                "use_all_flags": self.use_all_flags,
                "use_trend_flag": self.use_trend_flag,
                "use_time_flag": self.use_time_flag,
                "use_choch_flag": self.use_choch_flag
            }
        }

    def backtest(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Run backtesting on historical data with integrated plotting"""
        logger = TradingLogger.get_backtest_logger()
        from src.core.utils.plotter import TradingPlotter
        from src.core.data.fetcher import DataFetcher

        fetcher = DataFetcher()

        logger.info(f"Starting backtest: {symbols} from {start_date} to {end_date}")
        
        log_system_event("backtest_started", 
                        symbols=symbols, 
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        initial_balance=initial_balance)
        
        results = {}
        for symbol in symbols:
            results[symbol] = []

        try:
            # Fetch historical data
            self.logger.info(f"Fetching data for {symbols} from {start_date} to {end_date}")

            # Process day by day
            current_date = start_date
            signals = []
            days_processed = 0
            bars_processed = 0
            while current_date <= end_date:
                current_date_start = datetime(current_date.year, current_date.month, current_date.day, hour=0, minute=0)
                current_date_end = datetime(current_date.year, current_date.month, current_date.day, hour=23, minute=59)

                for symbol in symbols:
                    daily_bars = fetcher.fetch_bars_from_mt5(current_date_start, current_date_end, symbol)
                    bars_processed += len(daily_bars)
                   
                    if daily_bars:
                        self.symbol = symbol
                        self.add_bars(daily_bars)
                        main_signal = self.attempt_signal(current_date)
                        
                        if main_signal:
                            main_signal.evaluate_signal()
                            
                            if main_signal.is_completed:
                                results[symbol].append(main_signal)
                                signals.append(main_signal)
                                self.budget.apply_signal_gain(main_signal)
                                
                                self.logger.debug(f"Main signal completed: {main_signal.outcome.value}, "
                                                f"Gain: {main_signal.gain}")
                                
                                if main_signal.outcome.value == 'loss':
                                    
                                    recovery_signal = self.attempt_signal(current_date, faild_signal=main_signal)
                                    
                                    if recovery_signal:
                                        recovery_signal.evaluate_signal()
                                        
                                        if recovery_signal.is_completed:
                                            results[symbol].append(recovery_signal)
                                            signals.append(recovery_signal)
                                            self.budget.apply_signal_gain(recovery_signal)
                                            
                                            self.logger.debug(f"Recovery signal completed: "
                                                            f"{recovery_signal.outcome.value}, "
                                                            f"Gain: {recovery_signal.gain}")
                        
                days_processed += 1
                current_date += timedelta(days=1)
            
            # Evaluate prop status
            self.budget.evaluate_prop_status(signals)

            results["all"] = {
                    'signals': signals,
                    'budget': self.budget,
                    'bars_processed': bars_processed,
                    'days_processed': days_processed
                }

            # Generate summary
            overall_summary = self._generate_overall_summary(results)
            results['_summary'] = overall_summary
            
            log_system_event("backtest_completed", 
                            symbols=symbols,
                            total_signals=overall_summary.get('total_signals', 0),
                            overall_profit=overall_summary.get('total_profit', 0))

            # Integrated plotting functionality
            logger.info("Generating plots and reports...")
            
            try:
                # Initialize plotter
                report_dir = output_dir or "reports"
                plotter = TradingPlotter(report_dir=report_dir)
                fetcher = DataFetcher()
                
                all_charts = []
                bars_data = {}
                signals_data = {}
                
                for symbol in symbols:
                    try:
                        logger.info(f"Generating chart for {symbol}")
                        
                        # Get backtest results for this symbol
                        signals = results.get(f"{symbol}.signals", {})
                        
                        # Fetch bars (same data used in backtest)
                        bars = fetcher.fetch_bars_from_mt5(start_date, end_date, symbol)
                        if not bars:
                            logger.warning(f"No data found for {symbol}")
                            continue
                        
                        # Store data for comprehensive report
                        bars_data[symbol] = bars
                        if signals:
                            signals_data[symbol] = signals
                        
                        # Generate interactive chart with actual signals from backtest
                        chart_path = plotter.plot_candlestick_interactive(
                            bars=bars,
                            signals=signals if True else None,
                            symbol=symbol,
                            title=f"{symbol} Backtest Analysis ({start_date.date()} to {end_date.date()})"
                        )
                        all_charts.append(chart_path)
                        
                        logger.info(f"Chart created for {symbol}: {chart_path}")
                        
                    except Exception as e:
                        logger.error(f"Error creating chart for {symbol}: {e}")
                
                # Generate comprehensive reports if requested
                try:
                    # Import ReportGenerator here to avoid circular imports
                    from src.core.reporting.report_generator import ReportGenerator
                    
                    report_gen = ReportGenerator(report_dir)
                    report_path = report_gen.generate_full_trading_report(
                        symbols=symbols,
                        bars_data=bars_data,
                        results=results,
                        report_title=f"Backtest Report: {start_date.date()} to {end_date.date()}"
                    )
                    
                    logger.info(f"Comprehensive report generated: {report_path}")
                    
                except Exception as e:
                    import sys, traceback
                    tb = traceback.extract_tb(sys.exc_info()[2])[-1]
                    filename = tb.filename
                    lineno = tb.lineno

                    logger.error(f"Error generating comprehensive report: {e} (File: {filename}, line {lineno})")
            
                # Update results with plotting information
                results['plotting'] = {
                    'charts': all_charts,
                    'report_directory': report_dir,
                    'symbols_plotted': len([s for s in symbols if s in bars_data])
                }

                logger.info(f"Plotting completed. Generated {len(all_charts)} charts.")
                
            except Exception as e:
                logger.error(f"Error in plotting integration: {e}")
                # Don't fail the entire backtest if plotting fails
            
            return results
        
        except Exception as e:
            log_system_event("backtest_error", error=str(e))
            raise

    def live(self, symbols):
        threads = []
        for symbol in symbols:
            try:
                twohunters = TwoHuntersStrategy()
                
                twohunters.budget = self.budget
                twohunters.symbol = symbol

                thread = threading.Thread(
                    target=twohunters.run_live_for_symbol,
                )

                threads.append(thread)
                thread.start()

            except Exception as e:
                self.logger.error(f"Error craeting thread for {symbol}: {e}")

    def run_live_for_symbol(self):
        """
        Live trading implementation with two states: sleeping and active trading
        
        States:
        1. Sleeping State: Monitor system time, wait for trading hours
        2. Live Trading State: Execute strategy during system hours
        """

        # Initialize components
        mt5_conn = MT5Connection()
        
        # Get system hours from config
        start_time_str = settings.get("strategies.two_hunters.live_trading.system_hours.start")
        end_time_str = settings.get("strategies.two_hunters.live_trading.system_hours.end")
        
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()
        
        # Work interval from config
        work_interval = settings.get("strategies.two_hunters.live_trading.work_interval", 1)
        
        # Daily signals file path
        signals_dir = Path("reports/signals")
        signals_dir.mkdir(exist_ok=True)
        
        self.logger.info("Live trading started")
        self.logger.info(f"System hours: {start_time_str} - {end_time_str}")
        
        try:
            while True:
                current_time = datetime.now().time()
                current_date = date.today()
                
                # Check if we're within system hours
                if start_time <= current_time <= end_time:
                    # LIVE TRADING STATE
                    self.logger.info("Entering live trading state")
                    
                    # Initialize daily signals file
                    daily_signals_file = signals_dir / f"signals_{current_date.strftime('%Y%m%d')}.json"
                    processed_signals = self._load_daily_signals(daily_signals_file)
                    
                    try:
                        self._execute_live_trading_for_symbol(
                            current_date,
                            daily_signals_file,
                            processed_signals
                        )
                    
                    except Exception as e:
                        self.logger.error(f"Error trading {self.symbol}: {e}")
                        continue
                    
                    # Sleep for work interval
                    goodtimes.sleep(work_interval)
                    
                else:
                    # SLEEPING STATE
                    if current_time < start_time:
                        wait_time = datetime.combine(current_date, start_time) - datetime.now()
                    else:  # current_time > end_time
                        # Wait until next day's start time
                        next_day = current_date + timedelta(days=1)
                        wait_time = datetime.combine(next_day, start_time) - datetime.now()
                    
                    wait_seconds = max(60, wait_time.total_seconds())  # Minimum 1 minute wait
                    self.logger.info(f"Sleeping state - waiting {wait_seconds/60:.1f} minutes until trading hours")
                    goodtimes.sleep(min(wait_seconds, 300))  # Max 5 minute sleep intervals
                    
        except KeyboardInterrupt:
            self.logger.info("Live trading interrupted by user")
        except Exception as e:
            self.logger.error(f"Critical error in live trading: {e}")
            raise

    def _execute_live_trading_for_symbol(self, current_date: date, daily_signals_file: Path, processed_signals: dict):
        """Execute live trading logic for a specific symbol"""
        
        symbol = self.symbol
        signal_key = f"{symbol}_{current_date.strftime('%Y%m%d')}"
        rec_signal_key = f"{symbol}_{current_date.strftime('%Y%m%d')}_rec"

        mt5_conn = MT5Connection()
        data_fetcher = DataFetcher()

        # Fetch latest bars
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=12)  # Get enough data for analysis
        
        new_bars = data_fetcher.fetch_bars_from_mt5(start_time, end_time, symbol)
        
        if not new_bars:
            self.logger.warning(f"No bars fetched for {symbol}")
            return
        
        # Update strategy bars
        self.all_bars = new_bars
        live_bar = self.all_bars.pop()

        # Check if we already have main signal for this symbol today
        if signal_key in processed_signals:
            existing_signal = processed_signals[signal_key]
            signal = self._reconstruct_signal_from_dict(existing_signal)
        else:
            # Main signal generation
            signal = self.attempt_signal(datetime.now())
        
        if signal and not signal.is_completed and not mt5_conn.order_is_open(signal):
            if mt5_conn.place_order(signal):

                # Save signal to daily file
                processed_signals[signal_key] = signal.to_dict()
                self._save_daily_signals(daily_signals_file, processed_signals)
                
                self.logger.info(f"Signal generated and order placed for {symbol}: {signal}")
        
        if signal and mt5_conn.order_is_open(signal):
            risk_free_tiggered = signal.risk_free()

            if risk_free_tiggered:
                mt5_conn.update_order(signal)

                # Save signal to daily file
                processed_signals[signal_key] = signal.to_dict()
                self._save_daily_signals(daily_signals_file, processed_signals)
                
                self.logger.info(f"Signal SL/TP updated for {symbol}: {signal}")

        if signal and mt5_conn.check_order_status(signal):
            # Save signal to daily file
            processed_signals[signal_key] = signal.to_dict()
            self._save_daily_signals(daily_signals_file, processed_signals)
            
            self.logger.info(f"Signal concluded for {symbol}: {signal}")

            if signal.outcome.value == 'loss':
                # Check if we already have recovery signal for this symbol today
                if rec_signal_key in processed_signals:
                    existing_signal = processed_signals[rec_signal_key]
                    rec_signal = self._reconstruct_signal_from_dict(existing_signal)
                else:
                    # Reecovery signal generation
                    rec_signal = self.attempt_signal(datetime().now(), signal)

                if rec_signal and not rec_signal.is_completed and not mt5_conn.order_is_open(rec_signal):
                    if mt5_conn.place_order(rec_signal):

                        # Save signal to daily file
                        processed_signals[rec_signal_key] = rec_signal.to_dict()
                        self._save_daily_signals(daily_signals_file, processed_signals)
                        
                        self.logger.info(f"Recovery Signal generated and order placed for {symbol}: {rec_signal}")
                
                if rec_signal and mt5_conn.order_is_open(rec_signal):
                    risk_free_tiggered = rec_signal.risk_free()

                    if risk_free_tiggered:
                        mt5_conn.update_order(rec_signal)

                        # Save signal to daily file
                        processed_signals[rec_signal_key] = rec_signal.to_dict()
                        self._save_daily_signals(daily_signals_file, processed_signals)
                        
                        self.logger.info(f"Signal SL/TP updated for {symbol}: {signal}")
                    
                if rec_signal and mt5_conn.check_order_status(rec_signal):
                    # Save signal to daily file
                    processed_signals[rec_signal_key] = rec_signal.to_dict()
                    self._save_daily_signals(daily_signals_file, processed_signals)
                    
                    self.logger.info(f"Signal concluded for {symbol}: {rec_signal}")

                if rec_signal.is_completed and signal.is_completed:
                    try:
                        mt5_conn.shutdown_connection()
                    except:
                        pass
                    self.logger.info("Live trading stopped")

    def _load_daily_signals(self, signals_file: Path) -> dict:
        """Load daily signals from JSON file"""
        
        if signals_file.exists():
            try:
                with open(signals_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"Error loading signals file: {e}")
        
        return {}

    def _save_daily_signals(self, signals_file: Path, signals: dict):
        """Save signals to daily JSON file"""
        
        try:
            with open(signals_file, 'w') as f:
                json.dump(signals, f, indent=2, default=str)
        except IOError as e:
            self.logger.error(f"Error saving signals file: {e}")

    def _reconstruct_signal_from_dict(self, signal_dict: dict):
        """Reconstruct Signal object from dictionary"""
        
        from src.core.models.signal import Signal, SignalAction, SignalType, SignalOutcome
        from datetime import datetime
        
        # Create basic signal
        signal = Signal(
            action=SignalAction(signal_dict['action']),
            entry_price=signal_dict['entry_price'],
            stop_loss=signal_dict['stop_loss'],
            take_profit=signal_dict['take_profit'],
            symbol=signal_dict['symbol'],
            timestamp=datetime.fromisoformat(signal_dict['timestamp']),
            signal_type=SignalType(signal_dict.get('signaltype', 'main'))
        )
        
        # Set additional attributes
        signal.ticket = signal_dict.get('ticket')
        signal.entry_lot = signal_dict.get('entry_lot')
        signal.gain = signal_dict.get('gain')
        
        # Set outcome if exists
        if signal_dict.get('outcome'):
            signal.outcome = SignalOutcome(signal_dict['outcome'])
            if signal_dict.get('outcome_timestamp'):
                signal.outcome_timestamp = datetime.fromisoformat(signal_dict['outcome_timestamp'])
        
        return signal

