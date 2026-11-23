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
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import TypedDict
from zoneinfo import ZoneInfo

from apps.data_center.domain.institutional_calendar import six_period_for
from apps.research.application.calendar_validation import ValidationDesign, ValidationSlice
from apps.research.domain.calendar_validation_statistics import LossInference, paired_loss_inference
from apps.research.domain.institutional_event_study import (
    Session,
    WalkForwardFold,
    holm_adjusted_p_values,
    plan_walk_forward,
    six_category_contrast,
)
from apps.research.domain.statistics import benjamini_hochberg_q_values
from apps.research.infrastructure.calendar_validation_design import (
    SPEC_SHA256,
    load_validation_design,
)
from apps.research.infrastructure.sse_holiday_overlap import (
    REVIEW_SHA256,
    HolidayPanel,
    load_holiday_panel,
)
from apps.research.infrastructure.validation_ridge import ridge_predict
from shared.numeric import safe_float

# The identity binds field sets, date ranges and each response's byte digest.
ARCHIVE_SHA256 = "4fe7ba52497571c04cfa82a73bbc926f3a872fc5cb1346259a4f9882c187f279"
LATER_ARCHIVE_SHA256 = "6d6d78649a1ba7fb2d7e9429e1b1b8b1b0637a14830952a5aeacb974b8ea5b3a"
LATER_DESIGN_SHA256 = "be27ca2306ed01026286baecaca605746a0faf6bd06eecb53f69ca64761a8fbe"
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
    archive: Path,
    q: _Query,
    target: str,
    days: tuple[date, ...],
    used: dict[str, str],
    *,
    later_end: date | None = None,
) -> tuple[float, ...]:
    start, end = (_START, _PRICE_END) if later_end is None else (date(2019, 1, 1), later_end)
    if _day(q["params"]["start_date"]) != start or _day(q["params"]["end_date"]) != end:
        raise ValueError("Unexpected price range for the selected snapshot")
    prices = {}
    for code, stamp, value in _rows(archive, q, ("ts_code", "trade_date", "close"), used):
        d = _day(stamp)
        price = safe_float(value)
        if code != target or d in prices or price is None or price <= 0 or not start <= d <= end:
            raise ValueError(f"Invalid or duplicate price for {target} on {d}")
        prices[d] = price
    if prices.keys() - set(days) or (later_end is None and set(prices) != set(days)):
        raise ValueError(f"Price calendar mismatch for {target}")
    # A missing close stays on its original session. The later-cohort selector
    # removes every origin whose feature or label would depend on that close.
    return tuple(prices.get(d, math.nan) for d in days)


@dataclass(frozen=True)
class _LaterFoldSupport:
    start: date
    end: date
    last_label: date
    training_expected: int
    training_valid: int
    validation_expected: int
    validation_valid: int
    reason: str


def _later_cohort(
    folds: Sequence[WalkForwardFold],
    dates: tuple[date, ...],
    reserve_start: int,
    missing: set[int],
    horizon: int,
    design: ValidationDesign,
) -> tuple[list[WalkForwardFold], list[_LaterFoldSupport]]:
    maximum = max(design.clock.horizons)

    # A feature uses the closes [origin-20, origin]; a label uses [origin, origin+h].
    def invalid(h: int) -> set[int]:
        return {i - _WARMUP for m in missing for i in range(m - h, m + _WARMUP + 1)}

    bad_train = invalid(horizon)
    bad_validation = invalid(maximum)
    selected = []
    support = []
    for f in folds:
        val = range(f.validation_origins.start, f.validation_origins.stop)
        start = _WARMUP + val.start
        stop = _WARMUP + val.stop - 1
        last = stop + maximum
        if (
            dates[start] <= _PRICE_END
            or last + design.policy.minimum_separation_sessions >= reserve_start
        ):
            continue
        train = tuple(i for i in f.training_origins if i not in bad_train)
        valid = len(val) - len(bad_validation.intersection(val))
        reason = ""
        if valid != len(val):
            reason = "VALIDATION_FOLD_INCOMPLETE"
        elif len(train) / len(f.training_origins) < design.gates.coverage_min:
            reason = "TRAINING_COVERAGE_INSUFFICIENT"
        else:
            selected.append(replace(f, training_origins=train))
        support.append(
            _LaterFoldSupport(
                dates[start],
                dates[stop],
                dates[last],
                len(f.training_origins),
                len(train),
                len(val),
                valid,
                reason,
            )
        )
    if len(selected) < design.policy.minimum_folds:
        raise ValueError("Too few complete later validation folds")
    return selected, support


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
) -> tuple[_Result, list[tuple[int, float, float]]]:
    labels = [math.fsum(squares[j + 1 : j + h + 1]) for j in range(_WARMUP, len(days) - h)]
    diagnostics = []
    scored: list[tuple[int, float, float]] = []
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
        scored.extend(zip(val, losses[1], losses[2], strict=True))
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
    return (
        _Result(
            target,
            h,
            tuple(diagnostics),
            mse,
            (1 - mse[2] / mse[1]) * 100 if mse[1] else None,
            paired_loss_inference(
                tuple((i, a - b) for i, a, b in scored),
                bandwidth=design.hac_lags,
                confidence=design.confidence,
            ),
        ),
        scored,
    )


