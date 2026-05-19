from pathlib import Path
from typing import List, Dict, Optional, Tuple
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

    def generate_reports(
        self,
        symbols: List[str],
        date_range: Tuple[datetime, datetime],
        results: Dict[str, List[Signal]],
        flags: Dict[str, bool]
    ) -> str:
        """Generate comprehensive trading report with symbol-separated charts"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reportdir = self.report_dir / f"{timestamp}"

        if not flags['no_reports'] and not flags['no_plots']:
            reportdir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Generating plots and reports. This will take time..")

        if flags['no_reports'] and flags['no_plots']:
            self.logger.info("Generated nothing.")

        # Generate charts organized by symbol
        chartpaths = {}
        if not flags.get("no_plots"):
            reportdir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Generating {flags.get('display_range')} charts for symbols separatly...")
            chartpaths = self.plotter.generate_charts(
                date_range=date_range,
                results=results,
                reportdir=reportdir,
                showmbox=not flags.get("no_mbox"),
                show_15m_bars=flags.get("show_15m_bars"),
                dispaly_timeframe=flags.get("dispaly_timeframe"),
                display_range=flags.get("display_range")
            )
            total_charts = sum(len(months) for months in chartpaths.values())
            self.logger.info(f"Generated {total_charts} charts across {len(chartpaths)} symbols")
        
        # Generate main report
        comparisonpath = None
        if len(symbols) >= 1 and not flags.get("no_reports"):
            reportdir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Generating main report...")
            comparisonpath = self.plotter.create_symbol_comparison_report(
                results=results,
                chartpaths=chartpaths,
                savepath=reportdir / "report.html"
            )
        
        if not flags.get("no_plots") or not flags.get("no_reports"):
            self.logger.info(f"Report generated: {comparisonpath}")
        else:
            self.logger.info(f"Outputs logged.")
        
        return str(comparisonpath) if comparisonpath else str(reportdir)
