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
        click.echo(f"🚀 {settings.system_name} v{settings.system_version}")
        click.echo(f"📊 Symbols: {', '.join(settings.symbols)}")
        click.echo(f"💰 Initial Balance: ${settings.initial_balance:,}")


@cli.command()
@click.option('--symbols', '-s', multiple=True, 
              help='Trading symbols (e.g., EURUSD, GBPUSD)')
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
def backtest(ctx, symbols, start_date, end_date, balance, risk, 
             save_results, output_dir, show_signals, show_sessions, 
             show_choch, interactive, create_report, no_plots):
    """Run backtesting on historical data with integrated plotting"""
    from .commands.backtest import run_backtest
    
    # Use defaults if not provided
    symbols = list(symbols) if symbols else settings.symbols
    
    if not start_date:
        from datetime import datetime
        start_date = datetime.strptime(settings.get('backtesting.default_start', '2025-08-01'), '%Y-%m-%d')
    
    if not end_date:
        from datetime import datetime
        end_date = datetime.strptime(settings.get('backtesting.default_end', '2025-08-31'), '%Y-%m-%d')
    
    balance = balance or settings.initial_balance
    risk = risk or settings.default_risk_percent
    
    if not ctx.obj['quiet']:
        click.echo(f"🔄 Starting backtest with integrated plotting...")
        click.echo(f"📈 Symbols: {', '.join(symbols)}")
        click.echo(f"📅 Period: {start_date.date()} to {end_date.date()}")
        click.echo(f"💰 Balance: ${balance:,} | Risk: {risk:.1%}")
        
        if not no_plots:
            click.echo(f"📊 Charts: {'Interactive' if interactive else 'Static'}")
            click.echo(f"📋 Reports: {'Yes' if create_report else 'No'}")
        else:
            click.echo(f"📊 Charts: Disabled")
    
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
            click.echo("✅ Backtest completed successfully!")
            
            # Show plotting results if enabled
            if not no_plots and 'plotting' in results:
                plotting_info = results['plotting']
                click.echo(f"📊 Generated {len(plotting_info['charts'])} charts")
                click.echo(f"📁 Reports saved to: {plotting_info['report_directory']}")
                
    except Exception as e:
        import sys, traceback
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        filename = tb.filename
        lineno = tb.lineno

        click.echo(f"❌ Backtest failed: {e} (File: {filename}, line {lineno})", err=True)

        if ctx.obj['verbose']:
            traceback.print_exc()

        sys.exit(1)



@cli.command()
@click.option('--symbols', '-s', multiple=True,
              help='Trading symbols for live trading')
@click.option('--account', type=int, help='MT5 account number')
@click.option('--password', help='MT5 account password')
@click.option('--server', help='MT5 server name')
@click.option('--balance', '-b', type=float, default=None,
              help='Override account balance')
@click.option('--risk', '-r', type=float, default=None,
              help='Risk percentage per trade')
@click.option('--dry-run', is_flag=True, default=False,
              help='Run in simulation mode (no real trades)')
