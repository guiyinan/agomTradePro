"""Fail-closed equity research snapshot application contract and use case."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, TypeAlias

from shared.numeric import safe_float

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ReadPayload: TypeAlias = Mapping[str, object] | list[object] | None

_UNUSABLE_CURRENT_DATA_STATUSES = frozenset(
    {
        "blocked",
        "error",
        "failed",
        "missing",
        "stale",
        "unavailable",
        "unverified",
        "unknown",
    }
)


class EquityResearchSnapshotReader(Protocol):
    """Port exposing only the published Data Center reads needed by the use case."""

    def resolve_asset(self, stock_code: str) -> ReadPayload: ...

    def get_decision_readiness(self) -> ReadPayload: ...

    def get_latest_quotes(
        self, stock_code: str, *, strict_freshness: bool = True
    ) -> ReadPayload: ...

    def get_price_history(self, stock_code: str, *, limit: int) -> ReadPayload: ...

    def get_valuations(self, stock_code: str, *, limit: int) -> ReadPayload: ...

    def get_financials(self, stock_code: str, *, limit: int) -> ReadPayload: ...

    def get_news(self, stock_code: str, *, limit: int) -> ReadPayload: ...

    def get_capital_flows(self, stock_code: str, *, limit: int) -> ReadPayload: ...


@dataclass(frozen=True)
class EquityResearchSnapshotRequest:
    """Bounded input for one complete equity evidence read."""

    stock_code: str
    history_limit: int = 252
    financial_limit: int = 20
    valuation_limit: int = 252
    news_limit: int = 20
    capital_flow_limit: int = 60

    def __post_init__(self) -> None:
        normalized_code = self.stock_code.strip()
        if not normalized_code:
            raise ValueError("stock_code is required")
        if len(normalized_code) > 32:
            raise ValueError("stock_code must not exceed 32 characters")
        object.__setattr__(self, "stock_code", normalized_code)
        for field_name, value, maximum in (
            ("history_limit", self.history_limit, 1000),
            ("financial_limit", self.financial_limit, 100),
            ("valuation_limit", self.valuation_limit, 1000),
            ("news_limit", self.news_limit, 100),
            ("capital_flow_limit", self.capital_flow_limit, 1000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{field_name} must be between 1 and {maximum}")


@dataclass(frozen=True)
class EquityResearchSection:
    """Normalized reliability envelope for one evidence section."""

    status: str
    required: bool
    data: JsonValue
    must_not_use_for_decision: bool
    block_reason_code: str

    def to_payload(self) -> JsonObject:
        """Serialize the section without losing its source payload."""

        return {
            "status": self.status,
            "required": self.required,
            "data": self.data,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "block_reason_code": self.block_reason_code,
        }


@dataclass(frozen=True)
class EquityResearchCapability:
    """One use-specific evidence status, separate from decision qualification."""

    status: Literal["observation_only", "blocked", "not_evaluated"]
    reason_codes: tuple[str, ...]
    evidence_sections: tuple[str, ...]

    def to_payload(self) -> JsonObject:
        """Serialize stable reasons and evidence section references."""

        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "evidence_sections": list(self.evidence_sections),
        }


@dataclass(frozen=True)
class EquityResearchSnapshotResult:
    """Complete equity evidence envelope returned by the use case."""

    status: str
    stock_code: str | None
    identity: EquityResearchSection
    sections: Mapping[str, EquityResearchSection]
    decision_readiness: JsonValue
    missing_optional_sections: tuple[str, ...]
    reliability: JsonObject
    must_not_use_for_decision: bool
    capabilities: Mapping[str, EquityResearchCapability] = field(default_factory=dict)

    def to_payload(self) -> JsonObject:
        """Serialize the result with an execution outcome, not trade qualification."""

        outcome = (
            "success"
            if self.status == "fresh" and not self.must_not_use_for_decision
            else (
                "partial"
                if self.status == "partial" and not self.must_not_use_for_decision
                else "blocked"
            )
        )
        payload: JsonObject = {
            "status": self.status,
            "outcome": outcome,
            "stock_code": self.stock_code,
            "identity": self.identity.to_payload(),
            "sections": {name: section.to_payload() for name, section in self.sections.items()},
            "decision_readiness": self.decision_readiness,
            "reliability": dict(self.reliability),
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "capabilities": {
                name: capability.to_payload() for name, capability in self.capabilities.items()
            },
        }
        if self.stock_code is not None:
            payload["missing_optional_sections"] = list(self.missing_optional_sections)
        return payload


class EquityResearchSnapshotUseCase:
    """Compose published equity evidence while preserving fail-closed semantics."""

    def __init__(self, reader: EquityResearchSnapshotReader) -> None:
        self._reader = reader

    def execute(self, request: EquityResearchSnapshotRequest) -> EquityResearchSnapshotResult:
        """Resolve an equity and compose its bounded evidence sections."""

        decision_readiness = _safe_read(self._reader.get_decision_readiness)
        identity = _read_section(
            lambda: self._reader.resolve_asset(request.stock_code),
            required=True,
        )
        identity_data = identity.data
        canonical_code = (
            str(identity_data.get("code"))
            if isinstance(identity_data, Mapping) and identity_data.get("code")
            else None
        )
        if canonical_code is None:
            return EquityResearchSnapshotResult(
                status="missing",
                stock_code=None,
                identity=identity,
                sections={},
                decision_readiness=decision_readiness,
                missing_optional_sections=(),
                reliability={
                    "status": "missing",
                    "source": "agomtradepro_api",
                    "must_not_use_for_decision": True,
                    "block_reason_code": "equity_identity_unresolved",
                    "block_reason": "无法从证券主数据唯一解析该名称或代码。",
                },
                must_not_use_for_decision=True,
                capabilities=_blocked_capabilities("equity_identity_unresolved"),
            )

        sections = {
            "latest_quote": _read_section(
                lambda: self._reader.get_latest_quotes(canonical_code, strict_freshness=True),
                required=True,
            ),
            "price_history": _read_section(
                lambda: self._reader.get_price_history(canonical_code, limit=request.history_limit),
                required=True,
            ),
            "valuation": _read_section(
                lambda: self._reader.get_valuations(canonical_code, limit=request.valuation_limit),
                required=True,
            ),
            "financials": _read_section(
                lambda: self._reader.get_financials(canonical_code, limit=request.financial_limit),
                required=True,
            ),
            "news": _read_section(
                lambda: self._reader.get_news(canonical_code, limit=request.news_limit),
                required=False,
            ),
            "capital_flows": _read_section(
                lambda: self._reader.get_capital_flows(
                    canonical_code, limit=request.capital_flow_limit
                ),
                required=False,
            ),
        }
        blocked_sections = tuple(
            name
            for name, section in sections.items()
            if section.required and section.must_not_use_for_decision
        )
        global_blocked = _mapping_bool(decision_readiness, "must_not_use_for_decision", True)
        identity_blocked = _identity_blocked(identity)
        must_not_use = global_blocked or identity_blocked or bool(blocked_sections)
        optional_missing = tuple(
            name
            for name, section in sections.items()
            if not section.required and section.status != "fresh"
        )
        has_partial_sections = any(section.status == "partial" for section in sections.values())
        status = (
            "blocked"
            if must_not_use
            else ("partial" if optional_missing or has_partial_sections else "fresh")
        )
        block_reason_code = ""
        block_reason = ""
        if global_blocked:
            block_reason_code = "decision_readiness_blocked"
            block_reason = "系统严格决策就绪度未通过。"
        elif identity_blocked:
            block_reason_code = identity.block_reason_code or "equity_identity_blocked"
            block_reason = "证券身份分区未通过可靠性校验。"
        elif blocked_sections:
            block_reason_code = "equity_core_evidence_incomplete"
            block_reason = f"缺少核心证据分区: {', '.join(blocked_sections)}"

        return EquityResearchSnapshotResult(
            status=status,
            stock_code=canonical_code,
            identity=identity,
            sections=sections,
            decision_readiness=decision_readiness,
            missing_optional_sections=optional_missing,
            reliability={
                "status": status,
                "source": "agomtradepro_api",
                "must_not_use_for_decision": must_not_use,
                "block_reason_code": block_reason_code,
                "block_reason": block_reason,
            },
            must_not_use_for_decision=must_not_use,
            capabilities=_build_capabilities(
                canonical_code,
                identity=identity,
                sections=sections,
                decision_readiness=decision_readiness,
            ),
        )


def _safe_read(loader: Callable[[], ReadPayload]) -> JsonValue:
    try:
        return _to_json(loader())
    except Exception:
        return {"status": "blocked", "must_not_use_for_decision": True}


def _read_section(loader: Callable[[], ReadPayload], *, required: bool) -> EquityResearchSection:
    try:
        raw_payload = loader()
    except Exception:
        return EquityResearchSection(
            status="failed",
            required=required,
            data=None,
            must_not_use_for_decision=required,
            block_reason_code="upstream_read_failed",
        )
    block_reason = _payload_block_reason(raw_payload)
    gate_blocked = block_reason is not None
    has_evidence = not gate_blocked and _payload_has_evidence(raw_payload)
    publication_outcome = (
        raw_payload.get("publication_outcome") if isinstance(raw_payload, Mapping) else None
    )
    if gate_blocked:
        status = "blocked"
    elif has_evidence and isinstance(publication_outcome, str) and publication_outcome == "partial":
        status = "partial"
    elif has_evidence:
        status = "fresh"
    else:
        status = "missing"
    return EquityResearchSection(
        status=status,
        required=required,
        data=_to_json(raw_payload),
        must_not_use_for_decision=gate_blocked or (required and not has_evidence),
        block_reason_code=block_reason or ("" if has_evidence else "section_evidence_missing"),
    )


def _payload_has_evidence(payload: ReadPayload) -> bool:
    if isinstance(payload, list):
        return bool(payload)
    if not isinstance(payload, Mapping):
        return False
    for key in (
        "rows",
        "results",
        "data",
        "bars",
        "financials",
        "valuations",
        "news",
        "flows",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return bool(value)
    return any(
        value not in (None, "", [], {})
        for key, value in payload.items()
        if key not in {"status", "success", "detail", "error", "message"}
    )


def _payload_block_reason(payload: ReadPayload) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    candidates: list[Mapping[str, object]] = [payload]
    for key in ("contract", "publication", "reliability"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    for candidate in candidates:
        if (
            "must_not_use_for_decision" in candidate
            and candidate["must_not_use_for_decision"] is not False
        ):
            return str(
                candidate.get("blocked_reason")
                or candidate.get("block_reason_code")
                or candidate.get("block_reason")
                or "decision_reliability_blocked"
            )
    for candidate in candidates:
        freshness = str(candidate.get("freshness_status") or "").strip().lower()
        if freshness in _UNUSABLE_CURRENT_DATA_STATUSES:
            return str(
                candidate.get("blocked_reason")
                or candidate.get("block_reason_code")
                or candidate.get("block_reason")
                or f"section_freshness_{freshness}"
            )
        status = str(candidate.get("status") or "").strip().lower()
        if status in _UNUSABLE_CURRENT_DATA_STATUSES:
            return str(
                candidate.get("blocked_reason")
                or candidate.get("block_reason_code")
                or candidate.get("block_reason")
                or f"section_status_{status}"
            )
    return None


def _mapping_bool(payload: JsonValue, key: str, default: bool) -> bool:
    if not isinstance(payload, Mapping):
        return default
    value = payload.get(key, default)
    return value if isinstance(value, bool) else default


def _blocked_capabilities(reason_code: str) -> Mapping[str, EquityResearchCapability]:
    """Block asset-specific capability claims when the security identity is unresolved."""

    return {
        "market_research": EquityResearchCapability(
            status="blocked",
            reason_codes=(reason_code,),
            evidence_sections=("latest_quote", "price_history"),
        ),
        "technical_scoring": EquityResearchCapability(
            status="blocked",
            reason_codes=(reason_code,),
            evidence_sections=("price_history",),
        ),
        "financial_valuation": EquityResearchCapability(
            status="blocked",
            reason_codes=(reason_code,),
            evidence_sections=("price_history", "valuation", "financials"),
        ),
        "plan_calculation": EquityResearchCapability(
            status="not_evaluated",
            reason_codes=("account_context_required",),
            evidence_sections=(),
        ),
        "order_submission": EquityResearchCapability(
            status="not_evaluated",
            reason_codes=("account_context_required",),
            evidence_sections=(),
        ),
    }


def _build_capabilities(
    stock_code: str,
    *,
    identity: EquityResearchSection,
    sections: Mapping[str, EquityResearchSection],
    decision_readiness: JsonValue,
) -> Mapping[str, EquityResearchCapability]:
    """Report bounded use-specific evidence without qualifying analysis or trading."""

    market_reason_codes: tuple[str, ...] = ()
    if _mapping_bool(decision_readiness, "must_not_use_for_decision", True):
        market_reason_codes = ("decision_readiness_blocked",)
    elif _identity_blocked(identity):
        market_reason_codes = (identity.block_reason_code or "equity_identity_blocked",)
    else:
        other_required_blockers = _market_research_other_blockers(sections)
        if other_required_blockers:
            market_reason_codes = other_required_blockers
        else:
            quote_reason = _published_quote_evidence_reason(sections["latest_quote"], stock_code)
            history_reason = _published_history_evidence_reason(
                sections["price_history"], stock_code
            )
            market_reason_codes = tuple(
                reason for reason in (quote_reason, history_reason) if reason is not None
            )

    market_research = (
        EquityResearchCapability(
            status="blocked",
            reason_codes=market_reason_codes,
            evidence_sections=("latest_quote", "price_history"),
        )
        if market_reason_codes
        else EquityResearchCapability(
            status="observation_only",
            reason_codes=("published_market_evidence_observed",),
            evidence_sections=("latest_quote", "price_history"),
        )
    )
    technical_scoring = _analysis_capability(
        sections,
        evidence_sections=("price_history",),
        not_evaluated_reason="technical_score_not_evaluated",
    )
    financial_valuation = _analysis_capability(
        sections,
        evidence_sections=("price_history", "valuation", "financials"),
        not_evaluated_reason="valuation_calculation_not_evaluated",
    )
    return {
        "market_research": market_research,
        "technical_scoring": technical_scoring,
        "financial_valuation": financial_valuation,
        "plan_calculation": EquityResearchCapability(
            status="not_evaluated",
            reason_codes=("account_context_required",),
            evidence_sections=(),
        ),
        "order_submission": EquityResearchCapability(
            status="not_evaluated",
            reason_codes=("account_context_required",),
            evidence_sections=(),
        ),
    }


def _identity_blocked(section: EquityResearchSection) -> bool:
    """Require a clean resolved identity before describing an asset capability."""

    return (
        section.status != "fresh"
        or section.must_not_use_for_decision
        or bool(section.block_reason_code)
    )


def _market_research_other_blockers(
    sections: Mapping[str, EquityResearchSection],
) -> tuple[str, ...]:
    """Preserve hard blockers outside the two market observation sections."""

    reason_codes: list[str] = []
    for section_name in ("valuation", "financials"):
        section = sections[section_name]
        if (
            section.status == "missing"
            and section.must_not_use_for_decision
            and section.block_reason_code == "section_evidence_missing"
        ):
            continue
        if (
            section.status in {"fresh", "partial"}
            and not section.must_not_use_for_decision
            and not section.block_reason_code
        ):
            continue
        reason_codes.append(section.block_reason_code or "required_section_blocked")
    return tuple(dict.fromkeys(reason_codes))


def _analysis_capability(
    sections: Mapping[str, EquityResearchSection],
    *,
    evidence_sections: tuple[str, ...],
    not_evaluated_reason: str,
) -> EquityResearchCapability:
    """Block known input failures without inferring algorithm availability from data."""

    blocking_reasons: list[str] = []
    for section_name in evidence_sections:
        section = sections.get(section_name)
        if section is None:
            blocking_reasons.append(f"{section_name}_section_unavailable")
        elif (
            section.must_not_use_for_decision
            or section.status not in {"fresh", "partial"}
            or bool(section.block_reason_code)
        ):
            blocking_reasons.append(section.block_reason_code or "evidence_section_blocked")
    if blocking_reasons:
        return EquityResearchCapability(
            status="blocked",
            reason_codes=tuple(dict.fromkeys(blocking_reasons)),
            evidence_sections=evidence_sections,
        )
    return EquityResearchCapability(
        status="not_evaluated",
        reason_codes=(not_evaluated_reason,),
        evidence_sections=evidence_sections,
    )


def _published_quote_evidence_reason(
    section: EquityResearchSection,
    stock_code: str,
) -> str | None:
    """Require the explicit publication gate, identity, and a positive current quote."""

    payload = section.data
    if section.block_reason_code == "section_evidence_missing":
        return section.block_reason_code
    if not isinstance(payload, Mapping):
        return section.block_reason_code or "market_publication_gate_unverified"
    gate = payload.get("must_not_use_for_decision")
    if gate is not False:
        if gate is True and section.must_not_use_for_decision:
            return section.block_reason_code or "decision_reliability_blocked"
        return "market_publication_gate_unverified"
    if section.must_not_use_for_decision:
        return section.block_reason_code or "latest_quote_section_blocked"
    if not _has_publication_id(payload):
        return "market_publication_id_missing"
    if not _asset_code_matches(payload.get("asset_code"), stock_code):
        return "market_asset_identity_mismatch"
    if not _is_aware_timestamp(payload.get("snapshot_at")):
        return "market_quote_snapshot_time_unverified"
    if not _is_positive_finite_price(payload.get("current_price")):
        return "market_quote_price_missing"
    return None


def _published_history_evidence_reason(
    section: EquityResearchSection,
    stock_code: str,
) -> str | None:
    """Require the explicit publication gate and at least one valid bar for this asset."""

    payload = section.data
    if section.block_reason_code == "section_evidence_missing":
        return section.block_reason_code
    if not isinstance(payload, Mapping):
        return section.block_reason_code or "market_publication_gate_unverified"
    gate = payload.get("must_not_use_for_decision")
    if gate is not False:
        if gate is True and section.must_not_use_for_decision:
            return section.block_reason_code or "decision_reliability_blocked"
        return "market_publication_gate_unverified"
    if section.must_not_use_for_decision:
        return section.block_reason_code or "price_history_section_blocked"
    if not _has_publication_id(payload):
        return "market_publication_id_missing"
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return "market_price_history_missing"
    for row in rows:
        if not isinstance(row, Mapping):
            return "market_price_history_row_unverified"
        if not _asset_code_matches(row.get("asset_code"), stock_code):
            return "market_asset_identity_mismatch"
        if "must_not_use_for_decision" in row and row.get("must_not_use_for_decision") is not False:
            return "market_price_history_row_blocked"
        if not _is_iso_date(row.get("timestamp")):
            return "market_price_history_missing"
        if not _is_positive_finite_price(row.get("close")):
            return "market_price_history_missing"
    return None


def _has_publication_id(payload: Mapping[str, object]) -> bool:
    publication_id = payload.get("publication_id")
    return isinstance(publication_id, str) and bool(publication_id.strip())


def _asset_code_matches(value: object, stock_code: str) -> bool:
    return isinstance(value, str) and value == stock_code


def _is_aware_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        observed_at = datetime.fromisoformat(value)
    except ValueError:
        return False
    return observed_at.utcoffset() is not None


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_positive_finite_price(value: object) -> bool:
    if isinstance(value, bool):
        return False
    price = safe_float(value)
    return price is not None and price > 0


def _to_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return str(value)


__all__ = [
    "EquityResearchCapability",
    "EquityResearchSection",
    "EquityResearchSnapshotReader",
    "EquityResearchSnapshotRequest",
    "EquityResearchSnapshotResult",
    "EquityResearchSnapshotUseCase",
]
