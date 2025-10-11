from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from pathlib import Path

from src.core.models.signal import Signal
from src.core.models.budget import Budget
from src.core.models.bar import Bar
from src.core.data.fetcher import DataFetcher
from src.strategies.manager import StrategyManager
from config.settings import settings
from src.core.utils.logger import TradingLogger, log_system_event


class BacktestEngine:
    """Backtesting engine for strategy evaluation"""
    
    def __init__(self):
        self.logger = TradingLogger.get_backtest_logger()
        self.data_fetcher = DataFetcher()
        self.strategy_manager = StrategyManager()
        
        # Backtest configuration
        self.save_results = settings.get('backtesting.save_results', True)
        self.output_format = settings.get('backtesting.output_format', 'csv')
    
    def run_backtest(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run comprehensive backtest across multiple symbols
        
        Args:
            symbols: List of trading symbols
            start_date: Backtest start date
            end_date: Backtest end date
            initial_balance: Starting balance
            risk_percent: Risk per trade
            output_dir: Output directory for results
            
        Returns:
            Backtest results dictionary
        """
        log_system_event("backtest_started", 
                        symbols=symbols, 
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        initial_balance=initial_balance)
        
        results = {}
        for symbol in symbols:
            results[symbol] = []

        try:
            strategy = self.strategy_manager.create_two_hunters_strategy()

            # Fetch historical data
            self.logger.info(f"Fetching data for {symbols} from {start_date} to {end_date}")

            # Process day by day
            current_date = start_date
            signals = []
            days_processed = 0
            bars_processed = 0
            while current_date <= end_date:

                current_date_start = datetime(current_date.year, current_date.month, current_date.day, hour=0, minute=0)
                current_date_end = datetime(current_date.year, current_date.month, current_date.day, hour=23, minute=59)

                for symbol in symbols:

                    daily_bars = self.data_fetcher.fetch_bars_from_mt5(current_date_start, current_date_end, symbol)
                    bars_processed += len(daily_bars)
                    
                    if daily_bars:
                        
                        strategy.symbol = symbol
                        strategy.add_bars(daily_bars)
                        main_signal = strategy.attempt_signal(current_date)
                        
                        if main_signal:
                            main_signal.evaluate_signal()
                            
                            if main_signal.is_completed:
                                results[symbol].append(main_signal)
                                signals.append(main_signal)
                                strategy.budget.apply_signal_gain(main_signal)
                                
                                self.logger.debug(f"Main signal completed: {main_signal.outcome.value}, "
                                                f"Gain: {main_signal.gain}")
                                
                                if main_signal.outcome.value == 'loss':
                                    
                                    recovery_signal = strategy.attempt_signal(current_date, main_signal)
                                    
                                    if recovery_signal:
                                        recovery_signal.evaluate_signal()
                                        
                                        if recovery_signal.is_completed:
                                            results[symbol].append(recovery_signal)
                                            signals.append(recovery_signal)
                                            strategy.budget.apply_signal_gain(recovery_signal)
                                            
                                            self.logger.debug(f"Recovery signal completed: "
                                                            f"{recovery_signal.outcome.value}, "
                                                            f"Gain: {recovery_signal.gain}")
                        
                days_processed += 1
                current_date += timedelta(days=1)
            
            # Evaluate prop status
            strategy.budget.evaluate_prop_status(signals)

            results["all"] = {
                    'signals': signals,
                    'budget': strategy.budget,
                    'bars_processed': bars_processed,
                    'days_processed': days_processed
                }

            # Generate summary
            overall_summary = self._generate_overall_summary(results)
            results['_summary'] = overall_summary
            
            # Save results if configured
            if self.save_results and output_dir:
                self._save_results(results, output_dir, start_date, end_date)
            
            log_system_event("backtest_completed", 
                            symbols=symbols,
                            total_signals=overall_summary.get('total_signals', 0),
                            overall_profit=overall_summary.get('total_profit', 0))
            
            return results
            
        except Exception as e:
            log_system_event("backtest_error", error=str(e))
            raise

    def _generate_overall_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall backtest summary"""
        
        signals = results['all']['signals']
        budget = results['all']['budget']

        if not signals:
            return {
                'total_signals': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'avg_profit_per_trade': 0.0,
                'symbols_processed': len(results) - 1
            }
        
        # Calculate metrics
        completed_signals = [s for s in signals if s.is_completed]
        wins = sum(1 for s in completed_signals if s.outcome.value == 'win')
        total_profit = sum(s.gain for s in completed_signals if s.gain)
        
        return {
            'total_signals': len(completed_signals),
            'win_rate': (wins / len(completed_signals)) * 100 if completed_signals else 0,
            'total_profit': total_profit,
            'avg_profit_per_trade': total_profit / len(completed_signals) if completed_signals else 0,
            'symbols_processed': len([k for k in results.keys() if not k.startswith('_')])-1,
            'prop_statuses': budget.evaluate_prop_status(signals)
        }
    
    def _save_results(self, results: Dict[str, Any], output_dir: str, start_date: datetime, end_date: datetime):
        """Save backtest results to files"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        date_range = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        
        # Save detailed results per symbol
        all_data = []
        
        for symbol, result in results.items():
            if symbol.startswith('_'):
                continue
                
            signals = result['signals']
            budget = result['budget']
            
            for signal in signals:
                all_data.append({
                    'Symbol': symbol,
                    'Timestamp': signal.timestamp.isoformat(),
                    'Action': signal.action.value,
                    'Type': signal.signal_type.value,
                    'Entry_Price': signal.entry_price,
                    'Stop_Loss': signal.stop_loss,
                    'Take_Profit': signal.take_profit,
                    'Entry_Lot': signal.entry_lot,
                    'SL_Pips': signal.stop_loss_pips,
                    'TP_Pips': signal.take_profit_pips,
                    'Outcome': signal.outcome.value if signal.outcome else 'pending',
                    'Gain': signal.gain,
                    'Outcome_Timestamp': signal.outcome_timestamp.isoformat() if signal.outcome_timestamp else None
                })
        
        # Save to CSV
        if all_data:
            df = pd.DataFrame(all_data)
            csv_file = output_path / f"backtest_results_{date_range}_{timestamp}.csv"
            df.to_csv(csv_file, index=False)
            self.logger.info(f"Results saved to: {csv_file}")
        
        # Save summary
        summary = results.get('_summary', {})
        summary_file = output_path / f"backtest_summary_{date_range}_{timestamp}.txt"
        
        with open(summary_file, 'w') as f:
            f.write(f"Two Hunters Trading System - Backtest Summary\n")
            f.write(f"{'='*50}\n")
            f.write(f"Date Range: {start_date.date()} to {end_date.date()}\n")
            f.write(f"Symbols: {', '.join([k for k in results.keys() if not k.startswith('_')])}\n")
            f.write(f"Total Signals: {summary.get('total_signals', 0)}\n")
            f.write(f"Win Rate: {summary.get('win_rate', 0):.2f}%\n")
            f.write(f"Total Profit: ${summary.get('total_profit', 0):.2f}\n")
            f.write(f"Avg Profit/Trade: ${summary.get('avg_profit_per_trade', 0):.2f}\n")
        
        self.logger.info(f"Summary saved to: {summary_file}")