@click.pass_context
def live(ctx, symbols, account, password, server, balance, risk, dry_run):
    """Start live trading"""
    from .commands.live import run_live_trading
    
    symbols = list(symbols) if symbols else settings.symbols
    
    if not ctx.obj['quiet']:
        mode = "DRY RUN" if dry_run else "LIVE"
        click.echo(f"🎯 Starting {mode} trading...")
        click.echo(f"📈 Symbols: {', '.join(symbols)}")
        
        if dry_run:
            click.echo("⚠️  DRY RUN MODE - No real trades will be placed!")
    
    try:
        run_live_trading(
            symbols=symbols,
            account=account,
            password=password,
            server=server,
            balance=balance,
            risk_percent=risk,
            dry_run=dry_run,
            verbose=ctx.obj['verbose']
        )
        
    except KeyboardInterrupt:
        click.echo("\n🛑 Live trading stopped by user")
    except Exception as e:
        click.echo(f"❌ Live trading failed: {e}", err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option('--show-all', is_flag=True, help='Show all configuration')
@click.option('--section', help='Show specific configuration section')
@click.option('--set', 'set_value', nargs=2, type=str, metavar='KEY VALUE',
              help='Set configuration value')
@click.option('--save', is_flag=True, help='Save configuration changes')
@click.pass_context
def config(ctx, show_all, section, set_value, save):
    """View and modify configuration"""
    from .commands.config import run_config_management
    
    try:
        run_config_management(
            show_all=show_all,
            section=section,
            set_value=set_value,
            save_changes=save,
            verbose=ctx.obj['verbose']
        )
        
    except Exception as e:
        click.echo(f"❌ Configuration management failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--logs-dir', type=click.Path(exists=True), default=None,
              help='Logs directory to analyze')
@click.option('--log-type', type=click.Choice(['all', 'trading', 'backtest', 'connection', 'system']),
              default='all', help='Type of logs to show')
@click.option('--tail', '-n', type=int, default=50, 
              help='Number of recent entries to show')
@click.option('--follow', '-f', is_flag=True, help='Follow log file (like tail -f)')
@click.option('--filter', 'filter_text', help='Filter log entries by text')
@click.pass_context
def logs(ctx, logs_dir, log_type, tail, follow, filter_text):
    """View and analyze system logs"""
    from .commands.logs import run_log_analysis
    
    try:
        run_log_analysis(
            logs_dir=logs_dir,
            log_type=log_type,
            tail_count=tail,
            follow=follow,
            filter_text=filter_text,
            verbose=ctx.obj['verbose']
        )
        
    except KeyboardInterrupt:
        click.echo("\n📋 Log monitoring stopped")
    except Exception as e:
        click.echo(f"❌ Log analysis failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--connection-test', is_flag=True, help='Test MT5 connection')
@click.option('--data-test', is_flag=True, help='Test data fetching')
@click.option('--strategy-test', is_flag=True, help='Test strategy initialization')
@click.option('--all-tests', is_flag=True, help='Run all tests')
@click.pass_context
def test(ctx, connection_test, data_test, strategy_test, all_tests):
    """Run system tests and diagnostics"""
    from .commands.test import run_system_tests
    
    if not ctx.obj['quiet']:
        click.echo("🧪 Running system tests...")
    
    try:
        results = run_system_tests(
            test_connection=connection_test or all_tests,
            test_data=data_test or all_tests,
            test_strategy=strategy_test or all_tests,
            verbose=ctx.obj['verbose']
        )
        
        if not ctx.obj['quiet']:
            passed = sum(1 for r in results.values() if r['passed'])
            total = len(results)
            click.echo(f"✅ Tests completed: {passed}/{total} passed")
            
            for test_name, result in results.items():
                status = "✅" if result['passed'] else "❌"
                click.echo(f"  {status} {test_name}: {result['message']}")
                
    except Exception as e:
        click.echo(f"❌ System tests failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """Show system status with system hours and session hours distinction"""
    
    from datetime import datetime, timedelta
    
    if not ctx.obj['quiet']:
        current_time = datetime.now()
        current_time_str = current_time.strftime('%H:%M:%S')
        
        # Get system hours configuration
        system_config = settings.get('live_trading.system_hours', {
            'start': '09:30', 
            'end': '13:30'
        })
        
        # Get trading sessions
        sessions_config = settings.get("trading.sessions", {})
        
        # Get MBox hours  
        mbox_config = settings.get('trading.mbox_hours', {
            'start': '01:00',
            'end': '08:59'
        })
        
        # Check current status
        system_start = datetime.strptime(system_config['start'], '%H:%M').time()
        system_end = datetime.strptime(system_config['end'], '%H:%M').time()
        is_system_time = system_start <= current_time.time() <= system_end
        
        # Check if in any trading session
        is_trading_session = False
        active_sessions = []
        
        for session_name, session_data in sessions_config.items():
            session_start = datetime.strptime(session_data['start'], '%H:%M').time()
            session_end = datetime.strptime(session_data['end'], '%H:%M').time()
            
            if session_start <= current_time.time() <= session_end:
                is_trading_session = True
                active_sessions.append(session_name)
        
        click.echo("📊 Two Hunters Trading System Status")
        click.echo("=" * 50)
        click.echo(f"🕐 Current Time: {current_time_str}")
        click.echo("")
        
        # System Configuration
        click.echo(f"🔧 Configuration: Loaded")
        click.echo(f"📁 Logs Directory: {settings.get_paths()['logs']}")
        click.echo(f"💾 Data Directory: {settings.get_paths()['data']}")
        click.echo(f"📤 Outputs Directory: {settings.get_paths()['outputs']}")
        click.echo("")
        
        # System Hours vs Session Hours
        click.echo(f"⏰ SYSTEM HOURS (Engine Operation)")
        system_status = "🟢 ACTIVE" if is_system_time else "🔴 INACTIVE"
        click.echo(f"   {system_config['start']} - {system_config['end']} | Status: {system_status}")
        click.echo("")
        
        click.echo(f"📈 TRADING SESSIONS (Signal Generation)")
        if not sessions_config:
            click.echo("   No trading sessions configured")
        else:
            for session_name, session_data in sessions_config.items():
                session_start = datetime.strptime(session_data['start'], '%H:%M').time()
                session_end = datetime.strptime(session_data['end'], '%H:%M').time()
                is_active = session_start <= current_time.time() <= session_end
                session_status = "🟢 ACTIVE" if is_active else "⚫ INACTIVE"
                
                click.echo(f"   {session_name.title()}: {session_data['start']} - {session_data['end']} | {session_status}")
        
        click.echo("")
        click.echo(f"🔍 MBOX ANALYSIS HOURS")
        mbox_start = datetime.strptime(mbox_config['start'], '%H:%M').time()
        mbox_end = datetime.strptime(mbox_config['end'], '%H:%M').time()
        is_mbox_time = mbox_start <= current_time.time() <= mbox_end
        mbox_status = "🟢 ACTIVE" if is_mbox_time else "⚫ INACTIVE"
        click.echo(f"   {mbox_config['start']} - {mbox_config['end']} | Status: {mbox_status}")
        click.echo("")
        
        # Strategy Configuration
        click.echo(f"🎯 Strategy: TwoHunters")
        click.echo(f"📈 Symbols: {', '.join(settings.symbols)}")
        click.echo(f"💰 Initial Balance: ${settings.initial_balance:,}")
        click.echo(f"⚠️  Risk per Trade: {settings.default_risk_percent:.1%}")
        click.echo("")
        
        # Current System State
        click.echo(f"🚦 CURRENT SYSTEM STATE:")
        if is_system_time:
            if is_trading_session:
                if active_sessions:
                    click.echo(f"   ✅ SYSTEM ACTIVE - Trading in session(s): {', '.join(active_sessions)}")
                else:
                    click.echo(f"   ✅ SYSTEM ACTIVE - Trading sessions active")
            else:
                click.echo(f"   🟡 SYSTEM ACTIVE - Monitoring only (no trading sessions)")
        else:
            click.echo(f"   🛑 SYSTEM INACTIVE - Outside system operating hours")
        
        # Next state change
        click.echo("")
        click.echo(f"⏭️  NEXT STATE CHANGES:")
        
        # Find next system hours change
        if is_system_time:
            # System is active, when does it end?
            system_end_today = datetime.combine(current_time.date(), system_end)
            if current_time < system_end_today:
                next_change = system_end_today
                next_action = "System will go INACTIVE"
            else:
                # System ends tomorrow
                next_change = datetime.combine(current_time.date() + timedelta(days=1), system_start)
                next_action = "System will become ACTIVE"
        else:
            # System is inactive, when does it start?
            system_start_today = datetime.combine(current_time.date(), system_start)
            if current_time < system_start_today:
                next_change = system_start_today
                next_action = "System will become ACTIVE"
            else:
                # System starts tomorrow
                next_change = datetime.combine(current_time.date() + timedelta(days=1), system_start)
                next_action = "System will become ACTIVE"
        
        time_until = next_change - current_time
        hours, remainder = divmod(int(time_until.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        
        click.echo(f"   {next_action} at {next_change.strftime('%H:%M')} (in {hours}h {minutes}m)")
        
        # Find next trading session change
        if is_trading_session and active_sessions:
            # Find when current session ends
            for session_name in active_sessions:
                session_data = sessions_config[session_name]
                session_end_time = datetime.strptime(session_data['end'], '%H:%M').time()
                session_end_today = datetime.combine(current_time.date(), session_end_time)
                
                if current_time < session_end_today:
                    time_until_end = session_end_today - current_time
                    hours, remainder = divmod(int(time_until_end.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    click.echo(f"   {session_name.title()} session ends at {session_data['end']} (in {hours}h {minutes}m)")
        else:
            # Find next trading session start
            next_session_start = None
            next_session_name = None
            
            for session_name, session_data in sessions_config.items():
                session_start_time = datetime.strptime(session_data['start'], '%H:%M').time()
                session_start_today = datetime.combine(current_time.date(), session_start_time)
                
                if current_time < session_start_today:
                    if next_session_start is None or session_start_today < next_session_start:
                        next_session_start = session_start_today
                        next_session_name = session_name
            
            if next_session_start:
                time_until_session = next_session_start - current_time
                hours, remainder = divmod(int(time_until_session.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                click.echo(f"   Next trading session ({next_session_name}) starts at {next_session_start.strftime('%H:%M')} (in {hours}h {minutes}m)")
        
        click.echo("")
        
        # System health checks
        try:
            from pathlib import Path
            logs_path = Path(settings.get_paths()['logs'])
            if logs_path.exists():
                click.echo(f"📝 Logs: Available ({len(list(logs_path.glob('*.log')))} files)")
            else:
                click.echo(f"📝 Logs: Directory not found")
        except Exception:
            click.echo(f"📝 Logs: Error checking status")
        
        click.echo("")
        click.echo("=" * 50)
        click.echo("💡 Legend:")
        click.echo("   🟢 ACTIVE - Currently operating")
        click.echo("   🔴/⚫ INACTIVE - Not currently operating")
        click.echo("   🟡 ACTIVE (monitoring) - System running but no trading")
        click.echo("")
        click.echo("📚 Note: System Hours = When engine runs, Trading Sessions = When signals are generated")

if __name__ == '__main__':
    cli()
