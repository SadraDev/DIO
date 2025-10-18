import MetaTrader5 as mt5
from typing import List
import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

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
        Fetch OHLCV bars from MT5 using only tick data (copy_ticks_range),
        supporting pricing modes: 'bid', 'ask', 'mid', 'hybrid', 'min', 'max'.
        """
        tf = timeframe or self.default_timeframe
        mode = (mode or self.default_mode).lower()

        self.logger.info(f"Fetching {symbol} bars from {start_dt} to {end_dt} (TF: {tf}, Mode: {mode})")
        self._ensure_connection()

        try:
            # Pull raw ticks for the interval (both info and trade ticks)
            ticks = mt5.copy_ticks_range(symbol, start_dt, end_dt, mt5.COPY_TICKS_ALL)
            if ticks is None or len(ticks) == 0:
                self.logger.info(f"No tick data available for {symbol} in range {start_dt.date()}-{end_dt.date()}.")
                return []

            self.logger.debug(f"Retrieved {len(ticks)} ticks for {symbol}")

            # Group ticks into candle buckets according to timeframe
            candle_ticks = self._group_ticks_by_candle(ticks, tf)

            # Build bars from tick groups using requested price mode
            bars: List[Bar] = []

            for candle_start, ticks_in_candle in sorted(candle_ticks.items()):
                if not ticks_in_candle:
                    continue

                bids, asks, mids = [], [], []
                # Also build per-tick extrema series for min/max modes
                series_min_per_tick, series_max_per_tick = [], []

                for t in ticks_in_candle:
                    b = float(t['bid']) if 'bid' in t.dtype.names else None
                    a = float(t['ask']) if 'ask' in t.dtype.names else None

                    # Collect sides if present
                    if b is not None and b == b:
                        bids.append(b)
                    if a is not None and a == a:
                        asks.append(a)

                    # Mid for other modes (not used for min/max extremization)
                    if b is not None and a is not None and b == b and a == a:
                        mids.append(0.5 * (b + a))
                    elif b is not None and b == b:
                        mids.append(b)
                    elif a is not None and a == a:
                        mids.append(a)

                    # Extrema per tick (exclude mid so extremes come from actual sides)
                    candidates = []
                    if b is not None and b == b:
                        candidates.append(b)
                    if a is not None and a == a:
                        candidates.append(a)
                    if candidates:
                        series_min_per_tick.append(min(candidates))
                        series_max_per_tick.append(max(candidates))

                if mode in ("bid", "ask", "mid"):
                    series = bids if mode == "bid" else asks if mode == "ask" else mids
                    if not series:
                        continue
                    open_price = series[0]
                    close_price = series[-1]
                    high_price = max(series)
                    low_price = min(series)

                elif mode == "hybrid":
                    # Open/Close prefer mid; High from Ask; Low from Bid; with fallbacks
                    if not (bids or asks or mids):
                        continue
                    open_price = (mids[0] if mids else (bids[0] if bids else asks[0]))
                    close_price = (mids[-1] if mids else (bids[-1] if bids else asks[-1]))
                    high_price = (max(asks) if asks else (max(bids) if bids else close_price))
                    low_price = (min(bids) if bids else (min(asks) if asks else close_price))

                elif mode == "max":
                    # Use the per-tick maxima stream so OHLC are all "max-side" extremas but not identical
                    if not series_max_per_tick:
                        continue
                    series = series_max_per_tick
                    open_price = series[0]
                    close_price = series[-1]
                    high_price = max(series)
                    low_price = min(series)

                elif mode == "min":
                    # Use the per-tick minima stream so OHLC are all "min-side" extremas but not identical
                    if not series_min_per_tick:
                        continue
                    series = series_min_per_tick
                    open_price = series[0]
                    close_price = series[-1]
                    high_price = max(series)
                    low_price = min(series)

                else:
                    raise ValueError(f"Unknown pricing mode: {mode}")

                bars.append(
                    Bar(
                        timestamp=candle_start,
                        open_price=float(open_price),
                        high=float(high_price),
                        low=float(low_price),
                        close=float(close_price),
                        volume=int(len(ticks_in_candle)),  # tick count as volume
                    )
                )

            self.logger.info(f"Created {len(bars)} {mode} bars for {symbol} from ticks")
            return bars

        except Exception as e:
            self.logger.error(f"Error fetching bars for {symbol}: {e}")
            raise
        finally:
            self._close_connection()

    def _group_ticks_by_candle(self, ticks, timeframe) -> dict:
        """
        Group ticks by their corresponding candle periods using a timeframe like 'M1','M5','M15','H1','H4','D1','W1','MN1' or an integer minute count.
        """
        from collections import defaultdict

        def timeframe_to_minutes(tf_val):
            if isinstance(tf_val, int):
                return tf_val
            tf_val = str(tf_val).upper()
            mapping = {
                "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
                "H1": 60, "H2": 120, "H3": 180, "H4": 240, "H6": 360, "H8": 480, "H12": 720,
                "D1": 1440, "W1": 10080, "MN1": 43200
            }
            if tf_val not in mapping:
                raise ValueError(f"Unsupported timeframe: {tf_val}")
            return mapping[tf_val]

        minutes_per_candle = timeframe_to_minutes(timeframe)
        candle_ticks = defaultdict(list)

        for tick in ticks:
            tick_dt = dt.datetime.fromtimestamp(int(tick['time']))
            # Align to the start of the timeframe bucket
            aligned_minute = tick_dt.minute - (tick_dt.minute % minutes_per_candle)
            candle_start = tick_dt.replace(minute=aligned_minute, second=0, microsecond=0)
            candle_ticks[candle_start].append(tick)

        return candle_ticks

    
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
