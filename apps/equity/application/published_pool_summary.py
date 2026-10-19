"""Build a typed, fail-closed summary for the published equity stock pool."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from shared.numeric import safe_float

PublishedRowStatus = Literal["published", "partial"]
PublishedPoolStatus = Literal["published", "partial", "blocked"]
PublishedPoolOutcome = Literal["success", "partial", "blocked"]

_FINANCIAL_DATASET = "equity.financial.fact"
_VALUATION_DATASET = "equity.valuation.fact"
_SUPPORTED_VALUATION_BLOCK = "valuation_source_data_unavailable"
_SCOPE_UNVERIFIED = "canonical_publication_scope_unverified"
_MEMBERS_MISSING = "canonical_publication_members_missing"
_POOL_RESTRICTION = "本次估值发布范围存在缺口；股票池仅供观察，" "当前结果不可用于决策。"
_VALUATION_RESTRICTION = (
    "估值资料缺失，暂不用于依赖估值的筛选/计划；" "仅供观察，当前估值资料不可用于决策。"
)


class PublishedStockContextReader(Protocol):
    """Read publication-gated facts for the requested equity codes."""

    def __call__(
        self,
        stock_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
    ) -> dict[str, dict[str, object]]:
        """Return safe Application context rows keyed by requested asset code."""


@dataclass(frozen=True)
class PublishedPoolStock:
    """One validated published stock-pool row."""

    code: str
    asset_code: str
    name: str
    sector: str
    roe: float | None
    pe: float | None
    pb: float | None
    revenue_growth: float | None
    profit_growth: float | None
    score: None
    status: PublishedRowStatus
    status_label: str
    must_not_use_for_decision: bool
    blocked_datasets: tuple[str, ...]
    blocked_reason: str | None
    restriction_message: str | None
    publication_gates: dict[str, object]
    source_times: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        """Serialize the row into the stable API response shape."""

        return {
            "code": self.code,
            "asset_code": self.asset_code,
            "name": self.name,
            "sector": self.sector,
            "roe": self.roe,
            "pe": self.pe,
            "pb": self.pb,
            "revenue_growth": self.revenue_growth,
            "profit_growth": self.profit_growth,
            "score": self.score,
            "status": self.status,
            "status_label": self.status_label,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_datasets": list(self.blocked_datasets),
            "blocked_reason": self.blocked_reason,
            "restriction_message": self.restriction_message,
            "publication_gates": dict(self.publication_gates),
            "source_times": dict(self.source_times),
        }


@dataclass(frozen=True)
class PublishedPoolSectorCount:
    """One sector-count chart row for the validated pool result."""

    sector: str
    count: int

    def to_payload(self) -> dict[str, object]:
        """Serialize one chart row."""

        return {"sector": self.sector, "count": self.count}


@dataclass(frozen=True)
class PublishedPoolSummary:
    """Typed success, partial, or blocked result for the published pool."""

    success: bool
    status: PublishedPoolStatus
    outcome: PublishedPoolOutcome
    publication_key: str
    requested_count: int
    count: int
    blocked_count: int | None
    avg_roe: float | None
    avg_pe: float | None
    aggregate_coverage: dict[str, dict[str, int]]
    stocks: tuple[PublishedPoolStock, ...]
    sector_distribution: tuple[PublishedPoolSectorCount, ...]
    publication_gates: dict[str, object]
    must_not_use_for_decision: bool
    blocked_reason: str | None
    restriction_message: str | None

    def to_payload(self) -> dict[str, object]:
        """Return JSON-renderable fields without applying new policy."""

        return {
            "success": self.success,
            "status": self.status,
            "outcome": self.outcome,
            "mode": "published",
            "publication_key": self.publication_key,
            "requested_count": self.requested_count,
            "count": self.count,
            "blocked_count": self.blocked_count,
            "avg_roe": self.avg_roe,
            "avg_pe": self.avg_pe,
            "aggregate_coverage": {
                key: dict(value) for key, value in self.aggregate_coverage.items()
            },
            "stocks": [row.to_payload() for row in self.stocks],
            "sector_distribution": [row.to_payload() for row in self.sector_distribution],
            "publication_gates": dict(self.publication_gates),
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reason": self.blocked_reason,
            "restriction_message": self.restriction_message,
        }


def build_published_stock_pool_summary(
    stock_codes: Sequence[str],
    *,
    publication_key: str,
    publication_gates: Mapping[str, object],
    context_reader: PublishedStockContextReader,
) -> PublishedPoolSummary:
    """Validate publication scope, read rows, and aggregate without shrinking scope.

    Only a fully identity-bound current valuation scope block with the supported
    ``valuation_source_data_unavailable`` reason can produce a partial result.
    All financial, unknown, stale, audit, identity, or missing-context failures
    remain whole-pool blocked. The context reader is called only after both
    global publication gates pass validation.
    """

    requested_codes = tuple(_normalize_code(code) for code in stock_codes)
    unique_codes = tuple(dict.fromkeys(requested_codes))
    gates = _safe_dataset_gates(publication_gates)
    financial_gate, financial_error = _validate_global_gate(
        gates.get(_FINANCIAL_DATASET),
        expected_dataset=_FINANCIAL_DATASET,
        publication_key=publication_key,
        allow_partial=False,
    )
    if financial_error is not None:
        return _blocked_summary(requested_codes, publication_key, gates, financial_error)
    valuation_gate, valuation_error = _validate_global_gate(
        gates.get(_VALUATION_DATASET),
        expected_dataset=_VALUATION_DATASET,
        publication_key=publication_key,
        allow_partial=True,
    )
    if valuation_error is not None:
        return _blocked_summary(requested_codes, publication_key, gates, valuation_error)
    if financial_gate is None or valuation_gate is None:
        return _blocked_summary(requested_codes, publication_key, gates, _SCOPE_UNVERIFIED)

    context_rows = context_reader(
        list(unique_codes),
        publication_key=publication_key,
        include_price=False,
    )
    if len(context_rows) != len(unique_codes):
        return _blocked_summary(requested_codes, publication_key, gates, _MEMBERS_MISSING)

    rows: list[PublishedPoolStock] = []
    for code in requested_codes:
        context = _mapping(context_rows.get(code))
        if context is None:
            return _blocked_summary(requested_codes, publication_key, gates, _MEMBERS_MISSING)
        row, error = _published_stock_row(
            code,
            context,
            publication_key=publication_key,
            financial_global_gate=financial_gate,
            valuation_global_gate=valuation_gate,
        )
        if error is not None or row is None:
            reason = error or _SCOPE_UNVERIFIED
            return _blocked_summary(requested_codes, publication_key, gates, reason)
        rows.append(row)

    partial = valuation_gate.get("publication_outcome") == "partial" or any(
        row.status == "partial" for row in rows
    )
    roe_values = [row.roe for row in rows if row.roe is not None]
    pe_values = [row.pe for row in rows if row.pe is not None]
    requested_count = len(requested_codes)
    avg_roe = (
        round(sum(roe_values) / len(roe_values), 2)
        if requested_count > 0 and len(roe_values) == requested_count
        else None
    )
    avg_pe = (
        round(sum(pe_values) / len(pe_values), 2)
        if requested_count > 0 and len(pe_values) == requested_count
        else None
    )
    sector_counts: dict[str, int] = {}
    for row in rows:
        sector_counts[row.sector] = sector_counts.get(row.sector, 0) + 1
    sectors = tuple(
        PublishedPoolSectorCount(sector=sector, count=count)
        for sector, count in sorted(sector_counts.items(), key=lambda item: (-item[1], item[0]))
    )

    return PublishedPoolSummary(
        success=True,
        status="partial" if partial else "published",
        outcome="partial" if partial else "success",
        publication_key=publication_key,
        requested_count=requested_count,
        count=len(rows),
        blocked_count=sum(row.status == "partial" for row in rows),
        avg_roe=avg_roe,
        avg_pe=avg_pe,
        aggregate_coverage={
            "avg_roe": {"known_count": len(roe_values), "requested_count": requested_count},
            "avg_pe": {"known_count": len(pe_values), "requested_count": requested_count},
        },
        stocks=tuple(rows),
        sector_distribution=sectors,
        publication_gates=gates,
        must_not_use_for_decision=partial,
        blocked_reason=None,
        restriction_message=_POOL_RESTRICTION if partial else None,
    )


def _normalize_code(value: str) -> str:
    """Normalize one requested code using the existing uppercase contract."""

    return value.strip().upper()


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one untyped mapping boundary to string-keyed fields."""

    if not isinstance(value, Mapping):
        return None
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _safe_dataset_gates(value: Mapping[str, object]) -> dict[str, object]:
    """Whitelist public metadata for the two gates used by this use case."""

    result: dict[str, object] = {}
    for dataset in (_FINANCIAL_DATASET, _VALUATION_DATASET):
        gate = _mapping(value.get(dataset))
        if gate is not None:
            result[dataset] = _public_gate(gate)
    return result


