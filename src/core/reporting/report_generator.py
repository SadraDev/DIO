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
        if not flags.get("no_plots"):
            self.logger.info("Generating symbol-separated monthly charts...")
            chartpaths = self.plotter.generate_monthly_charts(
                barsdata=barsdata,
                results=results,
                reportdir=reportdir,  # Pass report dir, not charts dir
                showmbox=not flags.get("no_mbox")
            )
            total_charts = sum(len(months) for months in chartpaths.values())
            self.logger.info(f"Generated {total_charts} charts across {len(chartpaths)} symbols")
        
        # Generate main report
        comparisonpath = None
        if len(symbols) >= 1 and not flags.get("no_reports"):
            self.logger.info("Generating main report...")
            comparisonpath = self.plotter.create_symbol_comparison_report(
                results=results,
                chartpaths=chartpaths,
                savepath=reportdir / "report.html"
            )
        
        if not flags.get("no_plots") or not flags.get("no_reports"):
            self.logger.info(f"Reports generated: {comparisonpath}")
        else:
            self.logger.info(f"Outputs logged.")
        
        return str(comparisonpath) if comparisonpath else str(reportdir)
