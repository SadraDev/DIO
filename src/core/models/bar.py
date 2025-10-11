from datetime import datetime
from typing import Optional


class Bar:
    """Represents a single price bar/candlestick"""
    
    def __init__(
        self,
        timestamp: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: int = 0
    ):
        # Basic OHLCV data
        self.timestamp = timestamp
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        
        # Technical attributes
        self._calculate_attributes()
    
    def _calculate_attributes(self):
        """Calculate technical attributes of the candlestick"""
        # Basic measurements
        self.body = abs(self.close - self.open)
        self.range = self.high - self.low  # Total range (wick to wick)
        self.upper_wick = self.high - max(self.open, self.close)
        self.lower_wick = min(self.open, self.close) - self.low
        
        # Directional properties
        self.is_bullish = self.close > self.open
        self.is_bearish = self.close < self.open
        self.is_doji = self.close == self.open
        
        # Candlestick pattern recognition
        self._classify_candle()
    
    def _classify_candle(self):
        """Classify candlestick patterns and characteristics"""
        self.is_weak = False
        self.is_head_down = False
        self.is_head_up = False
        
        if self.body == 0:
            # Perfect Doji
            self.is_weak = True
            self.is_doji = True
        elif self.range > 0:
            # Calculate body-to-range ratio
            body_to_range_ratio = self.body / self.range
            
            # Weak candle if body is less than 1/3 of total range
            if body_to_range_ratio < 0.33:
                self.is_weak = True
                
                # Determine wick dominance for weak candles
                if self.upper_wick >= 2 * self.lower_wick:
                    self.is_head_down = True  # Upper wick dominant
                elif self.lower_wick >= 2 * self.upper_wick:
                    self.is_head_up = True   # Lower wick dominant
                else:
                    self.is_doji = True      # Both wicks similar
    
    @property
    def midpoint(self) -> float:
        """Get midpoint of the high-low range"""
        return (self.high + self.low) / 2
    
    @property
    def typical_price(self) -> float:
        """Get typical price (HLC/3)"""
        return (self.high + self.low + self.close) / 3
    
    @property
    def weighted_close(self) -> float:
        """Get weighted close (OHLC/4)"""
        return (self.open + self.high + self.low + self.close) / 4
    
    def is_inside_bar(self, previous_bar: 'Bar') -> bool:
        """Check if this is an inside bar relative to previous bar"""
        return (self.high <= previous_bar.high and 
                self.low >= previous_bar.low)
    
    def is_outside_bar(self, previous_bar: 'Bar') -> bool:
        """Check if this is an outside bar relative to previous bar"""
        return (self.high > previous_bar.high and 
                self.low < previous_bar.low)
    
    def overlaps_with(self, other_bar: 'Bar') -> bool:
        """Check if this bar's range overlaps with another bar"""
        return not (self.high < other_bar.low or self.low > other_bar.high)
    
    def get_body_midpoint(self) -> float:
        """Get midpoint of the body (open-close range)"""
        return (self.open + self.close) / 2
    
    def percentage_change(self) -> float:
        """Get percentage change from open to close"""
        if self.open == 0:
            return 0.0
        return ((self.close - self.open) / self.open) * 100
    
    def __repr__(self):
        """String representation of the bar"""
        direction = "↑" if self.is_bullish else "↓" if self.is_bearish else "─"
        
        return (
            f"Bar({self.timestamp.strftime('%Y-%m-%d %H:%M')} | "
            f"O:{self.open:.5f} H:{self.high:.5f} L:{self.low:.5f} C:{self.close:.5f} | "
            f"{direction} V:{self.volume})"
        )
    
    def __str__(self):
        """String representation for human reading"""
        return self.__repr__()
    
    def __eq__(self, other):
        """Check equality based on timestamp and OHLCV data"""
        if not isinstance(other, Bar):
            return NotImplemented
        
        return (
            self.timestamp == other.timestamp and
            self.open == other.open and
            self.high == other.high and
            self.low == other.low and
            self.close == other.close and
            self.volume == other.volume
        )
    
    def __hash__(self):
        """Hash based on timestamp and OHLCV data"""
        return hash((
            self.timestamp,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume
        ))
    
    def __lt__(self, other):
        """Compare bars by timestamp"""
        if not isinstance(other, Bar):
            return NotImplemented
        return self.timestamp < other.timestamp
    
    def __gt__(self, other):
        """Compare bars by timestamp"""
        if not isinstance(other, Bar):
            return NotImplemented
        return self.timestamp > other.timestamp
    
    def to_dict(self) -> dict:
        """Convert bar to dictionary representation"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'body': self.body,
            'range': self.range,
            'is_bullish': self.is_bullish,
            'is_bearish': self.is_bearish,
            'is_doji': self.is_doji,
            'is_weak': self.is_weak,
            'is_head_down': self.is_head_down,
            'is_head_up': self.is_head_up
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Bar':
        """Create Bar instance from dictionary"""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            open_price=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data.get('volume', 0)
        )
    
    @classmethod
    def from_mt5_rate(cls, rate_data, timestamp: datetime) -> 'Bar':
        """Create Bar instance from MT5 rate data"""
        return cls(
            timestamp=timestamp,
            open_price=float(rate_data['open']),
            high=float(rate_data['high']),
            low=float(rate_data['low']),
            close=float(rate_data['close']),
            volume=int(rate_data['tick_volume'])
        )
