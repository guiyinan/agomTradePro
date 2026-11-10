"""Read current published financial metrics for one authorized holding."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from django.utils import timezone

from core.exceptions import BusinessLogicError
from shared.numeric import safe_float

_MAX_ROWS = 20
_SCOPE = "simulation_only"
_COVERAGE_NOTE = "当前发布的财务指标仅供参考，不代表完整公告、事件修订或公司行为覆盖。"
_EMPTY_COVERAGE_NOTE = "当前发布未返回该证券的财务指标；这不证明公告或公司行为不存在。"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class HoldingDisclosureScopeReaderProtocol(Protocol):
    """Resolve read authority and exact held-security membership for an account."""

    def has_readable_active_holding(
        self, *, actor_user_id: int, account_id: int, asset_code: str
    ) -> bool:
        """Return whether this actor may read this exact held security."""


class PublishedFinancialFactsReaderProtocol(Protocol):
    """Read a bounded Data Center publication through its public application port."""

    def read_published_financial_facts(
        self, asset_code: str, *, limit: int, publication_key: str
    ) -> Mapping[str, object]:
        """Return the publication gate and its financial-fact rows."""


@dataclass(frozen=True, slots=True)
class HoldingDisclosureRow:
    """One published financial metric with its original source clocks."""

    asset_code: str
    metric_code: str
    value: float
    unit: str
    period_end: str
    period_type: str
    report_date: str | None
    announced_at: str | None
    available_at: str | None
    fetched_at: str
    source: str
    source_record_id: str | None
    raw_payload_hash: str | None

    def to_payload(self) -> dict[str, object]:
        """Serialize the exact row fields in the holding-disclosure contract."""

        return {
            "asset_code": self.asset_code,
            "metric_code": self.metric_code,
            "value": self.value,
            "unit": self.unit,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "report_date": self.report_date,
            "announced_at": self.announced_at,
            "available_at": self.available_at,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "raw_payload_hash": self.raw_payload_hash,
        }


@dataclass(frozen=True, slots=True)
class HoldingDisclosureResult:
    """Read-only user payload that remains unusable for decisions and execution."""

    account_id: int
    asset_code: str
    as_of: str
    outcome: Literal["partial", "blocked"]
    coverage_note: str
    blocked_reason: str
    freshness: str
    reliability: str
    rows: tuple[HoldingDisclosureRow, ...]

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON payload for the API and TUI read path."""

        return {
            "account_id": self.account_id,
            "asset_code": self.asset_code,
            "as_of": self.as_of,
            "outcome": self.outcome,
            "scope": _SCOPE,
            "read_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "coverage_note": self.coverage_note,
            "blocked_reason": self.blocked_reason,
            "freshness": self.freshness,
            "reliability": self.reliability,
            "rows": [row.to_payload() for row in self.rows],
        }


class GetHoldingDisclosuresUseCase:
    """Read at most twenty current published metrics for an exact held asset."""

    def __init__(
        self,
        *,
        holding_reader: HoldingDisclosureScopeReaderProtocol,
        financial_facts_reader: PublishedFinancialFactsReaderProtocol,
    ) -> None:
        """Inject the account scope and Data Center application read ports."""

        self._holding_reader = holding_reader
        self._financial_facts_reader = financial_facts_reader

    def execute(
        self, *, actor_user_id: int, account_id: int, asset_code: str
    ) -> HoldingDisclosureResult:
        """Return source-bound references without refreshing or changing account state."""

        read_at = timezone.now()
        normalized_asset_code = _validated_asset_code(asset_code)
        if (
            type(actor_user_id) is not int
            or actor_user_id <= 0
            or type(account_id) is not int
            or account_id <= 0
            or normalized_asset_code is None
        ):
            return _blocked_result(
                account_id=account_id,
                asset_code=asset_code if isinstance(asset_code, str) else "",
                read_at=read_at,
                blocked_reason=(
                    "invalid_asset_code"
                    if normalized_asset_code is None
                    else "account_scope_or_holding_unavailable"
                ),
            )

        if not self._holding_reader.has_readable_active_holding(
            actor_user_id=actor_user_id,
            account_id=account_id,
            asset_code=normalized_asset_code,
        ):
            return _blocked_result(
                account_id=account_id,
                asset_code=normalized_asset_code,
                read_at=read_at,
                blocked_reason="account_scope_or_holding_unavailable",
            )

        payload = self._financial_facts_reader.read_published_financial_facts(
            normalized_asset_code,
            limit=_MAX_ROWS,
            publication_key="current",
        )
        return _result_from_publication(
            payload,
            account_id=account_id,
            asset_code=normalized_asset_code,
            read_at=read_at,
        )


_use_case_factory: Callable[[str], GetHoldingDisclosuresUseCase] | None = None


class HoldingDisclosureUnavailable(BusinessLogicError):
    """The account disclosure read factory has not been composed."""

    default_code = "HOLDING_DISCLOSURE_UNAVAILABLE"
    default_message = "当前无法读取持仓证券披露资料。"
    default_status_code = 503


