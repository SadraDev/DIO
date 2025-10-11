import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Optional, List

from src.core.models.bar import Bar
from src.core.models.signal import Signal, SignalAction
from config.settings import settings
from src.core.utils.logger import TradingLogger, log_connection_event, log_order_event


class MT5Connection:
    """Enhanced MT5 connection with configuration support"""
    
    def __init__(self):
        self.logger = TradingLogger.get_connection_logger()
        self.orders_logger = TradingLogger.get_orders_logger()
        
        # Load MT5 configuration
        self.magic_number = settings.mt5_magic_number
        self.deviation = settings.mt5_deviation
        self.timeout = settings.get('mt5.connection_timeout', 30)
        self.reconnect_attempts = settings.get('mt5.reconnect_attempts', 3)
        self.reconnect_delay = settings.get('mt5.reconnect_delay', 5)
        
        # Connection state
        self._connected = False
    
    def initialize_connection(self) -> bool:
        """Initialize MT5 connection with retry logic"""
        for attempt in range(self.reconnect_attempts):
            try:
                if mt5.initialize():
                    self._connected = True
                    log_connection_event("connection_established", "success", attempt=attempt + 1)
                    return True
                else:
                    log_connection_event("initialization_failed", "warning", attempt=attempt + 1)
                    
            except Exception as e:
                log_connection_event("connection_error", "error", 
                                   attempt=attempt + 1, error=str(e))
            
            if attempt < self.reconnect_attempts - 1:
                import time
                time.sleep(self.reconnect_delay)
        
        self._connected = False
        log_connection_event("connection_failed", "error", 
                           total_attempts=self.reconnect_attempts)
        return False
    
    def shutdown_connection(self):
        """Safely shutdown MT5 connection"""
        if self._connected:
            try:
                mt5.shutdown()
                self._connected = False
                log_connection_event("connection_closed", "success")
            except Exception as e:
                log_connection_event("shutdown_error", "warning", error=str(e))
    
    def ensure_connection(self) -> bool:
        """Ensure connection is active, reconnect if needed"""
        if not self._connected:
            return self.initialize_connection()
        
        # Test connection
        try:
            mt5.account_info()
            return True
        except:
            self._connected = False
            return self.initialize_connection()
    
    def login_with_credentials(self, account: int, password: str, server: str) -> bool:
        """Login to MT5 account with credentials"""
        if not self.ensure_connection():
            return False
        
        try:
            if mt5.login(account, password, server):
                account_info = mt5.account_info()
                log_connection_event("login_successful", "success",
                                   account=account, server=server,
                                   balance=account_info.balance if account_info else None)
                return True
            else:
                log_connection_event("login_failed", "error",
                                   account=account, server=server)
                return False
                
        except Exception as e:
            log_connection_event("login_error", "error",
                               account=account, server=server, error=str(e))
            return False
    
    def get_account_info(self) -> Optional[object]:
        """Get current account information"""
        if not self.ensure_connection():
            return None
        
        try:
            info = mt5.account_info()
            if info:
                self.logger.debug(f"Account info: Balance=${info.balance}, Equity=${info.equity}")
            return info
            
        except Exception as e:
            log_connection_event("account_info_error", "error", error=str(e))
            return None
    
    def get_last_bars(self, symbol: str, count: int = 2) -> Optional[List[Bar]]:
        """Fetch the most recent bars for a symbol"""
        if not self.ensure_connection():
            return None
        
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
            
            if rates is None or len(rates) == 0:
                self.logger.warning(f"No recent bars found for {symbol}")
                return None
            
            bars = []
            for rate in rates:
                bars.append(Bar(
                    timestamp=datetime.utcfromtimestamp(rate["time"]),
                    open_price=float(rate["open"]),
                    high=float(rate["high"]),
                    low=float(rate["low"]),
                    close=float(rate["close"]),
                    volume=int(rate["tick_volume"])
                ))
            
            return bars
            
        except Exception as e:
            log_connection_event("bar_fetch_error", "error", symbol=symbol, error=str(e))
            return None
    
    def place_order(self, signal: Signal) -> bool:
        """Place a trading order based on signal"""
        if not self.ensure_connection():
            return False
        
        try:
            # Get current price
            tick = mt5.symbol_info_tick(signal.symbol)
            if not tick:
                log_order_event("tick_error", signal.symbol, signal.action.value,
                              error="Cannot get current price")
                return False
            
            # Determine order type and price
            if signal.action == SignalAction.SELL:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            
            # Build order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": signal.symbol,
                "volume": signal.entry_lot,
                "type": order_type,
                "price": price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "deviation": self.deviation,
                "magic": self.magic_number,
                "comment": f"TwoHunters_{signal.action.value}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            # Send order
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                signal.ticket = result.order
                signal.entry_price = price
                
                log_order_event("order_placed", signal.symbol, signal.action.value,
                              ticket=result.order, price=price, volume=signal.entry_lot,
                              sl=signal.stop_loss, tp=signal.take_profit)
                return True
            else:
                log_order_event("order_failed", signal.symbol, signal.action.value,
                              error_code=result.retcode, error_desc=result.comment)
                return False
                
        except Exception as e:
            log_order_event("order_exception", signal.symbol, signal.action.value,
                          error=str(e))
            return False
    
    def update_order(self, signal: Signal) -> bool:
        """Update stop loss and take profit for an existing order"""
        if not self.ensure_connection() or not signal.ticket:
            return False
        
        try:
            # Check if position still exists
            position = mt5.positions_get(ticket=signal.ticket)
            if not position:
                self.logger.warning(f"Position {signal.ticket} not found for update")
                return False
            
            # Build update request
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": signal.ticket,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "magic": self.magic_number,
                "comment": "SL/TP Update",
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                log_order_event("order_updated", signal.symbol, signal.action.value,
                              ticket=signal.ticket, new_sl=signal.stop_loss,
                              new_tp=signal.take_profit)
                return True
            else:
                log_order_event("update_failed", signal.symbol, signal.action.value,
                              ticket=signal.ticket, error_code=result.retcode)
                return False
                
        except Exception as e:
            log_order_event("update_exception", signal.symbol, signal.action.value,
                          ticket=signal.ticket, error=str(e))
            return False
    
    def check_order_status(self, signal: Signal) -> bool:
        """Check if order is closed and update signal outcome"""
        if not self.ensure_connection() or not signal.ticket:
            return False
        
        try:
            # Look for deals in recent history
            from_time = signal.timestamp
            to_time = from_time + timedelta(days=2)
            
            deals = mt5.history_deals_get(from_time, to_time)
            if not deals:
                return False
            
            # Find position ID from opening deal
            position_id = None
            for deal in deals:
                if deal.order == signal.ticket:
                    position_id = deal.position_id
                    break
            
            if position_id is None:
                return False
            
            # Look for closing deal
            for deal in deals:
                if (deal.position_id == position_id and 
                    deal.entry == mt5.DEAL_ENTRY_OUT and
                    hasattr(deal, "profit")):
                    
                    signal.gain = deal.profit
                    signal.outcome = "win" if deal.profit >= 0 else "loss"
                    signal.outcome_timestamp = datetime.fromtimestamp(deal.time)
                    
                    log_order_event("order_closed", signal.symbol, signal.action.value,
                                  ticket=signal.ticket, profit=deal.profit,
                                  outcome=signal.outcome)
                    return True
            
            return False
            
        except Exception as e:
            log_order_event("status_check_error", signal.symbol, signal.action.value,
                          ticket=signal.ticket, error=str(e))
            return False
    
    def get_signal_profit(self, signal: Signal) -> Optional[float]:
        """Get current profit for a signal"""
        if not signal.ticket or not self.ensure_connection():
            return None
        
        try:
            # Check open positions first
            positions = mt5.positions_get(ticket=signal.ticket)
            if positions:
                return positions[0].profit
            
            # Check closed positions in history
            from_time = signal.timestamp - timedelta(hours=48)
            to_time = datetime.now()
            
            deals = mt5.history_deals_get(from_time, to_time)
            if deals:
                for deal in deals:
                    if deal.order == signal.ticket and hasattr(deal, "profit"):
                        return deal.profit
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting profit for signal {signal.ticket}: {e}")
            return None
    
    def get_today_signals(self) -> List[Signal]:
        """Fetch today's completed trades as Signal objects"""
        if not self.ensure_connection():
            return []
        
        try:
            from_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            to_time = datetime.now()
            
            deals = mt5.history_deals_get(from_time, to_time)
            if not deals:
                return []
            
            signals = []
            processed_positions = set()
            
            for deal in deals:
                if (hasattr(deal, "entry") and 
                    deal.entry == mt5.DEAL_ENTRY_OUT and
                    deal.position_id not in processed_positions):
                    
                    processed_positions.add(deal.position_id)
                    
                    # Find opening deal
                    entry_deal = None
                    for d in deals:
                        if (d.position_id == deal.position_id and 
                            d.entry == mt5.DEAL_ENTRY_IN):
                            entry_deal = d
                            break
                    
                    if not entry_deal:
                        continue
                    
                    # Create Signal object
                    action = SignalAction.BUY if entry_deal.type == mt5.ORDER_TYPE_BUY else SignalAction.SELL
                    
                    signal = Signal(
                        action=action,
                        entry_price=entry_deal.price,
                        stop_loss=0.0,  # Not available in history
                        take_profit=0.0,  # Not available in history
                        symbol=entry_deal.symbol,
                        timestamp=datetime.fromtimestamp(entry_deal.time),
                        entry_lot=entry_deal.volume,
                        gain=deal.profit,
                        ticket=entry_deal.order
                    )
                    
                    signal.outcome = "win" if deal.profit >= 0 else "loss"
                    signal.outcome_timestamp = datetime.fromtimestamp(deal.time)
                    
                    signals.append(signal)
            
            self.logger.info(f"Retrieved {len(signals)} completed signals for today")
            return signals
            
        except Exception as e:
            self.logger.error(f"Error fetching today's signals: {e}")
            return []
    
    def test_connection(self) -> bool:
        """Test the MT5 connection"""
        try:
            if self.ensure_connection():
                account = self.get_account_info()
                if account:
                    self.logger.info(f"Connection test successful - Account: {account.login}, Balance: ${account.balance}")
                    return True
            return False
            
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
        finally:
            self.shutdown_connection()


# Compatibility alias for existing code
Connection = MT5Connection
