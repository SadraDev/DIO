from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, time
from src.core.models.bar import Bar, TrendDirection
from src.core.data.fetcher import DataFetcher
from src.indicators.fvg_detector import FVGDetector
from src.core.models.budget import Budget
from src.core.models.signal import Signal, SignalType, SignalOutcome, SignalAction
from src.core.utils.logger import TradingLogger
from src.core.utils.plotter import TradingPlotter
from config.settings import settings
import click


class Tweny:
    """
    Tweny Strategy - Detects Fair Value Gaps (FVGs) using 3-bar price action patterns.
    
    Logic:
    1. Loop through bars sequentially
    2. Check each bar pair (bar_i, bar_i+1, bar_i+2)
    3. Detect FVG patterns:
       - Bullish: bar_i.close > bar_i+2.high OR bar_i+1.close > bar_i+2.high (gap up)
       - Bearish: bar_i.close < bar_i+2.low OR bar_i+1.close < bar_i+2.low (gap down)
    4. Validate both condition bars have same color and trendy direction
    5. Store FVG and mark as filled when price penetrates
    """
    
    def __init__(
        self,
        name: str = "Tweny",
        symbol: str = "GBPUSD.",
        budget: Optional[Budget] = None,
        timeframe: str = "M15"
    ):
        self.name = name
        self.symbol = symbol
        self.timeframe = timeframe
        self.budget = Budget() if budget is None else budget
        self.config: dict = settings.get("strategies.Tweny")
        
        # Initialize components
        self.fetcher = DataFetcher()
        self.fvg_detector = FVGDetector(symbols=[symbol])
        self.logger = TradingLogger.get_main_logger()
        
        # Strategy state
        self.M15_bars: List[Bar] = []
        self.M5_bars: List[Bar] = []
        self.detected_fvgs: List[dict] = []
        
        self.logger.info(f"Tweny strategy initialized: {symbol} {timeframe}")
    
  
    def detect_fvgs_in_bars(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """
        Detect FVGs by scanning consecutive 3-bar patterns.
        """
        
        self.logger.info(f"Fetching {self.timeframe} bars...")
        bars = self.fetcher.fetch_bars_from_mt5(
            start_dt=start_date,
            end_dt=end_date,
            symbol=self.symbol,
            timeframe=self.timeframe
        )

        if not bars:
            self.logger.warning("No bars fetched! FVG detection aborted.")
            return []
        
        self.M15_bars = bars
        self.logger.info(f"Fetched {len(bars)} M15 bars.")

        fvgs: List[Dict[str, Any]] = []
        
        if len(bars) < 3:
            return fvgs
        
        # Calculate pip size for this symbol
        self.budget.calculate_pip_size(self.symbol)
        pip_size = self.budget.pip_size or 0.0001
        
        # Main loop: check each 3-bar sequence
        n = len(bars)
        for i in range(n - 2):
            bar1 = bars[i]
            bar2 = bars[i + 1]
            bar3 = bars[i + 2]
            
            # === BULLISH FVG ===
            if bar2.close > bar1.high and bar3.close > bar2.high:
                # Validate: bar2 and bar3 same color
                if bar2.is_bullish and bar3.is_bullish:
                    # Validate: bar2 and bar3 same trend direnction
                    if bar2.trendy == bar3.trendy == TrendDirection.UPTREND:
                        # Calculate FVG size in pips
                        gap_high = bar1.high
                        gap_low = bar1.low
                        gap_pips = (gap_high - gap_low) / pip_size
                        
                        fvg = {
                            "type": "bullish",
                            "high": gap_high,
                            "low": gap_low,
                            "size_pips": gap_pips,
                            "bar_open_time": bar1.timestamp.isoformat(),
                            "detection_time": bar3.timestamp.isoformat(),
                            "filled_timestamp": None,
                        }
                        fvgs.append(fvg)
                        self.detected_fvgs.append(fvg)
                        self.logger.debug(
                            f"Bullish FVG detected: {gap_pips:.1f}p at {bar3.timestamp}"
                        )
            
            # === BEARISH FVG ===
            if bar2.close < bar1.low and bar3.close < bar2.low:
                # Validate: bar2 and bar3 same color
                if bar2.is_bearish and bar3.is_bearish:
                    # Validate: bar2 and bar3 same trendy
                    if bar2.trendy == bar3.trendy == TrendDirection.DOWNTREND:
                        # Calculate FVG size in pips
                        gap_low = bar1.low
                        gap_high = bar1.high
                        gap_pips = (gap_high - gap_low) / pip_size
                        
                        fvg = {
                            "type": "bearish",
                            "high": gap_high,
                            "low": gap_low,
                            "size_pips": gap_pips,
                            "bar_open_time": bar1.timestamp.isoformat(),
                            "detection_time": bar3.timestamp.isoformat(),
                            "filled_timestamp": None,
                        }
                        fvgs.append(fvg)
                        self.detected_fvgs.append(fvg)
                        self.logger.debug(
                            f"Bearish FVG detected: {gap_pips:.1f}p at {bar3.timestamp}"
                        )
        
        if not fvgs:
            self.logger.info("No FVGs detected.")
        else:
            self.logger.info(f"Detected {len(fvgs)} FVGs.")
        
        self.fvg_detector.ensure_symbol_storage(self.symbol)
        
        for fvg in fvgs:
            # Add to FVGDetector storage
            self.fvg_detector.fvgs[self.symbol][self.timeframe].append(fvg)

        # Clean and save
        self.fvg_detector.clean_filled_fvgs()
        self.fvg_detector.save_fvgs_to_cache()
        self.detected_fvgs.sort(key=lambda x: x['detection_time'])

    def calculate_entry_details(self, bar: Bar, action: str, extrema: int) -> Signal:
        _m = self.config.get("ratio")["tp"]
        _n = self.config.get("sl_margin_pct")
        if action == 'BUY':
            entry = bar.close
            r = abs(entry - extrema)

            sl = extrema - (_n*r)
            tp = entry + _m*r
            
            lot_size = self.budget.lots_from_diff(self.symbol, entry - sl)
            slp = self.budget.pips_from_diff(entry - sl)
            tpp = self.budget.pips_from_diff(entry - tp)

            signal = Signal(
                action=SignalAction.BUY,
                signal_type=SignalType.MAIN,
                stop_loss=sl,
                take_profit=tp,
                entry_price=entry,
                symbol=self.symbol,
                stop_loss_pips=slp,
                take_profit_pips=tpp,
                timestamp=bar.timestamp,
                entry_lot=lot_size
            )

        if action == 'SELL':
            entry = bar.close
            r = abs(entry - extrema)

            sl = extrema + (_n*r)
            tp = entry - _m*r
            
            lot_size = self.budget.lots_from_diff(self.symbol, entry - sl)
            slp = self.budget.pips_from_diff(entry - sl)
            tpp = self.budget.pips_from_diff(entry - tp)

            signal = Signal(
                action=SignalAction.SELL,
                signal_type=SignalType.MAIN,
                stop_loss=sl,
                take_profit=tp,
                entry_price=entry,
                symbol=self.symbol,
                stop_loss_pips=slp,
                take_profit_pips=tpp,
                timestamp=bar.timestamp,
                entry_lot=lot_size
            )
        
        return signal

    def echo(self, signal: Signal, commission: int):
        click.echo(f"Date: {signal.timestamp.date()} --> Running Balance: {round(self.budget.current_balance)}$ ~+ {round(commission)}$ <--")

    def _pre_process_fvgs(self):
        fvgs = self.detected_fvgs
        _pips_to_widen = self.config.get("pips_to_widen_fgvs")

        # Widen fvgs
        for fvg in fvgs:
            fvg["high"] += self.budget.diff_from_pips(_pips_to_widen)
            fvg["low"]  -= self.budget.diff_from_pips(_pips_to_widen)
            fvg["size_pips"] += 2*_pips_to_widen

        # merge same-type FVGs closer than 1.6 pips
        merged_fvgs = []
        used = set()

        # Helper function
        def fvg_distance_pips(a, b) -> float:
            # distance between closest vertical edges
            if a["high"] < b["low"]:
                diff = b["low"] - a["high"]
            elif b["high"] < a["low"]:
                diff = a["low"] - b["high"]
            else:
                # overlapping (or touching): treat as zero distance
                diff = 0.0
            return self.budget.pips_from_diff(diff)
        
        n = len(fvgs)
        for i in range(n):
            if i in used:
                continue

            base = fvgs[i]
            same_cluster = [base]
            used.add(i)

            for j in range(i + 1, n):
                if j in used:
                    continue
                other = fvgs[j]
                # only merge same type
                if other.get("type") != base.get("type"):
                    continue

                if base.get("filled_timestamp") is not None:
                    if datetime.fromisoformat(other.get("detection_time")) > datetime.fromisoformat(base.get("filled_timestamp")):
                        continue

                if fvg_distance_pips(base, other) <= self.config.get("pips_to_merge_fgvs"):
                    same_cluster.append(other)
                    used.add(j)

            if len(same_cluster) == 1:
                merged_fvgs.append(base)
            else:
                # combine into one FVG covering full range
                high = max(f["high"] for f in same_cluster)
                low = min(f["low"] for f in same_cluster)
                size_pips = self.budget.pips_from_diff(high - low)

                # base FVG for metadata
                combined = dict(base)
                combined["high"] = high
                combined["low"] = low
                combined["size_pips"] = size_pips

                # timestamps as minimums in cluster
                combined["bar_open_time"] = min(
                    f.get("bar_open_time") for f in same_cluster if f.get("bar_open_time") is not None
                )
                combined["detection_time"] = min(
                    f.get("detection_time") for f in same_cluster if f.get("detection_time") is not None
                )
                # filled_timestamp: minimum non-None, or None if all None
                filled_candidates = [f.get("filled_timestamp") for f in same_cluster if f.get("filled_timestamp") is not None]
                combined["filled_timestamp"] = min(filled_candidates) if filled_candidates else None

                merged_fvgs.append(combined)

        self.detected_fvgs = merged_fvgs
        self.logger.info(f"Merged FVGs to {len(self.detected_fvgs)}.")


    def generate_signals(self, start_date: datetime, end_date: datetime):
        bars = self.fetcher.fetch_bars_from_mt5(start_date, end_date, self.symbol, "M5")
        fvgs = self.detected_fvgs
        results = {}
        results[self.symbol] = []
        commission: int = 0

        _force_stop_time = datetime.strptime(self.config.get("force_stop_time"), "%H:%M").time()
        _allowed_trading_hour = self.config.get("allowed_trading_hour")
        _vaild_signal_generation_time = (datetime.strptime(_allowed_trading_hour["start"], "%H:%M").time(),
                                          datetime.strptime(_allowed_trading_hour["end"], "%H:%M").time())

        for fvg in fvgs:
            if fvg["size_pips"] < self.config.get("minimum_pips_for_fgvs"):
                continue

            if not fvg["filled_timestamp"]:
                continue

            # valid_fvg_
            if datetime.fromisoformat(fvg["filled_timestamp"]) > datetime.fromisoformat(fvg["detection_time"]) + timedelta(days=3):
                continue

            _bars = [bar for bar in bars if bar.timestamp >= datetime.fromisoformat(fvg["filled_timestamp"]) - timedelta(minutes=10)]

            if not _bars:
                continue

            if fvg["type"] == "bearish":
                if _bars[0].high > fvg["high"]:
                    continue

            if fvg["type"] == "bullish":
                if _bars[0].low < fvg["low"]:
                    continue

            # bar1, bar2, bar3 = _bars[0], _bars[1], _bars[2]
            hunter = [bar for bar in _bars if bar.timestamp == datetime.fromisoformat(fvg["filled_timestamp"])][0]
            hunter_index = _bars.index(hunter)

            _fvg_mid = (fvg["high"] + fvg["low"]) / 2

            _current_high = -float("inf")
            _current_low = float("inf")
            signal = None
            for i in range(hunter_index, len(_bars)):
                bar = _bars[i]
                prev_bar = _bars[i-1]

                if bar.range == 0: continue

                if _current_high < bar.high: _current_high = bar.high
                if _current_low > bar.low: _current_low = bar.low 

                if fvg["type"] == "bullish": # We are buying here
                    if bar.low < fvg['low']:
                        break

                    if bar.lower_wick / bar.range >= 0.7:
                        signal = self.calculate_entry_details(bar, "BUY", _current_low)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bullish and bar.lower_wick / bar.range >= 0.5 and bar.body / bar.range >= 0.26:
                        signal = self.calculate_entry_details(bar, "BUY", _current_low)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bearish and bar.lower_wick / bar.range >= 0.6 and bar.body / bar.range >= 0.20:
                        signal = self.calculate_entry_details(bar, "BUY", _current_low)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bullish:
                        if bar.close >= max(prev_bar.open, prev_bar.close) + (prev_bar.upper_wick / 2):
                            signal = self.calculate_entry_details(bar, "BUY", _current_low)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break


                if fvg["type"] == "bearish": # we are selling here
                    if bar.high > fvg['high']:
                        break

                    if bar.upper_wick / bar.range >= 0.7:
                        signal = self.calculate_entry_details(bar, "SELL", _current_high)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bearish and bar.upper_wick / bar.range >= 0.5 and bar.body / bar.range >= 0.26:
                        signal = self.calculate_entry_details(bar, "SELL", _current_high)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bullish and bar.upper_wick / bar.range >= 0.6 and bar.body / bar.range >= 0.20:
                        signal = self.calculate_entry_details(bar, "SELL", _current_high)
                        if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                            _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                            signal.evaluate_signal(self.budget, _force_stop_dt)
                            self.budget.apply_signal_gain(signal)
                            commission += signal.commission
                            self.echo(signal, commission)
                            results[self.symbol].append(signal)
                        break

                    elif bar.is_bearish:
                        if bar.close <= min(prev_bar.open, prev_bar.close) - (prev_bar.lower_wick / 2):
                            signal = self.calculate_entry_details(bar, "SELL", _current_high)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break


            # RECOVERY signal generation
            _should_recover = self.config.get("should_recover")
            if _should_recover and signal and (signal.is_completed and signal.gain <= 0):
                _recovery_bars = [bar for bar in _bars if bar.timestamp >= signal.outcome_timestamp - timedelta(minutes=5)]
                
                _current_high = -float("inf")
                _current_low = float("inf")
                for i in range(1, len(_recovery_bars)):
                    bar = _recovery_bars[i]
                    prev_bar = _recovery_bars[i-1]

                    if bar.range == 0: continue

                    if _current_high < bar.high: _current_high = bar.high
                    if _current_low > bar.low: _current_low = bar.low 

                    if fvg["type"] == "bullish": # We are buying here
                        if bar.low < fvg['low']:
                            break

                        if bar.lower_wick / bar.range >= 0.7:
                            signal = self.calculate_entry_details(bar, "BUY", _current_low)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break

                        elif bar.is_bullish and bar.lower_wick / bar.range >= 0.5 and bar.body / bar.range >= 0.26:
                            signal = self.calculate_entry_details(bar, "BUY", _current_low)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break

                        elif bar.is_bearish and bar.lower_wick / bar.range >= 0.6 and bar.body / bar.range >= 0.20:
                            signal = self.calculate_entry_details(bar, "BUY", _current_low)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break
                        
                        elif bar.is_bullish:
                            if bar.close >= max(prev_bar.open, prev_bar.close) + (prev_bar.upper_wick / 2):
                                signal = self.calculate_entry_details(bar, "BUY", _current_low)
                                if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                    _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                    signal.evaluate_signal(self.budget, _force_stop_dt)
                                    signal.signal_type = SignalType.RECOVERY
                                    self.budget.apply_signal_gain(signal)
                                    commission += signal.commission
                                    self.echo(signal, commission)
                                    results[self.symbol].append(signal)
                                break


                    if fvg["type"] == "bearish": # we are selling here
                        if bar.high > fvg['high']:
                            break

                        if bar.upper_wick / bar.range >= 0.7:
                            signal = self.calculate_entry_details(bar, "SELL", _current_high)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break

                        elif bar.is_bearish and bar.upper_wick / bar.range >= 0.5 and bar.body / bar.range >= 0.26:
                            signal = self.calculate_entry_details(bar, "SELL", _current_high)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break

                        elif bar.is_bullish and bar.upper_wick / bar.range >= 0.6 and bar.body / bar.range >= 0.20:
                            signal = self.calculate_entry_details(bar, "SELL", _current_high)
                            if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                signal.evaluate_signal(self.budget, _force_stop_dt)
                                signal.signal_type = SignalType.RECOVERY
                                self.budget.apply_signal_gain(signal)
                                commission += signal.commission
                                self.echo(signal, commission)
                                results[self.symbol].append(signal)
                            break
                        
                        elif bar.is_bearish:
                            if bar.close <= min(prev_bar.open, prev_bar.close) - (prev_bar.lower_wick / 2):
                                signal = self.calculate_entry_details(bar, "SELL", _current_high)
                                if _vaild_signal_generation_time[0] <= signal.timestamp.time() <= _vaild_signal_generation_time[1]:
                                    _force_stop_dt = datetime.combine(signal.timestamp.date(), _force_stop_time)
                                    signal.evaluate_signal(self.budget, _force_stop_dt)
                                    signal.signal_type = SignalType.RECOVERY
                                    self.budget.apply_signal_gain(signal)
                                    commission += signal.commission
                                    self.echo(signal, commission)
                                    results[self.symbol].append(signal)
                                break

        return results

    def run(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Execute Tweny strategy workflow.
        
        Args:
            start_date: Start datetime for analysis
            end_date: End datetime for analysis
        
        Returns:
            Dictionary with strategy results
        """
        self.logger.info(
            f"Starting Tweny run for {self.symbol} {self.timeframe} "
            f"from {start_date} to {end_date}"
        )
        
        self.fvg_detector.clear_cache()

        try:
            self.logger.info("Detecting FVGs...")
            self.detect_fvgs_in_bars(start_date, end_date)
            self._pre_process_fvgs()

            self.logger.info(f"Generating signals...")
            results = self.generate_signals(start_date, end_date)
            self.logger.info(f"Signals generated: {len(results[self.symbol])}")
            
            flags = {
                "no_plots": False,
                "no_reports": False,
                "no_mbox": False,
                "show_15m_bars": False,
                "dispaly_timeframe": "M5",
                "display_range": "monthly"
            }

            from src.core.reporting.report_generator import ReportGenerator
            report_gen = ReportGenerator("reports")
            report_gen.generate_reports(
                symbols=[self.symbol],
                date_range=(start_date, end_date),
                results=results,
                flags=flags
            )
        
            self.logger.info(f"Tweny backtest complete. Final budget: {self.budget.current_balance:.0f}")
            
            return results
        
        except Exception as e:
            import sys, traceback
            tb = traceback.extract_tb(sys.exc_info()[2])[-1]
            filename = tb.filename
            lineno = tb.lineno

            self.logger.error(f"Error generating reports: {e} (File: {filename}, line {lineno})")