@dataclass(frozen=True, kw_only=True)
class _Sensitivity(ValidationSlice):
    target: str
    horizon: int
    fold_counts: tuple[int, ...]
    reduction_percent: float | None


def _window_start(day: date) -> date:
    return six_period_for(day, rule_version="snapshot-development").start_date


def _selections(
    days: tuple[date, ...], panel: HolidayPanel
) -> tuple[tuple[date, ...], dict[str, set[int]]]:
    marked_days = {m.origin for m in panel.markers}
    marked_windows = {_window_start(d) for d in marked_days}
    # Retrospective exclusions never enter model inputs. If a notice arrived
    # mid-window, its earlier days also cannot certify a clean whole window.
    windows = tuple(_window_start(day) for day in days)
    if not days or days[0] < panel.start or days[-1] > panel.end:
        raise ValueError("Sensitivity outside event coverage")
    return windows, {
        "all": set(range(len(days))),
        "single_event": {i for i, d in enumerate(days) if d not in marked_days},
        "exclusive_window": {i for i, w in enumerate(windows) if w not in marked_windows},
    }


def _sensitivity(
    result: _Result,
    scored: list[tuple[int, float, float]],
    folds: Sequence[WalkForwardFold],
    windows: tuple[date, ...],
    selections: dict[str, set[int]],
    design: ValidationDesign,
) -> list[_Sensitivity]:
    estimates = []
    for name, include in selections.items():
        selected = [(i, a, b) for i, a, b in scored if i in include]
        training = [{windows[i] for i in f.training_origins if i in include} for f in folds]
        train_union = set.union(*training)
        minimum = min(map(len, training))
        val_windows = {windows[i] for i, _, _ in selected}
        distinct = len(train_union | val_windows)
        counts = tuple(
            sum(i in include for i in range(f.validation_origins.start, f.validation_origins.stop))
            for f in folds
        )
        reasons: tuple[str, ...] = ()
        inference = None
        if (
            minimum < design.gates.training_min
            or len(val_windows) < design.gates.validation_min
            or distinct < design.gates.distinct_total_min
            or not all(counts)
        ):
            reasons = ("EVENT_SUPPORT_INSUFFICIENT",)
        else:
            inference = paired_loss_inference(
                tuple((i, a - b) for i, a, b in selected),
                bandwidth=design.hac_lags,
                confidence=design.confidence,
            )
            if inference.raw_p is None:
                reasons = ("LOSS_INFERENCE_UNAVAILABLE",)
        adjusted = math.fsum(a for _, a, _ in selected)
        with_period = math.fsum(b for _, _, b in selected)
        estimates.append(
            _Sensitivity(
                name=name,
                target=result.target,
                horizon=result.horizon,
                observations=len(selected),
                training_windows=len(train_union),
                minimum_fold_training_windows=minimum,
                validation_windows=len(val_windows),
                distinct_windows=distinct,
                fold_counts=counts,
                inference=inference,
                reasons=reasons,
                reduction_percent=(1 - with_period / adjusted) * 100 if adjusted else None,
            )
        )
    return estimates


