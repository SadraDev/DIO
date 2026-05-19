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

    if balance is None:
        balance = settings.get("account.balance", None)
    
    if risk is None:
        risk = settings.get("account.default_risk_percent", None)

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
        click.echo(f"    Risk Manager:                   {'-Active' if use_risk_manager else '-DeActive'}")
        click.echo(f"    2R for EURUSD:                  {'-Active' if use_2r_for_eur else '-DeActive'}")
        click.echo(f"    Online Commission Manager:      {'-Active' if use_online_commission_manager else '-DeActive'}")
        click.echo(f"    Offline Commission Manager:     {'-Active' if use_offline_commission_manager else '-DeActive'}")
        click.echo(f"    Reports:                        {'-Active' if not no_reports else '-DeActive'}")
        click.echo(f"    Charts:                         {'-Active' if not no_plots else '-DeActive'}")
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
@click.pass_context
def live(ctx):
    import json
    import time
    import threading

    from datetime import datetime, timedelta, timezone

    from config.settings import settings
    from src.core.models.budget import Budget
    from src.core.execution.mt5_connection import MT5Connection
    from src.indicators.fvg_detector import FVGDetector
    from src.strategies.two_hunters import TwoHunters
    from src.core.utils.logger import TradingLogger

    log = TradingLogger.get_main_logger()

    BROKER_TZ = timezone(timedelta(hours=6, minutes=30))
    symbols   = settings.symbols
    risk      = settings.default_risk_percent

    running_workers    = {}
    signals_file_lock  = threading.Lock()

    # ──────────────────────────────────────────────────────────
    # helpers
    # ──────────────────────────────────────────────────────────

    def now():
        return datetime.now(BROKER_TZ)

    def is_weekend(dt):
        return dt.weekday() >= 5

    def session_start_dt(dt):
        return datetime.combine(
            dt.date(),
            datetime.strptime(
                settings.get("strategies.two_hunters.sessions.main.start"),
                "%H:%M"
            ).time(),
            tzinfo=BROKER_TZ
        )

    def session_end_dt(dt):
        return datetime.combine(
            dt.date(),
            datetime.strptime(
                settings.get("strategies.two_hunters.sessions.main.end"),
                "%H:%M"
            ).time(),
            tzinfo=BROKER_TZ
        )

    def wait_until_market_open():
        while True:
            current = now()
            if is_weekend(current):
                log.info("Weekend – sleeping 60 min...")
                time.sleep(3600)
                continue
            start = session_start_dt(current)
            if current >= start:
                return
            secs = max(int((start - current).total_seconds()), 1)
            log.info(f"Waiting for session open in {secs}s...")
            time.sleep(min(secs, 1800))

    def stop_all_workers():
        for symbol, w in list(running_workers.items()):
            log.info(f"Stopping worker {symbol}")
            w["stop_event"].set()
            w["thread"].join(timeout=10)
        running_workers.clear()

    # ──────────────────────────────────────────────────────────
    # MAIN LOOP  – runs forever, one trading day per iteration
    # ──────────────────────────────────────────────────────────

    while True:

        wait_until_market_open()

        current_date = now().date()
        log.info(f"=== Starting trading day {current_date} ===")

        # ── MT5 connection ────────────────────────────────────
        mt5_conn = MT5Connection()
        if not mt5_conn.initialize_connection():
            log.error("MT5 connection failed – retrying in 10s")
            time.sleep(10)
            continue

        account_info = mt5_conn.get_account_info()
        if account_info is None:
            log.error("Could not get account info – retrying in 10s")
            time.sleep(10)
            continue

        balance = account_info.balance
        log.info(f"Account balance: ${balance:.0f}")

        budget = Budget(initial_balance=balance, initial_risk_percent=risk)

        # ── preload FVGs ──────────────────────────────────────
        try:
            log.info("Loading FVG cache...")
            detector = FVGDetector(symbols=symbols, timeframes=["M15", "H8"])
            detector.load_fvgs_from_cache()
            log.info("FVGs loaded")
        except Exception as e:
            log.error(f"FVG load failed: {e}")

        # ── kill any leftover workers from the previous day ───
        stop_all_workers()

        # ── launch one worker thread per symbol ───────────────
        for symbol in symbols:
            budget.calculate_lot_size(symbol)
            budget.calculate_pip_size(symbol)

            strategy = TwoHunters(budget=budget)
            strategy.symbol = symbol

            stop_event = threading.Event()

            thread = threading.Thread(
                target=strategy.live_worker,
                args=(stop_event, mt5_conn, signals_file_lock),
                daemon=True
            )
            thread.start()

            running_workers[symbol] = {
                "thread": thread,
                "stop_event": stop_event,
                "date": current_date,
            }
            log.info(f"Worker started: {symbol}")

        # ── wait until session end ────────────────────────────
        while True:
            current = now()

            if is_weekend(current):
                log.info("Weekend started mid-day")
                break

            if current >= session_end_dt(current):
                log.info("Session ended")
                break

            # also break if the calendar date rolled over
            if current.date() != current_date:
                log.info("New calendar day - restarting loop")
                break

            time.sleep(30)

        stop_all_workers()
        mt5_conn.shutdown_connection()
        log.info(f"=== Trading day {current_date} complete ===")

        # brief pause before the next wait_until_market_open check
        time.sleep(60)