def _text(value: object) -> str | None:
    """Return a trimmed nonempty string without coercing arbitrary values."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_text(value: object) -> str | None:
    """Accept only already-canonical nonempty identity text."""

    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value


def _count(gate: Mapping[str, object], key: str) -> int | None:
    """Read a nonnegative count while rejecting bool and malformed values."""

    value = gate.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _validate_global_gate(
    value: object,
    *,
    expected_dataset: str,
    publication_key: str,
    allow_partial: bool,
) -> tuple[dict[str, object] | None, str | None]:
    """Validate complete global publication identity and coverage semantics."""

    gate_mapping = _mapping(value)
    if gate_mapping is None:
        return None, "canonical_publication_missing"
    gate = dict(gate_mapping)
    if gate.get("must_not_use_for_decision") is not False:
        return None, _text(gate.get("blocked_reason")) or "canonical_publication_missing"
    blocked_reason = _text(gate.get("blocked_reason"))
    if blocked_reason is not None:
        return None, blocked_reason
    expected_identity = {
        "dataset_key": expected_dataset,
        "publication_key": publication_key,
    }
    if any(gate.get(key) != expected for key, expected in expected_identity.items()):
        return None, _SCOPE_UNVERIFIED
    publication_id = _canonical_text(gate.get("publication_id"))
    policy_identity = _canonical_text(gate.get("policy_identity"))
    policy_version = _canonical_text(gate.get("policy_version"))
    source = _canonical_text(gate.get("selected_source"))
    run_id = _canonical_text(gate.get("publication_run_id"))
    if (
        publication_id is None
        or policy_identity is None
        or policy_version is None
        or policy_identity != policy_version
        or source is None
        or run_id is None
    ):
        return None, _SCOPE_UNVERIFIED

    outcome = gate.get("publication_outcome")
    requested = _count(gate, "coverage_requested_count")
    eligible = _count(gate, "coverage_eligible_count")
    selected = _count(gate, "coverage_selected_count")
    missing = _count(gate, "coverage_missing_count")
    if None in (requested, eligible, selected, missing):
        return None, _SCOPE_UNVERIFIED
    assert requested is not None and eligible is not None
    assert selected is not None and missing is not None
    if selected > eligible or eligible > requested or selected + missing != requested:
        return None, _SCOPE_UNVERIFIED
    if outcome == "success" and missing == 0 and selected == requested:
        return gate, None
    if (
        allow_partial
        and expected_dataset == _VALUATION_DATASET
        and publication_key == "current"
        and outcome == "partial"
        and requested > 0
        and selected > 0
        and missing > 0
    ):
        return gate, None
    return None, _text(gate.get("blocked_reason")) or _SCOPE_UNVERIFIED


def _identity_matches(
    value: object,
    *,
    expected_dataset: str,
    global_gate: Mapping[str, object],
) -> dict[str, object] | None:
    """Require a per-asset gate to match every declared global identity field."""

    gate_mapping = _mapping(value)
    if gate_mapping is None:
        return None
    gate = dict(gate_mapping)
    for key, expected in (
        ("dataset_key", expected_dataset),
        ("publication_key", global_gate.get("publication_key")),
        ("publication_id", global_gate.get("publication_id")),
        ("policy_identity", global_gate.get("policy_identity")),
        ("policy_version", global_gate.get("policy_version")),
        ("selected_source", global_gate.get("selected_source")),
        ("publication_run_id", global_gate.get("publication_run_id")),
        ("publication_outcome", global_gate.get("publication_outcome")),
    ):
        if expected is None or gate.get(key) != expected:
            return None
    if (
        gate.get("must_not_use_for_decision") is not True
        and gate.get("must_not_use_for_decision") is not False
    ):
        return None
    if (
        gate.get("must_not_use_for_decision") is False
        and _text(gate.get("blocked_reason")) is not None
    ):
        return None
    return gate


def _valid_local_valuation_block(
    gate: Mapping[str, object],
    *,
    code: str,
    global_gate: Mapping[str, object],
) -> bool:
    """Validate the one supported, publication-bound valuation block."""

    block = _mapping(gate.get("scope_block"))
    if block is None or gate.get("must_not_use_for_decision") is not True:
        return False
    if gate.get("blocked_reason") != _SUPPORTED_VALUATION_BLOCK:
        return False
    block_code = _canonical_text(block.get("asset_code"))
    if block_code != code:
        return False
    if block.get("reason_code") != _SUPPORTED_VALUATION_BLOCK:
        return False
    target_date = _text(block.get("target_trade_date"))
    if target_date is None:
        return False
    try:
        if date.fromisoformat(target_date).isoformat() != target_date:
            return False
    except ValueError:
        return False
    identity_fields = {
        "publication_id": "publication_id",
        "source": "selected_source",
        "publication_run_id": "publication_run_id",
        "policy_version": "policy_version",
    }
    if any(
        block.get(key) != global_gate.get(global_key) for key, global_key in identity_fields.items()
    ):
        return False
    if "dataset_key" in block and block.get("dataset_key") != _VALUATION_DATASET:
        return False
    if "publication_key" in block and block.get("publication_key") != global_gate.get(
        "publication_key"
    ):
        return False
    return True


def _published_stock_row(
    code: str,
    context: Mapping[str, object],
    *,
    publication_key: str,
    financial_global_gate: Mapping[str, object],
    valuation_global_gate: Mapping[str, object],
) -> tuple[PublishedPoolStock | None, str | None]:
    """Build one row only when the asset and dataset gates are trustworthy."""

    context_code = _canonical_text(context.get("asset_code"))
    if context_code is None or context.get("requested_code") != code:
        return None, _text(context.get("blocked_reason")) or _MEMBERS_MISSING
    missing = context.get("missing_datasets")
    if isinstance(missing, list) and "financial" in missing:
        return None, _MEMBERS_MISSING
    raw_gates = _mapping(context.get("publication_gates"))
    if raw_gates is None:
        return None, _text(context.get("blocked_reason")) or _SCOPE_UNVERIFIED
    financial_gate = _identity_matches(
        raw_gates.get("financial"),
        expected_dataset=_FINANCIAL_DATASET,
        global_gate=financial_global_gate,
    )
    valuation_gate = _identity_matches(
        raw_gates.get("valuation"),
        expected_dataset=_VALUATION_DATASET,
        global_gate=valuation_global_gate,
    )
    if financial_gate is None or valuation_gate is None:
        return None, _text(context.get("blocked_reason")) or _SCOPE_UNVERIFIED
    if financial_gate.get("must_not_use_for_decision") is not False:
        return None, _text(financial_gate.get("blocked_reason")) or _SCOPE_UNVERIFIED
    if _mapping(financial_gate.get("scope_block")) is not None:
        return None, _SCOPE_UNVERIFIED

    valuation_blocked = valuation_gate.get("must_not_use_for_decision") is True
    if valuation_blocked:
        if not _valid_local_valuation_block(
            valuation_gate,
            code=context_code,
            global_gate=valuation_global_gate,
        ):
            return None, _text(valuation_gate.get("blocked_reason")) or _SCOPE_UNVERIFIED
        if context.get("must_not_use_for_decision") is not True:
            return None, _SCOPE_UNVERIFIED
        if context.get("blocked_reason") != _SUPPORTED_VALUATION_BLOCK:
            return None, _SCOPE_UNVERIFIED
    elif (
        valuation_gate.get("must_not_use_for_decision") is not False
        or _mapping(valuation_gate.get("scope_block")) is not None
        or context.get("must_not_use_for_decision") is not False
        or context.get("blocked_reason") not in (None, "")
    ):
        return None, _text(valuation_gate.get("blocked_reason")) or _SCOPE_UNVERIFIED

    name = _text(context.get("name")) or ""
    sector = _text(context.get("sector")) or "未知"
    roe = safe_float(context.get("roe"), default=None)
    pe = safe_float(context.get("pe"), default=None)
    pb = safe_float(context.get("pb"), default=None)
    revenue_growth = safe_float(context.get("revenue_growth"), default=None)
    profit_growth = safe_float(context.get("profit_growth"), default=None)
    if pe is not None and pe <= 0:
        pe = None
    if pb is not None and pb <= 0:
        pb = None
    if valuation_blocked:
        pe = None
        pb = None

    gates: dict[str, object] = {
        "financial": _public_gate(financial_gate),
        "valuation": _public_gate(valuation_gate),
    }
    source_times = _public_source_times(context.get("source_times"))
    return (
        PublishedPoolStock(
            code=code,
            asset_code=context_code,
            name=name,
            sector=sector,
            roe=roe,
            pe=pe,
            pb=pb,
            revenue_growth=revenue_growth,
            profit_growth=profit_growth,
            score=None,
            status="partial" if valuation_blocked else "published",
            status_label="估值资料受限" if valuation_blocked else "资料已发布",
            must_not_use_for_decision=valuation_blocked,
            blocked_datasets=(_VALUATION_DATASET,) if valuation_blocked else (),
            blocked_reason=_SUPPORTED_VALUATION_BLOCK if valuation_blocked else None,
            restriction_message=_VALUATION_RESTRICTION if valuation_blocked else None,
            publication_gates=gates,
            source_times=source_times,
        ),
        None,
    )


def _public_gate(value: Mapping[str, object]) -> dict[str, object]:
    """Project only stable publication metadata and scope evidence to the API."""

    fields = (
        "dataset_key",
        "publication_key",
        "publication_id",
        "published_at",
        "as_of",
        "policy_identity",
        "policy_version",
        "selected_source",
        "publication_run_id",
        "publication_outcome",
        "coverage_requested_count",
        "coverage_eligible_count",
        "coverage_selected_count",
        "coverage_missing_count",
        "freshness_status",
        "must_not_use_for_decision",
        "blocked_reason",
    )
    gate = {key: value[key] for key in fields if key in value}
    block = _mapping(value.get("scope_block"))
    if block is not None:
        allowed = (
            "asset_code",
            "reason_code",
            "target_trade_date",
            "publication_id",
            "source",
            "publication_run_id",
            "policy_version",
            "evidence_source",
        )
        gate["scope_block"] = {key: block[key] for key in allowed if key in block}
    return gate


def _public_source_times(value: object) -> dict[str, object]:
    """Copy only source-clock fields while preserving explicit unknown values."""

    source_times = _mapping(value)
    if source_times is None:
        return {}
    result: dict[str, object] = {}
    allowed_fields = {
        "financial": (
            "period_end",
            "report_date",
            "observed_at",
            "available_at",
            "fetched_at",
            "announced_at",
            "source_time_witness",
        ),
        "valuation": ("val_date", "observed_at", "available_at", "fetched_at"),
        "price": ("timestamp", "observed_at", "available_at", "fetched_at"),
    }
    for dataset, fields in allowed_fields.items():
        raw_dataset = _mapping(source_times.get(dataset))
        if raw_dataset is None:
            continue
        if dataset == "financial":
            metrics: dict[str, object] = {}
            for metric, raw_clock in raw_dataset.items():
                metric_clock = _mapping(raw_clock)
                if metric_clock is None:
                    continue
                public_clock = {
                    key: metric_clock[key]
                    for key in fields
                    if key in metric_clock and key != "source_time_witness"
                }
                if "source_time_witness" in metric_clock:
                    public_clock["source_time_witness"] = _public_source_time_witness(
                        metric_clock["source_time_witness"]
                    )
                metrics[metric] = public_clock
            result[dataset] = metrics
        else:
            result[dataset] = {key: raw_dataset[key] for key in fields if key in raw_dataset}
    return result


def _public_source_time_witness(value: object) -> dict[str, object] | None:
    """Expose witness clocks while withholding artifact locations and key refs."""

    witness = _mapping(value)
    if witness is None:
        return None
    allowed = (
        "financial_announced_date",
        "source_timezone",
        "announced_at",
        "available_at",
        "availability_basis",
        "source_time_precision",
    )
    return {key: witness[key] for key in allowed if key in witness}


def _blocked_summary(
    stock_codes: Sequence[str],
    publication_key: str,
    publication_gates: dict[str, object],
    reason: str,
) -> PublishedPoolSummary:
    """Build the stable empty result when any required pool proof fails."""

    requested_count = len(stock_codes)
    return PublishedPoolSummary(
        success=False,
        status="blocked",
        outcome="blocked",
        publication_key=publication_key,
        requested_count=requested_count,
        count=0,
        blocked_count=None,
        avg_roe=None,
        avg_pe=None,
        aggregate_coverage={
            "avg_roe": {"known_count": 0, "requested_count": requested_count},
            "avg_pe": {"known_count": 0, "requested_count": requested_count},
        },
        stocks=(),
        sector_distribution=(),
        publication_gates=publication_gates,
        must_not_use_for_decision=True,
        blocked_reason=reason,
        restriction_message=None,
    )


__all__ = [
    "PublishedPoolSectorCount",
    "PublishedPoolStock",
    "PublishedPoolSummary",
    "PublishedStockContextReader",
    "build_published_stock_pool_summary",
]
