import click
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from src.core.utils.logger import TradingLogger, log_system_event


@click.group()
@click.version_option(version=settings.system_version, prog_name=settings.system_name)
@click.option('--config', '-c', type=click.Path(exists=True), 
              help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--quiet', '-q', is_flag=True, help='Suppress output except errors')
@click.pass_context
def cli(ctx, config, verbose, quiet):
   
    # Initialize context object
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['quiet'] = quiet
    
    # Load custom config if provided
    if config:
        settings.load_config(config)
        log_system_event("config_loaded", config_path=config)
    
    # Initialize logging
    TradingLogger.initialize()
    
    # Set log levels based on verbosity
    if verbose:
        settings.set('logging.level', 'DEBUG')
    elif quiet:
        settings.set('logging.level', 'ERROR')
    
    if not quiet:
        click.echo(f"{settings.system_name} v{settings.system_version}")

@cli.command()
@click.option('--symbol', '-s', multiple=True, 
              help='Trading symbol (e.g., EURUSD, GBPUSD)')
@click.option('--start-date', '-sd', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Backtest start date (YYYY-MM-DD)')
@click.option('--end-date', '-ed', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Backtest end date (YYYY-MM-DD)')  
@click.option('--balance', '-b', type=float, default=None,
              help='Initial balance for backtest')
@click.option('--risk', '-r', type=float, default=None,
              help='Risk percentage per trade (e.g., 0.01 for 1%)')
@click.option('--save-results', is_flag=True, default=True,
              help='Save backtest results to file')
@click.option('--output-dir', type=click.Path(), default=None,
              help='Output directory for results')
# NEW PLOTTING OPTIONS INTEGRATED INTO BACKTEST
@click.option('--show-signals', is_flag=True, default=True,
              help='Show trading signals on charts')
@click.option('--show-sessions', is_flag=True, default=True,
              help='Highlight trading sessions on charts')
@click.option('--show-choch', is_flag=True, default=True,
              help='Show CHoCH detection lines on charts')
@click.option('--interactive', is_flag=True, default=True,
              help='Generate interactive charts (vs static)')
@click.option('--create-report', is_flag=True, default=True,
              help='Generate comprehensive trading report')
@click.option('--no-plots', is_flag=True, default=False,
              help='Skip chart generation (backtest only)')
@click.pass_context
def backtest(ctx, symbol, start_date, end_date, balance, risk, 
             save_results, output_dir, show_signals, show_sessions, 
             show_choch, interactive, create_report, no_plots):
    """Run backtesting on historical data with integrated plotting"""
    from .commands.backtest import run_backtest
    
    # Use defaults if not provided
    symbols = list(symbol) if symbol else settings.symbols
    
    if not start_date:
        from datetime import datetime
        start_date = datetime.strptime(settings.get('backtesting.default_start', '2025-08-01'), '%Y-%m-%d')
    
    if not end_date:
        from datetime import datetime
        end_date = datetime.strptime(settings.get('backtesting.default_end', '2025-08-31'), '%Y-%m-%d')
    
    balance = balance or settings.initial_balance
    risk = risk or settings.default_risk_percent
    
    if not ctx.obj['quiet']:
        click.echo(f"Starting backtest with {', '.join(symbols)}")
        click.echo(f"Period: {start_date.date()} to {end_date.date()}")
        click.echo(f"Balance: ${balance:,} | Risk: {risk:.1%}")
        
        if not no_plots:
            click.echo(f"Charts: {'Yes' if interactive else 'Static'}")
            click.echo(f"Reports: {'Yes' if create_report else 'No'}")
        else:
            click.echo(f"Charts: Disabled")
    
    try:
        results = run_backtest(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            initial_balance=balance,
            risk_percent=risk,
            save_results=save_results,
            output_dir=output_dir,
            verbose=ctx.obj['verbose'],
            # Plotting parameters (only if not disabled)
            show_signals=show_signals and not no_plots,
            show_sessions=show_sessions and not no_plots,
            show_choch=show_choch and not no_plots,
            interactive=interactive and not no_plots,
            create_report=create_report and not no_plots
        )
        
        if not ctx.obj['quiet']:
            click.echo("Backtest completed successfully")
            
            # Show plotting results if enabled
            if not no_plots and 'plotting' in results:
                plotting_info = results['plotting']
                click.echo(f"Generated {len(plotting_info['charts'])} charts")
                click.echo(f"Reports saved to: {plotting_info['report_directory']}")
                
    except Exception as e:
        import sys, traceback
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        filename = tb.filename
        lineno = tb.lineno

        click.echo(f"Backtest failed: {e} (File: {filename}, line {lineno})", err=True)

        if ctx.obj['verbose']:
            traceback.print_exc()

        sys.exit(1)


if __name__ == '__main__':
    cli()
