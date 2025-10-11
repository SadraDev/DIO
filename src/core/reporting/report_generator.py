from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from src.core.models.signal import Signal
from src.core.models.bar import Bar
from src.core.utils.plotter import TradingPlotter
from src.core.utils.logger import TradingLogger


class ReportGenerator:
    """
    Advanced report generator for trading analysis
    """
    
    def __init__(self, report_dir: str = "reports"):
        self.report_dir = Path(report_dir)
        self.plotter = TradingPlotter(str(self.report_dir))
        self.logger = TradingLogger.get_main_logger()
        
    def generate_full_trading_report(self, 
                                   symbols: List[str],
                                   bars_data: Dict[str, List[Bar]],
                                   results: Dict[str, List[Signal]],
                                   report_title: str = "Trading Analysis Report") -> str:
        """Generate comprehensive trading report with all components"""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = self.report_dir / f"full_report_{timestamp}"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate individual symbol charts
        chart_paths = []
        for symbol in symbols:
            if symbol in bars_data:
                bars = bars_data[symbol]
                signals = results.get(symbol, [])
                
                chart_path = self.plotter.plot_candlestick_interactive(
                    bars=bars,
                    signals=signals,
                    symbol=symbol,
                    savepath=report_dir / f"{symbol}_chart.html"
                )
                chart_paths.append(chart_path)
        
        # Generate performance reports
        performance_paths = []
        for symbol in symbols:
            if symbol in results and results[symbol]:
                perf_path = self.plotter.create_performance_report(
                    signals=results[symbol],
                    symbol=symbol,
                    savepath=report_dir / f"{symbol}_performance.html"
                )
                performance_paths.append(perf_path)
        
        # Generate comparison report
        comparison_path = None
        if len(results)-1 > 1:
            comparison_path = self.plotter.create_symbol_comparison_report(
                results,
                save_path=report_dir / "symbol_comparison.html"
            )
        
        # Create main index file
        index_path = self._create_report_index(
            report_dir, 
            symbols, 
            chart_paths, 
            performance_paths, 
            comparison_path,
            report_title
        )
        
        self.logger.info(f"Full trading report generated: {index_path}")
        return str(index_path)
    
    def _create_report_index(self, 
                           report_dir: Path,
                           symbols: List[str],
                           chart_paths: List[str],
                           performance_paths: List[str],
                           comparison_path: Optional[str],
                           title: str) -> Path:
        """Create main index file for the report"""
        
        index_path = report_dir / "index.html"
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    margin: 0;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    min-height: 100vh;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background: rgba(0,0,0,0.1);
                    padding: 30px;
                    border-radius: 15px;
                    backdrop-filter: blur(10px);
                }}
                .nav-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin: 20px 0;
                }}
                .nav-card {{
                    background: rgba(255,255,255,0.1);
                    padding: 20px;
                    border-radius: 10px;
                    text-align: center;
                    transition: transform 0.3s ease;
                }}
                .nav-card:hover {{
                    transform: translateY(-5px);
                }}
                .nav-card a {{
                    color: white;
                    text-decoration: none;
                    font-weight: bold;
                    font-size: 18px;
                }}
                .section-title {{
                    font-size: 24px;
                    margin: 30px 0 15px 0;
                    color: #00ff88;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div style="text-align: center; margin-bottom: 40px;">
                    <h1>📊 {title}</h1>
                    <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Symbols: {', '.join(symbols)}</p>
                </div>
                
                <div class="section-title">📈 Interactive Charts</div>
                <div class="nav-grid">
        """
        
        # Add chart links
        for i, chart_path in enumerate(chart_paths):
            symbol = symbols[i] if i < len(symbols) else f"Chart {i+1}"
            chart_name = Path(chart_path).name
            html_content += f"""
                    <div class="nav-card">
                        <a href="{chart_name}" target="_blank">
                            📊 {symbol} Chart
                        </a>
                    </div>
            """
        
        html_content += """
                </div>
                
                <div class="section-title">📋 Performance Reports</div>
                <div class="nav-grid">
        """
        
        # Add performance report links
        for i, perf_path in enumerate(performance_paths):
            symbol = symbols[i] if i < len(symbols) else f"Performance {i+1}"
            perf_name = Path(perf_path).name
            html_content += f"""
                    <div class="nav-card">
                        <a href="{perf_name}" target="_blank">
                            📈 {symbol} Performance
                        </a>
                    </div>
            """
        
        html_content += """
                </div>
        """
        
        # Add comparison report if available
        if comparison_path:
            comp_name = Path(comparison_path).name
            html_content += f"""
                <div class="section-title">🔍 Analysis</div>
                <div class="nav-grid">
                    <div class="nav-card">
                        <a href="{comp_name}" target="_blank">
                            🎯 Symbol Comparison
                        </a>
                    </div>
                </div>
            """
        
        html_content += """
            </div>
        </body>
        </html>
        """
        
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return index_path
