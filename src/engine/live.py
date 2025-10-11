import time
import threading
from datetime import datetime, timedelta, time as datetime_time
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.core.models.signal import Signal, SignalOutcome
from src.core.models.bar import Bar
from src.core.models.budget import Budget
from src.core.data.fetcher import DataFetcher
from src.core.execution.mt5_connection import MT5Connection
from src.strategies.manager import StrategyManager
from src.core.utils.logger import TradingLogger, log_system_event
from config.settings import settings


class LiveTradingEngine:
    """
    Live trading engine that manages real-time trading across multiple symbols
    Supports both system hours (when engine runs) and session hours (when trading happens)
    """
    
    def __init__(self, symbols: List[str], account_config: Dict = None):
        self.symbols = symbols
        self.account_config = account_config or {}
        
        # Core components
        self.logger = TradingLogger.get_trading_logger()
        self.connection = MT5Connection()
        self.data_fetcher = DataFetcher()
        self.strategy_manager = StrategyManager()
        
        # Trading state
        self.is_running = False
        self.active_signals: Dict[str, List[Signal]] = {symbol: [] for symbol in symbols}
        self.daily_budgets: Dict[str, Budget] = {}
        
        # Threading
        self.main_thread: Optional[threading.Thread] = None
        self.symbol_threads: Dict[str, threading.Thread] = {}
        self.shutdown_event = threading.Event()
        
        # Configuration - SYSTEM HOURS vs SESSION HOURS
        self.work_interval = settings.get('live_trading.work_interval', 1)  # seconds
        
        # SYSTEM HOURS - When the trading ENGINE should be running
        self.system_hours = self._get_system_hours()
        
        # SESSION HOURS - When trading analysis/signals should be generated
        self.trading_sessions = self._get_trading_sessions()
        
        self.logger.info(f"System Hours: {self.system_hours[0]} - {self.system_hours[1]}")
        self.logger.info(f"Trading Sessions: {self.trading_sessions}")
        
        # Initialize strategies for each symbol
        self._initialize_strategies()
    
    def _get_system_hours(self) -> Tuple[datetime_time, datetime_time]:
        """Get system operating hours from config"""
        system_config = settings.get('live_trading.system_hours', {
            'start': '09:30', 
            'end': '13:30'
        })
        
        start_time = datetime.strptime(system_config['start'], '%H:%M').time()
        end_time = datetime.strptime(system_config['end'], '%H:%M').time()
        
        return start_time, end_time
    
    def _get_trading_sessions(self) -> List[Tuple[datetime_time, datetime_time]]:
        """Get trading session hours from config"""
        sessions_config = settings.get("trading.sessions.two_hunters", {})
        sessions = []
        
        for session_name, session_data in sessions_config.items():
            start_time = datetime.strptime(session_data["start"], "%H:%M").time()
            end_time = datetime.strptime(session_data["end"], "%H:%M").time()
            sessions.append((start_time, end_time))
        
        return sessions
    
    def _parse_time(self, time_str: str) -> datetime_time:
        """Parse time string to time object"""
        return datetime.strptime(time_str, '%H:%M').time()
    
    def _initialize_strategies(self):
        """Initialize strategies for each symbol"""
        initial_balance = self.account_config.get('balance') or settings.initial_balance
        risk_percent = self.account_config.get('risk_percent') or settings.default_risk_percent
        
        for symbol in self.symbols:
            budget = Budget(initial_balance, risk_percent)
            self.daily_budgets[symbol] = budget
            self.strategy_manager.create_two_hunters_strategy(symbol, budget)
            
        self.logger.info(f"Initialized strategies for {len(self.symbols)} symbols")
    
    def is_system_time(self, current_time: datetime_time = None) -> bool:
        """Check if current time is within SYSTEM operating hours"""
        if current_time is None:
            current_time = datetime.now().time()
        
        start_time, end_time = self.system_hours
        return start_time <= current_time <= end_time
    
    # def is_trading_session(self, current_time: datetime_time = None) -> bool:
    #     """Check if current time is within any TRADING session"""
    #     if current_time is None:
    #         current_time = datetime.now().time()
        
    #     return any(
    #         start <= current_time <= end
    #         for start, end in self.trading_sessions
    #     )
    
    def sleep_until_system_start(self):
        """Sleep until system operating hours begin"""
        now = datetime.now()
        start_time = datetime.combine(now.date(), self.system_hours[0])
        
        if now > start_time:
            # System start time has passed today, wait until tomorrow
            start_time += timedelta(days=1)
        
        wait_seconds = (start_time - now).total_seconds()
        if wait_seconds > 0:
            self.logger.info(f"Sleeping {wait_seconds:.0f} seconds until system start at {start_time}")
            time.sleep(wait_seconds)
    
    def start_live_trading(self) -> bool:
        """Start live trading engine"""
        if self.is_running:
            self.logger.warning("Live trading is already running")
            return False
        
        # Check if we're in system operating hours
        if not self.is_system_time():
            self.logger.info("Outside system operating hours, waiting...")
            self.sleep_until_system_start()
        
        # Connect to MT5
        if not self._establish_connection():
            return False
        
        self.is_running = True
        self.shutdown_event.clear()
        
        # Start main trading thread
        self.main_thread = threading.Thread(target=self._main_trading_loop, daemon=True)
        self.main_thread.start()
        
        log_system_event("live_trading_started", 
                        symbols=self.symbols,
                        system_hours=f"{self.system_hours[0]}-{self.system_hours[1]}",
                        trading_sessions=len(self.trading_sessions))
        self.logger.info("🚀 Live trading engine started")
        return True
    
    def stop_live_trading(self):
        """Stop live trading engine"""
        if not self.is_running:
            return
        
        self.logger.info("Stopping live trading engine...")
        self.is_running = False
        self.shutdown_event.set()
        
        # Wait for threads to finish
        if self.main_thread and self.main_thread.is_alive():
            self.main_thread.join(timeout=10)
        
        for thread in self.symbol_threads.values():
            if thread.is_alive():
                thread.join(timeout=5)
        
        # Close connection
        self.connection.shutdown_connection()
        
        log_system_event("live_trading_stopped")
        self.logger.info("🛑 Live trading engine stopped")
    
    def _establish_connection(self) -> bool:
        """Establish MT5 connection"""
        if not self.connection.initialize_connection():
            self.logger.error("Failed to initialize MT5 connection")
            return False
        
        # Login with credentials if provided
        if all(key in self.account_config for key in ['account', 'password', 'server']):
            if not self.connection.login_with_credentials(
                self.account_config['account'],
                self.account_config['password'],
                self.account_config['server']
            ):
                self.logger.error("Failed to login to MT5 account")
                return False
        
        account_info = self.connection.get_account_info()
        if account_info:
            self.logger.info(f"Connected to account {account_info.login}, Balance: ${account_info.balance}")
            return True
        
        return False
    
    def _main_trading_loop(self):
        """Main trading loop with system hours and session hours management"""
        self.logger.info("Main trading loop started")
        
        while self.is_running and not self.shutdown_event.is_set():
            try:
                current_time = datetime.now().time()
                
                # First check: Are we in system operating hours?
                if not self.is_system_time(current_time):
                    self.logger.info("Outside system hours, engine going to sleep...")
                    self._handle_outside_system_hours()
                    continue
                
                # Second check: Are we in trading session?
                if self.is_trading_session(current_time):
                    self.logger.debug("In trading session - executing trading cycle")
                    self._execute_trading_cycle()
                else:
                    self.logger.debug("Outside trading sessions - monitoring only")
                    self._handle_outside_trading_sessions()
                
                time.sleep(self.work_interval)
                
            except Exception as e:
                self.logger.error(f"Error in main trading loop: {e}")
                time.sleep(5)  # Prevent rapid error loops
        
        self.logger.info("Main trading loop ended")
    
    def _handle_outside_system_hours(self):
        """Handle logic when outside system operating hours"""
        # Close any remaining positions if configured to do so
        self._emergency_position_check()
        
        # Sleep until system start time
        self.sleep_until_system_start()
    
    def _handle_outside_trading_sessions(self):
        """Handle logic when in system hours but outside trading sessions"""
        # Still monitor existing positions but don't generate new signals
        for symbol in self.symbols:
            active_signals = self.active_signals[symbol]
            
            for signal in active_signals:
                if signal.is_pending:
                    # Check status and apply risk management
                    self.connection.check_order_status(signal)
                    self._update_risk_free_management(signal)
        
        # Sleep longer when outside trading sessions
        time.sleep(min(30, self.work_interval * 10))
    
    def _execute_trading_cycle(self):
        """Execute one trading cycle for all symbols (only during trading sessions)"""
        try:
            # Update market data for all symbols
            self._update_market_data()
            
            # Process signals in parallel
            with ThreadPoolExecutor(max_workers=len(self.symbols)) as executor:
                futures = []
                
                for symbol in self.symbols:
                    future = executor.submit(self._process_symbol_safely, symbol)
                    futures.append((symbol, future))
                
                for symbol, future in futures:
                    try:
                        future.result(timeout=30)
                    except Exception as e:
                        self.logger.error(f"Error processing {symbol}: {e}")
        
        except Exception as e:
            self.logger.error(f"Critical error in trading cycle: {e}")

    def _process_symbol_safely(self, symbol: str):
        """Safe wrapper for symbol processing"""
        try:
            self._process_symbol(symbol)
        except Exception as e:
            self.logger.error(f"Error in symbol {symbol} processing: {e}")
    
    def _update_market_data(self):
        """Update market data for all symbols"""
        for symbol in self.symbols:
            try:
                # Get latest bars
                latest_bars = self.connection.get_last_bars(symbol, count=2)
                if latest_bars:
                    strategy = self.strategy_manager.get_strategy("TwoHunters", symbol)
                    if strategy:
                        strategy.add_bars(latest_bars)
            except Exception as e:
                self.logger.error(f"Error updating data for {symbol}: {e}")
    
    def _process_symbol(self, symbol: str):
        """Process trading logic for a single symbol (only during trading sessions)"""
        strategy = self.strategy_manager.get_strategy("TwoHunters", symbol)
        if not strategy:
            return
        
        active_signals = self.active_signals[symbol]
        
        # Check existing signals (always monitor)
        self._monitor_active_signals(symbol, active_signals, strategy)
        
        # Attempt new signals ONLY if we're in trading session and have capacity
        if (self.is_trading_session() and 
            len(active_signals) < settings.max_signals_per_symbol):
            self._attempt_new_signals(symbol, strategy)
    
    def _monitor_active_signals(self, symbol: str, signals: List[Signal], strategy):
        """Monitor and update active signals"""
        for signal in signals[:]:  # Copy list to allow modification
            if signal.is_pending:
                # Check if order was filled/closed
                if self.connection.check_order_status(signal):
                    if signal.is_completed:
                        self.logger.info(f"Signal completed: {symbol} {signal.outcome.value} ${signal.gain}")
                        
                        # Apply gain to budget
                        budget = self.daily_budgets[symbol]
                        budget.apply_signal_gain(signal.gain)
                        
                        # Remove from active signals
                        signals.remove(signal)
                        
                        # Check for recovery signal if main signal failed AND we're in trading session
                        if (signal.signal_type.value == 'main' and 
                            signal.outcome == SignalOutcome.LOSS and
                            self.is_trading_session()):
                                self._attempt_recovery_signal(symbol, signal, strategy)
                
                else:
                    # Update stop loss if risk-free conditions are met
                    self._update_risk_free_management(signal)
    
    def _attempt_new_signals(self, symbol: str, strategy):
        """Attempt to generate new signals (only during trading sessions)"""
        try:
            current_date = datetime.now()
            main_signal = strategy.attempt_main_signal(current_date)
            
            if main_signal:
                # Place order
                if self.connection.place_order(main_signal):
                    self.active_signals[symbol].append(main_signal)
                    strategy.signals_generated.append(main_signal)
                    
                    self.logger.info(f"New signal placed: {symbol} {main_signal.action.value} "
                                   f"@ {main_signal.entry_price}")
                else:
                    self.logger.warning(f"Failed to place order for {symbol}")
                    
        except Exception as e:
            self.logger.error(f"Error generating signal for {symbol}: {e}")
    
    def _attempt_recovery_signal(self, symbol: str, failed_signal: Signal, strategy):
        """Attempt recovery signal after main signal failure (only during trading sessions)"""
        try:
            # Get bars since failed signal outcome
            recovery_bars = []
            latest_bars = self.connection.get_last_bars(symbol, count=50)
            
            if latest_bars:
                recovery_bars = [
                    bar for bar in latest_bars
                    if bar.timestamp >= failed_signal.outcome_timestamp
                ]
            
            if recovery_bars:
                recovery_signal = strategy.attempt_recovery_signal(failed_signal, recovery_bars)
                
                if recovery_signal:
                    if self.connection.place_order(recovery_signal):
                        self.active_signals[symbol].append(recovery_signal)
                        strategy.signals_generated.append(recovery_signal)
                        
                        self.logger.info(f"Recovery signal placed: {symbol} {recovery_signal.action.value}")
                    
        except Exception as e:
            self.logger.error(f"Error generating recovery signal for {symbol}: {e}")
    
    def _update_risk_free_management(self, signal: Signal):
        """Update risk-free management for active signals"""
        try:
            # Get recent bars for risk-free calculation
            recent_bars = self.connection.get_last_bars(signal.symbol, count=20)
            
            if recent_bars:
                bars_since_signal = [
                    bar for bar in recent_bars
                    if bar.timestamp >= signal.timestamp
                ]
                
                if signal.risk_free(bars_since_signal):
                    # Update order with new stop loss
                    self.connection.update_order(signal)
                    
        except Exception as e:
            self.logger.error(f"Error updating risk-free management: {e}")
    
    def _emergency_position_check(self):
        """Emergency check for any remaining open positions"""
        for symbol in self.symbols:
            active_signals = self.active_signals[symbol]
            
            for signal in active_signals:
                if signal.is_pending:
                    # Check final status
                    self.connection.check_order_status(signal)
    
    def get_trading_status(self) -> Dict:
        """Get current trading status"""
        current_time = datetime.now().time()
        total_signals = sum(len(signals) for signals in self.active_signals.values())
        
        status = {
            'is_running': self.is_running,
            'system_hours': {
                'start': self.system_hours[0].strftime('%H:%M'),
                'end': self.system_hours[1].strftime('%H:%M'),
                'is_system_time': self.is_system_time(current_time)
            },
            'trading_sessions': [
                {
                    'start': start.strftime('%H:%M'),
                    'end': end.strftime('%H:%M')
                }
                for start, end in self.trading_sessions
            ],
            'is_trading_session': self.is_trading_session(current_time),
            'symbols': self.symbols,
            'active_signals_count': total_signals,
            'active_signals': {
                symbol: len(signals) for symbol, signals in self.active_signals.items()
            },
            'account_info': self.connection.get_account_info()._asdict() if self.connection.get_account_info() else None,
            'daily_pnl': {
                symbol: budget.current_balance - budget.initial_balance
                for symbol, budget in self.daily_budgets.items()
            }
        }
        
        return status
    
    def force_close_all_positions(self):
        """Emergency function to close all positions"""
        self.logger.warning("Force closing all positions")
        
        for symbol_signals in self.active_signals.values():
            for signal in symbol_signals:
                if signal.ticket and signal.is_pending:
                    try:
                        # Force close position (implementation depends on MT5 API)
                        self.logger.info(f"Force closed position {signal.ticket}")
                    except Exception as e:
                        self.logger.error(f"Error force closing position {signal.ticket}: {e}")
