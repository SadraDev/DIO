from src.core.utils.logger import TradingLogger
import MetaTrader5 as mt5
from typing import List, Union, Sequence, Optional, Dict
from datetime import datetime, timedelta
import csv
import os
from src.core.models.bar import Bar
from config.settings import settings
import pandas as pd

class DataFetcher:
    """Enhanced data fetcher with configuration support."""
    
    def __init__(self):
        """Initialize DataFetcher with MT5 configuration."""
        # Timeframe mapping
        self.timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "H8": mt5.TIMEFRAME_H8,
            "D1": mt5.TIMEFRAME_D1,
        }
        self.default_timeframe = self.timeframe_map.get("M1", mt5.TIMEFRAME_M1)
        self.connection_timeout = 30
        self.logger = TradingLogger.get_main_logger()
    
    def ensure_connection(self) -> bool:
        """Ensure MT5 connection is active."""
        try:
            if not mt5.initialize():
                raise RuntimeError("Failed to initialize MetaTrader 5 connection")
            return True
        except Exception as e:
            raise e
    
    def close_connection(self):
        """Safely close MT5 connection."""
        try:
            mt5.shutdown()
        except Exception:
            pass
    
    def fetch_bars_from_mt5(
        self,
        start_dt: datetime,
        end_dt: datetime,
        symbol: str,
        timeframe: Optional[str] = None,
    ) -> List[Bar]:
        """
        Fetch OHLCV bars directly from MT5 using copy_rates_range.
        
        Args:
            start_dt: Start datetime (in broker time)
            end_dt: End datetime (in broker time)
            symbol: Symbol to fetch (e.g., "EURUSD")
            timeframe: Timeframe string (e.g., "M1", "M15", "H1")
            
        Returns:
            List of Bar objects
        """
        tf = timeframe or "M1"
        
        self.ensure_connection()
        
        try:
            # Get the MT5 timeframe enum
            tf_enum = self.timeframe_map.get(tf, mt5.TIMEFRAME_M1)
            
            # Fetch rates directly from MT5 (already properly grouped)
            rates = mt5.copy_rates_range(symbol, tf_enum, start_dt, end_dt)
            
            if rates is None or len(rates) == 0:
                return []
            
            # Convert MT5 rates to Bar objects
            bars = []
            for rate in rates:
                bar = Bar(
                    timestamp=datetime.fromtimestamp(int(rate['time'])),
                    open_price=float(rate['open']),
                    high=float(rate['high']),
                    low=float(rate['low']),
                    close=float(rate['close']),
                    volume=int(rate['tick_volume']),
                )
                bars.append(bar)
            
            return bars
        
        except Exception as e:
            raise e
        
        finally:
            self.close_connection()
    
    def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols."""
        self.ensure_connection()
        try:
            symbols = mt5.symbols_get()
            if symbols:
                symbol_names = [s.name for s in symbols if s.visible]
                return symbol_names
            return []
        except Exception:
            return []
        finally:
            self.close_connection()
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get detailed symbol information."""
        self.ensure_connection()
        try:
            info = mt5.symbol_info(symbol)
            if info:
                return {
                    "name": info.name,
                    "description": info.description,
                    "point": info.point,
                    "digits": info.digits,
                    "spread": info.spread,
                    "trade_allowed": info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED,
                }
            return None
        except Exception:
            return None
        finally:
            self.close_connection()
    
    def test_connection(self) -> bool:
        """Test MT5 connection."""
        try:
            self.ensure_connection()
            return True
        except Exception:
            return False
        finally:
            try:
                self.close_connection()
            except:
                pass

    def get_latest_bars(self, symbol: str, timeframe: int = mt5.TIMEFRAME_M1, count: int = 1) -> List[Bar]:
        """
        Fetch latest OHLC bars for a symbol and convert to Bar objects.
        
        Args:
            symbol: Asset symbol (e.g., "EURUSD")
            timeframe: MT5 timeframe constant (e.g., mt5.TIMEFRAME_H1)
            count: Number of bars to fetch (default 100)
            
        Returns:
            List[Bar]: List of Bar objects ordered from oldest to newest.
        """
        if not self.ensure_connection():
            return []

        try:
            # Fetch rates starting from index 0 (current forming candle)
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            
            if rates is None or len(rates) == 0:
                self.logger.warning(f"No rates returned for {symbol}")
                return []

            bars = []
            for rate in rates:
                # Convert MT5 timestamp (seconds) to datetime
                # Matches your existing logic in get_today_signals
                dt = datetime.fromtimestamp(int(rate['time']))
                
                # Create Bar instance
                # Note: Using tick_volume as it's standard for Forex/CFDs
                bar = Bar(
                    timestamp=dt,
                    open_price=float(rate['open']),
                    high=float(rate['high']),
                    low=float(rate['low']),
                    close=float(rate['close']),
                    volume=float(rate['tick_volume']) 
                )
                bars.append(bar)

            return bars

        except Exception as e:
            self.logger.error(f"Error fetching bars for {symbol}: {e}")
            return []

    def get_current_price(self, symbol: str) -> Optional[dict]:
        """
        Get the absolute latest real-time tick (Bid/Ask).
        Useful for precise order entry validation.
        """
        if not self.ensure_connection():
            return None
            
        try:
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.logger.warning(f"Tick data unavailable for {symbol}")
                return None
                
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "time": datetime.fromtimestamp(tick.time),
                "spread": abs(tick.bid - tick.ask)
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching tick for {symbol}: {e}")
            return None

    # def fetch_bars_from_mt5(
    #     self,
    #     start_dt: datetime,
    #     end_dt: datetime,
    #     symbol: str,
    #     timeframe: Optional[str] = "M1",
    # ) -> List[Bar]:
    #     """
    #     Fetch OHLCV bars from CSV files with in-memory caching for performance.
    #     """

    
    #     # Clean broker suffix "." (e.g., GBPUSD. -> GBPUSD)
    #     clean_symbol = symbol.rstrip(".")

    #     csv_dir = settings.get("paths.csvs")
    #     filename = f"{clean_symbol}_{timeframe}.csv"
    #     filepath = os.path.join(csv_dir, filename)

    #     # ---------- CACHE INITIALIZATION ----------
    #     if not hasattr(self, "_csv_cache"):
    #         self._csv_cache = {}  # dict: { filepath: DataFrame }

    #     # ---------- LOAD OR USE CACHED DF ----------
    #     if filepath in self._csv_cache:
    #         df = self._csv_cache[filepath]
    #     else:
    #         if not os.path.exists(filepath):
    #             return []
    #         try:
    #             df = pd.read_csv(filepath)
    #             df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    #         except Exception as e:
    #             raise e

    #         # Store in cache
    #         self._csv_cache[filepath] = df

    #     # ---------- FILTER ----------
    #     # Use pandas indexing
    #     df_filtered = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)]

    #     if df_filtered.empty:
    #         return []

    #     # ---------- CONVERT TO BAR LIST ----------
    #     bars = [
    #         Bar(
    #             timestamp=row["timestamp"].to_pydatetime(),
    #             open_price=float(row["open"]),
    #             high=float(row["high"]),
    #             low=float(row["low"]),
    #             close=float(row["close"]),
    #             volume=int(row["volume"]),
    #         )
    #         for _, row in df_filtered.iterrows()
    #     ]

    #     return bars