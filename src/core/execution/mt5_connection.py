import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from src.core.models.bar import Bar
from src.core.models.signal import Signal, SignalAction, SignalOutcome
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

    def place_market_order(self, signal: Signal, force: bool = False) -> bool:
        """
        Place an order for `signal`.

        force=True  →  if the broker returns TRADE_RETCODE_INVALID_STOPS,
                        retry immediately without SL and TP (market order only).
        """
        if not self.ensure_connection():
            return False

        try:
            _atmp = 0
            tick = mt5.symbol_info_tick(signal.symbol)

            if tick is None:
                mt5.initialize()

            if not tick: import time
            
            while not tick:
                _atmp += 1
                if _atmp == 10:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 10 attempts, keeping order attempt", signal.symbol)
                if _atmp == 50:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 50 attempts, keeping order attempt", signal.symbol)
                if _atmp == 100:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 100 attempts, aborting order attempt", signal.symbol)
                    return False
                tick = mt5.symbol_info_tick(signal.symbol)
                time.sleep(0.1)

            if signal.is_sell:
                order_type  = mt5.ORDER_TYPE_SELL
                price       = tick.bid
                stop_loss   = signal.stop_loss   if signal.stop_loss   > price else price + 0.00001
                take_profit = signal.take_profit if signal.take_profit < price else price - 0.00001
            else:
                order_type  = mt5.ORDER_TYPE_BUY
                price       = tick.ask
                stop_loss   = signal.stop_loss   if signal.stop_loss   < price else price - 0.00001
                take_profit = signal.take_profit if signal.take_profit > price else price + 0.00001

            

            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    signal.symbol,
                "volume":    min(signal.entry_lot, 0.05),
                "type":      order_type,
                "price":     price,
                "sl":        stop_loss,
                "tp":        take_profit,
                "deviation": self.deviation,
                "magic":     self.magic_number,
                "comment":   "TwoHunters-S",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            print(result)

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                signal.ticket      = result.order
                signal.entry_price = price
                self.orders_logger.debug("Order accepted by broker (ticket %s)", result.order)
                return result

            # ── force_order fallback: retry without SL/TP ─────────────
            if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS and force:
                self.orders_logger.warning(
                    "Invalid Stops error — retrying WITHOUT SL/TP (force_order is enabled)"
                )
                request_no_sl = {k: v for k, v in request.items() if k not in ("sl", "tp")}
                result2 = mt5.order_send(request_no_sl)
                if result2.retcode == mt5.TRADE_RETCODE_DONE:
                    signal.ticket      = result2.order
                    signal.entry_price = price
                    self.orders_logger.warning(
                        "Order placed WITHOUT SL/TP (ticket %s) — manual stop management required",
                        result2.order,
                    )
                    return result
                self.orders_logger.error("force_order retry also failed: retcode=%s", result2.comment)
                return False

            self.orders_logger.warning("Order rejected: retcode=%s", result.comment)
            return False

        except Exception as exc:
            self.orders_logger.error("place_deal exception: %s", exc)
            return False
        
    def place_pending_order(self, signal: Signal, force: bool = False) -> bool:
        """
        Place a PENDING order for `signal`.

        force=True  →  if broker returns TRADE_RETCODE_INVALID_STOPS,
                        retry immediately without SL and TP.
        """
        if not self.ensure_connection():
            return False

        try:
            _atmp = 0
            tick = mt5.symbol_info_tick(signal.symbol)

            if tick is None:
                mt5.initialize()
            
            if not tick: import time

            while not tick:
                _atmp += 1
                if _atmp == 10:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 10 attempts, keeping order attempt", signal.symbol)
                if _atmp == 50:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 50 attempts, keeping order attempt", signal.symbol)
                if _atmp == 100:
                    mt5.initialize()
                    self.orders_logger.warning("No tick data for %s after 100 attempts, aborting order attempt", signal.symbol)
                    return False
                tick = mt5.symbol_info_tick(signal.symbol)
                time.sleep(0.1)

            entry_price = signal.entry_price

            # ── Determine pending order type ─────────────────────────────
            if signal.is_sell:
                if entry_price > tick.bid:
                    order_type = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    order_type = mt5.ORDER_TYPE_SELL_STOP

                stop_loss = signal.stop_loss if signal.stop_loss > entry_price else entry_price + 0.00001
                take_profit = signal.take_profit if signal.take_profit < entry_price else entry_price - 0.00001

            else:
                if entry_price < tick.ask:
                    order_type = mt5.ORDER_TYPE_BUY_LIMIT
                else:
                    order_type = mt5.ORDER_TYPE_BUY_STOP

                stop_loss = signal.stop_loss if signal.stop_loss < entry_price else entry_price - 0.00001
                take_profit = signal.take_profit if signal.take_profit > entry_price else entry_price + 0.00001

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": signal.symbol,
                "volume": min(signal.entry_lot, 0.05),
                "type": order_type,
                "price": entry_price,
                "sl": stop_loss,
                "tp": take_profit,
                "deviation": self.deviation,
                "magic": self.magic_number,
                "comment": "TwoHunters-S",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            result = mt5.order_send(request)
            print(result)


            if result.retcode == mt5.TRADE_RETCODE_DONE:
                signal.ticket = result.order
                signal.entry_price = entry_price
                self.orders_logger.debug("Pending order placed (ticket %s)", result.order)
                return result

            # ── force fallback: retry without SL/TP ──────────────────────
            if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS and force:
                self.orders_logger.warning("Invalid Stops — retrying WITHOUT SL/TP")

                request_no_sl = {k: v for k, v in request.items() if k not in ("sl", "tp")}
                result2 = mt5.order_send(request_no_sl)

                if result2.retcode == mt5.TRADE_RETCODE_DONE:
                    signal.ticket = result2.order
                    signal.entry_price = entry_price
                    self.orders_logger.warning(
                        "Pending order placed WITHOUT SL/TP (ticket %s)",
                        result2.order,
                    )
                    return result

                self.orders_logger.error("force retry failed: retcode=%s", result2.comment)
                return False

            self.orders_logger.warning("Pending order rejected: retcode=%s", result.comment)
            return False

        except Exception as exc:
            self.orders_logger.error("place_order exception: %s", exc)
            return False

    def update_order(self, signal: Signal, volume_change: float, force: bool = False) -> bool:
        """
        Increase or decrease the volume of an existing open position.

        volume_change > 0  →  add lots to the position (scale in / buy more)
        volume_change < 0  →  partially close the position (scale out / reduce)

        force=True  →  on TRADE_RETCODE_INVALID_STOPS, retry without SL/TP.

        Returns True (or the result object) on success, False on failure.
        """
        if not self.ensure_connection() or not signal.ticket:
            return False

        try:
            positions = mt5.positions_get(ticket=signal.ticket)
            if not positions:
                self.orders_logger.warning(
                    "modify_position: ticket %s not found as an open position", signal.ticket
                )
                return False

            position   = positions[0]
            abs_volume = round(abs(volume_change), 2)

            # ── guard: can't remove more than what's open ─────────────────
            if volume_change < 0 and abs_volume > position.volume:
                self.orders_logger.error(
                    "modify_position: requested close volume %.2f exceeds open volume %.2f",
                    abs_volume, position.volume,
                )
                return False

            # ── tick data ─────────────────────────────────────────────────
            _atmp = 0
            tick  = mt5.symbol_info_tick(signal.symbol)
            if tick is None:
                mt5.initialize()
                import time

            while not tick:
                _atmp += 1
                if _atmp == 10:
                    mt5.initialize()
                    self.orders_logger.warning(
                        "No tick data for %s after 10 attempts", signal.symbol
                    )
                if _atmp == 50:
                    mt5.initialize()
                    self.orders_logger.warning(
                        "No tick data for %s after 50 attempts", signal.symbol
                    )
                if _atmp == 100:
                    mt5.initialize()
                    self.orders_logger.warning(
                        "No tick data for %s after 100 attempts, aborting", signal.symbol
                    )
                    return False
                tick = mt5.symbol_info_tick(signal.symbol)
                time.sleep(0.1)

            # ── SCALE-IN (add volume) ──────────────────────────────────────
            if volume_change > 0:
                if position.type == mt5.ORDER_TYPE_BUY:          # existing BUY → add BUY
                    order_type  = mt5.ORDER_TYPE_BUY
                    price       = tick.ask
                    stop_loss   = signal.stop_loss   if signal.stop_loss   < price  else price - 0.00001
                    take_profit = signal.take_profit if signal.take_profit > price  else price + 0.00001
                else:                                             # existing SELL → add SELL
                    order_type  = mt5.ORDER_TYPE_SELL
                    price       = tick.bid
                    stop_loss   = signal.stop_loss   if signal.stop_loss   > price  else price + 0.00001
                    take_profit = signal.take_profit if signal.take_profit < price  else price - 0.00001

                request = {
                    "action":       mt5.TRADE_ACTION_DEAL,
                    "symbol":       signal.symbol,
                    "volume":       abs_volume,
                    "type":         order_type,
                    "price":        price,
                    "sl":           stop_loss,
                    "tp":           take_profit,
                    "deviation":    self.deviation,
                    "magic":        self.magic_number,
                    "comment":      "TwoHunters-S-ScaleIn",
                    "type_time":    mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = mt5.order_send(request)

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.orders_logger.info(
                        "Scale-in OK: +%.2f lots on %s (new ticket %s)",
                        abs_volume, signal.symbol, result.order,
                    )
                    return result

                if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS and force:
                    self.orders_logger.warning("Scale-in: Invalid Stops — retrying without SL/TP")
                    req2   = {k: v for k, v in request.items() if k not in ("sl", "tp")}
                    result2 = mt5.order_send(req2)
                    if result2.retcode == mt5.TRADE_RETCODE_DONE:
                        self.orders_logger.warning(
                            "Scale-in placed WITHOUT SL/TP (ticket %s)", result2.order
                        )
                        return result2
                    self.orders_logger.error("Scale-in force retry failed: %s", result2.comment)
                    return False

                self.orders_logger.warning("Scale-in rejected: %s", result.comment)
                return False

            # ── SCALE-OUT (partial close) ──────────────────────────────────
            elif volume_change < 0:
                # Partial close = open the opposite side against the same position
                if position.type == mt5.ORDER_TYPE_BUY:
                    order_type = mt5.ORDER_TYPE_SELL
                    price      = tick.bid
                else:
                    order_type = mt5.ORDER_TYPE_BUY
                    price      = tick.ask

                request = {
                    "action":       mt5.TRADE_ACTION_DEAL,
                    "symbol":       signal.symbol,
                    "volume":       abs_volume,
                    "type":         order_type,
                    "price":        price,
                    "position":     signal.ticket,      # ties the deal to the open position
                    "deviation":    self.deviation,
                    "magic":        self.magic_number,
                    "comment":      "TwoHunters-S-ScaleOut",
                    "type_time":    mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = mt5.order_send(request)

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.orders_logger.info(
                        "Scale-out OK: -%.2f lots on %s (ticket %s)",
                        abs_volume, signal.symbol, signal.ticket,
                    )
                    return result

                self.orders_logger.warning("Scale-out rejected: %s", result.comment)
                return False

            else:
                if signal.is_buy:
                    price = tick.ask
                    stop_loss = signal.stop_loss if signal.stop_loss < price else price - 0.00001
                    take_profit =  signal.take_profit if signal.take_profit > price else price + 0.00001

                if signal.is_sell:
                    price = tick.bid
                    stop_loss = signal.stop_loss if signal.stop_loss > price else price + 0.00001
                    take_profit =  signal.take_profit if signal.take_profit < price else price - 0.00001


                # Build update request
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": signal.ticket,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "magic": self.magic_number,
                    "comment": "TwoHunters-S-SL/TP-Update",
                }
                
                result = mt5.order_send(request)
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.orders_logger.info("SL/TP Adj OK.")
                    return True
                else:
                    self.orders_logger.info("SL/TP Adj failed.")
                    return False
                
        except Exception as exc:
            self.orders_logger.error("modify_position exception: %s", exc)
            return False

    def get_open_order(self, signal) -> dict | None:
        """
        Pull the live open position OR pending order that belongs to `signal`
        and return its data as a plain dict.  Returns None if nothing is found.
        """
        if not signal.ticket or not self.ensure_connection():
            return None

        # 1. open position?
        positions = mt5.positions_get(ticket=signal.ticket)
        if positions:
            p = positions[0]
            return {
                "ticket":      p.ticket,
                "symbol":      p.symbol,
                "type":        "position",
                "order_type":  p.type,          # 0=BUY, 1=SELL
                "volume":      p.volume,
                "price_open":  p.price_open,
                "sl":          p.sl,
                "tp":          p.tp,
                "profit":      p.profit,
                "swap":        p.swap,
                "time_open":   datetime.fromtimestamp(p.time),
            }

        # 2. pending order?
        orders = mt5.orders_get(ticket=signal.ticket)
        if orders:
            o = orders[0]
            return {
                "ticket":      o.ticket,
                "symbol":      o.symbol,
                "type":        "pending",
                "order_type":  o.type,
                "volume":      o.volume_current,
                "price_open":  o.price_open,
                "sl":          o.sl,
                "tp":          o.tp,
                "profit":      None,
                "swap":        None,
                "time_open":   datetime.fromtimestamp(o.time_setup),
            }

        return None

    def monitor_signal(self, signal):

        BROKER_TZ = timezone(timedelta(hours=6, minutes=30))

        if signal.ticket is None:
            return signal

        _target_profit = signal.entry_lot * signal.stop_loss_pips

        try:

            # ==========================================
            # OPEN POSITION
            # ==========================================

            positions = mt5.positions_get(ticket=signal.ticket)
            if positions:

                position = positions[0]

                signal.gain = position.profit

                return signal

            # ==========================================
            # PENDING ORDER
            # ==========================================

            orders = mt5.orders_get(ticket=signal.ticket)

            if orders:
                return signal

            # ==========================================
            # CLOSED POSITION
            # ==========================================

            history = mt5.history_deals_get(
                datetime.now(BROKER_TZ) - timedelta(days=1),
                datetime.now(BROKER_TZ) + timedelta(days=1)
            )

            if history is None:
                return signal

            related_deals = [
                d for d in history
                if d.order == signal.ticket
            ]

            if not related_deals:
                return signal

            last_deal = related_deals[-1]

            signal.outcome_timestamp = datetime.fromtimestamp(last_deal.time)

            signal.exit_price = last_deal.price

            signal.gain = last_deal.profit

            # ==========================================
            # DETERMINE WIN/LOSS
            # ==========================================

            if signal.gain >= 0:
                signal.outcome = SignalOutcome.WIN
            else:
                signal.outcome = SignalOutcome.LOSS

            return signal

        except Exception as e:

            self.orders_logger.error(
                f"monitor_signal error: {e}"
            )

            return signal
    
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
            from_time = datetime.now(timezone(timedelta(hours=6, minutes=30))).replace(hour=0, minute=0, second=0, microsecond=0)
            to_time   = datetime.now(timezone(timedelta(hours=6, minutes=30)))
            
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
                    
                    signal.outcome = SignalOutcome.WIN if deal.profit >= 0 else SignalOutcome.LOSS
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
