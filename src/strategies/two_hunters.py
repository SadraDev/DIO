import threading

from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict

from src.strategies.base import BaseStrategy
from src.core.models.signal import Signal, SignalAction, SignalType
from src.core.models.bar import Bar
from src.core.models.budget import Budget
from src.indicators.breakout import BreakoutEngine
from src.indicators.mbox import MBoxAnalyzer
from src.indicators.choch import FakeCHoCHDetector
from src.core.utils.logger import TradingLogger, log_signal_event
from config.settings import settings


class TwoHuntersStrategy(BaseStrategy):
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
    
    def __init__(self, name: str = "Two-Hunters"):
        # Load strategy configuration
        self.config = settings.get_strategy_config("two_hunters")
        
        self._state_lock = threading.Lock()

        # Initialize indicators
        self._init_indicators()

        # Initialize budget
        self.budget = Budget()
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
        # print(self.all_bars[0].timestamp)
        
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
        with self._state_lock:
            self.all_bars = []
            self.all_bars.extend(bars)
            max_bars = settings.get("data.max_bars_memory", 720)
        
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
            with self._state_lock:
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
