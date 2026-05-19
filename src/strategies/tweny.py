from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from config.settings import settings

from src.core.data.fetcher import DataFetcher
from src.core.models.bar import Bar
from src.core.models.signal import Signal, SignalAction
from src.core.models.budget import Budget

from src.core.utils.logger import TradingLogger

@dataclass
class TwenyFVG:
    direction: str

    top: float
    bottom: float

    start_index: int
    end_index: int

    created_at: datetime

    filled: bool = False
    filled_at: Optional[datetime] = None

    entry_price: Optional[float] = None


class Tweny:

    def __init__(self, budget: Optional[Budget] = None):

        self.logger = TradingLogger.get_main_logger()

        self.fetcher = DataFetcher()

        self.budget = budget or Budget()

        self.config = settings.get_strategy_config("Tweny")

        self.sl_ratio = self.config.get("ratio", {}).get("sl", 1)
        self.tp_ratio = self.config.get("ratio", {}).get("tp", 4)

        self.minimum_fvg_pips = 3

        self.fvgs: List[TwenyFVG] = []
        self.signals: List[Signal] = []

    # =====================================================
    # HELPERS
    # =====================================================

    def pip_size(self, symbol: str) -> float:

        symbol = symbol.rstrip(".").upper()

        if "JPY" in symbol:
            return 0.01

        return 0.0001

    def price_to_pips(self, symbol: str, price_diff: float) -> float:

        return abs(price_diff) / self.pip_size(symbol)

    # =====================================================
    # DETECT FVGS
    # =====================================================

    def detect_fvgs(
        self,
        bars: List[Bar],
        symbol: str
    ) -> List[TwenyFVG]:

        fvgs: List[TwenyFVG] = []

        for i in range(2, len(bars)):

            _good_to_go = False

            bar1 = bars[i - 2]
            bar2 = bars[i - 1]
            bar3 = bars[i]


            # =================================================
            # Trendy candle conditions
            # =================================================

            if bar2.body / bar2.range >= 0.65 and bar3.body / bar3.range >= 0.65: 
                _good_to_go = True
            
            if ((bar2.upper_wick / bar2.range <= 0.2 and bar2.body / bar2.range >= 0.2) and
                (bar3.upper_wick / bar3.range <= 0.2 and bar3.body / bar3.range >= 0.2)): 
                
                _good_to_go = True


            if not _good_to_go:
                continue

            # =================================================
            # BULLISH FVG
            # =================================================

            bullish_condition = (
                bar2.close > bar1.high and
                bar3.close > bar2.high
            )

            if bullish_condition:

                top = bar1.high

                bottom = min(
                    bar1.low,
                    bar2.low,
                    bar3.low
                )

                fvg_size_pips = self.price_to_pips(
                    symbol,
                    top - bottom
                )

                if fvg_size_pips >= self.minimum_fvg_pips:

                    fvgs.append(
                        TwenyFVG(
                            direction="buy",
                            top=top,
                            bottom=bottom,
                            start_index=bar1.timestamp.isoformat(),
                            end_index=i,
                            created_at=bar3.timestamp.isoformat()
                        )
                    )

            # =================================================
            # BEARISH FVG
            # =================================================

            bearish_condition = (
                bar2.close < bar1.low and
                bar3.close < bar2.low
            )

            if bearish_condition:

                top = max(
                    bar1.high,
                    bar2.high,
                    bar3.high
                )

                bottom = bar1.low

                fvg_size_pips = self.price_to_pips(
                    symbol,
                    top - bottom
                )

                if fvg_size_pips >= self.minimum_fvg_pips:

                    fvgs.append(
                        TwenyFVG(
                            direction="sell",
                            top=top,
                            bottom=bottom,
                            start_index=bar1.timestamp.isoformat(),
                            end_index=i,
                            created_at=bar3.timestamp.isoformat()
                        )
                    )

        self.logger.info(f"Detected {len(fvgs)} FVGs")

        return fvgs

    # =====================================================
    # GENERATE SIGNALS
    # =====================================================

    def generate_signals(
        self,
        bars: List[Bar],
        symbol: str,
        fvgs: List[TwenyFVG]
    ) -> List[Signal]:

        signals: List[Signal] = []

        for fvg in fvgs:

            if fvg.filled:
                continue

            start_scan_index = fvg.end_index + 1

            for i in range(start_scan_index, len(bars)):

                current_bar = bars[i]

                # =============================================
                # BUY FVG FILL
                # =============================================

                if fvg.direction == "buy":

                    touched = (
                        current_bar.low <= fvg.top and
                        current_bar.high >= fvg.bottom
                    )

                    if touched:

                        # entry = current_bar.close
                        entry = fvg.top

                        sl = fvg.bottom

                        risk = entry - sl

                        if risk <= 0:
                            break

                        tp = entry + (risk * self.tp_ratio)

                        lot_size = self.budget.lots_from_diff(
                            symbol=symbol,
                            sl_distance=entry-sl
                        )

                        signal = Signal(
                            action=SignalAction.BUY,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            symbol=symbol,
                            timestamp=current_bar.timestamp,
                            entry_lot=lot_size
                        )

                        signal.take_profit_pips = self.budget.pips_from_diff(tp - entry)
                        signal.stop_loss_pips   = self.budget.pips_from_diff(sl - entry)

                        signals.append(signal)

                        fvg.filled = True
                        fvg.filled_at = current_bar.timestamp
                        fvg.entry_price = entry

                        break

                # =============================================
                # SELL FVG FILL
                # =============================================

                if fvg.direction == "sell":

                    touched = (
                        current_bar.high >= fvg.bottom and
                        current_bar.low <= fvg.top
                    )

                    if touched:

                        # entry = current_bar.close
                        entry = fvg.bottom

                        sl = fvg.top

                        risk = sl - entry

                        if risk <= 0:
                            break

                        tp = entry - (risk * self.tp_ratio)

                        lot_size = self.budget.lots_from_diff(
                            symbol=symbol,
                            sl_distance=entry-sl
                        )

                        signal = Signal(
                            action=SignalAction.SELL,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            symbol=symbol,
                            timestamp=current_bar.timestamp,
                            entry_lot=lot_size
                        )

                        signal.take_profit_pips = self.budget.pips_from_diff(tp - entry)
                        signal.stop_loss_pips   = self.budget.pips_from_diff(sl - entry)

                        signals.append(signal)

                        fvg.filled = True
                        fvg.filled_at = current_bar.timestamp
                        fvg.entry_price = entry

                        break

        self.logger.info(f"Generated {len(signals)} signals")

        return signals

    # =====================================================
    # SAVE FVGS USING DIO CACHE SYSTEM
    # =====================================================

    def save_fvgs(
        self,
        fvgs: List[TwenyFVG],
        symbol: str,
        timeframe: str
    ):

        try:

            from src.indicators.fvg_detector import FVGDetector

            detector = FVGDetector()
            detector.clear_cache()
            detector.ensure_symbol_storage(symbol)

            for fvg in fvgs:

                detector.fvgs[symbol][timeframe].append({
                    'type': "bullish" if fvg.direction == "buy" else "bearish",
                    'high': fvg.top,
                    'low': fvg.bottom,
                    'size_pips': abs(fvg.top - fvg.bottom) / 0.0001, # Standard pip size
                    'bar_open_time': fvg.start_index,
                    'detection_time': fvg.created_at,
                    'filled_timestamp': None,
                })

            detector.clean_filled_fvgs()
            detector.save_fvgs_to_cache()

        except Exception as e:

            import sys
            import traceback

            tb = traceback.extract_tb(sys.exc_info()[2])[-1]

            self.logger.warning(
                f"FVG cache save failed: {e} "
                f"| file: {tb.filename} "
                f"| line: {tb.lineno}"
            )

    # =====================================================
    # MAIN BACKTEST
    # =====================================================

    def backtest(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "M15"
    ):

        all_results = {}

        for symbol in symbols:

            self.logger.info(f"Running Tweny on {symbol}")

            bars = self.fetcher.fetch_bars_from_mt5(
                start_dt=start_date,
                end_dt=end_date,
                symbol=symbol,
                timeframe=timeframe
            )

            if not bars:

                self.logger.warning(f"No bars for {symbol}")

                continue

            fvgs = self.detect_fvgs(
                bars=bars,
                symbol=symbol
            )

            self.save_fvgs(
                fvgs=fvgs,
                symbol=symbol,
                timeframe=timeframe
            )

            signals = self.generate_signals(
                bars=bars,
                symbol=symbol,
                fvgs=fvgs
            )

            for signal in signals:
                signal.evaluate_signal(self.budget)

            all_results[symbol] = signals

            # =============================================
            # OPTIONAL PLOTTER INTEGRATION
            # =============================================

            try:

                from src.core.utils.plotter import TradingPlotter

                plotter = TradingPlotter()

                if hasattr(plotter, "plot_backtest"):

                    plotter.plot_backtest(
                        bars=bars,
                        signals=signals,
                        symbol=symbol
                    )

            except Exception as e:

                self.logger.warning(f"Plotter skipped: {e}")

            # =============================================
            # OPTIONAL REPORT GENERATOR
            # =============================================

            try:

                from src.core.reporting.report_generator import ReportGenerator

                report_generator = ReportGenerator()


                args = {}
                if hasattr(report_generator, "generate_reports"):
                    args["no_reports"] = False
                    args["no_plots"] = False
                    args["no_signal"] = False
                    args["no_mbox"] = False
                    args["show_15m_bars"] = False
                    args['dispaly_timeframe'] = timeframe
                    args['display_range'] = 'monthly'
                    
                    report_generator.generate_reports(
                    symbols=symbols,
                    date_range=(start_date, end_date),
                    results=all_results,
                    flags=args
                )

            except Exception as e:

                import sys
                import traceback

                tb = traceback.extract_tb(sys.exc_info()[2])[-1]

                filename = tb.filename
                lineno = tb.lineno

                self.logger.warning(
                    f"Report generation skipped: {e} | file: {filename} | line: {lineno}"
                )

        return all_results

