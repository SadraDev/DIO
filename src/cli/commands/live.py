import signal
import sys
from datetime import datetime, timedelta
from typing import List, Optional
from src.engine.live import LiveTradingEngine
from src.core.utils.logger import TradingLogger

class LiveTradingSession:
    """Manages live trading session with graceful shutdown"""
    
    def __init__(self):
        self.engine: Optional[LiveTradingEngine] = None
        self.logger = TradingLogger.get_trading_logger()
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
        if self.engine:
            self.engine.stop_live_trading()
        sys.exit(0)

def run_live_trading(
    symbols: List[str],
    account: int = None,
    password: str = None,
    server: str = None,
    balance: float = None,
    risk_percent: float = None,
    verbose: bool = False
):
    """Enhanced live trading function"""
    
    session = LiveTradingSession()
    session.setup_signal_handlers()
    
    # Prepare account configuration
    account_config = {}
    if account and password and server:
        account_config.update({
            'account': account,
            'password': password,
            'server': server
        })
    
    if balance:
        account_config['balance'] = balance
    if risk_percent:
        account_config['risk_percent'] = risk_percent
    
    # Create and start engine
    engine = LiveTradingEngine(symbols, account_config)
    session.engine = engine
    
    try:
        if engine.start_live_trading():
            print("✅ Live trading started successfully!")
            print("📊 Trading Status Dashboard:")
            print("=" * 50)
            
            # Keep the session alive and show periodic updates
            import time
            while engine.is_running:
                time.sleep(5)  # Update every 30 seconds
                
                status = engine.get_trading_status()
                if status['is_running']:
                    print(f"⏰ {datetime.now().strftime('%H:%M:%S')} | "
                          f"Active Signals: {status['active_signals_count']} | "
                          f"Account Balance: ${status['account_info']['balance'] if status['account_info'] else 'N/A'}")
                
        else:
            print("❌ Failed to start live trading")
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping live trading...")
    except Exception as e:
        print(f"❌ Live trading error: {e}")
    finally:
        if engine:
            engine.stop_live_trading()
