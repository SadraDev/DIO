import click
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from src.core.utils.logger import TradingLogger, log_system_event
from src.core.execution.mt5_connection import MT5Connection


@click.group()
@click.version_option(version=settings.system_version, prog_name=settings.system_name)
@click.option('--config', '-c', type=click.Path(exists=True), 
              help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--quiet', '-q', is_flag=True, help='Suppress output except errors')
@click.pass_context
def two_hunters_cli(ctx, config, verbose, quiet):
    
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

@two_hunters_cli.command()
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
@click.option('--no-risk-manager', is_flag=True, default=False,
              help='Show trading signals on charts')
@click.option('--output-dir', type=click.Path(), default=None,
              help='Output directory for results')

# PLOTTING OPTIONS 
@click.option('--no-signals', is_flag=True, default=False,
              help='Show trading signals on charts')
@click.option('--no-mbox', is_flag=True, default=False,
              help='Highlight trading mbox on charts')
@click.option('--no-reports', is_flag=True, default=False,
              help='Skip report generation (backtest only)')
@click.option('--no-plots', is_flag=True, default=False,
              help='Skip chart generation (backtest only)')
@click.option('--use-trend-flag', is_flag=True, default=False,
              help='If the Mbox has trend, no signal will be generated.')
@click.option('--use-time-flag', is_flag=True, default=False,
              help='If the Mbox has extrema after 12, no signal will be generated.')
@click.pass_context
def backtest(ctx, symbol, start_date, end_date, balance,
             risk, no_risk_manager, output_dir, no_signals,
             no_mbox, no_reports, no_plots, use_trend_flag, use_time_flag
             ):
    """Run backtesting on historical data with integrated plotting"""
    from src.strategies.two_hunters import TwoHuntersStrategy
    twohunters = TwoHuntersStrategy()

    # Use defaults if not provided
    symbols = list(symbol) if symbol else settings.symbols
    
    if not start_date:
        from datetime import datetime
        start_date = datetime.strptime(settings.get('strategies.two_hunters.backtesting.default_start', '2001-09-11'), '%Y-%m-%d')
    
    if not end_date:
        from datetime import datetime
        end_date = datetime.strptime(settings.get('strategies.two_hunters.backtesting.default_end', '2001-09-11'), '%Y-%m-%d')
    
    balance = balance or settings.initial_balance
    risk = risk or settings.default_risk_percent
    
    if not ctx.obj['quiet']:
        click.echo(f"Starting backtest with {', '.join(symbols)}")
        click.echo(f"Period: {start_date.date()} to {end_date.date()}")
        click.echo(f"Balance: ${balance:,} | Risk: {risk:.1%} | Risk Manager: {'Enabled' if not no_risk_manager else 'Disabled'}")
        click.echo(f"Charts: {'Enabled' if not no_plots else 'Disabled'}")
        click.echo(f"   Show Mbox: {'Enabled' if not no_mbox else 'Disabled'}") if not no_plots else None
        click.echo(f"   Show Signals: {'Enabled' if not no_signals else 'Disabled'}") if not no_plots else None
        click.echo(f"Reports: {'Enabled' if not no_reports else 'Disabled'}")
    
    
    try:
        twohunters.budget.initial_balance = balance
        twohunters.budget.current_balance = balance
        twohunters.budget.initial_risk_percent = risk
        twohunters.budget.current_risk_percent = risk
        twohunters.use_trend_flag = use_trend_flag
        twohunters.use_trend_flag = use_time_flag

        results = twohunters.backtest(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            output_dir=output_dir,
            no_risk_manager=no_risk_manager,
            verbose=ctx.obj['verbose'],
            # Plotting parameters (only if not disabled)
            no_reports=no_reports,
            no_plots=no_plots,
            no_signals=no_signals,
            no_mbox=no_mbox,
        )
        
        if not ctx.obj['quiet']:
            click.echo("Backtest completed successfully")

    except Exception as e:
        import sys, traceback
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        filename = tb.filename
        lineno = tb.lineno

        click.echo(f"Backtest failed: {e} (File: {filename}, line {lineno})", err=True)

        if ctx.obj['verbose']:
            traceback.print_exc()

        sys.exit(1)


# NEW LIVE COMMAND - ADDED HERE
@two_hunters_cli.command()
@click.option('--symbol', '-s', multiple=True, 
              help='Trading symbol (e.g., EURUSD, GBPUSD). If not provided, uses symbols from config.')
@click.option('--risk', '-r', help='Risk percent to risk. If not provided, uses default from config.')
@click.pass_context
def live(ctx, symbol, risk):
    """Start live trading with the Two Hunters strategy"""
    
    from src.core.models.budget import Budget
    from src.strategies.two_hunters import TwoHuntersStrategy
    
    mt5 = MT5Connection()

    # Resolve symbols
    symbols = list(symbol) if symbol else settings.get('trading.symbols', ['EURUSD.', 'GBPUSD.'])

    # Handle risk configuration
    risk = settings.get('account.default_risk_percent', 0.01)

    # Detect account balance
    account = mt5.get_account_info()
    if account is not None and hasattr(account, "balance"):
        balance = float(account.balance)
        settings.set('account.initial_balance', balance)
        if not ctx.obj['quiet']:
            click.echo(f"Account balance detected from MT5: ${balance:,.2f}")
    else:
        balance = settings.get('account.initial_balance', 1000.0)
        if not ctx.obj['quiet']:
            click.echo(f"Account balance fallback (config): ${balance:,.2f}")

    if not ctx.obj['quiet']:
        click.echo(f"Starting live trading with Two Hunters strategy")
        click.echo(f"Symbols: {', '.join(symbols)}")
        click.echo(f"Balance: ${balance:,.2f}")
        click.echo(f"  Risk per trade: {risk:.2%}")
        click.echo()
        click.echo("Press Ctrl+C to stop live trading")
        click.echo("=" * 50)

    budget = Budget(initial_risk_percent=risk, initial_balance=balance)
    twohunters = TwoHuntersStrategy(budget=budget)
    twohunters.budget.initial_balance = balance
    twohunters.budget.initial_risk_percent
    
    import signal
    def signal_handler(signum, frame):
            """Handle Ctrl+C gracefully"""
            print("\n=Shuting down...")
            print("live trading stoped.")
            sys.exit(0)
        
        # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        twohunters.live(symbols)
    except KeyboardInterrupt:
        print("\nLive trading interrupted by user")
    except Exception as e:
        click.echo(f"Error running live: {e}")
    
if __name__ == '__main__':
    two_hunters_cli()
