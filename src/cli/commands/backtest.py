"""Backtest command implementation with integrated plotting"""
from datetime import datetime
from typing import List
from src.engine.backtest import BacktestEngine
from src.core.utils.logger import TradingLogger
from src.core.utils.plotter import TradingPlotter
from src.core.data.fetcher import DataFetcher

def run_backtest(
    symbols: List[str],
    start_date: datetime, 
    end_date: datetime,
    initial_balance: float,
    risk_percent: float,
    save_results: bool = True,
    output_dir: str = None,
    verbose: bool = False,
    # New plotting parameters integrated
    show_signals: bool = True,
    show_sessions: bool = True,
    show_choch: bool = True,
    interactive: bool = True,
    create_report: bool = True
):
    """Run backtesting on historical data with integrated plotting"""
    logger = TradingLogger.get_backtest_logger()
    engine = BacktestEngine()
    
    logger.info(f"Starting backtest: {symbols} from {start_date} to {end_date}")
    
    # Run the backtest
    results = engine.run_backtest(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_balance=initial_balance,
        risk_percent=risk_percent,
        output_dir=output_dir
    )
    
    # Integrated plotting functionality
    logger.info("Generating plots and reports...")
    
    try:
        # Initialize plotter
        report_dir = output_dir or "reports"
        plotter = TradingPlotter(report_dir=report_dir)
        fetcher = DataFetcher()
        
        all_charts = []
        bars_data = {}
        signals_data = {}
        
        for symbol in symbols:
            try:
                logger.info(f"Generating chart for {symbol}")
                
                # Get backtest results for this symbol
                signals = results.get(f"{symbol}.signals", {})
                
                # Fetch bars (same data used in backtest)
                bars = fetcher.fetch_bars_from_mt5(start_date, end_date, symbol)
                if not bars:
                    logger.warning(f"No data found for {symbol}")
                    continue
                
                # Store data for comprehensive report
                bars_data[symbol] = bars
                if signals:
                    signals_data[symbol] = signals
                
                # Generate interactive chart with actual signals from backtest
                if interactive:
                    chart_path = plotter.plot_candlestick_interactive(
                        bars=bars,
                        signals=signals if show_signals else None,
                        symbol=symbol,
                        title=f"{symbol} Backtest Analysis ({start_date.date()} to {end_date.date()})"
                    )
                    all_charts.append(chart_path)
                else:
                    # Fallback to static plotting
                    chart_path = plotter.plot_ohlc(
                        bars=bars,
                        signals=signals if show_signals else None,
                        highlight_sessions=show_sessions,
                        symbol=symbol,
                        title=f"{symbol} Backtest Analysis"
                    )
                    all_charts.append(chart_path)
                
                logger.info(f"Chart created for {symbol}: {chart_path}")
                
            except Exception as e:
                logger.error(f"Error creating chart for {symbol}: {e}")
        
        # Generate comprehensive reports if requested
        if create_report:
            try:
                # Import ReportGenerator here to avoid circular imports
                from src.core.reporting.report_generator import ReportGenerator
                
                report_gen = ReportGenerator(report_dir)
                report_path = report_gen.generate_full_trading_report(
                    symbols=symbols,
                    bars_data=bars_data,
                    results=results,
                    report_title=f"Backtest Report: {start_date.date()} to {end_date.date()}"
                )
                
                logger.info(f"Comprehensive report generated: {report_path}")
                
            except Exception as e:
                import sys, traceback
                tb = traceback.extract_tb(sys.exc_info()[2])[-1]
                filename = tb.filename
                lineno = tb.lineno

                logger.error(f"Error generating comprehensive report: {e} (File: {filename}, line {lineno})")
        
        # Update results with plotting information
        results['plotting'] = {
            'charts': all_charts,
            'report_directory': report_dir,
            'symbols_plotted': len([s for s in symbols if s in bars_data])
        }

        logger.info(f"Plotting completed. Generated {len(all_charts)} charts.")
        
    except Exception as e:
        logger.error(f"Error in plotting integration: {e}")
        # Don't fail the entire backtest if plotting fails
    
    return results