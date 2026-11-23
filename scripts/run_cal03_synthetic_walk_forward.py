"""Run the CAL-03 synthetic validation demonstration, without a provider or database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from apps.data_center.domain.institutional_calendar import six_period_for
from apps.research.application.calendar_validation import (
    CalendarValidationReport,
    PeriodObservation,
    ValidationCalendar,
    ValidationDesign,
    ValidationSeries,
    run_calendar_validation,
)
from apps.research.domain.institutional_event_study import (
    MatchingFeatures,
    PriceVersion,
    Session,
    plan_walk_forward,
)
from apps.research.infrastructure.calendar_validation_design import (
    SPEC_SHA256,
    load_validation_design,
)
from apps.research.infrastructure.validation_ridge import ridge_predict

_ROOT = Path(__file__).resolve().parents[1]


def _design() -> ValidationDesign:
    return load_validation_design(_ROOT / "tests/fixtures/research/cal_event_study_v1.json")


def _fixture_series(
    code: str, seed: int, calendar: ValidationCalendar, limit: int, design: ValidationDesign
) -> ValidationSeries:
    rng = random.Random(seed)
    prices: dict[date, tuple[PriceVersion, ...]] = {}
    features: dict[date, PeriodObservation] = {}
    # Pre-calendar synthetic warm-up permits a trailing-volatility feature on day one.
    returns = [rng.gauss(0, 0.012) for _ in range(19)]
    value = 100.0
    elapsed = 0
    previous_month = 0
    for session in calendar.sessions[:limit]:
        day = session.session_on
        elapsed = elapsed + 1 if previous_month == day.month else 1
        previous_month = day.month
        r = rng.gauss(0, 0.009 if day.day <= 15 else 0.014)
        value *= math.exp(r)
        returns.append(r)
        recorded = session.closes_at + timedelta(minutes=2)
        prices[day] = (
            PriceVersion(
                day,
                value,
                f"{code}-{day}-v1",
                session.closes_at,
                session.closes_at + timedelta(minutes=1),
                recorded,
            ),
        )
        vol = math.sqrt(sum(x * x for x in returns[-20:]) / 20)
        period = six_period_for(day, rule_version="synthetic-six-period-v1")
        window_id = period.start_date.isoformat()
        # A synthetic second event is scheduled on day 3 of each six-period window.
        # Only alternating months have it; the schedule is fixed before path generation.
        overlaps = (f"scheduled-{window_id}",) if day.month % 2 == 0 else ()
        today = overlaps if (day - period.start_date).days == 2 else ()
        cutoff = datetime.combine(
            day, design.clock.local_cutoff, ZoneInfo(design.clock.timezone_name)
        )
        cov = MatchingFeatures(
            f"{code}-{day}",
            cutoff,
            session.closes_at,
            recorded,
            recorded,
            recorded,
            day.weekday(),
            day.month,
            design.states[int(vol > 0.012)],
            vol,
            today,
        )
        features[day] = PeriodObservation(cov, period.category.value, window_id, elapsed, overlaps)
    return ValidationSeries(
        code, frozenset(s.session_on for s in calendar.sessions), prices, features
    )


def synthetic_case() -> tuple[ValidationDesign, ValidationCalendar, dict[str, ValidationSeries]]:
    """Create deterministic date metadata and three synthetic pre-holdout price paths."""
    design = _design()
    zone = ZoneInfo(design.clock.timezone_name)
    first = date(2010, 1, 4)
    last = date(2020, 12, 31)
    dates = (first + timedelta(days=i) for i in range((last - first).days + 1))
    sessions = tuple(
        Session(d, datetime.combine(d, time(15), zone)) for d in dates if d.weekday() < 5
    )
    calendar = ValidationCalendar(
        sessions, "synthetic-weekdays-v1", datetime.combine(last, time(18), zone)
    )
    plan = plan_walk_forward(
        sessions=sessions,
        calendar_version=calendar.version,
        complete_price_dates=frozenset(s.session_on for s in sessions),
        known_at=calendar.known_at,
        clock=design.clock,
        policy=design.policy,
        prior_final_oos_uses=0,
    )
    return (
        design,
        calendar,
        {
            code: _fixture_series(code, 1103 + i, calendar, plan.final_oos_origins.start, design)
            for i, code in enumerate(design.targets)
        },
    )


def _json_bytes(value: object) -> bytes:
    def encode(obj: object) -> str:
        if isinstance(obj, (date, time)):
            return obj.isoformat()
        raise TypeError(f"Cannot encode {type(obj).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=encode,
        allow_nan=False,
    ).encode("utf8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _markdown(reports: tuple[CalendarValidationReport, ...], design: ValidationDesign) -> str:
    lines = [
        "# CAL-03 合成走步验证报告",
        "",
        "仅使用合成价格、因果特征和工作日历。最终 OOS 在第一条价格生成之前划界，保留区间只含日历元数据。",
        "",
        "每折在扩张训练集拟合三个模型，分别使用历史波动与市场状态、再加入星期与月份及月内已过交易日数、再加入五个六候对比变量。"
        "效应量为第二个模型减第三个模型的验证均方误差，正值表示加入六候后误差较小。各期限独立报告。",
        "",
        f"合成演练采用训练集标准化岭回归，惩罚 {design.ridge_penalty:g}。区间为 {design.confidence:.0%} 双侧正态近似，"
        f"按实际交易日距离使用 Bartlett 权重，带宽 {design.hac_lags}。Holm 校正和探索性 BH 校正覆盖全部目标、期限及三个预设子样本。",
        "",
        "三个子样本分别保留所有预测日、当日仅有六候标记的预测日、整个六候窗口都无附加事件的预测日。"
        "三组共用每折训练模型。JSON 附有逐折分母、排除原因、各候样本数和标签均值。"
        "模拟器预设月内波动率差异，历史波动特征用日历开始前的 19 个合成收益预热。结果仅用于验证计算流程。",
        "",
        "| 指数 | 期限（日） | 子样本 | 验证行 | 效应量 | 区间 | 原始 p | Holm p | BH q |",
        "|---|---:|---|---:|---:|---|---:|---:|---:|",
    ]

    def fmt(value: float | None) -> str:
        return "—" if value is None else f"{value:.5g}"

    for report in reports:
        for s in report.slices:
            inf = s.inference
            lines.append(
                f"| {report.target} | {report.horizon} | {s.name} | {s.observations} | "
                f"{fmt(inf.mean if inf else None)} | {fmt(inf.lower if inf else None)} ～ {fmt(inf.upper if inf else None)} | "
                f"{fmt(inf.raw_p if inf else None)} | {fmt(s.holm_adjusted_p)} | {fmt(s.exploratory_bh_q)} |"
            )
    lines.extend(
        [
            "",
            "## 逐折验证",
            "",
            "| 指数 | 期限 | 验证期间 | 训练有效/预计 | 验证有效/预计 | 历史基准 MSE | 调整后 MSE | 加入六候 MSE |",
            "|---|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for report in reports:
        for f in report.folds:
            lines.append(
                f"| {report.target} | {report.horizon} | {f.first_validation} 至 {f.last_validation} | "
                f"{f.training_valid}/{f.training_expected} | {f.validation_valid}/{f.validation_expected} | "
                f"{fmt(f.historical_mse)} | {fmt(f.adjusted_mse)} | {fmt(f.calendar_mse)} |"
            )
        if report.reasons:
            lines.extend(
                [
                    "",
                    f"{report.target} / {report.horizon} 日未通过条件：{', '.join(report.reasons)}",
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def _write(path: Path, content: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(content)
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_demo(output: Path) -> None:
    """Write deterministic JSON and Markdown from the same validation-only evaluation."""
    design, cal, series = synthetic_case()
    reports = run_calendar_validation(design, cal, series, predict=ridge_predict)
    manifest = {}
    for code, s in series.items():
        manifest[code] = {
            "prices_sha256": _digest([asdict(p) for levels in s.prices.values() for p in levels]),
            "features_sha256": _digest([asdict(f) for f in s.features.values()]),
            "complete_date_metadata_sha256": _digest(sorted(s.complete_dates)),
            "last_generated_price": max(s.prices),
            "generated_prices": len(s.prices),
        }
    source_paths = (
        Path(__file__).resolve(),
        _ROOT / "apps/research/infrastructure/calendar_validation_design.py",
        _ROOT / "apps/research/application/calendar_validation.py",
        _ROOT / "apps/research/infrastructure/validation_ridge.py",
        _ROOT / "apps/research/domain/calendar_validation_statistics.py",
        _ROOT / "apps/research/domain/institutional_event_study.py",
        _ROOT / "apps/research/domain/statistics.py",
        _ROOT / "apps/data_center/domain/institutional_calendar.py",
    )
    report = {
        "run_kind": "synthetic_validation_only",
        "final_oos_evaluated": False,
        "final_oos_claimed": False,
        "final_oos_sessions_reserved": design.policy.final_oos_sessions,
        "spec_sha256": SPEC_SHA256,
        "design": asdict(design),
        "calendar_sha256": _digest([asdict(s) for s in cal.sessions]),
        "calendar_version": cal.version,
        "known_at": cal.known_at,
        "inputs": manifest,
        "implementation_sha256": {
            p.relative_to(_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_paths
        },
        "runtime": {"python": platform.python_version(), "numpy": version("numpy")},
        "effect": "validation MSE of adjusted covariates minus validation MSE with six-period contrasts",
        "method": "training-only standardized ridge, unpenalized intercept; Bartlett session-grid HAC, normal two-sided, no small-sample correction",
        "reports": [asdict(r) for r in reports],
    }
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "report.json", _json_bytes(report) + b"\n")
    _write(output / "report.md", _markdown(reports, design).encode("utf8"))


def main() -> None:
    """Run with python -m scripts.run_cal03_synthetic_walk_forward --output DIR."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_demo(args.output)


if __name__ == "__main__":
    main()
