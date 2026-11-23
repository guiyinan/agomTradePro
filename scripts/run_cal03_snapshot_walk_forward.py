"""Replay the pinned CAL-03 third-party index snapshots without a provider connection."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import TypedDict
from zoneinfo import ZoneInfo

from apps.data_center.domain.institutional_calendar import six_period_for
from apps.research.application.calendar_validation import ValidationDesign
from apps.research.domain.calendar_validation_statistics import LossInference, paired_loss_inference
from apps.research.domain.institutional_event_study import (
    Session,
    WalkForwardFold,
    plan_walk_forward,
    six_category_contrast,
)
from apps.research.infrastructure.calendar_validation_design import (
    SPEC_SHA256,
    load_validation_design,
)
from apps.research.infrastructure.validation_ridge import ridge_predict
from shared.numeric import safe_float

# The identity binds field sets, date ranges and each response's byte digest.
ARCHIVE_SHA256 = "4fe7ba52497571c04cfa82a73bbc926f3a872fc5cb1346259a4f9882c187f279"
_START = date(2010, 1, 4)
_PRICE_END = date(2018, 12, 31)
_PLANNING_END = date(2026, 11, 18)
_WARMUP = 20
_STATE_THRESHOLD = 0.012


class _Query(TypedDict):
    kind: str
    params: dict[str, str]
    fields: str
    raw_path: str
    body_sha256: str


def _verified(path: Path, digest: str) -> bytes:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    return raw


def _day(value: object) -> date:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("Invalid archive date")
    return date.fromisoformat(value)


def _rows(
    archive: Path, q: _Query, fields: tuple[str, ...], used: dict[str, str]
) -> Iterator[list[object]]:
    name = Path(q["raw_path"]).name
    if q["fields"].split(",") != list(fields) or name in used:
        raise ValueError(f"Unexpected query fields or repeated input for {name}")
    raw = _verified(archive / name, q["body_sha256"])
    obj = json.loads(raw)
    if obj["code"] != 0 or obj["data"]["fields"] != list(fields):
        raise ValueError(f"Unexpected table in {name}")
    used[name] = q["body_sha256"]
    for row in obj["data"]["items"]:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError(f"Invalid table row in {name}")
        yield row


def _sessions(
    archive: Path, queries: list[_Query], used: dict[str, str], zone: ZoneInfo
) -> tuple[Session, ...]:
    days = []
    for q in queries:
        if q["kind"] == "calendar" and q["params"]["exchange"] == "SSE":
            for exchange, stamp, is_open, _ in _rows(
                archive, q, ("exchange", "cal_date", "is_open", "pretrade_date"), used
            ):
                d = _day(stamp)
                if exchange != "SSE" or str(is_open) not in ("0", "1"):
                    raise ValueError("Unexpected calendar row")
                if str(is_open) == "1" and d >= _START:
                    days.append(d)
    if not days or len(set(days)) != len(days) or min(days) != _START or max(days) != _PLANNING_END:
        raise ValueError("Incomplete or ambiguous planning calendar")
    return tuple(Session(d, datetime.combine(d, time(15), zone)) for d in sorted(days))


def _target_query(queries: list[_Query], kind: str, target: str) -> _Query:
    matches = [q for q in queries if q["kind"] == kind and q["params"].get("ts_code") == target]
    if len(matches) != 1:
        raise ValueError(f"Expected one {kind} for {target}")
    return matches[0]


def _closes(
    archive: Path, q: _Query, target: str, days: tuple[date, ...], used: dict[str, str]
) -> tuple[float, ...]:
    if _day(q["params"]["start_date"]) != _START or _day(q["params"]["end_date"]) != _PRICE_END:
        raise ValueError("Unexpected price range; only the early snapshot is permitted")
    prices = {}
    for code, stamp, value in _rows(archive, q, ("ts_code", "trade_date", "close"), used):
        d = _day(stamp)
        price = safe_float(value)
        if (
            code != target
            or d in prices
            or price is None
            or price <= 0
            or not _START <= d <= _PRICE_END
        ):
            raise ValueError(f"Invalid or duplicate price for {target} on {d}")
        prices[d] = price
    if set(prices) != set(days):
        raise ValueError(f"Early price calendar mismatch for {target}")
    return tuple(prices[d] for d in days)


@dataclass(frozen=True)
class _Fold:
    start: str
    end: str
    last_label: str
    train: int
    validation: int
    mse: tuple[float, ...]


@dataclass(frozen=True)
class _Result:
    target: str
    horizon: int
    folds: tuple[_Fold, ...]
    mse: tuple[float, ...]
    reduction_percent: float | None
    paired_loss: LossInference


def _features(
    days: tuple[date, ...], squares: tuple[float, ...], design: ValidationDesign
) -> list[tuple[tuple[float, ...], ...]]:
    features: list[tuple[tuple[float, ...], ...]] = []
    month_count: Counter[tuple[int, int]] = Counter()
    for j, d in enumerate(days):
        month_count[d.year, d.month] += 1
        if j < _WARMUP:
            continue
        vol = math.sqrt(math.fsum(squares[j - _WARMUP + 1 : j + 1]) / _WARMUP)
        base = (vol, float(vol > _STATE_THRESHOLD))
        adjusted = (
            *base,
            *(float(d.weekday() == i) for i in range(1, 7)),
            *(float(d.month == i) for i in range(2, 13)),
            float(month_count[d.year, d.month]),
        )
        cat = six_period_for(d, rule_version="snapshot-development").category.value
        contrasts = six_category_contrast(
            cat, categories=design.categories, reference=design.reference
        )
        features.append((base, adjusted, (*adjusted, *contrasts)))
    return features


def _score(
    target: str,
    h: int,
    days: tuple[date, ...],
    squares: tuple[float, ...],
    features: list[tuple[tuple[float, ...], ...]],
    folds: Sequence[WalkForwardFold],
    design: ValidationDesign,
) -> _Result:
    labels = [math.fsum(squares[j + 1 : j + h + 1]) for j in range(_WARMUP, len(days) - h)]
    diagnostics = []
    deltas: list[tuple[int, float]] = []
    for fold in folds:
        train = fold.training_origins
        val = range(fold.validation_origins.start, fold.validation_origins.stop)
        if max(train) + h + design.policy.minimum_separation_sessions > val.start or val[-1] >= len(
            labels
        ):
            raise ValueError("Label crosses the planned fold boundary")
        y = tuple(labels[i] for i in train)
        losses = []
        for model in range(3):
            pred = ridge_predict(
                tuple(features[i][model] for i in train),
                y,
                tuple(features[i][model] for i in val),
                penalty=design.ridge_penalty,
            )
            losses.append([(labels[i] - p) ** 2 for i, p in zip(val, pred, strict=True)])
        deltas.extend((i, a - b) for i, a, b in zip(val, losses[1], losses[2], strict=True))
        diagnostics.append(
            _Fold(
                days[_WARMUP + val.start].strftime("%Y%m%d"),
                days[_WARMUP + val[-1]].strftime("%Y%m%d"),
                days[_WARMUP + val[-1] + h].strftime("%Y%m%d"),
                len(train),
                len(val),
                tuple(mean(loss) for loss in losses),
            )
        )
    mse = tuple(mean(f.mse[i] for f in diagnostics) for i in range(3))
    return _Result(
        target,
        h,
        tuple(diagnostics),
        mse,
        (1 - mse[2] / mse[1]) * 100 if mse[1] else None,
        paired_loss_inference(
            tuple(deltas), bandwidth=design.hac_lags, confidence=design.confidence
        ),
    )


def _markdown(results: list[_Result], last: date, design: ValidationDesign) -> str:
    first = results[0].folds[0].start
    end = results[0].folds[-1].end
    lines = [
        "# CAL-03 历史日线走步验证",
        "",
        f"数据来自第三方通道留存快照，收盘截至 {last}。逐日历史可得版本尚待核验。最终 OOS 保持锁定。",
        "",
        f"验证预测日从 {date.fromisoformat(first)} 到 {date.fromisoformat(end)}。"
        f"每折仅用此前的训练集拟合岭回归，再预测随后 {design.policy.validation_sessions} 个交易日。"
        "依次比较历史波动与状态基准、加入星期和月份及月内交易日数的模型、再加入六候的模型。",
        "降幅为加入六候后的验证均方误差相对降幅。区间衡量两个模型逐日配对的误差差值，正数表示加入六候后误差降低。"
        f"区间采用交易日距离的 Bartlett HAC，带宽 {design.hac_lags}，置信水平 {design.confidence:.0%}。仅作全部预测日的探索性描述，未检验重叠事件子样本。",
        "",
        "| 指数 | 期限（日） | 折数 | 验证预测日 | 误差降幅 | 配对误差差值区间 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        inf = r.paired_loss
        interval = (
            f"{inf.lower:.5g} ～ {inf.upper:.5g}"
            if inf.lower is not None and inf.upper is not None
            else "无法估计"
        )
        change = "无法估计" if r.reduction_percent is None else f"{r.reduction_percent:+.3f}%"
        lines.append(
            f"| {r.target} | {r.horizon} | {len(r.folds)} | {inf.count} | {change} | {interval} |"
        )
    lines.extend(
        [
            "",
            "各区间按单项估计，未做多重校正。逐折训练与验证样本数、标签结束日期和三种模型的均方误差见同目录 results.json。",
        ]
    )
    return "\n".join(lines) + "\n"


def _publish(output: Path, files: dict[str, bytes]) -> None:
    # Publish a completed directory in one rename. Concurrent identical replays can share it.
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        ready = Path(tmp) / "report"
        ready.mkdir()
        for name, body in files.items():
            (ready / name).write_bytes(body)
        if not output.exists():
            try:
                ready.rename(output)
                return
            except OSError:
                if not output.is_dir():
                    raise
        if not output.is_dir() or any(
            not (output / k).is_file() or (output / k).read_bytes() != v for k, v in files.items()
        ):
            raise ValueError("Output already exists; choose a new report directory")


def write_snapshot(archive: Path, output: Path) -> None:
    """Verify the retained input bundle and publish an offline development report."""
    spec_path = (
        Path(__file__).resolve().parents[1] / "tests/fixtures/research/cal_event_study_v1.json"
    )
    design = load_validation_design(spec_path)
    queries: list[_Query] = json.loads(_verified(archive / "report.json", ARCHIVE_SHA256))[
        "queries"
    ]
    used: dict[str, str] = {}
    zone = ZoneInfo(design.clock.timezone_name)
    sessions = _sessions(archive, queries, used, zone)
    dates = tuple(s.session_on for s in sessions)
    reserve = design.policy.final_oos_sessions + max(design.clock.horizons)
    if len(dates) <= reserve or _PRICE_END >= dates[-reserve]:
        raise ValueError("Early price range intersects the reserved period")
    early = dates[: bisect_right(dates, _PRICE_END)]
    results: list[_Result] = []
    for code in design.targets:
        target = f"{code}.SH"
        metadata = _target_query(queries, "full_date_coverage", target)
        covered = set()
        for symbol, stamp in _rows(archive, metadata, ("ts_code", "trade_date"), used):
            d = _day(stamp)
            if symbol != target or d in covered:
                raise ValueError(f"Unexpected coverage row for {target}")
            covered.add(d)
        plan = plan_walk_forward(
            sessions=sessions[_WARMUP:],
            calendar_version="retained-date-axis",
            complete_price_dates=frozenset(covered),
            known_at=datetime.combine(dates[-1], design.clock.local_cutoff, zone),
            clock=design.clock,
            policy=design.policy,
            prior_final_oos_uses=0,
        )
        if dates[_WARMUP + plan.final_oos_origins.start] != dates[-reserve]:
            raise ValueError("Inconsistent reserved window")
        folds = [
            f
            for f in plan.folds
            if _WARMUP + f.validation_origins.stop + max(design.clock.horizons) <= len(early)
        ]
        if len(folds) < design.policy.minimum_folds:
            raise ValueError("Too few complete early validation folds")
        prices = _closes(
            archive, _target_query(queries, "early_price_quality", target), target, early, used
        )
        log_prices = tuple(map(math.log, prices))
        squares = (0.0, *((b - a) ** 2 for a, b in pairwise(log_prices)))
        features = _features(early, squares, design)
        results.extend(
            _score(target, h, early, squares, features, folds, design)
            for h in design.clock.horizons
        )
    report = {
        "scope": "current-vintage pre-2019 descriptive development only",
        "spec_sha256": SPEC_SHA256,
        "archive_manifest_sha256": ARCHIVE_SHA256,
        "source_sha256": used,
        "date_axis_final_reserved_start": dates[-reserve].strftime("%Y%m%d"),
        "reserved_origins": design.policy.final_oos_sessions,
        "last_available_price": early[-1].strftime("%Y%m%d"),
        "oos_evaluated": False,
        "pit_qualified": False,
        "mse_order": [
            "historical volatility/state",
            "adjusted calendar controls",
            "adjusted controls plus six periods",
        ],
        "parameters": {
            "warmup_sessions": _WARMUP,
            "state_threshold": _STATE_THRESHOLD,
            "ridge_penalty": design.ridge_penalty,
            "hac_lags": design.hac_lags,
            "confidence": design.confidence,
        },
        "overlap_sensitivities": "unavailable; no qualified historical event panel",
        "inference": "Exploratory all-date paired MSE differences; raw p values are unadjusted and do not establish formal study significance.",
        "runtime": {"python": platform.python_version(), "numpy": version("numpy")},
        "results": [asdict(r) for r in results],
    }
    _publish(
        output,
        {
            "results.json": (
                json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
            ).encode(),
            "report.md": _markdown(results, early[-1], design).encode(),
        },
    )


def main() -> None:
    """Run the snapshot report with an archived input directory and a report destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", required=True, type=Path, help="Retained coverage-audit-v1 directory"
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New report directory or an identical previous result",
    )
    args = parser.parse_args()
    try:
        write_snapshot(args.archive, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"CAL-03 replay failed: {exc}\n")
    print(args.output / "report.md")


if __name__ == "__main__":
    main()
