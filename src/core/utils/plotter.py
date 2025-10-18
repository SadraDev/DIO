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
        self.mbox_hours = settings.get("strategies.two_hunters.mbox_time")
        
        # Color schemes - updated with blue MBox
        self.colors = {
            'bullish': '#00ff88',
            'bearish': '#ff4444',
            'mbox': 'rgba(52, 152, 219, 0.3)',  # Changed to blue
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
        signals: Optional[List[Signal]] = None, 
        symbol: str = "SYMBOL", 
        title: str = None, 
        show_mbox: bool = True,
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
            
            # Add candlestick chart
            fig.add_trace(go.Candlestick(
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
            ))
            
            # Add MBox highlights (blue, price-range height only)
            if show_mbox:
                self.add_mbox_highlights_fixed(fig, df['timestamp'], bars)
            
            # Add trading signal rectangles stretching to outcome timestamp
            if signals:
                self.add_signal_rectangles_extended(fig, signals, bars)
            
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
            
            # FIXED: Only return div if requested, otherwise save to specified path ONLY
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

    def add_mbox_highlights_fixed(self, fig, timestamps, bars: List[Bar]):
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
                    text="MBox",
                    showarrow=False,
                    font=dict(color="#2980b9", size=12),  # Blue text
                    bgcolor="rgba(255,255,255,0.8)"
                )
                
            current_date += timedelta(days=1)

    def add_signal_rectangles_extended(self, fig, signals: List[Signal], bars: List[Bar]):
        """Add trading signal visualization with separate areas and lines - CORRECTED
        Proper initial vs current level visualization"""
        
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
                    fillcolor="rgba(255, 68, 68, 0.2)",  # Light red for initial SL area
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
                    fillcolor="rgba(0, 255, 136, 0.2)",  # Light green for initial TP area
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
            
            # PART 3: SIGNAL MARKERS AND ANNOTATIONS
            
            # Add entry marker (blue circle at initial entry)
            fig.add_trace(go.Scatter(
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
                hovertext=f"Initial Entry: {initial_entry:.5f}<br>" +
                         f"Initial SL: {round(initial_sl, 5) if initial_sl else 'NA'}<br>" +
                         f"Current SL: {round(signal.stop_loss, 5) if hasattr(signal, 'stop_loss') and signal.stop_loss else 'NA'}<br>" +
                         f"Initial TP: {round(initial_tp, 5) if initial_tp else 'NA'}<br>" +
                         f"Current TP: {round(signal.take_profit, 5) if hasattr(signal, 'take_profit') and signal.take_profit else 'NA'}"
            ))
            
            # PART 4: OUTCOME MARKERS - CORRECTED
            if (hasattr(signal, 'outcome') and signal.outcome and 
                hasattr(signal, 'outcome_timestamp') and signal.outcome_timestamp):
                
                outcome_color = "green" if signal.outcome.value == "win" else "red"
                outcome_symbol = "triangle-up" if signal.outcome.value == "win" else "triangle-down"
                
                # CORRECTED: Determine actual exit price based on outcome
                if signal.outcome.value == "win":
                    # Win means TP was hit - exit at current TP level
                    actual_exit_price = signal.take_profit
                else:
                    # Loss means SL was hit - exit at current SL level
                    actual_exit_price = signal.stop_loss
                
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

    def create_performance_report(
        self, 
        signals: List[Signal], 
        symbol: str = "SYMBOL", 
        save_path: Optional[Path] = None
    ) -> str:
        """Create simplified performance report with cumulative PL chart and signals table"""
        
        if not signals:
            self.logger.warning("No signals provided for performance report")
            return ""
        
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{symbol}_performance_{timestamp}.html"
            save_path = self.report_dir / "interactive" / filename
        
        # Ensure directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get completed signals
        completed_signals = [s for s in signals if hasattr(s, 'is_completed') and s.is_completed]
        
        if not completed_signals:
            self.logger.warning("No completed signals for performance analysis")
            return ""
        
        wins = sum(1 for s in completed_signals if hasattr(s, 'gain') and s.gain and s.gain >= 0)
        total_profit = sum(s.gain for s in completed_signals if hasattr(s, 'gain') and s.gain)
        
        # Create single cumulative PL chart
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            
            # Cumulative PL line
            cumulative_pnl = []
            total = 0
            dates = []
            
            for signal in completed_signals:
                if hasattr(signal, 'gain') and signal.gain and hasattr(signal, 'timestamp') and signal.timestamp:
                    total += signal.gain
                    cumulative_pnl.append(total)
                    dates.append(signal.timestamp)
            
            if dates and cumulative_pnl:
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=cumulative_pnl,
                    mode='lines+markers',
                    name='Cumulative PL',
                    line=dict(color='#3498db', width=3),
                    marker=dict(size=6)
                ))
            
            fig.update_layout(
                title=f"{symbol} Performance",
                height=400,
                template='plotly_white',
                xaxis_title="Date",
                yaxis_title="Cumulative PL ($)"
            )
            
            # Generate HTML with signals table
            html_content = self.generate_simple_performance_html(fig, completed_signals, symbol, total_profit, wins)
            
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.logger.info(f"Performance report saved: {save_path}")
            return str(save_path)

    def generate_simple_performance_html(self, fig, signals: List[Signal], symbol: str, total_profit: float, wins: int) -> str:
        """Generate simplified performance report HTML with signals table"""
        
        plot_div = pyo.plot(fig, output_type='div', include_plotlyjs=True)
        
        # Create signals table with correct lot size field
        table_rows = ""
        from src.core.models.budget import Budget
        budget = Budget()
        commless_balance = 0
        
        for i, signal in enumerate(signals, 1):
            gain = round(signal.gain, 2) if getattr(signal, 'gain', None) not in [None, 0.0] else 0.0 if getattr(signal, 'gain', None) == 0.0 else 0
            commission = round(signal.commission, 2) if getattr(signal, 'commission') and signal.commission else 0
            lot_size = f"{signal.entry_lot:.2f}" if hasattr(signal, 'entry_lot') and signal.entry_lot else 0
            
            stop_loss_pips = f"{signal.stop_loss_pips:.2f}" if hasattr(signal, 'stop_loss_pips') and signal.stop_loss_pips else 0
            take_profit_pips = f"{signal.take_profit_pips:.2f}" if hasattr(signal, 'take_profit_pips') and signal.take_profit_pips else 0
            timestamp = signal.timestamp.strftime("%Y-%m-%d %H:%M") if signal.timestamp else 0
            
            budget.apply_signal_gain(signal)
            current_balance = round(budget.current_balance)
            commless_balance = int(current_balance) + int(commission)
            
            outcome_class = "win" if signal.gain > 0 else "loss" if signal.gain < 0 else "neutral"
            
            table_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{timestamp}</td>
                <td>{signal.action.value}</td>
                <td class="{outcome_class}">{outcome_class.upper()}</td>
                <td>{signal.sl_adjusted_count}</td>
                <td>{lot_size}</td>
                <td>{stop_loss_pips}</td>
                <td>{take_profit_pips}</td>
                <td>{commission}$</td>
                <td class="{outcome_class}">{gain}$</td>
                <td><b>{current_balance}$</b></td>
                <td><b>{commless_balance}$</b></td>
            </tr>
            """

        html_template = f"""
        <!DOCTYPE html>
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
                <h1>{symbol} Analysis</h1>
                
                <div class="summary">
                    <h2>Total Profit: ${total_profit:.2f}</h2>
                    <p>Wins: {wins} / Total Trades: {len(signals)} | Win Rate: {(wins/len(signals)*100):.1f}%</p>
                </div>
                
                <div class="chart-section">
                    <h2>Performance</h2>
                    {plot_div}
                </div>
                
                <div class="signals-section">
                    <h2>Signal Details</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Date/Time</th>
                                <th>Action</th>
                                <th>Outcome</th>
                                <th>SL Adj</th>
                                <th>Lot Size</th>
                                <th>Stop Loss Pips</th>
                                <th>Take Profit Pips</th>
                                <th>Commission</th>
                                <th>Profit</th>
                                <th>Curent Balance</th>
                                <th>C-L Balance</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template

    def create_symbol_comparison_report(
        self, 
        results: Dict[str, List[Signal]], 
        save_path: Optional[Path] = None
    ) -> str:
        """Create simplified symbol comparison report focused on cumulative performance"""
        
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"full_report_{timestamp}"
            save_path = self.report_dir / filepath / "comparison.html"
        
        # Ensure directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Calculate comprehensive metrics for each symbol
        all_signals = []  # For joint analysis
        individual_stats = {}
        
        for symbol, signals in results.items():
            if symbol == "all":
                continue
                
            completed = [s for s in signals if hasattr(s, 'is_completed') and s.is_completed]
            
            if completed:
                # Implement draw down
                wins = [s for s in completed if hasattr(s, 'gain') and s.gain and s.gain >= 0]
                losses = [s for s in completed if hasattr(s, 'gain') and s.gain and s.gain < 0]
                win_gains = [s.gain for s in wins if hasattr(s, 'gain') and s.gain]
                loss_gains = [s.gain for s in losses if hasattr(s, 'gain') and s.gain]
                total_profit = sum(s.gain for s in completed if hasattr(s, 'gain') and s.gain)
                total_commission = sum(s.commission for s in completed if hasattr(s, 'commission') and s.commission)
                total_lot_sizes = sum(s.entry_lot for s in completed if hasattr(s, 'entry_lot') and s.entry_lot)
                
                # Individual symbol statistics
                individual_stats[symbol] = {
                    'total_trades': len(completed),
                    'wins': len(wins),
                    'losses': len(losses),
                    'win_rate': (len(wins) / len(completed)) * 100,
                    'total_profit': total_profit,
                    'total_commission': total_commission,
                    'avg_profit': total_profit / len(completed),
                    'avg_lot_size': round(total_lot_sizes / len(completed), 2),
                    'max_win': max(win_gains) if win_gains else 0,
                    'max_loss': min(loss_gains) if loss_gains else 0,  # Most negative
                    'avg_win': sum(win_gains) / len(win_gains) if win_gains else 0,
                    'avg_loss': sum(loss_gains) / len(loss_gains) if loss_gains else 0
                }

                # Add to joint analysis
                all_signals.extend(completed)
        

        # Calculate joint/overall statistics
        joint_stats = self.calculate_joint_statistics(all_signals)
        
        # Create only the cumulative chart if Plotly available
        charts_html = ""
        if PLOTLY_AVAILABLE:
            charts_html = self.create_cumulative_chart_only(joint_stats)
        
        # Generate simplified HTML
        html_content = self.generate_simplified_comparison_html(charts_html, individual_stats, joint_stats)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        self.logger.info(f"Simplified symbol comparison report saved: {save_path}")
        return str(save_path)

    def calculate_joint_statistics(self, all_signals: List[Signal]) -> Dict[str, Any]:
        """Calculate joint statistics across all signals"""
        
        if not all_signals:
            return {}
        
        wins = [s for s in all_signals if hasattr(s, 'gain') and s.gain and s.gain >= 0]
        losses = [s for s in all_signals if hasattr(s, 'gain') and s.gain and s.gain < 0]
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

    def create_cumulative_chart_only(self, joint_stats: Dict) -> str:
        """Create only the joint cumulative performance chart"""
        charts_html = ""
        if joint_stats.get('signals'):
            fig_cumulative = self.create_joint_cumulative_chart(joint_stats['signals'])
            chart_div = pyo.plot(
                fig_cumulative,
                output_type='div',
                include_plotlyjs=False,
                config={'responsive': True, 'displayModeBar': True}
            )
            charts_html = f"""
            <div class="chart-section">
                <h3>Joint Performance - All Signals</h3>
                <div class="chart-container">
                    {chart_div}
                </div>
            </div>
            """
        return charts_html

    def create_joint_cumulative_chart(self, signals: List[Signal]) -> go.Figure:
        """Create joint cumulative performance chart for all signals"""
        
        fig = go.Figure()
        
        # Sort signals by timestamp
        sorted_signals = sorted(signals, key=lambda s: s.timestamp if hasattr(s, 'timestamp') and s.timestamp else datetime.min)
        
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
            name='Joint Cumulative PL',
            line=dict(color='#3498db', width=4),
            marker=dict(size=6),
            fill='tonexty' if cumulative_pnl[-1] > 0 else None,
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
                name=f"{symbol}",
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
                'text': 'Joint Cumulative Performance',
                'x': 0.5,
                'xanchor': 'center'
            },
            xaxis_title="Date",
            yaxis_title="Cumulative Profit ($)",
            autosize=True,
            height=None,
            width=None,
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
            margin=dict(
                l=60,
                r=150,
                t=60,
                b=60,
                pad=0
            )
        )
        
        return fig

    def generate_simplified_comparison_html(self, charts_html: str, individual_stats: Dict, joint_stats: Dict) -> str:
        """Generate simplified HTML report with only cumulative chart"""
        
        # Create detailed statistics tables
        individual_table = self.create_individual_stats_table(individual_stats)
        joint_summary = self.create_joint_summary_section(joint_stats)
        
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
                .win {{
                    color: #27ae60;
                    font-weight: bold;
                }}
                .loss {{
                    color: #e74c3c;
                    font-weight: bold;
                }}
                .neutral {{
                    color: #f39c12;
                    font-weight: bold;
                }}
                .section-divider {{
                    height: 3px;
                    background: linear-gradient(45deg, #3498db, #2980b9);
                    margin: 40px 0;
                    border-radius: 2px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1 style="text-align: center; color: #2c3e50; margin-bottom: 40px;">Symbol Comparison Analysis</h1>
                
                {joint_summary}
                
                {charts_html}
                
                <hr class="section-divider">
                
                <div class="chart-section">
                    <h3>Detailed Individual Symbol Statistics</h3>
                    {individual_table}
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template

    def create_joint_summary_section(self, joint_stats: Dict) -> str:
        """Create joint summary section with key metrics"""
        
        if not joint_stats:
            return ""
        
        return f"""
        <div class="chart-section">
            <h3>Overall Performance Summary</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0;">
                <div style="background: rgba(52, 152, 219, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #3498db;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{joint_stats.get('total_signals', 0)}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Total Signals</div>
                </div>
                <div style="background: rgba(39, 174, 96, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #27ae60;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">{joint_stats.get('overall_win_rate', 0):.1f}%</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Overall Win Rate</div>
                </div>
                <div style="background: rgba(231, 76, 60, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #e74c3c;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">${joint_stats.get('total_profit', 0):.2f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Total Profit</div>
                </div>
                <div style="background: rgba(155, 89, 182, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #9b59b6;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">${joint_stats.get('avg_profit_per_trade', 0):.2f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Avg per Trade</div>
                </div>
                <div style="background: rgba(230, 126, 34, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #e67e22;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">${joint_stats.get('max_win', 0):.2f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Max Single Win</div>
                </div>
                <div style="background: rgba(52, 73, 94, 0.1); padding: 20px; border-radius: 10px; text-align: center; border-left: 4px solid #34495e;">
                    <div style="font-size: 24px; font-weight: bold; color: #2c3e50;">${abs(joint_stats.get('max_loss', 0)):.2f}</div>
                    <div style="font-size: 14px; color: #7f8c8d; margin-top: 5px;">Max Single Loss</div>
                </div>
            </div>
        </div>
        """

    def create_individual_stats_table(self, individual_stats: Dict) -> str:
        """Create detailed individual statistics table"""
        
        table_rows = ""
        for symbol, stats in individual_stats.items():
            profit_class = "win" if stats['total_profit'] > 0 else "loss" if stats['total_profit'] < 0 else "neutral"
            win_rate_class = "win" if stats['win_rate'] >= 60 else "neutral" if stats['win_rate'] >= 40 else "loss"
            avg_lot_size = individual_stats[symbol]['avg_lot_size']

            table_rows += f"""
            <tr>
                <td><strong>{symbol}</strong></td>
                <td>{stats['total_trades']}</td>
                <td><b>{stats['win_rate']:.1f}%</b></td>
                <td class="{profit_class}">${stats['total_profit']:.2f}</td>
                <td>${stats['total_commission']:.2f}</td>
                <td>${stats['avg_profit']:.2f}</td>
                <td>{avg_lot_size}</td>
            </tr>
            """
        
        return f"""
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Total Trades</th>
                    <th>Win Rate%</th>
                    <th>Total Profit</th>
                    <th>Total Commission</th>
                    <th>Avg Profit/Trade</th>
                    <th>Avg Lots Size</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        """
    