def _correct_sensitivities(rows: list[_Sensitivity]) -> list[_Sensitivity]:
    raw = tuple(
        r.inference.raw_p
        for r in rows
        if not r.reasons and r.inference is not None and r.inference.raw_p is not None
    )
    if len(raw) != len(rows):
        return rows
    return [
        replace(r, holm_adjusted_p=p, exploratory_bh_q=q)
        for r, p, q in zip(
            rows, holm_adjusted_p_values(raw), benjamini_hochberg_q_values(list(raw)), strict=True
        )
    ]


def _markdown(
    results: list[_Result], last: date, design: ValidationDesign, slices: list[_Sensitivity]
) -> str:
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
        f"区间采用交易日距离的 Bartlett HAC，带宽 {design.hac_lags}，置信水平 {design.confidence:.0%}。"
        + (
            "下表汇总全部预测日。"
            if slices
            else "仅作全部预测日的探索性描述，未检验重叠事件子样本。"
        ),
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
    if slices:
        lines.extend(
            [
                "",
                "## 与上交所节前 T−2 重叠的敏感性",
                "",
                "每折沿用同一组预测。以公告休市首日之前的倒数第二个实际交易日为 T−2，仅纳入至少关闭一个工作日的安排。"
                "单事件组剔除 T−2 当天，互斥窗口组剔除包含 T−2 的整个六候自然日窗口。上述标签仅描述与所核上交所休市公告的重叠。"
                "期权到期、指数调仓等其他事件未纳入。区间为逐项探索性区间，Holm p 在本次 27 项比较内计算。",
                "",
                "| 指数 | 期限（日） | 样本 | 保留日数 | 误差降幅 | 配对差值区间 | Holm p |",
                "|---|---:|---|---:|---:|---|---:|",
            ]
        )
        names = {"all": "全部", "single_event": "剔除 T−2 当天", "exclusive_window": "剔除重叠六候"}
        for s in slices:
            estimate = s.inference
            ci = (
                f"{estimate.lower:.5g} ～ {estimate.upper:.5g}"
                if estimate and estimate.lower is not None and estimate.upper is not None
                else "无法估计"
            )
            effect = f"{s.reduction_percent:+.3f}%" if s.reduction_percent is not None else "—"
            p = f"{s.holm_adjusted_p:.4g}" if s.holm_adjusted_p is not None else "—"
            lines.append(
                f"| {s.target} | {s.horizon} | {names[s.name]} | {s.observations} | {effect} | {ci} | {p} |"
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


def _later_report(
    results: list[_Result],
    early_effects: list[_Result],
    later_support: dict[str, dict[int, list[_LaterFoldSupport]]],
    missing_dates: dict[str, list[date]],
) -> tuple[dict[str, object], str]:
    raw = tuple(r.paired_loss.raw_p for r in results if r.paired_loss.raw_p is not None)
    holm: Sequence[float | None] = (
        holm_adjusted_p_values(raw) if len(raw) == len(results) else [None] * len(results)
    )
    fields: dict[str, object] = {
        "scope": "post-2018 full-fold development comparison, current-vintage snapshots",
        "inference": "Paired MSE difference with marginal 95% HAC intervals; Holm p covers all nine later-period comparisons.",
        "later_archive_sha256": LATER_ARCHIVE_SHA256,
        "pre_outcome_design_sha256": LATER_DESIGN_SHA256,
        "missing_closes": missing_dates,
        "early_reference_results": [asdict(r) for r in early_effects],
        "later_fold_support": {
            t: {h: [asdict(f) for f in fs] for h, fs in hs.items()}
            for t, hs in later_support.items()
        },
        "later_comparisons": [
            {"target": r.target, "horizon": r.horizon, "holm_p": p}
            for r, p in zip(results, holm, strict=True)
        ],
    }
    lines = [
        "",
        "## 新增年份与早期结果",
        "",
        "沿用原折起点，仅纳入 2019 年起开始、所有期限标签都在保留区间前留足五个交易日的完整验证折。"
        "缺收盘值时排除受影响的训练行和不完整的验证折。Holm 校正覆盖新增时期的九项比较。",
        "",
        "| 指数 | 期限 | 早期误差降幅 | 新增时期误差降幅 | 新增时期 Holm p | 实际/计划折数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for prior, r, p in zip(early_effects, results, holm, strict=True):
        changes = [
            "—" if v is None else f"{v:+.3f}%"
            for v in (prior.reduction_percent, r.reduction_percent)
        ]
        prob = "—" if p is None else f"{p:.4g}"
        lines.append(
            f"| {r.target} | {r.horizon} | {changes[0]} | {changes[1]} | {prob} | {len(r.folds)}/{len(later_support[r.target][r.horizon])} |"
        )
    for code, missing_days in missing_dates.items():
        if missing_days:
            lines.append(f"\n{code} 缺少日收盘：{', '.join(map(str,missing_days))}。")
    omitted: dict[tuple[date, date, int, int, str], set[str]] = {}
    for code, horizons in later_support.items():
        for h, records in horizons.items():
            for record in records:
                if record.reason:
                    key = (
                        record.start,
                        record.end,
                        record.validation_valid,
                        record.validation_expected,
                        record.reason,
                    )
                    omitted.setdefault(key, set()).add(f"{code}/{h}日")
    if omitted:
        lines.extend(
            [
                "",
                "| 排除的验证期间 | 全期限可评分日/计划日 | 原因 | 涉及组合 |",
                "|---|---:|---|---|",
            ]
        )
        for (start, end, valid, expected, reason), members in sorted(omitted.items()):
            cause = "验证折不完整" if reason == "VALIDATION_FOLD_INCOMPLETE" else "训练覆盖不足"
            scope = "全部九组" if len(members) == len(results) else "、".join(sorted(members))
            lines.append(f"| {start} 至 {end} | {valid}/{expected} | {cause} | {scope} |")
    positive = sum(r.paired_loss.mean > 0 for r in results)
    supported = sum(
        r.paired_loss.mean > 0 and p is not None and p < 0.05
        for r, p in zip(results, holm, strict=True)
    )
    lines.append(
        f"\n在纳入的完整折中，新增时期有 {positive}/{len(results)} 组验证误差下降；其中 {supported} 组达到预定的 Holm p < 0.05。"
    )
    return fields, "\n".join(lines) + "\n"


def write_snapshot(
    archive: Path,
    output: Path,
    *,
    event_archive: Path | None = None,
    later_archive: Path | None = None,
) -> None:
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
    if later_archive is not None and event_archive is not None:
        raise ValueError(
            "The frozen later cohort uses all dates; the holiday panel covers the early comparison"
        )
    reserve_start = len(dates) - reserve
    price_days = early if later_archive is None else dates[:reserve_start]
    later_queries: list[_Query] = []
    frozen_folds: list[list[str]] = []
    if later_archive is not None:
        later_manifest = json.loads(_verified(later_archive / "report.json", LATER_ARCHIVE_SHA256))
        frozen = json.loads(_verified(later_archive / "design.json", LATER_DESIGN_SHA256))
        if (
            later_manifest["design_sha256"] != LATER_DESIGN_SHA256
            or frozen["spec_sha256"] != SPEC_SHA256
            or frozen["archive_sha256"] != ARCHIVE_SHA256
            or _day(frozen["reserved_start"]) != dates[reserve_start]
            or _day(frozen["end_date"]) != price_days[-1]
            or frozen["targets"] != [f"{c}.SH" for c in design.targets]
        ):
            raise ValueError("Later archive does not match the frozen design and OOS boundary")
        later_queries = later_manifest["queries"]
        frozen_folds = frozen["folds"]
    panel = (
        load_holiday_panel(event_archive, dates, _START, _PRICE_END)
        if event_archive is not None
        else None
    )
    selection = _selections(early[_WARMUP:], panel) if panel is not None else None
    slices: list[_Sensitivity] = []
    results: list[_Result] = []
    early_effects = []
    later_support: dict[str, dict[int, list[_LaterFoldSupport]]] = {}
    missing_dates: dict[str, list[date]] = {}
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
        missing: set[int] = set()
        if later_archive is not None:
            prices += _closes(
                later_archive,
                _target_query(later_queries, "later_price", target),
                target,
                price_days[len(early) :],
                used,
                later_end=price_days[-1],
            )
            missing = {i for i, v in enumerate(prices) if math.isnan(v)}
            missing_dates[target] = [price_days[i] for i in sorted(missing)]
            later_support[target] = {}
        log_prices = tuple(map(math.log, prices))
        squares = (0.0, *((b - a) ** 2 for a, b in pairwise(log_prices)))
        features = _features(price_days, squares, design)
        for h in design.clock.horizons:
            evaluate = folds
            if later_archive is not None:
                prior, _ = _score(target, h, early, squares, features, folds, design)
                early_effects.append(prior)
                evaluate, audit = _later_cohort(
                    plan.folds, dates, reserve_start, missing, h, design
                )
                if [[str(f.start), str(f.end), str(f.last_label)] for f in audit] != frozen_folds:
                    raise ValueError("Later folds differ from the pre-outcome schedule")
                later_support[target][h] = audit
            result, scored = _score(target, h, price_days, squares, features, evaluate, design)
            results.append(result)
            if selection is not None:
                slices.extend(_sensitivity(result, scored, folds, *selection, design))
    report = {
        "scope": "current-vintage pre-2019 descriptive development only",
        "spec_sha256": SPEC_SHA256,
        "archive_manifest_sha256": ARCHIVE_SHA256,
        "source_sha256": used,
        "date_axis_final_reserved_start": dates[-reserve].strftime("%Y%m%d"),
        "reserved_origins": design.policy.final_oos_sessions,
        "last_available_price": price_days[-1].strftime("%Y%m%d"),
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
    if panel is not None:
        slices = _correct_sensitivities(slices)
        report["overlap_sensitivities"] = {
            "scope": "Six-period windows versus verified SSE pre-closure T-2 only; other event families unknown.",
            "rule": "Second trading session strictly before announced closure with at least one closed weekday; combined holidays form one episode.",
            "coverage_start": panel.start,
            "coverage_end": panel.end,
            "review_sha256": REVIEW_SHA256,
            "sources": panel.sources,
            "events": [
                {
                    **asdict(m),
                    "six_period_start": _window_start(m.origin),
                    "published_before_window": m.closure.published < _window_start(m.origin),
                }
                for m in panel.markers
            ],
            "window_knowledge": "Retrospective filtering only. When published during a marked window, pre-publication days are also excluded from the exclusive view; the later notice is never a model feature.",
            "correction_family": "All target/horizon/selection combinations of this retrospective development replay only.",
            "results": [asdict(s) for s in slices],
        }
    markdown = _markdown(results, price_days[-1], design, slices)
    if later_archive is not None:
        fields, comparison = _later_report(results, early_effects, later_support, missing_dates)
        report.update(fields)
        markdown += comparison
    _publish(
        output,
        {
            "results.json": (
                json.dumps(
                    report, indent=2, sort_keys=True, allow_nan=False, default=date.isoformat
                )
                + "\n"
            ).encode(),
            "report.md": markdown.encode(),
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
    parser.add_argument(
        "--event-archive",
        type=Path,
        help="Retained CAL-03 directory containing calendar-publication-review.json and calendar-originals/",
    )
    parser.add_argument(
        "--later-archive",
        type=Path,
        help="Pinned post-2018 pre-holdout close archive with its frozen design",
    )
    args = parser.parse_args()
    try:
        write_snapshot(
            args.archive,
            args.output,
            event_archive=args.event_archive,
            later_archive=args.later_archive,
        )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"CAL-03 replay failed: {exc}\n")
    print(args.output / "report.md")


if __name__ == "__main__":
    main()
