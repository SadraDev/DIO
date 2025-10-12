from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path
import json

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
        self.mbox_hours = settings.get('strategies.two_hunters.mbox_time')
        
        # Color schemes - updated with blue MBox
        self.colors = {
            'bullish': '#00ff88',
            'bearish': '#ff4444', 
            'mbox': 'rgba(52, 152, 219, 0.3)',  # Changed to blue
            'stop_loss': 'rgba(255, 68, 68, 0.3)',  # Red for SL rectangles
            'take_profit': 'rgba(0, 255, 136, 0.3)'  # Green for TP rectangles
        }
    
    def plot_candlestick_interactive(
        self,
        bars: List[Bar],
        signals: Optional[List[Signal]] = None,
        symbol: str = "SYMBOL",
        title: str = None,
        show_mbox: bool = True,
        savepath: Optional[Path] = None
    ) -> str:
        """
        Create clean interactive candlestick chart with signal rectangles
        """
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly not available, falling back to static chart")
            return self.plot_ohlc(bars, signals, symbol=symbol, title=title)
        
        if not bars:
            self.logger.warning("No bars provided for plotting")
            return ""
        
        # Convert bars to DataFrame
        df = self._bars_to_dataframe(bars)
        
        # Create single plot (no volume subplot)
        fig = go.Figure()
        
        # Add candlestick chart
        fig.add_trace(
            go.Candlestick(
                x=df['timestamp'],
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name=symbol,
                increasing_line_color=self.colors['bullish'],
                decreasing_line_color=self.colors['bearish'],
                increasing_fillcolor=self.colors['bullish'],
                decreasing_fillcolor=self.colors['bearish']
            )
        )
        
        # Add MBox highlights (blue, price-range height only)
        if show_mbox:
            self._add_mbox_highlights_fixed(fig, df['timestamp'], bars)
        
        # Add trading signal rectangles stretching to outcome timestamp
        if signals:
            self._add_signal_rectangles_extended(fig, signals, bars)
        
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
            height=700,
            width=1400,
            template='plotly_white',
            font=dict(family="Arial, sans-serif", size=12),
            dragmode='pan',           # FIX 1: Set pan as default instead of zoom
            hovermode='closest',      # FIX 2: Allow free cursor movement  
            showlegend=True,
            # FIX 3: Configure crosshair lines (horizontal + vertical)
            xaxis=dict(
                showspikes=True,      # Enable vertical crosshair line
                spikethickness=1,     # Thin line
                spikecolor='gray',    # Subtle color
                spikemode='across',   # Line spans full chart height
                spikesnap='cursor'    # Follows mouse cursor
            ),
            yaxis=dict(
                showspikes=True,      # Enable horizontal crosshair line  
                spikethickness=1,     # Thin line
                spikecolor='gray',    # Subtle color
                spikemode='across',   # Line spans full chart width
                spikesnap='cursor'    # Follows mouse cursor
            )
        )
        
        # Save chart
        if savepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{symbol}_interactive_{timestamp}.html"
            savepath = self.report_dir / filename
        else:
            savepath = Path(savepath)

        return str(savepath)
    
    def plot_ohlc(
        self,
        bars: List[Bar],
        signals: Optional[List[Signal]] = None,
        symbol: str = "SYMBOL",
        title: str = None,
        savepath: Optional[Path] = None
    ) -> str:
        """
        Create static OHLC chart using matplotlib as fallback
        """
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("Neither Plotly nor Matplotlib available for plotting")
            return ""
        
        # Convert bars to DataFrame for mplfinance
        df = self._bars_to_dataframe(bars, for_mplfinance=True)
        
        # Set up the plot
        if savepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{symbol}_static_{timestamp}.png"
            savepath = self.report_dir / "static" / filename
        else:
            savepath = Path(savepath)
        
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
            savefig=dict(fname=str(savepath), dpi=300, bbox_inches='tight')
        )
        
        self.logger.info(f"Static chart saved: {savepath}")
        return str(savepath)
    
    def create_performance_report(
        self,
        signals: List[Signal],
        symbol: str = "SYMBOL",
        savepath: Optional[Path] = None
    ) -> str:
        """
        Create simplified performance report with cumulative P&L chart and signals table
        """
        if not signals:
            self.logger.warning("No signals provided for performance report")
            return ""
        
        if savepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{symbol}_performance_{timestamp}.html"
            savepath = self.report_dir / "interactive" / filename
        
        # Get completed signals
        completed_signals = [s for s in signals if hasattr(s, 'is_completed') and s.is_completed]
        if not completed_signals:
            self.logger.warning("No completed signals for performance analysis")
            return ""
        
        wins = sum(1 for s in completed_signals if hasattr(s, 'outcome') and s.outcome and s.outcome.value == 'win')
        total_profit = sum(s.gain for s in completed_signals if hasattr(s, 'gain') and s.gain)
        
        # Create single cumulative P&L chart
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            
            # Cumulative P&L line
            cumulative_pnl = []
            total = 0
            dates = []
            for signal in completed_signals:
                if hasattr(signal, 'gain') and signal.gain and hasattr(signal, 'timestamp') and signal.timestamp:
                    total += signal.gain
                    cumulative_pnl.append(total)
                    dates.append(signal.timestamp)
            
            if dates and cumulative_pnl:
                fig.add_trace(
                    go.Scatter(
                        x=dates,
                        y=cumulative_pnl,
                        mode='lines+markers',
                        name='Cumulative P&L',
                        line=dict(color='#3498db', width=3),
                        marker=dict(size=6)
                    )
                )
            
            fig.update_layout(
                title=f"{symbol} Cumulative Performance",
                height=400,
                template='plotly_white',
                xaxis_title="Date",
                yaxis_title="Cumulative P&L ($)"
            )
            
            # Generate HTML with signals table
            html_content = self._generate_simple_performance_html(fig, completed_signals, symbol, total_profit, wins)
            
            with open(savepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
        
        self.logger.info(f"Performance report saved: {savepath}")
        return str(savepath)
    
    # Helper methods
    def _bars_to_dataframe(self, bars: List[Bar], for_mplfinance: bool = False) -> pd.DataFrame:
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
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High', 
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            df.set_index('timestamp', inplace=True)
        
        return df
    
    def _add_mbox_highlights_fixed(self, fig, timestamps, bars: List[Bar]):
        """Add MBox session highlights in blue with price-range height (not full chart)"""
        start_date = timestamps.min().date()
        end_date = timestamps.max().date()
        current_date = start_date
        
        start_time = datetime.strptime(self.mbox_hours['start'], '%H:%M').time()
        end_time = datetime.strptime(self.mbox_hours['end'], '%H:%M').time()
        
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
                    text="MBox",
                    showarrow=False,
                    font=dict(color="#2980b9", size=12),  # Blue text
                    bgcolor="rgba(255,255,255,0.8)"
                )
            
            current_date += timedelta(days=1)
    
    def _add_signal_rectangles_extended(self, fig, signals: List[Signal], bars: List[Bar]):
        """
        Add trading signal visualization with separate areas and lines
        CORRECTED: Proper initial vs current level visualization
        """
        for signal in signals:
            if not hasattr(signal, 'timestamp') or not signal.timestamp:
                continue
            
            # Find corresponding bar
            signal_bar = None
            for bar in bars:
                if abs((bar.timestamp - signal.timestamp).total_seconds()) < 60:
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
            
            # === PART 1: INITIAL SIGNAL AREAS (Rectangles) ===
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
                    fillcolor='rgba(255, 68, 68, 0.2)',  # Light red for initial SL area
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
                    fillcolor='rgba(0, 255, 136, 0.2)',  # Light green for initial TP area
                    opacity=0.4,
                    layer="below",
                    line=dict(color="green", width=1, dash="dot"),
                    name="Initial TP Zone"
                )
            
            # === PART 2: CURRENT LEVELS (Lines) ===
            # These show the adjusted/current SL, TP, Entry levels
            
            # Add Current Entry Line (blue solid) - use current entry price
            current_entry = signal.entry_price
            fig.add_shape(
                type="line",
                x0=signal.timestamp,
                y0=current_entry,
                x1=end_time,
                y1=current_entry,
                line=dict(color="blue", width=3),
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
                    line=dict(color="red", width=2),
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
                    line=dict(color="green", width=2),
                    name="Current TP"
                )
            
            # === PART 3: SIGNAL MARKERS AND ANNOTATIONS ===
            
            # Add entry marker (blue circle) at initial entry
            fig.add_trace(
                go.Scatter(
                    x=[signal.timestamp],
                    y=[initial_entry],
                    mode='markers',
                    marker=dict(
                        size=12,
                        color='blue',
                        symbol='circle',
                        line=dict(color='white', width=2)
                    ),
                    name=f"Entry {signal.action.value}",
                    showlegend=False,
                    hovertext=f"Initial Entry: {initial_entry:.5f}<br>Initial SL: {round(initial_sl, 5) if initial_sl else 'N/A'}<br>Current SL: {round(signal.stop_loss, 5) if hasattr(signal, 'stop_loss') and signal.stop_loss else 'N/A'}<br>Initial TP: {round(initial_tp, 5) if initial_tp else 'N/A'}<br>Current TP: {round(signal.take_profit, 5) if hasattr(signal, 'take_profit') and signal.take_profit else 'N/A'}"
                )
            )
            
            # === PART 4: OUTCOME MARKERS (CORRECTED) ===
            if hasattr(signal, 'outcome') and signal.outcome and hasattr(signal, 'outcome_timestamp') and signal.outcome_timestamp:
                outcome_color = 'green' if signal.outcome.value == 'win' else 'red'
                outcome_symbol = 'triangle-up' if signal.outcome.value == 'win' else 'triangle-down'
                
                # CORRECTED: Determine actual exit price based on outcome
                if signal.outcome.value == 'win':
                    # Win means TP was hit - exit at current TP level
                    actual_exit_price = signal.take_profit
                else:
                    # Loss means SL was hit - exit at current SL level  
                    actual_exit_price = signal.stop_loss
                
                if actual_exit_price is not None:
                    fig.add_trace(
                        go.Scatter(
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
                            hovertext=f"Exit Price: {actual_exit_price:.5f}<br>Initial Entry: {initial_entry:.5f}<br>Gain: ${round(getattr(signal, 'gain', 'N/A')) if getattr(signal, 'gain', None) is not None else 'N/A'}"
                        )
                    )

    def _generate_clean_html(self, fig, title: str, symbol: str, bars: List[Bar], signals: List[Signal] = None) -> str:
        """
        Generate clean HTML with updated legend for new visualization
        UPDATED: Legend reflects initial areas vs current lines
        """
        
        # Convert plotly figure to HTML
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=True)
        
        # Calculate statistics
        date_range = f"{bars[0].timestamp.date()} to {bars[-1].timestamp.date()}"
        signals_count = len(signals) if signals else 0
        
        # Calculate total gain
        completed_signals = [s for s in (signals or []) if hasattr(s, 'is_completed') and s.is_completed]
        total_gain = sum(s.gain for s in completed_signals if hasattr(s, 'gain') and s.gain)
        wins = sum(1 for s in completed_signals if hasattr(s, 'outcome') and s.outcome and s.outcome.value == 'win')
        win_rate = (wins / len(completed_signals) * 100) if completed_signals else 0
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        html_template = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }}
            .container {{
                max-width: 1600px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: linear-gradient(45deg, #2c3e50, #3498db);
                color: white;
                border-radius: 10px;
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }}
            .stat-card {{
                background: rgba(52, 152, 219, 0.1);
                padding: 15px;
                border-radius: 10px;
                text-align: center;
                border-left: 4px solid #3498db;
            }}
            .stat-value {{
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
            }}
            .stat-label {{
                font-size: 14px;
                color: #7f8c8d;
                margin-top: 5px;
            }}
            .chart-container {{
                background: white;
                border-radius: 10px;
                padding: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            }}
            .controls {{
                margin: 20px 0;
                text-align: center;
            }}
            .control-button {{
                background: #3498db;
                color: white;
                border: none;
                padding: 10px 20px;
                margin: 0 10px;
                border-radius: 5px;
                cursor: pointer;
                transition: background 0.3s;
            }}
            .control-button:hover {{
                background: #2980b9;
            }}
            .legend {{
                background: rgba(255, 255, 255, 0.9);
                padding: 15px;
                border-radius: 10px;
                margin-top: 20px;
                border: 1px solid #ddd;
            }}
            .legend-item {{
                display: inline-block;
                margin: 5px 15px;
                font-size: 14px;
            }}
            .legend-color {{
                display: inline-block;
                width: 20px;
                height: 15px;
                margin-right: 8px;
                border-radius: 3px;
            }}
            .legend-line {{
                display: inline-block;
                width: 20px;
                height: 3px;
                margin-right: 8px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 {title}</h1>
                <p>Generated on {current_time}</p>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">${total_gain:.2f}</div>
                    <div class="stat-label">Total Gain</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{date_range}</div>
                    <div class="stat-label">Date Range</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{signals_count}</div>
                    <div class="stat-label">Total Signals</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{win_rate:.1f}%</div>
                    <div class="stat-label">Win Rate</div>
                </div>
            </div>
            
            <div class="controls">
                <button class="control-button" onclick="toggleFullscreen()">🔍 Fullscreen</button>
            </div>
            
            <div class="chart-container" id="chart">
                {plot_div}
            </div>
        </div>
        
        <script>
            function toggleFullscreen() {{
                const chart = document.getElementById('chart');
                if (!document.fullscreenElement) {{
                    chart.requestFullscreen().then(() => {{
                        // Force chart to expand to full width
                        const plotlyDiv = chart.querySelector('[data-plotly-graph]');
                        if (plotlyDiv) {{
                            Plotly.relayout(plotlyDiv, {{
                                width: window.screen.width,
                                height: window.screen.height - 100
                            }});
                        }}
                    }});
                }} else {{
                    document.exitFullscreen().then(() => {{
                        // Restore original size
                        const plotlyDiv = chart.querySelector('[data-plotly-graph]');
                        if (plotlyDiv) {{
                            Plotly.relayout(plotlyDiv, {{
                                width: 1400,
                                height: 700
                            }});
                        }}
                    }});
                }}
            }}
        </script>
    </body>
    </html>"""
        
        return html_template
    
    def _generate_simple_performance_html(self, fig, signals: List[Signal], symbol: str, total_profit: float, wins: int) -> str:
        """Generate simplified performance report HTML with signals table"""
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=True)
        
        # Create signals table with correct lot size field
        table_rows = ""
        from src.core.models.budget import Budget
        budget = Budget()
        for i, signal in enumerate(signals, 1):
            outcome = signal.outcome.value.upper() if hasattr(signal, 'outcome') and signal.outcome else 'N/A'
            gain = f"{round(signal.gain)}" if getattr(signal, 'gain', None) not in (None, 0.0) else ("0.0" if getattr(signal, 'gain', None) == 0.0 else 'N/A')
            lot_size = f"{signal.entry_lot:.2f}" if hasattr(signal, 'entry_lot') and signal.entry_lot else 'N/A'
            
            if outcome == "WIN":
                pip_size = f"{signal.take_profit_pips:.2f}" if hasattr(signal, 'take_profit_pips') and signal.take_profit_pips else 'N/A'
            else:
                pip_size = f"{signal.stop_loss_pips:.2f}" if hasattr(signal, 'stop_loss_pips') and signal.stop_loss_pips else 'N/A'

            entry_price = f"{signal.entry_price:.5f}" if signal.entry_price else 'N/A'
            stop_loss = f"{signal.stop_loss:.5f}" if hasattr(signal, 'stop_loss') and signal.stop_loss else 'N/A'
            take_profit = f"{signal.take_profit:.5f}" if hasattr(signal, 'take_profit') and signal.take_profit else 'N/A'
            timestamp = signal.timestamp.strftime('%Y-%m-%d %H:%M') if signal.timestamp else 'N/A'
            
            budget.apply_signal_gain(signal)
            current_balance = round(budget.current_balance)

            outcome_class = "win" if signal.gain >= 0 else "loss" if signal.gain < 0 else "neutral"
            
            table_rows += f"""
                <tr>
                    <td>{i}</td>
                    <td>{timestamp}</td>
                    <td>{signal.action.value}</td>
                    <td>{entry_price}</td>
                    <td>{stop_loss}</td>
                    <td>{take_profit}</td>
                    <td class="{outcome_class}">{outcome_class.upper()}</td>
                    <td>{lot_size}</td>
                    <td>{pip_size}</td>
                    <td class="{outcome_class}">${gain}</td>
                    <td><b>${current_balance}</b></td>
                </tr>
            """
        
        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{symbol} Performance Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        .chart-section {{
            margin-bottom: 40px;
        }}
        .signals-section h2 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
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
        .summary {{
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 {symbol} Performance Report</h1>
        
        <div class="summary">
            <h2>Total P&L: ${total_profit:.2f}</h2>
            <p>Wins: {wins} | Total Trades: {len(signals)} | Win Rate: {(wins/len(signals)*100):.1f}%</p>
        </div>
        
        <div class="chart-section">
            <h2>Cumulative Performance</h2>
            {plot_div}
        </div>
        
        <div class="signals-section">
            <h2>Trading Signals Details</h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Date/Time</th>
                        <th>Action</th>
                        <th>Entry Price</th>
                        <th>Stop Loss</th>
                        <th>Take Profit</th>
                        <th>Outcome</th>
                        <th>Lot Size</th>
                        <th>Pip Gain</th>
                        <th>Profit</th>
                        <th>Curent Balance</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
        
        return html_template

    def create_symbol_comparison_report(self, results: Dict[str, List[Signal]], save_path: Optional[Path] = None) -> str:
        """
        Create simplified symbol comparison report focused on cumulative performance
        SIMPLIFIED: Shows only joint cumulative chart and comprehensive statistics
        """
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"symbol_comparison_{timestamp}.html"
            save_path = self.report_dir / "interactive" / filename

        # Calculate comprehensive metrics for each symbol
        comparison_data = {}
        all_signals = []  # For joint analysis
        individual_stats = {}
        
        for symbol, signals in results.items():
            if symbol == 'all':
                continue
            
            completed = [s for s in signals if hasattr(s, 'is_completed') and s.is_completed]
            
            if completed:
                wins = [s for s in completed if hasattr(s, 'outcome') and s.outcome and s.outcome.value == "win"]
                losses = [s for s in completed if hasattr(s, 'outcome') and s.outcome and s.outcome.value == "loss"]
                
                win_gains = [s.gain for s in wins if hasattr(s, 'gain') and s.gain]
                loss_gains = [s.gain for s in losses if hasattr(s, 'gain') and s.gain]
                
                total_profit = sum(s.gain for s in completed if hasattr(s, 'gain') and s.gain)
                
                # Individual symbol statistics
                individual_stats[symbol] = {
                    'total_trades': len(completed),
                    'wins': len(wins),
                    'losses': len(losses),
                    'win_rate': (len(wins) / len(completed)) * 100,
                    'total_profit': total_profit,
                    'avg_profit': total_profit / len(completed),
                    'max_win': max(win_gains) if win_gains else 0,
                    'max_loss': min(loss_gains) if loss_gains else 0,  # Most negative
                    'avg_win': sum(win_gains) / len(win_gains) if win_gains else 0,
                    'avg_loss': sum(loss_gains) / len(loss_gains) if loss_gains else 0,
                    'profit_factor': abs(sum(win_gains) / sum(loss_gains)) if loss_gains and sum(loss_gains) != 0 else float('inf'),
                    'signals': completed  # For timeline analysis
                }
                
                # Add to overall data for compatibility
                comparison_data[symbol] = {
                    'total_trades': len(completed),
                    'wins': len(wins),
                    'win_rate': (len(wins) / len(completed)) * 100,
                    'total_profit': total_profit,
                    'avg_profit': total_profit / len(completed)
                }
                
                # Add to joint analysis
                all_signals.extend(completed)

        if not comparison_data:
            self.logger.warning("No data for symbol comparison")
            return ""

        # Calculate joint/overall statistics
        joint_stats = self._calculate_joint_statistics(all_signals)
        
        # Create only the cumulative chart if Plotly available
        charts_html = ""
        if PLOTLY_AVAILABLE:
            charts_html = self._create_cumulative_chart_only(joint_stats)
        
        # Generate simplified HTML
        html_content = self._generate_simplified_comparison_html(
            charts_html, individual_stats, joint_stats, comparison_data
        )
        
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        self.logger.info(f"Simplified symbol comparison report saved: {save_path}")
        return str(save_path)

    def _calculate_joint_statistics(self, all_signals: List[Signal]) -> Dict[str, Any]:
        """Calculate joint statistics across all signals"""
        if not all_signals:
            return {}
        
        wins = [s for s in all_signals if hasattr(s, 'outcome') and s.outcome and s.outcome.value == "win"]
        losses = [s for s in all_signals if hasattr(s, 'outcome') and s.outcome and s.outcome.value == "loss"]
        
        win_gains = [s.gain for s in wins if hasattr(s, 'gain') and s.gain]
        loss_gains = [s.gain for s in losses if hasattr(s, 'gain') and s.gain]
        
        total_profit = sum(s.gain for s in all_signals if hasattr(s, 'gain') and s.gain)
        
        return {
            'total_signals': len(all_signals),
            'total_wins': len(wins),
            'total_losses': len(losses),
            'overall_win_rate': (len(wins) / len(all_signals)) * 100,
            'total_profit': total_profit,
            'avg_profit_per_trade': total_profit / len(all_signals),
            'max_win': max(win_gains) if win_gains else 0,
            'max_loss': min(loss_gains) if loss_gains else 0,
            'avg_win': sum(win_gains) / len(win_gains) if win_gains else 0,
            'avg_loss': sum(loss_gains) / len(loss_gains) if loss_gains else 0,
            'total_win_amount': sum(win_gains) if win_gains else 0,
            'total_loss_amount': sum(loss_gains) if loss_gains else 0,
            'profit_factor': abs(sum(win_gains) / sum(loss_gains)) if loss_gains and sum(loss_gains) != 0 else float('inf'),
            'signals': sorted(all_signals, key=lambda s: s.timestamp if hasattr(s, 'timestamp') and s.timestamp else datetime.min)
        }

    def _create_cumulative_chart_only(self, joint_stats: Dict) -> str:
        """Create only the joint cumulative performance chart"""
        charts_html = ""
        
        # Only create the cumulative performance chart
        if joint_stats.get('signals'):
            fig_cumulative = self._create_joint_cumulative_chart(joint_stats['signals'])
            charts_html += f"""
            <div class="chart-section">
                <h3>📈 Joint Cumulative Performance - All Signals</h3>
                <div class="chart-container">
                    {pyo.plot(fig_cumulative, output_type='div', include_plotlyjs=False)}
                </div>
            </div>
            """
        
        return charts_html

    def _create_joint_cumulative_chart(self, signals: List[Signal]) -> go.Figure:
        """Create joint cumulative performance chart for all signals"""
        fig = go.Figure()
        
        # Sort signals by timestamp
        sorted_signals = sorted(signals, key=lambda s: s.timestamp if hasattr(s, 'timestamp') and s.timestamp else datetime.min)
        
        # Calculate cumulative P&L
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
            name='Joint Cumulative P&L',
            line=dict(color='#3498db', width=4),
            marker=dict(size=6),
            fill='tonexty' if cumulative_pnl[-1] >= 0 else None,
            fillcolor='rgba(52, 152, 219, 0.15)'
        ))
        
        # Add zero line for reference
        fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Breakeven")
        
        # Add individual symbol traces (different colors)
        colors = ['#e74c3c', '#27ae60', '#f39c12', '#9b59b6', '#e67e22', '#1abc9c', '#95a5a6', '#34495e']
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
                name=f'{symbol}',
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
                'text': 'Joint Cumulative Performance - All Signals Combined',
                'x': 0.5,
                'xanchor': 'center',
                'font': {'size': 20, 'color': '#2c3e50'}
            },
            xaxis_title='Date',
            yaxis_title='Cumulative P&L ($)',
            height=600,
            template='plotly_white',
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
            margin=dict(r=150)
        )
        
        return fig

    def _generate_simplified_comparison_html(self, charts_html: str, individual_stats: Dict, 
                                        joint_stats: Dict, comparison_data: Dict) -> str:
        """Generate simplified HTML report with only cumulative chart"""
        
        # Create detailed statistics tables
        individual_table = self._create_individual_stats_table(individual_stats)
        joint_summary = self._create_joint_summary_section(joint_stats)
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Symbol Comparison - Cumulative Performance Analysis</title>
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
                    max-width: 1600px;
                    margin: 0 auto;
                    background: rgba(255, 255, 255, 0.95);
                    border-radius: 15px;
                    padding: 30px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 40px;
                    padding: 30px;
                    background: linear-gradient(45deg, #2c3e50, #3498db);
                    color: white;
                    border-radius: 15px;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 2.5em;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }}
                .summary-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin-bottom: 40px;
                }}
                .summary-card {{
                    background: linear-gradient(45deg, #667eea, #764ba2);
                    color: white;
                    padding: 25px;
                    border-radius: 15px;
                    text-align: center;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
                    transition: transform 0.3s ease;
                }}
                .summary-card:hover {{
                    transform: translateY(-5px);
                }}
                .summary-value {{
                    font-size: 2.2em;
                    font-weight: bold;
                    margin-bottom: 10px;
                    text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
                }}
                .summary-label {{
                    font-size: 1.1em;
                    opacity: 0.9;
                }}
                .chart-section {{
                    margin-bottom: 50px;
                    background: white;
                    padding: 30px;
                    border-radius: 15px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                }}
                .chart-section h3 {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 15px;
                    margin-bottom: 25px;
                    font-size: 1.8em;
                }}
                .chart-container {{
                    background: #fafafa;
                    border-radius: 10px;
                    padding: 15px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    background: white;
                    border-radius: 10px;
                    overflow: hidden;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                }}
                th, td {{
                    padding: 15px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}
                th {{
                    background: linear-gradient(45deg, #3498db, #2980b9);
                    color: white;
                    font-weight: bold;
                    text-transform: uppercase;
                    font-size: 0.9em;
                    letter-spacing: 1px;
                }}
                tr:nth-child(even) {{
                    background-color: #f8f9fa;
                }}
                tr:hover {{
                    background-color: #e3f2fd;
                    transition: background-color 0.3s ease;
                }}
                .win {{ color: #27ae60; font-weight: bold; }}
                .loss {{ color: #e74c3c; font-weight: bold; }}
                .neutral {{ color: #f39c12; font-weight: bold; }}
                .section-divider {{
                    height: 3px;
                    background: linear-gradient(45deg, #3498db, #2980b9);
                    border: none;
                    margin: 50px 0;
                    border-radius: 2px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📈 Symbol Comparison - Cumulative Performance</h1>
                    <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Symbols Analyzed: {', '.join(individual_stats.keys())}</p>
                </div>
                
                {joint_summary}
                
                <hr class="section-divider">
                
                {charts_html}
                
                <hr class="section-divider">
                
                <div class="chart-section">
                    <h3>📊 Detailed Individual Symbol Statistics</h3>
                    {individual_table}
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template

    def _create_joint_summary_section(self, joint_stats: Dict) -> str:
        """Create joint summary section with key overall metrics"""
        if not joint_stats:
            return ""
        
        # Calculate additional metrics
        expectancy = (joint_stats.get('avg_win', 0) * (joint_stats.get('overall_win_rate', 0) / 100)) + \
                    (joint_stats.get('avg_loss', 0) * ((100 - joint_stats.get('overall_win_rate', 0)) / 100))
        
        return f"""
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-value">{joint_stats.get('total_signals', 0)}</div>
                <div class="summary-label">Total Signals</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">{joint_stats.get('overall_win_rate', 0):.1f}%</div>
                <div class="summary-label">Overall Win Rate</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">${joint_stats.get('total_profit', 0):.2f}</div>
                <div class="summary-label">Total P&L</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">${joint_stats.get('avg_profit_per_trade', 0):.2f}</div>
                <div class="summary-label">Avg per Trade</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">${joint_stats.get('max_win', 0):.2f}</div>
                <div class="summary-label">Max Single Win</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">${abs(joint_stats.get('max_loss', 0)):.2f}</div>
                <div class="summary-label">Max Single Loss</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">{joint_stats.get('profit_factor', 0):.2f}</div>
                <div class="summary-label">Profit Factor</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">${expectancy:.2f}</div>
                <div class="summary-label">Expectancy per Trade</div>
            </div>
        </div>
        """

    def _create_individual_stats_table(self, individual_stats: Dict) -> str:
        """Create detailed individual statistics table"""
        table_rows = ""
        
        for symbol, stats in individual_stats.items():
            profit_class = "win" if stats['total_profit'] > 0 else "loss" if stats['total_profit'] < 0 else "neutral"
            winrate_class = "win" if stats['win_rate'] >= 60 else "neutral" if stats['win_rate'] >= 40 else "loss"
            
            table_rows += f"""
            <tr>
                <td><strong>{symbol}</strong></td>
                <td>{stats['total_trades']}</td>
                <td>{stats['wins']}</td>
                <td>{stats['losses']}</td>
                <td class="{winrate_class}">{stats['win_rate']:.1f}%</td>
                <td class="{profit_class}">${stats['total_profit']:.2f}</td>
                <td>${stats['avg_profit']:.2f}</td>
                <td class="win">${stats['max_win']:.2f}</td>
                <td class="loss">${abs(stats['max_loss']):.2f}</td>
                <td class="win">${stats['avg_win']:.2f}</td>
                <td class="loss">${abs(stats['avg_loss']):.2f}</td>
                <td>{stats['profit_factor']:.2f}</td>
            </tr>
            """
        
        return f"""
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Total Trades</th>
                    <th>Wins</th>
                    <th>Losses</th>
                    <th>Win Rate</th>
                    <th>Total P&L</th>
                    <th>Avg P&L/Trade</th>
                    <th>Max Win</th>
                    <th>Max Loss</th>
                    <th>Avg Win</th>
                    <th>Avg Loss</th>
                    <th>Profit Factor</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        """