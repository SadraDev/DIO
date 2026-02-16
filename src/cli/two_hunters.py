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
              help='Trading symbol (e.g., EURUSD, GBPUSD).')
@click.option('--start-date', '-sd', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Backtest start date (YYYY-MM-DD).')
@click.option('--end-date', '-ed', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Backtest end date (YYYY-MM-DD).')
@click.option('--output-dir', type=click.Path(), default=None,
              help='Output directory for results.')

# PLOTTING OPTIONS 
@click.option('--no-signals', is_flag=True, default=False,
              help='Show trading signals on charts.')
@click.option('--no-mbox', is_flag=True, default=False,
              help='Highlight trading mbox on charts.')
@click.option('--show-15m-bars', is_flag=True, default=False,
              help='Show 15m bars on 1m charts.')
@click.option('--no-reports', is_flag=True, default=False,
              help='Skip report generation (backtest only).')
@click.option('--no-plots', is_flag=True, default=False,
              help='Skip chart generation (backtest only).')

# TRADING FLAGS
@click.option('--use-trend-flag', is_flag=True, default=False,
              help='If the Mbox has trend, no signal will be generated.')
@click.option('--use-large-slp-flag', is_flag=True, default=False,
              help='If the Stop loss pips are large relative to lot size, switch to 1:2 ratio.')
@click.option('--use-2r-for-eur', is_flag=True, default=False,
              help='If active, uses 1:2 ratio for EURUSD.')
@click.option('--use-time-flag', is_flag=True, default=False,
              help='If the Mbox has extrema after 12, no signal will be generated.')
@click.option('--use-risk-manager', is_flag=True, default=False,
              help='Use 1R, 2R, 3R post 3R SL adjustments.')
@click.option('--use-online-commission-manager', is_flag=True, default=False,
              help='Cover commission cost by adjusting SL.')
@click.option('--use-offline-commission-manager', is_flag=True, default=False,
              help='Cover commission cost by adjusting Lot size.')
 
# VALUES
@click.option('--commission', type=float, default=None,
              help='Commission amount per lot.')
@click.option('--balance', '-b', type=float, default=None,
              help='Initial balance for backtest')
@click.option('--risk', '-r', type=float, default=None,
              help='Risk percentage per trade (e.g., 0.005 for 0.5%).')
@click.pass_context
def backtest(ctx, symbol, start_date, end_date, output_dir, no_signals, no_mbox, show_15m_bars,
             no_reports, no_plots, use_trend_flag, use_large_slp_flag, use_2r_for_eur,
             use_time_flag, use_risk_manager, use_online_commission_manager,
             use_offline_commission_manager, commission, balance, risk):
    
    """Run backtesting on historical data with integrated plotting"""
    from src.strategies.two_hunters import TwoHunters
    from src.core.models.budget import Budget
    from config.settings import settings

    _flags_path = "strategies.two_hunters.flags."
    settings.set("trading.commission", commission) if commission is not None else None
    if not settings.get(f"{_flags_path}use_2r_for_eur"): settings.set(f"{_flags_path}use_2r_for_eur", use_2r_for_eur)
    if not settings.get(f"{_flags_path}use_trend_flag"): settings.set(f"{_flags_path}use_trend_flag", use_trend_flag)
    if not settings.get(f"{_flags_path}use_risk_manager"): settings.set(f"{_flags_path}use_risk_manager", use_risk_manager)
    if not settings.get(f"{_flags_path}use_large_slp_flag"): settings.set(f"{_flags_path}use_large_slp_flag", use_large_slp_flag)
    if not settings.get(f"{_flags_path}use_online_commission_manager"): settings.set(f"{_flags_path}use_online_commission_manager", use_online_commission_manager)
    if not settings.get(f"{_flags_path}use_offline_commission_manager"): settings.set(f"{_flags_path}use_offline_commission_manager", use_offline_commission_manager)
    if not settings.get(f"{_flags_path}use_time_flag"): settings.set(f"{_flags_path}use_time_flag", use_time_flag)
    settings.set("account.default_risk_percent", risk) if risk is not None else None
    settings.set("account.balance", balance) if balance is not None else None

    budget = Budget(initial_balance=balance, initial_risk_percent=risk)
    twohunters = TwoHunters(budget=budget, use_trend_flag=use_trend_flag, use_time_flag=use_time_flag)

    # Use defaults if not provided
    symbols = list(symbol) if symbol else settings.symbols
    
    if not start_date:
        from datetime import datetime
        start_date = datetime.strptime(settings.get('strategies.two_hunters.backtesting.default_start', '2001-09-11'), '%Y-%m-%d')
    
    if not end_date:
        from datetime import datetime
        end_date = datetime.strptime(settings.get('strategies.two_hunters.backtesting.default_end', '2001-09-11'), '%Y-%m-%d')
    
    balance = balance or settings.balance
    risk = risk or settings.default_risk_percent

    if not ctx.obj['quiet']:
        click.echo(f"Starting backtest with          {', '.join(symbols)}")
        click.echo(f"Period:                         {start_date.date()} to {end_date.date()}")
        click.echo(f"Balance:                        ${balance:,} | Risk: {risk:.1%}")
        click.echo(f"Flags:")
        click.echo(f"    Risk Manager:               {'-Active' if use_risk_manager else '-DeActive'}")
        click.echo(f"    2R for EURUSD:              {'-Active' if use_2r_for_eur else '-DeActive'}")
        click.echo(f"    Online Commission Manager:  {'-Active' if use_online_commission_manager else '-DeActive'}")
        click.echo(f"    Offline Commission Manager: {'-Active' if use_offline_commission_manager else '-DeActive'}")
        click.echo(f"    Reports:                    {'-Active' if not no_reports else '-DeActive'}")
        click.echo(f"    Charts:                     {'-Active' if not no_plots else '-DeActive'}")
        click.echo(f"        Show Mbox:                  {'-Active' if not no_mbox else '-DeActive'}") if not no_plots else None
        click.echo(f"        Show Positions:             {'-Active' if not no_signals else '-DeActive'}") if not no_plots else None
        click.echo(f"        Show 15M candles:           {'-Active' if show_15m_bars else '-DeActive'}") if show_15m_bars else None
    
    try:
        results = twohunters.backtest(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            output_dir=output_dir,
            verbose=ctx.obj['verbose'],
            # Plotting parameters (only if not Active)
            no_reports=no_reports,
            no_plots=no_plots,
            no_signals=no_signals,
            no_mbox=no_mbox,
            show_15m_bars=show_15m_bars
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


@two_hunters_cli.command()
@click.option('--symbol', '-s', multiple=True, 
              help='Trading symbol e.g., EURUSD, GBPUSD. If not provided, uses symbols from config.')
@click.option('--risk', '-r', type=float, 
              help='Risk percent to risk. If not provided, uses default from config.')
@click.option('--max-concurrent', '-mc', type=int, default=5, 
              help='Maximum concurrent symbols trading (default: 5).')
@click.option('--check-interval', '-ci', type=int, default=5, 
              help='Bar check interval in seconds (default: 5).')
@click.option('--enable-monitoring', '-m', is_flag=True, 
              help='Enable real-time monitoring dashboard.')
@click.pass_context
def live(ctx, symbol, risk, max_concurrent, check_interval, enable_monitoring):
    """
    Start live trading with the Two Hunters strategy across multiple symbols.
    
    Key Features:
    • Multi-symbol concurrent trading with thread pool management
    • Automatic account balance sync from MT5 on startup
    • Daily trading loop (MBox end to Main session end)
    • Health monitoring with configurable check intervals
    • Graceful error recovery and thread management
    • Signal persistence with daily reset to prevent over-trading
    
    Examples:
        \b
        # Single symbol with default risk
        dio two-hunters live --symbol EURUSD.
        
        \b
        # Multiple symbols with custom risk
        dio two-hunters live -s EURUSD. -s GBPUSD. --risk 0.02
        
        \b
        # All configured symbols
        dio two-hunters live --risk 0.015 --max-concurrent 3
    """
    import sys
    import time
    import threading

    from src.core.models.budget import Budget
    from src.strategies.two_hunters import TwoHunters
    from src.core.execution.mt5_connection import MT5Connection
    from src.core.data.fetcher import DataFetcher
    from config.settings import settings
    from datetime import datetime, timedelta

    logger = TradingLogger.get_main_logger()
    fetcher = DataFetcher()

    # Resolve symbols
    symbols = list(symbol) if symbol else settings.get('trading.symbols', ['EURUSD.', 'GBPUSD.'])
    
    # Handle risk configuration
    risk = risk or settings.get('account.default_risk_percent', 0.01)
    
    # Validate risk
    if not (0 < risk <= 0.1):
        click.echo(f"ERROR: Risk must be between 0.001 and 0.1, got {risk}", err=True)
        sys.exit(1)
    
    if not ctx.obj.get('quiet'):
        click.echo(f"\n{'='*70}")
        click.echo(f"{'DIO LIVE TRADING - TWO HUNTERS STRATEGY':^70}")
        click.echo(f"{'='*70}\n")
    
    # Initialize MT5 connection
    mt5_connection = MT5Connection()
    
    if not mt5_connection.initialize_connection():
        click.echo("ERROR: Failed to initialize MT5 connection", err=True)
        logger.error("MT5 connection initialization failed")
        sys.exit(1)
    
    # Get account info
    account_info = mt5_connection.get_account_info()
    
    if account_info and hasattr(account_info, 'balance'):
        balance = float(account_info.balance)
        settings.set('account.balance', balance)
        if not ctx.obj.get('quiet'):
            click.echo(f"✓ Account balance: ${balance:,.2f}")
    else:
        balance = settings.get('account.balance', 10000.0)
        if not ctx.obj.get('quiet'):
            click.echo(f"⚠ Using fallback balance: ${balance:,.2f}")
    
    if not ctx.obj.get('quiet'):
        click.echo(f"\nConfiguration:")
        click.echo(f"  Symbols: {', '.join(symbols)}")
        click.echo(f"  Risk per trade: {risk*100:.2f}%")
        click.echo(f"  Max concurrent: {max_concurrent}")
        click.echo(f"  Check interval: {check_interval}s")
        click.echo(f"\n{'─'*70}")
        click.echo(f"Press Ctrl+C to stop live trading\n")
        click.echo(f"{'─'*70}\n")
    
    # Create budget
    budget = Budget(initial_balance=balance, initial_risk_percent=risk)
    
    # Initialize strategy instances
    two_hunters_instances = {}
    active_threads = {}
    stop_event = threading.Event()
    thread_lock = threading.Lock()
    
    # Get session times
    mbox_start_str = settings.get('strategies.two_hunters.mbox_time.start', '04:30')
    mbox_end_str = settings.get('strategies.two_hunters.mbox_time.end', '12:29')
    session_end_str = settings.get('strategies.two_hunters.sessions.main.end', '22:00')
    
    try:
        mbox_start = datetime.strptime(mbox_start_str, '%H:%M').time()
        mbox_end = datetime.strptime(mbox_end_str, '%H:%M').time()
        session_end = datetime.strptime(session_end_str, '%H:%M').time()
    except ValueError as e:
        click.echo(f"ERROR: Invalid session times in config: {e}", err=True)
        sys.exit(1)
    
    try:
        # Main trading loop
        while not stop_event.is_set():

            current_time = fetcher.get_latest_bars(symbols[0])[-1].timestamp if symbols else None
            current_time_only = current_time.time() if current_time else None
            
            # Check if we're in trading window (MBox end to session end)
            in_trading_window = (
                current_time_only >= mbox_end and 
                current_time_only <= session_end
            )
            
            if in_trading_window:
                with thread_lock:
                    # Initialize strategy instances if needed
                    for sym in symbols:
                        if sym not in two_hunters_instances:
                            try:
                                two_hunters_instances[sym] = TwoHunters(
                                    budget=budget,
                                    name=f"TwoHunters-{sym}"
                                )
                                two_hunters_instances[sym].symbol = sym
                                if not ctx.obj.get('quiet'):
                                    click.echo(
                                        f"[{current_time.strftime('%H:%M:%S')}] "
                                        f"Initialized {sym}"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to initialize strategy for {sym}: {e}")
                                continue
                        
                        # Start thread if not already running
                        if sym not in active_threads or not active_threads[sym].is_alive():
                            thread = threading.Thread(
                                target=_run_symbol_live_trading,
                                args=(
                                    two_hunters_instances[sym],
                                    stop_event,
                                    ctx.obj.get('quiet', False),
                                    check_interval,
                                    ctx.obj.get('verbose', False)
                                ),
                                name=f"TwoHunters-{sym}",
                                daemon=False
                            )
                            active_threads[sym] = thread
                            thread.start()
                            if not ctx.obj.get('quiet'):
                                click.echo(
                                    f"[{current_time.strftime('%H:%M:%S')}] "
                                    f"Started trading thread for {sym}"
                                )
                
                # Wait before next check
                time.sleep(min(check_interval, 5))
            
            else:
                # Outside trading window
                mbox_end_datetime = datetime.combine(
                    current_time.date(),
                    mbox_end
                )
                
                # Case 1: mbox_end hasn't arrived yet today - wait for it
                if mbox_end_datetime > current_time:
                    wait_seconds = (mbox_end_datetime - current_time).total_seconds()
                    next_event = mbox_end_datetime
                # Case 2: mbox_end has passed - wait for tomorrow's mbox_start
                else:
                    mbox_start_tomorrow = datetime.combine(
                        current_time.date() + timedelta(days=1),
                        mbox_start
                    )
                    wait_seconds = (mbox_start_tomorrow - current_time).total_seconds()
                    next_event = mbox_start_tomorrow
                
                if not ctx.obj.get('quiet'):
                    hours = int(wait_seconds // 3600)
                    minutes = int((wait_seconds % 3600) // 60)
                    click.echo(
                        f"[{current_time.strftime('%H:%M:%S')}] "
                        f"Outside trading window. Next in {hours}h {minutes}m"
                    )
                
                # Sleep (max 1 minute to stay responsive)
                time.sleep(min(wait_seconds, 60))

    
    except KeyboardInterrupt:
        if not ctx.obj.get('quiet'):
            click.echo("\n\n[!] Shutting down live trading...")
        stop_event.set()
    
    except Exception as e:
        import traceback
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        click.echo(f"\nERROR: {e}\n  File {tb.filename}, line {tb.lineno}", err=True)
        logger.error(f"Unexpected error in live trading: {e}", exc_info=True)
        if ctx.obj.get('verbose'):
            traceback.print_exc()
        sys.exit(1)
    
    finally:
        if not ctx.obj.get('quiet'):
            click.echo("\nWaiting for trading threads to finish...")
        
        # Wait for all threads
        for sym in list(active_threads.keys()):
            thread = active_threads[sym]
            if thread.is_alive():
                thread.join(timeout=10)
                if not ctx.obj.get('quiet'):
                    click.echo(f"  ✓ {sym} thread closed")
        
        # Cleanup
        mt5_connection.shutdown_connection()
        logger.info("Live trading session ended")
        
        if not ctx.obj.get('quiet'):
            click.echo("\n✓ Live trading stopped gracefully")


def _run_symbol_live_trading(
    two_hunters,
    stop_event,
    quiet=False,
    check_interval=5,
    verbose=False
):
    """
    Run live trading for a single symbol in a thread.
    This function is designed to be run in a separate thread for each symbol.
    It will continuously check for new bars and generate signals until the
    stop_event is set.
    """
    logger = TradingLogger.get_trading_logger()
    
    try:
        two_hunters.live(
            check_interval=check_interval,
            stop_event=stop_event
        )
    except Exception as e:
        logger.error(
            f"Error in live trading thread for {two_hunters.symbol}: {e}",
            exc_info=True
        )
        if verbose:
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    two_hunters_cli()