def configure_holding_disclosure_use_case(
    factory: Callable[[str], GetHoldingDisclosuresUseCase],
) -> None:
    """Register a lazy application factory without reading accounts at startup."""

    global _use_case_factory
    _use_case_factory = factory


def read_owned_holding_disclosures(
    *, user_id: int, account_id: int, asset_code: str, using: str = "default"
) -> dict[str, object]:
    """Read source-bound financial references after account and holding checks."""

    if _use_case_factory is None:
        raise HoldingDisclosureUnavailable("holding disclosure service is unavailable")
    use_case = _use_case_factory(using)
    return use_case.execute(
        actor_user_id=user_id,
        account_id=account_id,
        asset_code=asset_code,
    ).to_payload()


def _result_from_publication(
    payload: Mapping[str, object],
    *,
    account_id: int,
    asset_code: str,
    read_at: datetime,
) -> HoldingDisclosureResult:
    """Validate Data Center's publication envelope and preserve its row clocks."""

    freshness = _gate_label(payload, "freshness_status")
    reliability = _gate_label(payload, "reliability")
    if freshness is None or reliability is None:
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_gate_invalid",
            freshness=freshness or "unknown",
            reliability=reliability or "unknown",
        )

    if (
        "must_not_use_for_decision" not in payload
        or type(payload.get("must_not_use_for_decision")) is not bool
    ):
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_gate_invalid",
            freshness=freshness,
            reliability=reliability,
        )

    if payload["must_not_use_for_decision"] is True:
        blocked_reason = _blocked_reason(payload.get("blocked_reason"))
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason=blocked_reason,
            freshness=freshness,
            reliability=reliability,
        )

    publication_id = payload.get("publication_id")
    if type(publication_id) is not str or not publication_id.strip():
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_publication_identity_missing",
            freshness=freshness,
            reliability=reliability,
        )

    if "blocked_reason" in payload and payload["blocked_reason"] not in (None, ""):
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_gate_invalid",
            freshness=freshness,
            reliability=reliability,
        )

    raw_rows = payload.get("rows")
    if type(raw_rows) is not list:
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_rows_invalid",
            freshness=freshness,
            reliability=reliability,
        )
    if len(raw_rows) > _MAX_ROWS:
        return _blocked_result(
            account_id=account_id,
            asset_code=asset_code,
            read_at=read_at,
            blocked_reason="published_financial_rows_limit_exceeded",
            freshness=freshness,
            reliability=reliability,
        )

    parsed_rows: list[HoldingDisclosureRow] = []
    for raw_row in raw_rows:
        parsed, blocked_reason = _parse_row(
            raw_row,
            expected_asset_code=asset_code,
            read_at=read_at,
        )
        if parsed is None:
            return _blocked_result(
                account_id=account_id,
                asset_code=asset_code,
                read_at=read_at,
                blocked_reason=blocked_reason,
                freshness=freshness,
                reliability=reliability,
            )
        parsed_rows.append(parsed)

    return HoldingDisclosureResult(
        account_id=account_id,
        asset_code=asset_code,
        as_of=read_at.isoformat(),
        outcome="partial",
        coverage_note=_COVERAGE_NOTE if parsed_rows else _EMPTY_COVERAGE_NOTE,
        blocked_reason="",
        freshness=freshness,
        reliability=reliability,
        rows=tuple(parsed_rows),
    )


