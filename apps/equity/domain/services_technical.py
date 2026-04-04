"""
个股技术图表 Domain 服务。

遵循四层架构规范：
- Domain 层仅包含纯算法
- 不依赖 Django/第三方库
"""

from collections import OrderedDict
from decimal import Decimal

from .entities import TechnicalBar, TechnicalCrossoverSignal


class TechnicalChartService:
    """技术图表聚合与信号检测服务。"""

    def aggregate_bars(
        self,
        bars: list[TechnicalBar],
        timeframe: str,
    ) -> list[TechnicalBar]:
        """按日/周/月聚合K线。"""
        ordered_bars = sorted(bars, key=lambda item: item.trade_date)
        if timeframe == "day":
            return ordered_bars

        grouped: OrderedDict[tuple[int, int], list[TechnicalBar]] = OrderedDict()
        for bar in ordered_bars:
            if timeframe == "week":
                iso_year, iso_week, _ = bar.trade_date.isocalendar()
                key = (iso_year, iso_week)
            elif timeframe == "month":
                key = (bar.trade_date.year, bar.trade_date.month)
            else:
                raise ValueError(f"Unsupported timeframe: {timeframe}")
            grouped.setdefault(key, []).append(bar)

        aggregated: list[TechnicalBar] = []
        for bucket in grouped.values():
            first = bucket[0]
            last = bucket[-1]
            aggregated.append(
                TechnicalBar(
                    stock_code=last.stock_code,
                    trade_date=last.trade_date,
                    open=first.open,
                    high=max(item.high for item in bucket),
                    low=min(item.low for item in bucket),
                    close=last.close,
                    volume=sum(item.volume for item in bucket),
                    amount=sum(item.amount for item in bucket),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
            )

        return self._recalculate_indicators(aggregated)

    def detect_crossovers(
        self,
        bars: list[TechnicalBar],
    ) -> list[TechnicalCrossoverSignal]:
        """检测 MA5 与 MA20 的金叉/死叉。"""
        signals: list[TechnicalCrossoverSignal] = []
        ordered_bars = sorted(bars, key=lambda item: item.trade_date)

        for previous, current in zip(ordered_bars, ordered_bars[1:]):
            if (
                previous.ma5 is None
                or previous.ma20 is None
                or current.ma5 is None
                or current.ma20 is None
            ):
                continue

            previous_diff = previous.ma5 - previous.ma20
            current_diff = current.ma5 - current.ma20

            if previous_diff <= 0 < current_diff:
                signals.append(
                    TechnicalCrossoverSignal(
                        signal_type="golden_cross",
                        trade_date=current.trade_date,
                        price=current.close,
                        short_value=current.ma5,
                        long_value=current.ma20,
                        label="MA5 上穿 MA20",
                    )
                )
            elif previous_diff >= 0 > current_diff:
                signals.append(
                    TechnicalCrossoverSignal(
                        signal_type="death_cross",
                        trade_date=current.trade_date,
                        price=current.close,
                        short_value=current.ma5,
                        long_value=current.ma20,
                        label="MA5 下穿 MA20",
                    )
                )

        return signals

    def _recalculate_indicators(
        self,
        bars: list[TechnicalBar],
    ) -> list[TechnicalBar]:
        """基于聚合后的收盘价重算均线与 MACD。"""
        recalculated: list[TechnicalBar] = []
        closes: list[Decimal] = []
        ema12: float | None = None
        ema26: float | None = None
        signal_ema: float | None = None
        alpha12 = 2 / 13
        alpha26 = 2 / 27
        alpha9 = 2 / 10

        for bar in bars:
            closes.append(bar.close)
            close_float = float(bar.close)

            ema12 = close_float if ema12 is None else ema12 + (close_float - ema12) * alpha12
            ema26 = close_float if ema26 is None else ema26 + (close_float - ema26) * alpha26
            macd = ema12 - ema26
            signal_ema = macd if signal_ema is None else signal_ema + (macd - signal_ema) * alpha9
            macd_hist = macd - signal_ema

            recalculated.append(
                TechnicalBar(
                    stock_code=bar.stock_code,
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    amount=bar.amount,
                    ma5=self._calculate_sma(closes, 5),
                    ma20=self._calculate_sma(closes, 20),
                    ma60=self._calculate_sma(closes, 60),
                    macd=macd,
                    macd_signal=signal_ema,
                    macd_hist=macd_hist,
                    rsi=None,
                )
            )

        return recalculated

    def _calculate_sma(
        self,
        closes: list[Decimal],
        window: int,
    ) -> Decimal | None:
        """计算简单移动平均线。"""
        if len(closes) < window:
            return None
        return sum(closes[-window:]) / Decimal(window)
