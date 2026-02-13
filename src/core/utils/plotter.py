from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta, time, date
import pandas as pd
from pathlib import Path
import json
from config.settings import settings

# Chart generation libraries
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.offline as pyo
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("Warning: Plotly not available. Install with: pip install plotly")

# Fallback to matplotlib if plotly not available
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    import mplfinance as mpf
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: Matplotlib/mplfinance not available. Install with: pip install matplotlib mplfinance")

from src.core.models.bar import Bar
from src.core.models.signal import Signal, SignalAction
from src.core.utils.logger import TradingLogger
from config.settings import settings


class TradingPlotter:
    """
    Clean, trader-focused chart generator with:
    - Interactive candlestick charts (no volume)
    - Trading signal rectangles stretching to outcome timestamp
    - MBox session highlighting in blue (price-range height)
    - Simplified performance reports with proper lot sizes
    """

    def __init__(self, report_dir: str = "reports"):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.logger = TradingLogger.get_main_logger()
        
        # Load configuration
        self.mbox_hours = settings.get("strategies.two_hunters.mbox_time")
        self.london_hours = settings.get("strategies.two_hunters.sessions.london")
        self.newyork_hours = settings.get("strategies.two_hunters.sessions.newyork")
        
        # Color schemes - updated with blue MBox
        self.colors = {
            'bullish': '#00ff88',
            'bearish': '#ff4444',
            'mbox': 'rgba(52, 152, 219, 0.3)',  # Changed to blue
            'newyork': 'rgba(8, 153, 129, 0.15)',  # Changed to blue
            'london': 'rgba(255, 152, 0, 0.15)',  # Changed to blue
            'stoploss': 'rgba(255, 68, 68, 0.3)',  # Red for SL rectangles
            'takeprofit': 'rgba(0, 255, 136, 0.3)'  # Green for TP rectangles
        }

    def bars_to_dataframe(self, bars: List[Bar], for_mplfinance: bool = False) -> pd.DataFrame:
        """Convert bars to pandas DataFrame"""
        data = []
        for bar in bars:
            data.append({
                'timestamp': bar.timestamp,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': getattr(bar, 'volume', 0)
            })
        
        df = pd.DataFrame(data)
        
        if for_mplfinance:
            # Rename columns for mplfinance compatibility
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High', 
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            df.set_index('timestamp', inplace=True)
        
        return df

    def plot_candlestick_interactive(
        self, 
        bars: List[Bar],
        _15m_bars: List[Bar] = None,
        signals: Optional[List[Signal]] = None, 
        symbol: str = "SYMBOL", 
        title: str = None, 
        show_mbox: bool = False,
        show_15m_bars: bool = False,
        save_path: Optional[Path] = None,
        return_as_div: bool = False
    ) -> str:
        """
        Create clean interactive candlestick chart with signal rectangles
        
        Args:
            bars: List of OHLC bars
            signals: Optional list of trading signals
            symbol: Trading symbol name
            title: Chart title
            show_mbox: Whether to show MBox highlights
            save_path: Specific path to save file (optional)
            return_as_div: If True, returns plotly HTML div instead of saving file
            
        Returns:
            File path (if saved) or HTML div (if return_as_div=True)
        """
        
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly not available, falling back to static chart")
            return self.plot_ohlc(bars, signals, symbol=symbol, title=title)
        
        if not bars:
            self.logger.warning("No bars provided for plotting")
            return ""
        
        try:
            # Convert bars to DataFrame
            df = self.bars_to_dataframe(bars)
            
            # Create single plot (no volume subplot)
            fig = go.Figure()
            
            # Add candlestick chart (1-minute bars)
            fig.add_trace(go.Candlestick(
                x=df['timestamp'],
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name=symbol,
                increasing=dict(
                    line=dict(color=self.colors["bullish"]),
                    fillcolor=self.colors["bullish"]
                ),
                decreasing=dict(
                    line=dict(color=self.colors["bearish"]),
                    fillcolor=self.colors["bearish"]
                ),
                showlegend=True,
                legendgroup="1m"
            ))

            # === INLINED 15-MINUTE BAR OVERLAY ===
            if show_15m_bars:
                self.show_15m_bars(fig, _15m_bars)

            # Add MBox highlights (blue, price-range height only)
            if show_mbox:
                self.add_mbox_highlights(fig, df['timestamp'], bars)
                self.add_london_highlights(fig, df['timestamp'], bars)
                self.add_newyork_highlights(fig, df['timestamp'], bars)
            
            # Add trading signal rectangles stretching to outcome timestamp
            if signals:
                self.add_signal_rectangles(fig, signals, bars)
            
            _day_range = (df['low'].min(), df['high'].max())
            _time_range_for_fvgs = (bars[0].timestamp, bars[-1].timestamp)
            self.add_fvg_rectangles(fig, symbol, ['H1', 'M15'], _time_range_for_fvgs, _day_range)

            # Update layout
            chart_title = title or f"{symbol} Trading Analysis - {bars[0].timestamp.date()} to {bars[-1].timestamp.date()}"
            fig.update_layout(
                title={
                    'text': chart_title,
                    'x': 0.5,
                    'xanchor': 'center',
                    'font': {'size': 20, 'color': '#2c3e50'}
                },
                xaxis_rangeslider_visible=False,
                autosize=True,
                height=None,
                width=None,
                margin=dict(
                    l=10,
                    r=10,
                    t=50,
                    b=40,
                    pad=0
                ),
                template='plotly_white',
                font=dict(family="Arial, sans-serif", size=12),
                dragmode='pan',  
                hovermode='closest', 
                showlegend=True, 
                xaxis=dict(
                    rangeslider=dict(visible=False),
                    showspikes=True,
                    spikethickness=1,
                    spikecolor='gray',
                    spikemode='across',
                    spikesnap='cursor'
                ),
                yaxis=dict(
                    showspikes=True,
                    spikethickness=1,
                    spikecolor='gray',
                    spikemode='across',
                    spikesnap='cursor'
                )
            )
            
            # Only return div if requested, otherwise save to specified path ONLY
            if return_as_div:
                return pyo.plot(fig, output_type='div', include_plotlyjs=True)
            
            # Save chart only if save_path is provided (no default file generation)
            if save_path is not None:
                save_path = Path(save_path)
                
                # Ensure directory exists
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Save the chart using plotly offline
                pyo.plot(fig, filename=str(save_path), auto_open=False)
                
                # Validate file was created
                if save_path.exists():
                    self.logger.info(f"Chart saved: {save_path}")
                    return str(save_path)
                else:
                    self.logger.error(f"Failed to create chart at {save_path}")
                    return ""
                
        except Exception as e:
            self.logger.error(f"Error creating interactive chart: {e}")
            # Fall back to static chart if save_path was provided
            if save_path is not None:
                return self.plot_ohlc(bars, signals, symbol=symbol, title=title, save_path=save_path)
            return ""

    def show_15m_bars(self, fig, _15m_bars):
        try:
            
            if len(_15m_bars) > 100:
                bars = _15m_bars[-100:]
                self.logger.info(f"Breached max iterations. limiting to 100")
            else:
                bars = _15m_bars

            # Convert 15m bars to DataFrame
            df_15m = self.bars_to_dataframe(bars)

            # Draw 15-minute candles as shapes (for proper width control)
            opacity = 0.3
            shapes = []
            counter = 1
            self.logger.info(f"Loop start.")
            for idx, row in df_15m.iterrows():
                if round(len(bars) / 10)*counter == idx:
                    counter+=1
                
                candle_start = row['timestamp']
                candle_end = candle_start + timedelta(minutes=15)
                
                # Determine colors
                is_bullish = row['close'] >= row['open']
                base_color = self.colors["bullish"] if is_bullish else self.colors["bearish"]
                
                # Convert hex to rgba
                if base_color.startswith('#'):
                    r = int(base_color[1:3], 16)
                    g = int(base_color[3:5], 16)
                    b = int(base_color[5:7], 16)
                    fill_color = f'rgba({r},{g},{b},{opacity})'
                    line_color = f'rgba({r},{g},{b},{min(opacity + 0.3, 1.0)})'
                else:
                    fill_color = base_color
                    line_color = base_color
                
                # Draw wicks (centered at 7.5 minutes)
                wick_center = candle_start + timedelta(minutes=7.5)
                
                # Upper wick
                if row['high'] > max(row['open'], row['close']):
                    fig.add_shape(
                        type="line",
                        x0=wick_center, y0=max(row['open'], row['close']),
                        x1=wick_center, y1=row['high'],
                        line=dict(color=line_color, width=2.5),
                        layer="below"
                    )
                
                # Lower wick
                if row['low'] < min(row['open'], row['close']):
                    fig.add_shape(
                        type="line",
                        x0=wick_center, y0=row['low'],
                        x1=wick_center, y1=min(row['open'], row['close']),
                        line=dict(color=line_color, width=2.5),
                        layer="below"
                    )
                
                # Draw body (spans full 15 minutes with small margins)
                body_start = candle_start + timedelta(seconds=15)
                body_end = candle_end - timedelta(seconds=15)

                shapes.append(dict(
                    type="rect",
                    x0=body_start, y0=row['open'],
                    x1=body_end, y1=row['close'],
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=1.5),
                    layer="below"
                ))

            self.logger.info(f"Loop end and Fig update start")
            fig.update_layout(shapes=list(fig.layout.shapes) + shapes)
            self.logger.info(f"Fig update end")

        except Exception as e:
            self.logger.error(f"Error adding 15M overlay: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
        # === END INLINED 15-MINUTE BAR OVERLAY ===

    def add_mbox_highlights(self, fig, timestamps, bars: List[Bar]):
        """Add MBox session highlights in blue with price-range height"""
        start_date = timestamps.min().date()
        end_date = timestamps.max().date()
        current_date = start_date
        
        start_time = datetime.strptime(self.mbox_hours['start'], "%H:%M").time()
        end_time = datetime.strptime(self.mbox_hours['end'], "%H:%M").time()
        
        while current_date <= end_date:
            mbox_start = datetime.combine(current_date, start_time)
            mbox_end = datetime.combine(current_date, end_time)

            # Handle MBox crossing midnight
            if end_time < start_time:
                mbox_end += timedelta(days=1)
            
            # Find price range during MBox hours
            mbox_bars = [bar for bar in bars if mbox_start <= bar.timestamp <= mbox_end]
            
            if mbox_bars:
                min_price = min(bar.low for bar in mbox_bars)
                max_price = max(bar.high for bar in mbox_bars)

                # Add blue rectangle with price-range height
                fig.add_shape(
                    type="rect",
                    x0=mbox_start,
                    y0=min_price,
                    x1=mbox_end,
                    y1=max_price,
                    fillcolor=self.colors['mbox'],  # Blue color
                    opacity=0.5,
                    layer="below",
                    line_width=0
                )
                
                # Add annotation
                fig.add_annotation(
                    x=mbox_start + (mbox_end - mbox_start) / 2,
                    y=max_price,
                    text="mbox",
                    showarrow=False,
                    font=dict(color="#2980b9", size=12),  # Blue text
                    bgcolor="rgba(255,255,255,0.8)"
                )
                
            current_date += timedelta(days=1)

    def add_london_highlights(self, fig, timestamps, bars: List[Bar]):
        """Add London session highlights in blue with price-range height"""
        start_date = timestamps.min().date()
        end_date = timestamps.max().date()
        current_date = start_date
        
        start_time = datetime.strptime(self.london_hours['start'], "%H:%M").time()
        end_time = datetime.strptime(self.london_hours['end'], "%H:%M").time()
        
        while current_date <= end_date:
            mbox_start = datetime.combine(current_date, start_time)
            mbox_end = datetime.combine(current_date, end_time)

            # Handle MBox crossing midnight
            if end_time < start_time:
                mbox_end += timedelta(days=1)
            
            # Find price range during MBox hours
            mbox_bars = [bar for bar in bars if mbox_start <= bar.timestamp <= mbox_end]
            
            if mbox_bars:
                min_price = min(bar.low for bar in mbox_bars)
                max_price = max(bar.high for bar in mbox_bars)

                # Add blue rectangle with price-range height
                fig.add_shape(
                    type="rect",
                    x0=mbox_start,
                    y0=min_price,
                    x1=mbox_end,
                    y1=max_price,
                    fillcolor=self.colors['london'],  # Blue color
                    opacity=0.5,
                    layer="below",
                    line_width=0
                )
                

                # Add annotation
                fig.add_annotation(
                    x=mbox_start + (mbox_end - mbox_start) / 2,
                    y=max_price,
                    text="london",
                    showarrow=False,
                    font=dict(color="#ff9800", size=12),  # Blue text
                    bgcolor="rgba(255,255,255,0.8)"
                )
                
            current_date += timedelta(days=1)

    def add_newyork_highlights(self, fig, timestamps, bars: List[Bar]):
        """Add newyork session highlights in blue with price-range height"""
        start_date = timestamps.min().date()
        end_date = timestamps.max().date()
        current_date = start_date
        
        start_time = datetime.strptime(self.newyork_hours['start'], "%H:%M").time()
        end_time = datetime.strptime(self.newyork_hours['end'], "%H:%M").time()
        
        while current_date <= end_date:
            mbox_start = datetime.combine(current_date, start_time)
            mbox_end = datetime.combine(current_date, end_time)

            # Handle MBox crossing midnight
            if end_time < start_time:
                mbox_end += timedelta(days=1)
            
            # Find price range during MBox hours
            mbox_bars = [bar for bar in bars if mbox_start <= bar.timestamp <= mbox_end]
            
            if mbox_bars:
                min_price = min(bar.low for bar in mbox_bars)
                max_price = max(bar.high for bar in mbox_bars)

                # Add blue rectangle with price-range height
                fig.add_shape(
                    type="rect",
                    x0=mbox_start,
                    y0=min_price,
                    x1=mbox_end,
                    y1=max_price,
                    fillcolor=self.colors['newyork'],  # Blue color
                    opacity=0.5,
                    layer="below",
                    line_width=0
                )
                
                # Add annotation
                fig.add_annotation(
                    x=mbox_start + (mbox_end - mbox_start) / 2,
                    y=max_price,
                    text="newyork",
                    showarrow=False,
                    font=dict(color="#089981", size=12),  # Blue text
                    bgcolor="rgba(255,255,255,0.8)"
                )
                
            current_date += timedelta(days=1)

    def add_signal_rectangles(self, fig, signals: List[Signal], bars: List[Bar]):
        """Add trading signal visualization with separate areas and lines"""
        
        for signal in signals:
            if not hasattr(signal, 'timestamp') or not signal.timestamp:
                continue
                
            # Find corresponding bar
            signal_bar = None
            for bar in bars:
                if abs((bar.timestamp - signal.timestamp).total_seconds()) <= 60:
                    signal_bar = bar
                    break
                    
            if not signal_bar:
                continue
                
            # Determine end time for rectangles
            if hasattr(signal, 'outcome_timestamp') and signal.outcome_timestamp:
                end_time = signal.outcome_timestamp
            else:
                # Default to 4 hours if no outcome timestamp
                end_time = signal.timestamp + timedelta(hours=4)
            
            # PART 1: INITIAL SIGNAL AREAS (Rectangles)
            # These show the original risk/reward zones using INITIAL prices
            initial_entry = getattr(signal, 'initial_entry_price', signal.entry_price)
            initial_sl = getattr(signal, 'initial_stop_loss', signal.stop_loss)
            initial_tp = getattr(signal, 'initial_take_profit', signal.take_profit)
            
            # Add Initial Stop Loss rectangle (red) - based on INITIAL prices
            if initial_sl is not None:
                fig.add_shape(
                    type="rect",
                    x0=signal.timestamp,
                    y0=min(initial_entry, initial_sl),
                    x1=end_time,
                    y1=max(initial_entry, initial_sl),
                    fillcolor="rgba(255, 68, 68, 0.2)" if not signal.used_flag else "rgba(204, 204, 204, 0.1)",
                    opacity=0.4,
                    layer="below",
                    line=dict(color="red", width=1, dash="dot"),
                    name="Initial SL Zone"
                )
            
            # Add Initial Take Profit rectangle (green) - based on INITIAL prices  
            if initial_tp is not None:
                fig.add_shape(
                    type="rect",
                    x0=signal.timestamp,
                    y0=min(initial_entry, initial_tp),
                    x1=end_time,
                    y1=max(initial_entry, initial_tp),
                    fillcolor="rgba(0, 255, 136, 0.2)" if not signal.used_flag else "rgba(204, 204, 204, 0.05)",
                    opacity=0.4,
                    layer="below",
                    line=dict(color="green", width=1, dash="dot"),
                    name="Initial TP Zone"
                )
            
            # PART 2: CURRENT LEVELS (Lines)
            # These show the adjusted/current SL, TP, Entry levels
            
            # Add Current Entry Line (blue solid) - use current entry price
            current_entry = signal.entry_price
            fig.add_shape(
                type="line",
                x0=signal.timestamp,
                y0=current_entry,
                x1=end_time,
                y1=current_entry,
                line=dict(color="blue" if not signal.used_flag else "grey", width=3),
                name="Current Entry"
            )
            
            # Add Current Stop Loss Line (red solid)
            if hasattr(signal, 'stop_loss') and signal.stop_loss is not None:
                fig.add_shape(
                    type="line",
                    x0=signal.timestamp,
                    y0=signal.stop_loss,
                    x1=end_time,
                    y1=signal.stop_loss,
                    line=dict(color="red" if not signal.used_flag else "grey", width=2),
                    name="Current SL"
                )
            
            # Add Current Take Profit Line (green solid)
            if hasattr(signal, 'take_profit') and signal.take_profit is not None:
                fig.add_shape(
                    type="line",
                    x0=signal.timestamp,
                    y0=signal.take_profit,
                    x1=end_time,
                    y1=signal.take_profit,
                    line=dict(color="green" if not signal.used_flag else "grey", width=2),
                    name="Current TP"
                )
            
            # PART 3: SIGNAL MARKERS AND ANNOTATIONS
            # Add entry marker (blue circle at initial entry)
            fig.add_trace(go.Scatter(
                x=[signal.timestamp],
                y=[initial_entry],
                mode='markers',
                marker=dict(
                    size=12,
                    color='blue' if not signal.used_flag else "grey",
                    symbol='circle',
                    line=dict(color='white', width=2)
                ),
                name=f"Entry {signal.action.value}",
                showlegend=False,
                hovertext=f"Entry: {initial_entry:.5f}<br>" +
                         f"Current SL: {round(signal.stop_loss, 5) if hasattr(signal, 'stop_loss') and signal.stop_loss else 'NA'}<br>" +
                         f"Current TP: {round(signal.take_profit, 5) if hasattr(signal, 'take_profit') and signal.take_profit else 'NA'}<br>" +
                         f"Entry Lot: {signal.entry_lot if signal.entry_lot else 'NA'}<br>" +
                         f"SLP: {round(signal.stop_loss_pips, 1) if signal.stop_loss_pips else 'NA'}<br>" +
                         f"TPP: {round(signal.take_profit_pips, 1) if signal.take_profit_pips else 'NA'}<br>" +
                         f"Signal type: {signal.signal_type.name}"
            ))
            
            # PART 4: OUTCOME MARKERS
            if (hasattr(signal, 'outcome') and signal.outcome and 
                hasattr(signal, 'outcome_timestamp') and signal.outcome_timestamp):
                
                if not signal.used_flag:
                    outcome_color = "green" if signal.gain >= 0 else "red"
                else:
                    outcome_color = "grey"
                outcome_symbol = "triangle-up" if signal.gain >= 0 else "triangle-down"
                
                # CORRECTED: Determine actual exit price based on outcome
                if signal.gain >= 0:
                    # Win means TP was hit - exit at current TP level
                    actual_exit_price = signal.exit_price
                else:
                    # Loss means SL was hit - exit at current SL level
                    actual_exit_price = signal.exit_price
                
                if actual_exit_price is not None:
                    fig.add_trace(go.Scatter(
                        x=[signal.outcome_timestamp],
                        y=[actual_exit_price],
                        mode='markers',
                        marker=dict(
                            size=15,
                            color=outcome_color,
                            symbol=outcome_symbol,
                            line=dict(color='white', width=2)
                        ),
                        name=f"Exit {signal.outcome.value.upper()}",
                        showlegend=False,
                        hovertext=f"Exit Price: {actual_exit_price:.5f}<br>" +
                                 f"Initial Entry: {initial_entry:.5f}<br>" +
                                 f"Gain: {round(getattr(signal, 'gain', 'NA'), 2) if getattr(signal, 'gain', None) is not None else 'NA'}"
                    ))

    def add_fvg_rectangles(self, fig, symbol: str, timeframes: List[str] = None, 
                           date_range: tuple[datetime, datetime] = None, day_range: tuple[int, int] = None) -> None:        
        
        if timeframes is None:
            timeframes = ['H1', 'M15']
        
        try:
            # Get FVG cache directory
            fvg_dir = Path("reports") / "fvgs"
            if not fvg_dir.exists():
                self.logger.warning(f"FVG cache directory not found: {fvg_dir}")
                return
            
            # Build cache file path
            cache_path = fvg_dir / f"{symbol}_fvgs.json"
            if not cache_path.exists():
                self.logger.warning(f"No FVG cache found for {symbol}")
                return
            
            # Load FVG data from JSON
            with open(cache_path, 'r', encoding='utf-8') as f:
                fvg_data = json.load(f)
            
            # self.logger.info(f"Loaded FVG data for {symbol} from {cache_path}")
            
            # Process each timeframe
            for tf, fvg_list in fvg_data.items():
                if tf not in timeframes:
                    continue
                
                if not fvg_list:
                    continue
                
                # Sort FVGs by detection_time
                sorted_fvg_list = sorted(
                    fvg_list,
                    key=lambda x: datetime.fromisoformat(x['detection_time'])
                )
                
                # Filter by date_range if provided
                todays_fvgs = []
                if date_range is not None:
                    start_date, end_date = date_range
                    day_low, day_high = day_range
                    
                    for fvg in sorted_fvg_list:
                        if fvg['low'] > day_high+((day_high-day_low)/2): continue
                        if fvg['high'] < day_low-((day_high-day_low)/2): continue

                        if end_date <= datetime.fromisoformat(fvg['bar_open_time']):
                            continue
                        
                        if fvg['filled_timestamp'] is None:
                            todays_fvgs.append(fvg)
                            continue
                        
                        if start_date >= datetime.fromisoformat(fvg['filled_timestamp']):
                            continue

                        if datetime.fromisoformat(fvg['detection_time']) < start_date:
                            fvg['detection_time'] = (start_date - timedelta(minutes=30)).isoformat()

                        if datetime.fromisoformat(fvg['filled_timestamp']) > end_date:
                            fvg['filled_timestamp'] = (end_date + timedelta(minutes=30)).isoformat()

                        todays_fvgs.append(fvg)

                if not sorted_fvg_list:
                    # self.logger.info(f"No FVGs found for {symbol}/{tf} within date range")
                    continue
                
                # self.logger.info(f"Processing {len(sorted_fvg_list)} FVGs for {symbol}/{tf}")
                
                # Draw each FVG as a rectangle
                for fvg in todays_fvgs:
                    self._draw_fvg_rectangle(fig, fvg, symbol, tf)
        
        except Exception as e:
            self.logger.error(f"Error adding FVG rectangles: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def _draw_fvg_rectangle(self, fig, fvg: Dict[str, Any], symbol: str, timeframe: str) -> None:
        """
        Draw a single FVG rectangle on the chart.
        
        Rectangle spans from detection_time to filled_timestamp (or now if unfilled).
        Color and opacity depend on FVG type and fill status.
        
        Args:
            fig: Plotly figure to draw on
            fvg: FVG dictionary with keys: type, high, low, bar_open_time, 
                detection_time, filled_timestamp
            symbol: Trading symbol
            timeframe: Timeframe (for reference/logging)
            index: Index of FVG (for unique naming)
        """
        from datetime import datetime

        try:
            # Extract FVG properties
            fvg_type = fvg.get('type', 'unknown')
            high = fvg.get('high', 0)
            low = fvg.get('low', 0)
            detection_time_str = fvg.get('detection_time', '')
            filled_time_str = fvg.get('filled_timestamp')
            size_pips = fvg.get('size_pips', 0)
            
            # Parse timestamps
            try:
                detection_time = datetime.fromisoformat(detection_time_str)
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid detection_time: {detection_time_str}")
                return
            
            # End time is filled timestamp or now
            if filled_time_str:
                try:
                    filled_time = datetime.fromisoformat(filled_time_str)
                    end_time = filled_time
                    is_filled = True
                except (ValueError, TypeError):
                    self.logger.warning(f"Invalid filled_timestamp: {filled_time_str}")
                    end_time = detection_time + timedelta(days=2)
                    is_filled = False
            else:
                end_time = detection_time + timedelta(days=2)
                is_filled = False
            
            # Determine color and opacity based on FVG type
            if fvg_type == 'bullish':
                fill_color = 'rgba(0, 200, 100, 0.15)'  # Green, low opacity
                line_color = 'rgba(0, 150, 80, 0.6)'    # Darker green
                name_prefix = 'Bullish FVG'
            elif fvg_type == 'bearish':
                fill_color = 'rgba(255, 80, 80, 0.15)'  # Red, low opacity
                line_color = 'rgba(200, 40, 40, 0.6)'   # Darker red
                name_prefix = 'Bearish FVG'
            else:
                fill_color = 'rgba(150, 150, 150, 0.1)'  # Gray
                line_color = 'rgba(100, 100, 100, 0.5)'
                name_prefix = 'FVG'
            
            # Adjust line style based on fill status
            line_dash = 'solid' if is_filled else 'dot'
            
            # Create rectangle name with useful info
            rect_name = (f"{name_prefix} | {symbol}/{timeframe} | "
                        f"Size: {size_pips:.1f}p | "
                        f"{'Filled' if is_filled else 'Active'}")
            
            # Add rectangle to figure
            fig.add_shape(
                type='rect',
                x0=detection_time,
                y0=low,
                x1=end_time,
                y1=high,
                fillcolor=fill_color,
                line=dict(
                    color=line_color,
                    width=1.5,
                    dash=line_dash
                ),
                layer='below',
                name=rect_name
            )
            
            # Optional: Add text label at midpoint of rectangle
            if size_pips > 5:  # Only label large FVGs to avoid clutter
                mid_time = detection_time + (end_time - detection_time) / 2
                mid_price = (high + low) / 2
                label_text = f"{size_pips:.1f}p"
                
                fig.add_annotation(
                    x=mid_time,
                    y=mid_price,
                    text=label_text,
                    showarrow=False,
                    font=dict(size=9, color='rgba(0, 0, 0, 0.5)'),
                    bgcolor='rgba(255, 255, 255, 0.7)',
                    borderpad=2
                )
        
        except Exception as e:
            self.logger.error(f"Error drawing FVG rectangle for {fvg}: {e}")

    def plot_ohlc(
        self, 
        bars: List[Bar], 
        signals: Optional[List[Signal]] = None, 
        symbol: str = "SYMBOL", 
        title: str = None, 
        save_path: Optional[Path] = None
    ) -> str:
        """Create static OHLC chart using matplotlib as fallback"""
        
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("Neither Plotly nor Matplotlib available for plotting")
            return ""
        
        # Convert bars to DataFrame for mplfinance
        df = self.bars_to_dataframe(bars, for_mplfinance=True)
        
        # Set up the plot
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{symbol}_static_{timestamp}.png"
            save_path = self.report_dir / "static" / filename
        else:
            save_path = Path(save_path)
        
        # Ensure directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        chart_title = title or f"{symbol} Trading Analysis"
        
        # Create the plot (no volume, simplified)
        mpf.plot(
            df,
            type='candle',
            style='charles',
            title=chart_title,
            ylabel='Price',
            volume=False,  # No volume
            figsize=(16, 8),
            savefig=dict(fname=str(save_path), dpi=300, bbox_inches='tight')
        )
        
        self.logger.info(f"Static chart saved: {save_path}")
        return str(save_path)

    def create_symbol_comparison_report(
        self,
        results: Dict[str, List[Signal]],
        chartpaths: Dict[str, Dict[int, str]] = None,
        savepath: Optional[Path] = None
    ) -> str:
        """
        Create symbol comparison report with signals details section
        
        No changes needed - already works with the new chartpaths structure!
        """
        if savepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"{timestamp}"
            savepath = self.report_dir / filepath / "report.html"
        
        # Ensure directory exists
        savepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Calculate comprehensive metrics for each symbol
        allsignals = []
        individualstats = {}
        
        for symbol, signals in results.items():
            if symbol == "all":
                continue
            
            
            _multipyer_list = [s.take_profit_pips / s.stop_loss_pips for s in signals]
            multipyer = sum(_multipyer_list) / len(_multipyer_list) if _multipyer_list else 0
            completed = [s for s in signals if hasattr(s, 'is_completed') and s.is_completed]

            if completed:
                wins = [s for s in completed if hasattr(s, 'gain') and s.gain and s.gain >= 0]
                losses = [s for s in completed if hasattr(s, 'gain') and s.gain and s.gain < 0]
                
                wingains = [s.gain for s in wins if hasattr(s, 'gain') and s.gain]
                lossgains = [s.gain for s in losses if hasattr(s, 'gain') and s.gain]
                
                totalprofit = sum(s.gain for s in completed if hasattr(s, 'gain') and s.gain)
                totalcommission = sum(s.commission for s in completed if hasattr(s, 'commission') and s.commission)
                totallotsizes = sum(s.entry_lot for s in completed if hasattr(s, 'entry_lot') and s.entry_lot)
                
                individualstats[symbol] = {
                    "totaltrades": len(completed),
                    "wins": len(wins),
                    "losses": len(losses),
                    "winrate": (len(wins) / len(completed)) * 100,
                    "totalprofit": totalprofit,
                    "totalcommission": totalcommission,
                    "avgprofit": totalprofit / len(completed),
                    "avglotsize": round(totallotsizes / len(completed), 2),
                    "maxwin": max(wingains) if wingains else 0,
                    "maxloss": min(lossgains) if lossgains else 0,
                    "avgwin": sum(wingains) / len(wingains) if wingains else 0,
                    "avgloss": sum(lossgains) / len(lossgains) if lossgains else 0
                }
                
                allsignals.extend(completed)
        
        # Calculate joint/overall statistics
        jointstats = self.calculate_joint_statistics(allsignals)
        
        # Create cumulative chart
        chartshtml = ""
        if jointstats.get("signals"):
            chartshtml = self.create_cumulative_chart_only(jointstats)
        
        # Generate HTML with new structure
        htmlcontent = self.generate_report_html_with_signals(
            chartshtml=chartshtml,
            individualstats=individualstats,
            jointstats=jointstats,
            chartpaths=chartpaths
        )
        
        with open(savepath, "w", encoding="utf-8") as f:
            f.write(htmlcontent)
        
        return str(savepath)

    def calculate_joint_statistics(self, all_signals: List[Signal]) -> Dict[str, Any]:
        """Calculate joint statistics across all signals, including drawdown and underwater time"""

        if not all_signals:
            return {}

        # Configurable initial balance; fall back to a sane default if missing/invalid
        initial_balance = settings.get("account.initial_balance")
        try:
            initial_balance = float(initial_balance) if initial_balance is not None else 10000.0
        except Exception:
            initial_balance = 10000.0

        # Keep only signals that are not marked used_flag
        usable = [s for s in all_signals if not getattr(s, "used_flag", False)]

        # Aggregations on usable signals
        wins = [s for s in usable if getattr(s, 'gain', None) is not None and s.gain >= 0]
        losses = [s for s in usable if getattr(s, 'gain', None) is not None and s.gain < 0]
        win_gains = [s.gain for s in wins if s.gain is not None]
        loss_gains = [s.gain for s in losses if s.gain is not None]
        total_profit = sum(s.gain for s in usable if getattr(s, 'gain', None) is not None)

        # Sort usable signals by timestamp; stable fallback for missing timestamps
        signals_sorted = sorted(
            usable,
            key=lambda s: (s.timestamp if getattr(s, "timestamp", None) else datetime.min)
        )

        # Build equity curve starting at initial_balance
        equity_points = []  # list[(ts, equity)]
        equity = float(initial_balance)

        # Seed an initial point to establish the baseline peak at the start of series
        seed_ts = signals_sorted[0].timestamp if signals_sorted and signals_sorted[0].timestamp else datetime.min
        equity_points.append((seed_ts, equity))

        for s in signals_sorted:
            gain = s.gain if getattr(s, "gain", None) is not None else 0.0
            equity += gain
            ts = s.timestamp if getattr(s, "timestamp", None) else (equity_points[-1][0] + timedelta(microseconds=1))
            equity_points.append((ts, equity))

        _multipyer_list = [s.take_profit_pips / s.stop_loss_pips for s in signals_sorted]
        multipyer = sum(_multipyer_list) / len(_multipyer_list) if _multipyer_list else 0.0
       
        max_dd_abs = 0.0
        max_dd_pct = 0.0
        longest_uw = timedelta(0)
        current_uw_start: Optional[datetime] = None

        # Initialize rolling peak to initial_balance
        peak_equity = equity_points[0][1] if equity_points else initial_balance

        for ts, eq in equity_points:
            # New peak closes any underwater interval
            if eq > peak_equity + 1e-12:
                if current_uw_start is not None:
                    longest_uw = max(longest_uw, ts - current_uw_start)
                    current_uw_start = None
                peak_equity = eq

            dd_abs = max(0.0, peak_equity - eq)
            # Percent drawdown guarded against tiny peaks
            dd_pct = (dd_abs / peak_equity) if peak_equity > 1e-9 else 0.0

            if dd_abs > max_dd_abs:
                max_dd_abs = dd_abs
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # Track underwater intervals
            if eq < peak_equity - 1e-12:
                if current_uw_start is None:
                    current_uw_start = ts
            else:
                if current_uw_start is not None:
                    longest_uw = max(longest_uw, ts - current_uw_start)
                    current_uw_start = None

        # If still underwater at the end, close the interval at the last timestamp
        if current_uw_start is not None:
            last_ts = equity_points[-1][0]
            longest_uw = max(longest_uw, last_ts - current_uw_start)


        # Group equity points by date and calculate daily P&L and drawdown
        from collections import defaultdict
        
        daily_equity = defaultdict(list)  # {date: [equity_values]}
        
        for ts, eq in equity_points:
            date = ts.date()
            daily_equity[date].append(eq)
        
        # Calculate daily metrics
        daily_drawdowns = []  # List of (date, dd_abs, dd_pct)
        daily_pnl = []  # List of (date, pnl)
        
        sorted_dates = sorted(daily_equity.keys())
        for date in sorted_dates:
            day_equity_values = daily_equity[date]
            
            # Daily high/low equity
            day_high = max(day_equity_values)
            day_low = min(day_equity_values)

            # Calculate drawdown from daily peak to daily low
            daily_dd_abs = max(0.0, day_high - day_low)
            daily_dd_pct = (daily_dd_abs / day_high) if day_high > 1e-9 else 0.0
            
            daily_drawdowns.append((date, daily_dd_abs, daily_dd_pct))
            
        
        # Find maximum daily drawdown
        daily_dd_abs = max((dd[1] for dd in daily_drawdowns), default=0.0)
        daily_dd_pct = max((dd[2] for dd in daily_drawdowns), default=0.0)

        return {
            'total_signals': len(usable),
            'total_wins': len(wins),
            'total_losses': len(losses),
            'overall_win_rate': (len(wins) / len(usable)) * 100 if usable else 0.0,
            'total_profit': total_profit,
            'avg_profit_per_trade': (total_profit / len(usable)) if usable else 0.0,
            'max_win': max(win_gains) if win_gains else 0.0,
            'max_loss': min(loss_gains) if loss_gains else 0.0,
            'avg_win': (sum(win_gains) / len(win_gains)) if win_gains else 0.0,
            'avg_loss': (sum(loss_gains) / len(loss_gains)) if loss_gains else 0.0,
            'total_win_amount': sum(win_gains) if win_gains else 0.0,
            'total_loss_amount': sum(loss_gains) if loss_gains else 0.0,
            'profit_factor': (abs(sum(win_gains) / sum(loss_gains)) if loss_gains and sum(loss_gains) != 0 else float('inf')),
            'signals': all_signals,
            'initial_balance': initial_balance,
            'final_equity': equity,
            
            # Overall drawdown metrics
            'drawdown_abs': max_dd_abs,
            'drawdown_pct': max_dd_pct * 100.0,
            'underwater_time': longest_uw,
            
            # Daily drawdown metrics
            'daily_drawdown_abs': daily_dd_abs,
            'daily_drawdown_pct': daily_dd_pct * 100.0,
        }

    def create_cumulative_chart_only(self, joint_stats: Dict) -> str:
        """Create only the joint cumulative performance chart"""
        charts_html = ""
        if joint_stats.get('signals'):
            fig_cumulative = self.create_joint_cumulative_chart(
                                    joint_stats['signals'], joint_stats['daily_drawdown_pct'], 
                                    joint_stats['drawdown_pct'], joint_stats['underwater_time'])
            
            chart_div = pyo.plot(
                fig_cumulative,
                output_type='div',
                include_plotlyjs=False,
                config={'responsive': True, 'displayModeBar': True}
            )
            charts_html = f"""
            <div class="chart-section">
                <h3>Joint Performance</h3>
                <div class="chart-container">
                    {chart_div}
                </div>
            </div>
            """
        return charts_html

    def create_joint_cumulative_chart(self, signals: List[Signal], daily_pct, pct, uwt) -> go.Figure:
        """Create joint cumulative performance chart for all signals"""
        
        fig = go.Figure()
        
        # Sort signals by timestamp
        sorted_signals = sorted(signals, key=lambda s: s.timestamp if hasattr(s, 'timestamp') and s.timestamp else datetime.min)
        sorted_signals = [s for s in sorted_signals if not s.used_flag]

        # Calculate cumulative PL
        cumulative_pnl = [0]
        dates = [sorted_signals[0].timestamp if sorted_signals and hasattr(sorted_signals[0], 'timestamp') else datetime.now()]
        total = 0
        
        for signal in sorted_signals:
            if hasattr(signal, 'gain') and signal.gain:
                total += signal.gain
            cumulative_pnl.append(total)
            dates.append(signal.timestamp if hasattr(signal, 'timestamp') else datetime.now())
        
        # Add the main cumulative line
        fig.add_trace(go.Scatter(
            x=dates,
            y=cumulative_pnl,
            mode='lines+markers',
            name='Joint Profit',
            line=dict(color='#27ae60', width=4),
            marker=dict(size=6),
            fill='tonexty' if cumulative_pnl[-1] > 0 else None,
            fillcolor='rgba(46, 204, 113, 0.15)'
        ))
        
        # Add zero line for reference
        fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Breakeven")
        
        # Add individual symbol traces (different colors)
        colors = ['#e74c3c', '#9b59b6', '#f39c12', '#e67e22', '#1abc9c', '#95a5a6', '#34495e', '#27ae60']
        symbol_cumulative = {}
        
        for i, signal in enumerate(sorted_signals):
            symbol = getattr(signal, 'symbol', 'Unknown')
            if symbol not in symbol_cumulative:
                symbol_cumulative[symbol] = {'dates': [dates[0]], 'values': [0], 'total': 0}
            
            if hasattr(signal, 'gain') and signal.gain:
                symbol_cumulative[symbol]['total'] += signal.gain
                symbol_cumulative[symbol]['dates'].append(signal.timestamp if hasattr(signal, 'timestamp') else datetime.now())
                symbol_cumulative[symbol]['values'].append(symbol_cumulative[symbol]['total'])
        
        # Add individual symbol traces
        for i, (symbol, data) in enumerate(symbol_cumulative.items()):
            color = colors[i % len(colors)]
            fig.add_trace(go.Scatter(
                x=data['dates'],
                y=data['values'],
                mode='lines',
                name=f"{symbol} Profit",
                line=dict(color=color, width=2, dash='dot'),
                opacity=0.8
            ))
        
        # Add annotations for final values
        for symbol, data in symbol_cumulative.items():
            if data['values'] and data['dates']:
                final_value = data['values'][-1]
                final_date = data['dates'][-1]
                fig.add_annotation(
                    x=final_date,
                    y=final_value,
                    text=f"${final_value:.0f}",
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=2,
                    arrowcolor=colors[list(symbol_cumulative.keys()).index(symbol) % len(colors)],
                    bgcolor="white",
                    bordercolor=colors[list(symbol_cumulative.keys()).index(symbol) % len(colors)],
                    borderwidth=1,
                    font=dict(size=10)
                )
        
        fig.update_layout(
            title={
                'text': f'Daily DrawDown pct: {round(daily_pct, 2)}%    -    DrawDown pct: {round(pct, 2)}%    -    UnderWater Time: {uwt.days} days',
                'x': 0.5,
                'xanchor': 'right'
            },
            xaxis_title="Date",
            yaxis_title="Profit ($)",
            autosize=True,
            height=None,
            width=None,
            template='plotly_white',
            dragmode='pan',
            hovermode='closest',
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="rgba(0,0,0,0.2)",
                borderwidth=1
            ),
            margin=dict(
                l=60,
                r=150,
                t=60,
                b=60,
                pad=0
            )
        )
        
        return fig

    def create_flags_summary_section(self) -> str:
        """Create trading configuration summary with badge-style layout"""
        
        commission = settings.get("trading.commission")
        risk = settings.get("account.default_risk_percent")
        use_trend_flag = settings.get("strategies.two_hunters.flags.use_trend_flag")
        use_risk_manager = settings.get("strategies.two_hunters.flags.use_risk_manager")
        use_online_commission_manager = settings.get("strategies.two_hunters.flags.use_online_commission_manager")
        use_offline_commission_manager = settings.get("strategies.two_hunters.flags.use_offline_commission_manager")
        use_2R_for_EUR = settings.get("strategies.two_hunters.flags.use_2r_for_eur")
        use_large_slp_flag = settings.get("strategies.two_hunters.flags.use_large_slp_flag")
        use_time_flag = settings.get("strategies.two_hunters.flags.use_time_flag")
        balance = settings.get("account.initial_balance")

        # Helper to generate badge HTML
        def create_badge(label, value, is_active, icon=""):
            if not is_active:
                bg = "background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);"
                text_color = "color: white;"
                border = "border: 2px solid #c0392b;"
            else:
                bg = "background: linear-gradient(135deg, #27ae60 0%, #229954 100%);"
                text_color = "color: white;"
                border = "border: 2px solid #229954;"
            
            return f"""
            <div style="{bg} {border} {text_color} padding: 12px 24px; border-radius: 25px; 
                        display: inline-flex; align-items: center; gap: 10px; 
                        box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin: 8px;
                        font-weight: 600; font-size: 14px; white-space: nowrap;">
                <span style="font-size: 18px;">{icon}</span>
                <span>{label}: <strong>{value}</strong></span>
            </div>
            """

        # Generate badges
        trend_badge = create_badge(
            "Trend Flag", 
            "ACTIVE" if use_trend_flag else "INACTIVE",
            use_trend_flag,
            "📊"
        )
        
        time_badge = create_badge(
            "Time Flag",
            "ACTIVE" if use_time_flag else "INACTIVE", 
            use_time_flag,
            "⏰"
        )
        
        risk_mgr_badge = create_badge(
            "Risk Manager",
            "ACTIVE" if use_risk_manager else "INACTIVE",
            use_risk_manager,
            "🛡️"
        )
        
        _2R_for_EUR_str = create_badge(
            "1:2R for EUR",
            "ACTIVE" if use_2R_for_EUR else "INACTIVE",
            use_2R_for_EUR,
            "💱"
        )

        online_commission_mgr_badge = create_badge(
            "On-Comm Manager",
            "ACTIVE" if use_online_commission_manager else "INACTIVE",
            use_online_commission_manager,
            "💲"
        )

        offline_commission_mgr_badge = create_badge(
            "Off-Comm Manager",
            "ACTIVE" if use_offline_commission_manager else "INACTIVE",
            use_offline_commission_manager,
            "🧾"
        )

        large_slp_str = create_badge(
            "Large SLP Manager",
            "ACTIVE" if use_large_slp_flag else "INACTIVE",
            use_large_slp_flag,
            "🛠️"
        )

        return f"""
        <div class="flags-section" style="background: white; border-radius: 10px; padding: 25px; 
            box-shadow: 0 5px 15px rgba(0,0,0,0.1); margin-bottom: 30px;">
            
            <div style="border-left: 5px solid #3498db; padding-left: 20px; margin-bottom: 20px;">
                <h3 style="color: #2c3e50; margin: 0 0 5px 0; font-size: 1.6em;">Trading Configuration</h3>
                <p style="color: #7f8c8d; margin: 0; font-size: 0.95em;">Account settings and strategy flags</p>
            </div>

            <!-- Account Settings Row -->
            <div style="display: flex; flex-wrap: wrap; gap: 15px; align-items: center; 
                        padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 20px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 20px;">💰</span>
                    <span style="color: #2c3e50; font-size: 14px;">
                        <strong>Balance:</strong> ${balance:,.2f}
                    </span>
                </div>
                <div style="width: 2px; height: 30px; background: #ddd;"></div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 20px;">💸</span>
                    <span style="color: #2c3e50; font-size: 14px;">
                        <strong>Commission:</strong> ${commission}/lot
                    </span>
                </div>
                <div style="width: 2px; height: 30px; background: #ddd;"></div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 20px;">⚖️</span>
                    <span style="color: #2c3e50; font-size: 14px;">
                        <strong>Risk:</strong> {(risk or 0) * 100:.1f}%
                    </span>
                </div>
            </div>

            <!-- Strategy Flags Row -->
            <div style="border-top: 2px dashed #e0e0e0; padding-top: 20px;">
                <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 10px;">
                    {trend_badge}
                    {time_badge}
                    {risk_mgr_badge}
                    {_2R_for_EUR_str}
                    {online_commission_mgr_badge}
                    {offline_commission_mgr_badge}
                    {large_slp_str}
                </div>
            </div>
        </div>
        """

    def create_joint_summary_section(self, joint_stats: Dict) -> str:
        """Create joint summary section with key metrics"""
        
        if not joint_stats:
            return ""
        
        win_percent = (joint_stats.get('total_profit', 0) / joint_stats.get('initial_balance', 0)) * 100
        current_budget = joint_stats.get('final_equity', 0)
        return f"""
        <div class="chart-section">
            <h3>Overall Performance</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0;">
                <div style="background: rgba(39, 174, 96, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #27ae60;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{joint_stats.get('overall_win_rate', 0):.1f}%</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Win/Loss Rate</div>
                </div>
                <div style="background: rgba(52, 152, 219, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #3498db;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{win_percent:.2f}%</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Profit Percent</div>
                </div>
                <div style="background: rgba(230, 126, 34, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #e67e22;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">${current_budget:.0f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Current Budget</div>
                </div>
                <div style="background: rgba(231, 76, 60, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #e74c3c;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{joint_stats.get('daily_drawdown_pct', 0):.1f}%</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Daily DrawDown Percent</div>
                </div>
                <div style="background: rgba(52, 73, 94, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #34495e;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{abs(joint_stats.get('drawdown_pct', 0)):.1f}%</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">DrawDown Percent</div>
                </div>
                <div style="background: rgba(155, 89, 182, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #9b59b6;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{joint_stats.get('total_signals', 0):.0f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Total Signals</div>
                </div>
            </div>
        </div>
        """


    def create_individual_stats_table(self, individualstats: Dict) -> str:
        """
        Create individual symbol statistics table with all details
        
        FIXED: Added more columns for comprehensive statistics
        """
        
        if not individualstats:
            return "<p>No individual statistics available.</p>"
        
        tablerows = ""
        for symbol, stats in individualstats.items():
            win_rate = stats.get('winrate', 0)
            total_profit = stats.get('totalprofit', 0)
            
            profit_class = "win" if total_profit > 0 else "loss" if total_profit < 0 else "neutral"
            avg_lot_size = stats.get('avglotsize', 0)
            
            tablerows += f"""
            <tr>
                <td><strong>{symbol.rstrip(".")}</strong></td>
                <td>{stats.get('totaltrades', 0)}</td>
                <td>{stats.get('wins', 0)}</td>
                <td>{stats.get('losses', 0)}</td>
                <td><b>{win_rate:.1f}%</b></td>
                <td class="{profit_class}">{total_profit:.2f}</td>
                <td>{stats.get('totalcommission', 0):.2f}</td>
                <td>{stats.get('avgprofit', 0):.2f}</td>
                <td class="win">{stats.get('maxwin', 0):.2f}</td>
                <td class="loss">{stats.get('maxloss', 0):.2f}</td>
                <td class="win">{stats.get('avgwin', 0):.2f}</td>
                <td class="loss">{stats.get('avgloss', 0):.2f}</td>
                <td>{avg_lot_size}</td>
            </tr>
            """
        
        return f"""
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Total Trades</th>
                        <th>Wins</th>
                        <th>Losses</th>
                        <th>Win Rate</th>
                        <th>Total Profit</th>
                        <th>Total Commission</th>
                        <th>Avg Profit per Trade</th>
                        <th>Max Win</th>
                        <th>Max Loss</th>
                        <th>Avg Win</th>
                        <th>Avg Loss</th>
                        <th>Avg Lot Size</th>
                    </tr>
                </thead>
                <tbody>
                    {tablerows}
                </tbody>
            </table>
        </div>
        """

    def generate_charts(
            self,
            date_range: Tuple[datetime, datetime],
            results: Dict[str, List[Signal]],
            reportdir: Path,
            showmbox: bool = True,
            show_15m_bars: bool = False,
            dispaly_timeframe: str = "M1",
            display_range: str = "monthly" #, "daily"
        ) -> Dict[str, Dict[str, str]]:
        """
        Generate daily charts for each symbol by fetching bars from MT5.
        """
        from collections import defaultdict
        from datetime import timedelta
        from src.core.data.fetcher import DataFetcher
        
        fetcher = DataFetcher()
        start_date, end_date = date_range

        if display_range not in ["daily", "monthly"]:
            self.logger.error("Invaild display range given. Use 'monthly' or 'daily'.")
            return defaultdict(dict)

        # Get all symbols from results (excluding 'all')
        symbols = [sym for sym in results.keys() if sym != "all"]
        
        # Organize signals by symbol and DATE (not month)
        symbol_date_signals = defaultdict(lambda: defaultdict(list))
        for symbol, signals in results.items():
            if symbol == "all":
                continue
            for signal in signals:
                if hasattr(signal, 'timestamp') and signal.timestamp:
                    if display_range == 'daily':
                        display_date = signal.timestamp.date()
                    elif display_range == 'monthly':
                        display_date = signal.timestamp.date().replace(day=1)
                    symbol_date_signals[symbol][display_date].append(signal)
        
        # Generate list of dates to process
        current_date = start_date.date()
        dates_to_process = []
        
        # Storage for chart paths - RELATIVE paths for portability
        chartpaths = defaultdict(dict)

        if display_range == "daily":
            while current_date <= end_date.date():
                # Create datetime objects for the entire day
                date_start = datetime.combine(current_date, time(3, 30))
                date_end = datetime.combine(current_date+timedelta(days=1), time(3, 30))
                dates_to_process.append((current_date, date_start, date_end))
                current_date += timedelta(days=1)

        elif display_range == "monthly":
            import calendar
            def add_one_month(d: date) -> date:
                year = d.year
                month = d.month + 1
                if month > 12:
                    month = 1
                    year += 1
                last_day = calendar.monthrange(year, month)[1]
                day = min(d.day, last_day)
                return date(year, month, day)

            while current_date <= end_date.date():
                date_start = datetime.combine(current_date, time(3, 30))
                next_month_date = add_one_month(current_date)
                date_end = datetime.combine(next_month_date, time(3, 30))
                dates_to_process.append((current_date, date_start, date_end))
                current_date = next_month_date

        self.logger.info(f"Processing {len(dates_to_process)} {display_range} charts for {len(symbols)} symbols")

        for symbol in symbols:
            # Create symbol directory inside reportdir
            symbol_clean = symbol.rstrip('.').replace('/', '_')
            symboldir = reportdir / symbol_clean
            symboldir.mkdir(parents=True, exist_ok=True)
            
            # self.logger.info(f"Processing {symbol_clean}: {len(dates_to_process)} days...")
            for date_obj, date_start, date_end in dates_to_process:
                try:
                    # Get 1-minute bars for this day
                    # self.logger.info(f"Fetching 1M bars for {symbol_clean} - {date_obj}")
                    bars_1m = fetcher.fetch_bars_from_mt5(
                        start_dt=date_start,
                        end_dt=date_end,
                        symbol=symbol,
                        timeframe=dispaly_timeframe
                    )
                    
                    if not bars_1m:
                        # self.logger.warning(f"No 1M bars found for {symbol_clean} on {date_obj}")
                        continue
                    
                    # Fetch 15-minute bars for this date
                    if show_15m_bars:
                        bars_15m = []
                        # self.logger.info(f"Fetching 15M bars for {symbol_clean} - {date_obj}")
                        bars_15m = fetcher.fetch_bars_from_mt5(
                            start_dt=date_start,
                            end_dt=date_end,
                            symbol=symbol,
                            timeframe="M15"
                        )
                        # self.logger.info(f"Fetched {len(bars_15m)} 15M bars for {symbol_clean} - {date_obj}")
                    
                    # Get signals for this date
                    date_signals = symbol_date_signals[symbol][date_obj]
                    chartpath = symboldir / f"{date_obj}.html"

                    # Generate the chart
                    if date_signals:
                        self.plot_candlestick_interactive(
                            bars=bars_1m,
                            _15m_bars=bars_15m if show_15m_bars else [],
                            signals=date_signals if date_signals else None,
                            symbol=symbol,
                            title=f"{symbol_clean} - {date_obj.strftime('%Y-%m-%d')}",
                            show_mbox=showmbox,
                            show_15m_bars=show_15m_bars,
                            save_path=chartpath,
                            return_as_div=False
                        )
                        
                        relative_path = f"{symbol_clean}/{date_obj}.html"
                        chartpaths[symbol][date_obj.strftime("%Y-%m-%d")] = relative_path
                        
                        # self.logger.info(f"Generated chart: {relative_path} ({len(bars_1m)} bars, {len(date_signals)} signals)")
                    
                except Exception as e:
                    self.logger.error(f"Error generating chart for {symbol} on {date_obj}: {e}")
                    import traceback
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    continue
        
        return chartpaths

    def generate_report_html_with_signals(
        self,
        chartshtml: str,
        individualstats: Dict,
        jointstats: Dict,
        chartpaths: Dict[int, str] = None
    ) -> str:
        """Generate HTML report with signals details section"""
        
        # Create summary sections - FLAGS FIRST for prominence
        flags_summary = self.create_flags_summary_section()
        joint_summary = self.create_joint_summary_section(jointstats)
        individual_table = self.create_individual_stats_table(individualstats)
        
        # Create signals details section
        signals_details = self.create_signals_details_section(
            jointstats.get("signals", []),
            chartpaths
        )

        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Trading Report</title>
            <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                }}
                .container {{
                    max-width: 1800px;
                    margin: 0 auto;
                    background: rgba(255, 255, 255, 0.95);
                    border-radius: 15px;
                    padding: 30px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                }}
                .chart-section {{
                    margin-bottom: 40px;
                    background: white;
                    border-radius: 10px;
                    padding: 20px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                }}
                .chart-section h3 {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 15px;
                    margin-bottom: 25px;
                    font-size: 1.8em;
                }}
                .section-divider {{
                    border: none;
                    height: 3px;
                    background: linear-gradient(to right, transparent, #3498db, transparent);
                    margin: 40px 0;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}
                th {{
                    background-color: #3498db;
                    color: white;
                    font-weight: bold;
                    position: sticky;
                    top: 0;
                }}
                tr:nth-child(even) {{
                    background-color: #f8f9fa;
                }}
                tr:hover {{
                    background-color: #e8f4f8;
                    transition: background-color 0.2s;
                }}
                .win {{
                    color: #27ae60;
                    font-weight: bold;
                }}
                .loss {{
                    color: #e74c3c;
                    font-weight: bold;
                }}
                .neutral {{
                    color: #7f8c8d;
                }}
                .btn-show-chart {{
                    background: linear-gradient(135deg, #3498db, #2980b9);
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 13px;
                    font-weight: 600;
                    transition: all 0.3s;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                }}
                .btn-show-chart:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
                }}
                .btn-show-chart:disabled {{
                    background: #95a5a6;
                    cursor: not-allowed;
                    transform: none;
                }}
                table tbody tr.flagged {{
                    background-color: rgb(107 114 128 / 10%);
                    color: #374151;
                    border-left: 4px solid rgb(139 0 0 / 35%);
                }}
                table tbody tr.flagged td {{
                    color: #374151;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <!-- Trading Configuration (NEW STYLE) -->
                {flags_summary}
                
                <!-- Overall Performance Metrics (EXISTING GRID STYLE) -->
                {joint_summary}
                
                <!-- Performance Chart -->
                {chartshtml}
                
                <hr class="section-divider">
                
                <!-- Individual Symbol Stats -->
                <div class="chart-section">
                    <h3> Symbol Sumary </h3>
                    {individual_table}
                </div>
                
                <hr class="section-divider">
                
                <!-- Signals Details -->
                {signals_details}
            </div>
            
            <script>
                function openChart(chartFile, signalTime) {{
                    if (!chartFile) {{
                        alert('Chart file not available for this signal');
                        return;
                    }}
                    window.open(chartFile, '_blank');
                }}
            </script>
        </body>
        </html>
        """
        
        return html_template
    
    def create_signals_details_section(
        self,
        signals: List[Signal],
        chartpaths: Dict[str, Dict[int, str]] = None
    ) -> str:
        """Create signals details section with links to symbol-separated charts"""
        
        if not signals:
            return '<div class="chart-section"><h3>Signals Details</h3><p>No signals to display.</p></div>'
        
        # Sort signals by timestamp
        sorted_signals = sorted(
            signals,
            key=lambda s: s.timestamp if hasattr(s, 'timestamp') and s.timestamp else datetime.min
        )
        
        # Import Budget for balance calculation
        from src.core.models.budget import Budget
        budget = Budget()
        
        tablerows = ""
        for i, signal in enumerate(sorted_signals, 1):
            # Extract all signal information
            timestamp = signal.timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(signal, 'timestamp') and signal.timestamp else "N/A"
            symbol = getattr(signal, 'symbol', 'Unknown')
            action = signal.action.value if hasattr(signal, 'action') else 'N/A'
            
            # # Entry and exit prices
            # entry_price = f"{signal.entry_price:.5f}" if hasattr(signal, 'entry_price') and signal.entry_price else "N/A"
            # sl_price = f"{signal.stop_loss:.5f}" if hasattr(signal, 'stop_loss') and signal.stop_loss else "N/A"
            # tp_price = f"{signal.take_profit:.5f}" if hasattr(signal, 'take_profit') and signal.take_profit else "N/A"
            
            # Signal type
            signal_type = signal.signal_type.value.upper() if hasattr(signal, 'signal_type') and signal.signal_type else "N/A"

            # Outcome and adjustments
            outcome = signal.outcome.value.upper() if hasattr(signal, 'outcome') and signal.outcome else 'PENDING'
            sl_adjusted = signal.sl_adjusted_count if hasattr(signal, 'sl_adjusted_count') else 0
            
            # Lot size and pips
            lot_size = f"{signal.entry_lot:.2f}" if hasattr(signal, 'entry_lot') and signal.entry_lot else "N/A"
            sl_pips = f"{signal.stop_loss_pips:.2f}" if hasattr(signal, 'stop_loss_pips') and signal.stop_loss_pips else "N/A"
            tp_pips = f"{signal.take_profit_pips:.2f}" if hasattr(signal, 'take_profit_pips') and signal.take_profit_pips else "N/A"
            
            # Commission and profit
            commission = f"{signal.commission:.2f}" if hasattr(signal, 'commission') and signal.commission else "0.00"
            profit = f"{signal.gain:.2f}" if hasattr(signal, 'gain') and signal.gain is not None else "0.00"
            
            # Calculate balance
            budget.apply_signal_gain(signal) if not signal.used_flag else None
            current_balance = round(budget.current_balance)
            
            # Find chart file
            chart_file = ""
            chart_available = False

            if chartpaths and hasattr(signal, 'timestamp') and signal.timestamp:
                # exact date check
                date_str = signal.timestamp.strftime("%Y-%m-%d")
                if symbol in chartpaths and date_str in chartpaths[symbol]:
                    chart_file = chartpaths[symbol][date_str]
                    chart_available = True
                else:
                    # fallback: same year/month, day = 1
                    first_day_dt = signal.timestamp.replace(day=1)
                    first_day_str = first_day_dt.strftime("%Y-%m-%d")
                    if symbol in chartpaths and first_day_str in chartpaths[symbol]:
                        chart_file = chartpaths[symbol][first_day_str]
                        chart_available = True

            # Create button
            if chart_available:
                chart_button = f'<button class="btn-show-chart" onclick="openChart(\'{chart_file}\', \'{timestamp}\')">Show in Chart</button>'
            else:
                chart_button = '<button class="btn-show-chart" disabled>No Chart</button>'
            
            # Determine CSS class for outcome
            outcome_class = "win" if hasattr(signal, 'gain') and signal.gain and signal.gain > 0 else "loss" if hasattr(signal, 'gain') and signal.gain and signal.gain < 0 else "neutral"
            has_flag = signal.used_flag
            row_class = "flagged" if has_flag else ""

            tablerows += f"""
            <tr class="{row_class}">
                <td>{i}</td>
                <td>{timestamp}</td>
                <td>{symbol}</td>
                <td>{action}</td>
                <td>{signal_type}</td>
                <td class="{outcome_class}">{outcome}</td>
                <td>{sl_adjusted}</td>
                <td>{lot_size}</td>
                <td>{sl_pips}</td>
                <td>{tp_pips}</td>
                <td>{commission}</td>
                <td class="{outcome_class}">{profit}</td>
                <td>{current_balance}</td>
                <td>{chart_button}</td>
            </tr>
            """
        
        return f"""
        <div class="chart-section">
            <h3>Signals Details</h3>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>DateTime</th>
                            <th>Symbol</th>
                            <th>Action</th>
                            <th>Type</th>
                            <th>Outcome</th>
                            <th>SL Adj</th>
                            <th>Lot Size</th>
                            <th>SL Pips</th>
                            <th>TP Pips</th>
                            <th>Commission</th>
                            <th>Profit</th>
                            <th>Balance</th>
                            <th>Chart</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tablerows}
                    </tbody>
                </table>
            </div>
        </div>
        """
