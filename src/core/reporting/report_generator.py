from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from src.core.models.signal import Signal
from src.core.models.bar import Bar
from src.core.utils.plotter import TradingPlotter
from src.core.utils.logger import TradingLogger


class ReportGenerator:
    """Advanced report generator for trading analysis"""
    
    def __init__(self, report_dir: str = "reports"):
        self.report_dir = Path(report_dir)
        self.plotter = TradingPlotter(str(self.report_dir))
        self.logger = TradingLogger.get_main_logger()

    def generate_full_trading_report(
        self,
        symbols: List[str],
        barsdata: Dict[str, List[Bar]],
        results: Dict[str, List[Signal]],
        flags: Dict[str, bool],
        reporttitle: str = "Trading Analysis Report"
    ) -> str:
        """Generate comprehensive trading report with symbol-separated charts"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reportdir = self.report_dir / f"{timestamp}"
        reportdir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Generating report in: {reportdir}")
        
        # Generate charts organized by symbol
        chartpaths = {}
        if not flags.get("noplots"):
            self.logger.info("Generating symbol-separated monthly charts...")
            chartpaths = self.plotter.generate_monthly_charts(
                barsdata=barsdata,
                results=results,
                reportdir=reportdir,  # Pass report dir, not charts dir
                showmbox=not flags.get("nombox")
            )
            total_charts = sum(len(months) for months in chartpaths.values())
            self.logger.info(f"Generated {total_charts} charts across {len(chartpaths)} symbols")
        
        # Generate main report
        comparisonpath = None
        if len(symbols) >= 1 and not flags.get("noreports"):
            self.logger.info("Generating main report...")
            comparisonpath = self.plotter.create_symbol_comparison_report(
                results=results,
                chartpaths=chartpaths,
                savepath=reportdir / "report.html"
            )
        
        if not flags.get("noplots") or not flags.get("noreports"):
            self.logger.info(f"Reports generated: {comparisonpath}")
        else:
            self.logger.info(f"Outputs logged.")
        
        return str(comparisonpath) if comparisonpath else str(reportdir)

    
    def generate_index_page(
        self, 
        report_dir: Path, 
        chart_paths: List[str], 
        performance_paths: List[str], 
        comparison_path: Optional[str],
        symbols: List[str],
        title: str
    ) -> Path:
        """Generate navigation index page"""
        
        index_path = report_dir / "index.html"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                }}
                .container {{
                    max-width: 1200px;
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
                .section-title {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                    margin: 30px 0 20px 0;
                    font-size: 1.8em;
                    text-align: center;
                    width: 100%;
                }}
                .section-title {{
                    display: inline-block;
                    border-bottom: 3px solid #3498db;
                    text-align: center;
                    margin: 30px auto 20px auto;
                }}
                .nav-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .nav-card {{
                    background: white;
                    border-radius: 10px;
                    padding: 20px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                    transition: transform 0.3s ease, box-shadow 0.3s ease;
                }}
                .nav-card:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 8px 25px rgba(0,0,0,0.15);
                }}
                .nav-card a {{
                    text-decoration: none;
                    color: #2c3e50;
                    font-weight: bold;
                    font-size: 1.2em;
                    display: block;
                    text-align: center;
                }}
                .nav-card a:hover {{
                    color: #3498db;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{title}</h1>
                    <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Symbols: {', '.join(symbols)}</p>
                </div>
                
                <div class="section-title">Interactive Charts</div>
                <div class="nav-grid">
        """
        
        # Add chart links
        if chart_paths:
            for i, chart_path in enumerate(chart_paths):
                symbol = symbols[i] if i < len(symbols) else f"Chart {i+1}"
                chart_name = Path(chart_path).name
                html_content += f"""
                    <div class="nav-card">
                        <a href="{chart_name}" target="_blank">{symbol} Chart</a>
                    </div>
                """
            
            html_content += """
                    </div>
                    
                    <div class="section-title">Performance Reports</div>
                    <div class="nav-grid">
            """
        
        # Add performance report links
        if performance_paths:
            for i, perf_path in enumerate(performance_paths):
                symbol = symbols[i] if i < len(symbols) else f"Performance {i+1}"
                perf_name = Path(perf_path).name
                html_content += f"""
                    <div class="nav-card">
                        <a href="{perf_name}" target="_blank">{symbol} Performance</a>
                    </div>
                """
            
            html_content += "</div>"
        
        # Add comparison report if available
        if comparison_path:
            comp_name = Path(comparison_path).name
            html_content += f"""
                <div class="section-title">Joint symbol analysis</div>
                <div class="nav-grid">
                    <div class="nav-card">
                        <a href="{comp_name}" target="_blank">Symbol Comparison</a>
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
