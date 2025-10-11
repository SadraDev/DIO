import MetaTrader5 as mt5
from typing import List
import datetime as dt
from collections import defaultdict

from src.core.models.bar import Bar
from config.settings import settings
from src.core.utils.logger import TradingLogger, log_connection_event


class DataFetcher:
    """Enhanced data fetcher with configuration support"""
    
    def __init__(self):
        self.logger = TradingLogger.get_connection_logger()
        
        # Load configuration
        self.timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        }
        
        self.default_timeframe = self.timeframe_map.get(settings.get('data.timeframe', 'M1'))
        self.default_mode = settings.get('data.mode', 'mid')
        self.connection_timeout = settings.get('mt5.connection_timeout', 30)
    
    def _ensure_connection(self) -> bool:
        """Ensure MT5 connection is active"""
        try:
            if not mt5.initialize():
                log_connection_event("initialization_failed", "error")
                raise RuntimeError("Failed to initialize MetaTrader 5 connection")
            
            log_connection_event("connection_established", "success")
            return True
            
        except Exception as e:
            log_connection_event("connection_error", "error", error=str(e))
            raise
    
    def _close_connection(self):
        """Safely close MT5 connection"""
        try:
            mt5.shutdown()
            log_connection_event("connection_closed", "success")
        except Exception as e:
            log_connection_event("connection_close_error", "warning", error=str(e))
    
    def fetch_bars_from_mt5(
        self,
        start_dt: dt.datetime,
        end_dt: dt.datetime,
        symbol: str,
        timeframe: str = None,
        mode: str = None
    ) -> List[Bar]:
        """
        Fetch OHLCV bars from MT5 with different pricing modes
        
        Args:
            start_dt: Start datetime
            end_dt: End datetime  
            symbol: Trading symbol
            timeframe: Timeframe string (M1, M5, etc.)
            mode: Pricing mode - 'bid', 'ask', 'mid', 'hybrid'
            
        Returns:
            List of Bar objects
        """
        # Use defaults if not specified
        tf = timeframe or self.default_timeframe
        mode = mode or self.default_mode
        
        self.logger.info(f"Fetching {symbol} bars from {start_dt} to {end_dt} (TF: {timeframe}, Mode: {mode})")
        
        self._ensure_connection()
        
        try:
            # Get basic rate data
            rates = mt5.copy_rates_range(symbol, tf, start_dt, end_dt)
            
            if rates is None or len(rates) == 0:
                self.logger.warning(f"No rate data found for {symbol}")
                return []
            
            self.logger.debug(f"Retrieved {len(rates)} rate records for {symbol}")
            
            # For bid mode, use rates directly
            if mode.lower() == "bid":
                bars = [
                    Bar(
                        timestamp=dt.datetime.utcfromtimestamp(r['time']),
                        open_price=float(r['open']),
                        high=float(r['high']),
                        low=float(r['low']),
                        close=float(r['close']),
                        volume=int(r['tick_volume'])
                    )
                    for r in rates
                ]
                self.logger.info(f"Created {len(bars)} bid bars for {symbol}")
                return bars
            
            # For other modes, need tick data
            ticks = mt5.copy_ticks_range(symbol, start_dt, end_dt, mt5.COPY_TICKS_ALL)
            
            if ticks is None or len(ticks) == 0:
                self.logger.warning(f"No tick data available for {symbol}, falling back to bid prices")
                # Fallback to bid prices
                return self._create_bars_from_rates(rates, mode="bid")
            
            self.logger.debug(f"Retrieved {len(ticks)} ticks for {symbol}")
            
            # Group ticks by candle periods
            candle_ticks = self._group_ticks_by_candle(ticks, tf)
            
            # Create bars with tick-based pricing
            bars = self._create_bars_from_ticks(rates, candle_ticks, mode)
            
            self.logger.info(f"Created {len(bars)} {mode} bars for {symbol}")
            return bars
            
        except Exception as e:
            self.logger.error(f"Error fetching bars for {symbol}: {e}")
            raise
        finally:
            self._close_connection()
    
    def _group_ticks_by_candle(self, ticks, timeframe) -> dict:
        """Group ticks by their corresponding candle periods"""
        candle_ticks = defaultdict(list)
        minutes_per_candle = timeframe // mt5.TIMEFRAME_M1
        
        for tick in ticks:
            tick_dt = dt.datetime.utcfromtimestamp(tick['time'])
            # Calculate candle start time
            candle_start = tick_dt - dt.timedelta(
                minutes=tick_dt.minute % minutes_per_candle,
                seconds=tick_dt.second,
                microseconds=tick_dt.microsecond
            )
            candle_ticks[candle_start].append(tick)
        
        return candle_ticks
    
    def _create_bars_from_rates(self, rates, mode: str = "bid") -> List[Bar]:
        """Create bars directly from rate data"""
        return [
            Bar(
                timestamp=dt.datetime.utcfromtimestamp(r['time']),
                open_price=float(r['open']),
                high=float(r['high']),
                low=float(r['low']),
                close=float(r['close']),
                volume=int(r['tick_volume'])
            )
            for r in rates
        ]
    
    def _create_bars_from_ticks(self, rates, candle_ticks: dict, mode: str) -> List[Bar]:
        """Create bars using tick data for accurate bid/ask/mid pricing"""
        bars = []
        
        for rate in rates:
            candle_time = dt.datetime.utcfromtimestamp(rate['time'])
            ticks_for_candle = candle_ticks.get(candle_time, [])
            
            if not ticks_for_candle:
                # No ticks for this candle, use rate data
                bars.append(Bar(
                    timestamp=candle_time,
                    open_price=float(rate['open']),
                    high=float(rate['high']),
                    low=float(rate['low']),
                    close=float(rate['close']),
                    volume=int(rate['tick_volume'])
                ))
                continue
            
            # Extract prices from ticks
            bid_prices = [tick['bid'] for tick in ticks_for_candle]
            ask_prices = [tick['ask'] for tick in ticks_for_candle]
            mid_prices = [(b + a) / 2 for b, a in zip(bid_prices, ask_prices)]
            
            # Calculate OHLC based on mode
            if mode.lower() == "ask":
                open_price = ask_prices[0]
                high_price = max(ask_prices)
                low_price = min(ask_prices)
                close_price = ask_prices[-1]
                
            elif mode.lower() == "mid":
                open_price = mid_prices[0]
                high_price = max(mid_prices)
                low_price = min(mid_prices)
                close_price = mid_prices[-1]
                
            elif mode.lower() == "hybrid":
                # Use bid/ask extremes for high/low
                is_green = rate['close'] > rate['open']
                
                # For hybrid mode, use most conservative pricing
                high_price = max(max(bid_prices), max(ask_prices))
                low_price = min(min(bid_prices), min(ask_prices))
                
                if is_green:
                    open_price = min(bid_prices[0], ask_prices[0])
                    close_price = max(bid_prices[-1], ask_prices[-1])
                else:
                    open_price = max(bid_prices[0], ask_prices[0])
                    close_price = min(bid_prices[-1], ask_prices[-1])
                    
            else:
                raise ValueError(f"Unknown pricing mode: {mode}")
            
            bars.append(Bar(
                timestamp=candle_time,
                open_price=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=int(rate['tick_volume'])
            ))
        
        return bars
    
    def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols"""
        self._ensure_connection()
        
        try:
            symbols = mt5.symbols_get()
            if symbols:
                symbol_names = [s.name for s in symbols if s.visible]
                self.logger.info(f"Found {len(symbol_names)} available symbols")
                return symbol_names
            return []
            
        except Exception as e:
            self.logger.error(f"Error getting symbols: {e}")
            return []
        finally:
            self._close_connection()
    
    def get_symbol_info(self, symbol: str) -> dict:
        """Get detailed symbol information"""
        self._ensure_connection()
        
        try:
            info = mt5.symbol_info(symbol)
            if info:
                return {
                    'name': info.name,
                    'description': info.description,
                    'point': info.point,
                    'digits': info.digits,
                    'spread': info.spread,
                    'trade_allowed': info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED
                }
            return {}
            
        except Exception as e:
            self.logger.error(f"Error getting symbol info for {symbol}: {e}")
            return {}
        finally:
            self._close_connection()
    
    def test_connection(self) -> bool:
        """Test MT5 connection"""
        try:
            self._ensure_connection()
            self.logger.info("MT5 connection test successful")
            return True
        except Exception as e:
            self.logger.error(f"MT5 connection test failed: {e}")
            return False
        finally:
            try:
                self._close_connection()
            except:
                pass

    def get_latest_bar(
        self,
        symbol: str,
        timeframe: str = None,
        mode: str = None
    ) -> Bar:
        """
        Get the most recent candle for a given symbol and return as Bar object
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe string (M1, M5, etc.)
            mode: Pricing mode - 'bid', 'ask', 'mid', 'hybrid'
            
        Returns:
            Bar object with the latest candle data
            
        Raises:
            RuntimeError: If no data is available or connection fails
        """
        # Use defaults if not specified
        tf = self.timeframe_map.get(timeframe) if timeframe else self.default_timeframe
        mode = mode or self.default_mode
        
        self.logger.info(f"Fetching latest bar for {symbol} (TF: {timeframe}, Mode: {mode})")
        
        self._ensure_connection()
        
        try:
            # Get the most recent rate (1 candle from current position)
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, 1)
            
            if rates is None or len(rates) == 0:
                error_msg = f"No rate data found for {symbol}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            rate = rates[0]  # Get the single rate record
            candle_time = dt.datetime.utcfromtimestamp(rate['time'])
            
            self.logger.debug(f"Retrieved latest rate for {symbol} at {candle_time}")
            
            # For bid mode, use rates directly
            if mode.lower() == "bid":
                bar = Bar(
                    timestamp=candle_time,
                    open_price=float(rate['open']),
                    high=float(rate['high']),
                    low=float(rate['low']),
                    close=float(rate['close']),
                    volume=int(rate['tick_volume'])
                )
                self.logger.info(f"Created latest bid bar for {symbol}")
                return bar
            
            # For other modes, try to get tick data for more accurate pricing
            # Get ticks for the candle period
            candle_start = candle_time
            candle_end = candle_time + dt.timedelta(seconds=self._get_timeframe_seconds(tf))
            
            ticks = mt5.copy_ticks_range(symbol, candle_start, candle_end, mt5.COPY_TICKS_ALL)
            
            if ticks is None or len(ticks) == 0:
                self.logger.warning(f"No tick data available for latest {symbol} candle, using bid prices")
                # Fallback to bid prices
                bar = Bar(
                    timestamp=candle_time,
                    open_price=float(rate['open']),
                    high=float(rate['high']),
                    low=float(rate['low']),
                    close=float(rate['close']),
                    volume=int(rate['tick_volume'])
                )
                return bar
            
            # Create bar with tick-based pricing
            bid_prices = [tick['bid'] for tick in ticks]
            ask_prices = [tick['ask'] for tick in ticks]
            mid_prices = [(b + a) / 2 for b, a in zip(bid_prices, ask_prices)]
            
            # Calculate OHLC based on mode
            if mode.lower() == "ask":
                open_price = ask_prices[0]
                high_price = max(ask_prices)
                low_price = min(ask_prices)
                close_price = ask_prices[-1]
                
            elif mode.lower() == "mid":
                open_price = mid_prices[0]
                high_price = max(mid_prices)
                low_price = min(mid_prices)
                close_price = mid_prices[-1]
                
            elif mode.lower() == "hybrid":
                # Use bid/ask extremes for high/low
                is_green = rate['close'] > rate['open']
                
                # For hybrid mode, use most conservative pricing
                high_price = max(max(bid_prices), max(ask_prices))
                low_price = min(min(bid_prices), min(ask_prices))
                
                if is_green:
                    open_price = min(bid_prices[0], ask_prices[0])
                    close_price = max(bid_prices[-1], ask_prices[-1])
                else:
                    open_price = max(bid_prices[0], ask_prices[0])
                    close_price = min(bid_prices[-1], ask_prices[-1])
                    
            else:
                raise ValueError(f"Unknown pricing mode: {mode}")
            
            bar = Bar(
                timestamp=candle_time,
                open_price=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=int(rate['tick_volume'])
            )
            
            self.logger.info(f"Created latest {mode} bar for {symbol}")
            return bar
            
        except Exception as e:
            self.logger.error(f"Error fetching latest bar for {symbol}: {e}")
            raise
        finally:
            self._close_connection()

    def _get_timeframe_seconds(self, timeframe) -> int:
        """Helper method to get timeframe duration in seconds"""
        timeframe_seconds = {
            mt5.TIMEFRAME_M1: 60,
            mt5.TIMEFRAME_M5: 300,
            mt5.TIMEFRAME_M15: 900,
            mt5.TIMEFRAME_M30: 1800,
            mt5.TIMEFRAME_H1: 3600,
            mt5.TIMEFRAME_H4: 14400,
            mt5.TIMEFRAME_D1: 86400
        }
        return timeframe_seconds.get(timeframe, 60)  # Default to 1 minute