def _parse_row(
    raw_row: object,
    *,
    expected_asset_code: str,
    read_at: datetime,
) -> tuple[HoldingDisclosureRow | None, str]:
    """Narrow and validate one normalized Data Center fact before serialization."""

    if not isinstance(raw_row, Mapping):
        return None, "published_financial_row_invalid"
    row_asset_code = raw_row.get("asset_code")
    if type(row_asset_code) is not str or row_asset_code != expected_asset_code:
        return None, "published_financial_row_asset_mismatch"

    metric_code = _required_text(raw_row.get("metric_code"))
    unit = _text(raw_row.get("unit"))
    period_end = _date_text(raw_row.get("period_end"), allow_none=False)
    period_type = _required_text(raw_row.get("period_type"))
    report_date = _date_text(raw_row.get("report_date"), allow_none=True)
    source = _text(raw_row.get("source"))
    raw_value = raw_row.get("value")
    if isinstance(raw_value, bool):
        return None, "published_financial_row_value_invalid"
    value = safe_float(raw_value)
    if (
        period_end is _INVALID
        or not isinstance(period_end, str)
        or report_date is _INVALID
        or (report_date is not None and not isinstance(report_date, str))
    ):
        return None, "published_financial_row_date_invalid"
    if metric_code is None or unit is None or period_type is None or source is None:
        return None, "published_financial_row_invalid"
    if value is None or not math.isfinite(value):
        return None, "published_financial_row_value_invalid"

    fetched_at, fetched_datetime = _datetime_text(raw_row.get("fetched_at"), allow_none=False)
    available_at, available_datetime = _datetime_text(raw_row.get("available_at"), allow_none=True)
    if (
        fetched_at is _INVALID
        or not isinstance(fetched_at, str)
        or fetched_datetime is None
        or available_at is _INVALID
        or (available_at is not None and not isinstance(available_at, str))
    ):
        return None, "published_financial_row_time_invalid"

    source_evidence_value = raw_row.get("source_evidence")
    if source_evidence_value is None:
        source_evidence: Mapping[str, object] = {}
    elif isinstance(source_evidence_value, Mapping):
        source_evidence = source_evidence_value
    else:
        return None, "published_financial_row_invalid"
    announced_at, announced_datetime = _datetime_text(
        source_evidence.get("announced_at"), allow_none=True
    )
    source_record_id = _optional_text(source_evidence.get("source_record_id"))
    raw_payload_hash = _optional_text(source_evidence.get("raw_payload_hash"))
    if (
        announced_at is _INVALID
        or (announced_at is not None and not isinstance(announced_at, str))
        or source_record_id is _INVALID
        or (source_record_id is not None and not isinstance(source_record_id, str))
        or raw_payload_hash is _INVALID
        or (raw_payload_hash is not None and not isinstance(raw_payload_hash, str))
        or (isinstance(raw_payload_hash, str) and not _SHA256_PATTERN.fullmatch(raw_payload_hash))
    ):
        return None, "published_financial_row_invalid"

    timestamps = (fetched_datetime, available_datetime, announced_datetime)
    if any(timestamp is not None and timestamp > read_at for timestamp in timestamps):
        return None, "published_financial_row_future_time"

    return (
        HoldingDisclosureRow(
            asset_code=expected_asset_code,
            metric_code=metric_code,
            value=value,
            unit=unit,
            period_end=period_end,
            period_type=period_type,
            report_date=report_date,
            announced_at=announced_at,
            available_at=available_at,
            fetched_at=fetched_at,
            source=source,
            source_record_id=source_record_id,
            raw_payload_hash=raw_payload_hash,
        ),
        "",
    )


def _gate_label(payload: Mapping[str, object], key: str) -> str | None:
    """Preserve a Data Center gate label or mark an absent value unknown."""

    value = payload.get(key)
    if value is None:
        return "unknown"
    if type(value) is not str:
        return None
    return value or "unknown"


def _blocked_reason(value: object) -> str:
    """Keep a source-owned stable block reason or use a non-claiming fallback."""

    if type(value) is str and value.strip():
        return value
    return "published_financial_source_blocked"


def _blocked_result(
    *,
    account_id: int,
    asset_code: str,
    read_at: datetime,
    blocked_reason: str,
    freshness: str = "unknown",
    reliability: str = "unknown",
) -> HoldingDisclosureResult:
    """Build a closed, non-decisioning result with no disclosure rows."""

    return HoldingDisclosureResult(
        account_id=account_id if type(account_id) is int else 0,
        asset_code=asset_code,
        as_of=read_at.isoformat(),
        outcome="blocked",
        coverage_note=_COVERAGE_NOTE,
        blocked_reason=blocked_reason,
        freshness=freshness,
        reliability=reliability,
        rows=(),
    )


def _validated_asset_code(value: str) -> str | None:
    """Accept one exact, unpadded asset code without alias or ticker inference."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 20:
        return None
    return value


def _required_text(value: object) -> str | None:
    """Return nonempty unpadded source text."""

    if type(value) is not str or not value or value.strip() != value:
        return None
    return value


def _text(value: object) -> str | None:
    """Return source text while allowing its documented empty value."""

    if type(value) is not str or value.strip() != value:
        return None
    return value


_INVALID = object()


def _optional_text(value: object) -> str | None | object:
    """Preserve an optional source identifier or reject wrong/padded values."""

    if value is None:
        return None
    if type(value) is str and value.strip() == value:
        return value or None
    return _INVALID


def _date_text(value: object, *, allow_none: bool) -> str | None | object:
    """Retain date-only source precision while rejecting datetime-shaped values."""

    if value is None and allow_none:
        return None
    if type(value) is not str:
        return _INVALID
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return _INVALID
    return value if parsed.isoformat() == value else _INVALID


def _datetime_text(
    value: object, *, allow_none: bool
) -> tuple[str | None | object, datetime | None]:
    """Retain an aware source timestamp without imputing or normalizing its clock."""

    if value is None and allow_none:
        return None, None
    if type(value) is not str:
        return _INVALID, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return _INVALID, None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return _INVALID, None
    return value, parsed.astimezone(UTC)


__all__: tuple[str, ...] = (
    "GetHoldingDisclosuresUseCase",
    "HoldingDisclosureResult",
    "HoldingDisclosureRow",
    "HoldingDisclosureUnavailable",
    "configure_holding_disclosure_use_case",
    "read_owned_holding_disclosures",
)
