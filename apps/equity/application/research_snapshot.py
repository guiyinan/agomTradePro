"""Fail-closed equity research snapshot application contract and use case."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeAlias

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

    def to_payload(self) -> JsonObject:
        """Serialize the typed result using the legacy MCP-compatible shape."""

        payload: JsonObject = {
            "status": self.status,
            "stock_code": self.stock_code,
            "identity": self.identity.to_payload(),
            "sections": {name: section.to_payload() for name, section in self.sections.items()},
            "decision_readiness": self.decision_readiness,
            "reliability": dict(self.reliability),
            "must_not_use_for_decision": self.must_not_use_for_decision,
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
        must_not_use = global_blocked or bool(blocked_sections)
        optional_missing = tuple(
            name
            for name, section in sections.items()
            if not section.required and section.status != "fresh"
        )
        status = "blocked" if must_not_use else ("partial" if optional_missing else "fresh")
        block_reason_code = ""
        block_reason = ""
        if global_blocked:
            block_reason_code = "decision_readiness_blocked"
            block_reason = "系统严格决策就绪度未通过。"
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
    return EquityResearchSection(
        status="blocked" if gate_blocked else ("fresh" if has_evidence else "missing"),
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
        if bool(candidate.get("must_not_use_for_decision")):
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
    return bool(payload.get(key, default))


def _to_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return str(value)


__all__ = [
    "EquityResearchSection",
    "EquityResearchSnapshotReader",
    "EquityResearchSnapshotRequest",
    "EquityResearchSnapshotResult",
    "EquityResearchSnapshotUseCase",
]
