"""Typed use case for exact current-publication execution quote reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS
from apps.data_center.domain.execution_quotes import (
    CURRENT_ACTIVE_CONTRACT_RESOLUTION,
    ExecutionQuoteSnapshot,
)
from apps.data_center.domain.publication_evidence import validate_publication_quality_status
from core.exceptions import DataFetchError, InvalidInputError

EXECUTION_QUOTE_DATASET = "equity.quote.snapshot"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ExecutionQuoteBlockReason(StrEnum):
    """Stable rejection reasons for unavailable execution quote evidence."""

    PUBLICATION_MISSING = "execution_quote_publication_missing"
    PUBLICATION_BLOCKED = "execution_quote_publication_blocked"
    POLICY_MISSING = "execution_quote_policy_missing"
    INVALID_PROVIDER_RESULT = "execution_quote_provider_result_invalid"
    MEMBER_MISSING = "execution_quote_member_missing"
    MEMBER_AMBIGUOUS = "execution_quote_member_ambiguous"
    FACT_MISSING = "execution_quote_fact_missing"
    FACT_CHANGED = "execution_quote_fact_changed"
    SOURCE_UNVERIFIED = "execution_quote_source_unverified"
    SOURCE_EVIDENCE_MISSING = "execution_quote_source_evidence_missing"
    FUTURE_EVIDENCE = "execution_quote_future_evidence"
    STALE = "execution_quote_stale"
    CONTRACT_MISMATCH = "execution_quote_contract_mismatch"


class ExecutionQuoteUnavailable(DataFetchError):
    """Raised when an exact, fresh publication-bound quote cannot be proved."""

    default_message = "No verified fresh publication-bound execution quote is available"
    default_code = "EXECUTION_QUOTE_UNAVAILABLE"

    def __init__(
        self,
        reason: ExecutionQuoteBlockReason,
        *,
        publication_blocked_reason: str = "",
    ) -> None:
        """Create one typed fail-closed result with a stable reason code."""

        self.reason = reason
        self.publication_blocked_reason = publication_blocked_reason
        details = (
            {"publication_blocked_reason": publication_blocked_reason}
            if publication_blocked_reason
            else None
        )
        super().__init__(code=reason.value, details=details)


@dataclass(frozen=True, slots=True)
class ExecutionQuotePublicationGate:
    """Typed projection of the exact execution pointer and its catalog TTL."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_hash: str
    publication_as_of: datetime
    published_at: datetime
    policy_identity: str
    contract_version: str
    schema_version: str
    contract_resolution: str
    execution_freshness_seconds: int | None
    must_not_use_for_decision: bool
    blocked_reason: str
    freshness_status: str

    def validate(self) -> None:
        """Validate the gate projection independently of its adapter."""

        for field_name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_hash",
            "policy_identity",
            "contract_version",
            "schema_version",
            "contract_resolution",
            "blocked_reason",
            "freshness_status",
        ):
            if type(getattr(self, field_name)) is not str:
                raise ValueError(f"ExecutionQuotePublicationGate.{field_name} must be text")
        if not self.publication_id or not self.policy_identity:
            raise ValueError("Execution quote publication identity is incomplete")
        if _SHA256_RE.fullmatch(self.publication_hash) is None:
            raise ValueError("Execution quote publication hash must be lowercase SHA-256")
        if self.publication_as_of.tzinfo is None or self.publication_as_of.utcoffset() is None:
            raise ValueError("Execution quote publication as_of must be timezone-aware")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("Execution quote published_at must be timezone-aware")
        if self.publication_as_of > self.published_at:
            raise ValueError("Execution quote publication as_of follows published_at")
        if type(self.must_not_use_for_decision) is not bool:
            raise ValueError("Execution quote publication gate must be boolean")
        if self.contract_resolution != CURRENT_ACTIVE_CONTRACT_RESOLUTION:
            raise ValueError("Execution quote contract resolution must identify current catalog")
        if self.execution_freshness_seconds is not None and (
            type(self.execution_freshness_seconds) is not int
            or self.execution_freshness_seconds <= 0
            or self.execution_freshness_seconds > MAX_CATALOG_TTL_SECONDS
        ):
            raise ValueError("Execution quote execution TTL must fit a positive 64-bit integer")


class ExecutionQuotePublicationGateReader(Protocol):
    """Read the exact execution publication and active contract freshness gate."""

    def get_current_gate(
        self, asset_code: str, *, as_of: datetime
    ) -> ExecutionQuotePublicationGate | None:
        """Return the execution scope's typed publication gate when present."""


class ExecutionQuoteFactReader(Protocol):
    """Read one exact quote member from its publication-bound fact table."""

    def get_exact_quote(
        self,
        asset_code: str,
        *,
        publication_gate: ExecutionQuotePublicationGate,
        as_of: datetime,
    ) -> ExecutionQuoteSnapshot | None:
        """Return the exact publication-bound quote fact or no matching member."""


class GetExecutionQuoteUseCase:
    """Coordinate the execution pointer and exact persisted quote reader.

    The execution-only DatasetContract freshness budget bounds this quote.
    Contract selection is current-active, so ``as_of`` does not make catalog
    resolution point-in-time and this result does not authorize an order.
    """

    __slots__ = ("_gate_reader", "_quote_reader")

    def __init__(
        self,
        *,
        gate_reader: ExecutionQuotePublicationGateReader,
        quote_reader: ExecutionQuoteFactReader,
    ) -> None:
        """Inject the execution-publication gate and exact quote fact readers."""

        self._gate_reader = gate_reader
        self._quote_reader = quote_reader

    def execute(self, asset_code: str, *, as_of: datetime) -> ExecutionQuoteSnapshot:
        """Return one exact execution quote or fail closed with a stable reason."""

        normalized_asset = _validate_request(asset_code, as_of)
        gate = self._gate_reader.get_current_gate(normalized_asset, as_of=as_of)
        if gate is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.PUBLICATION_MISSING)
        if type(gate) is not ExecutionQuotePublicationGate:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        try:
            gate.validate()
        except (AttributeError, TypeError, ValueError):
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
        if gate.dataset_key != EXECUTION_QUOTE_DATASET or gate.publication_key != "execution":
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.PUBLICATION_BLOCKED)
        if gate.freshness_status == "stale":
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.STALE,
                publication_blocked_reason=gate.blocked_reason,
            )
        if gate.must_not_use_for_decision:
            reason = (
                ExecutionQuoteBlockReason.POLICY_MISSING
                if gate.blocked_reason
                in {"publication_policy_missing", "publication_freshness_policy_missing"}
                else ExecutionQuoteBlockReason.PUBLICATION_BLOCKED
            )
            raise ExecutionQuoteUnavailable(
                reason,
                publication_blocked_reason=gate.blocked_reason,
            )
        if gate.freshness_status != "fresh":
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if gate.execution_freshness_seconds is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.POLICY_MISSING)
        if not gate.contract_version or not gate.schema_version:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if gate.publication_as_of > as_of or gate.published_at > as_of:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FUTURE_EVIDENCE)

        quote = self._quote_reader.get_exact_quote(
            normalized_asset,
            publication_gate=gate,
            as_of=as_of,
        )
        if type(quote) is not ExecutionQuoteSnapshot:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        try:
            quote.validate_structure()
        except (AttributeError, OverflowError, TypeError, ValueError):
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
        if quote.queried_at != as_of:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if any(
            timestamp > as_of
            for timestamp in (
                quote.snapshot_at,
                quote.fetched_at,
                quote.publication_as_of,
                quote.published_at,
            )
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FUTURE_EVIDENCE)
        if as_of >= quote.freshness_deadline:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.STALE)
        try:
            quote.validate()
        except (AttributeError, OverflowError, TypeError, ValueError):
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
        try:
            validate_publication_quality_status(quote.quality_status)
        except ValueError:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_UNVERIFIED) from None

        if quote.asset_code != normalized_asset:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if (
            quote.publication_id != gate.publication_id
            or quote.publication_hash != gate.publication_hash
            or quote.publication_as_of != gate.publication_as_of
            or quote.published_at != gate.published_at
            or quote.policy_identity != gate.policy_identity
            or quote.dataset_key != gate.dataset_key
            or quote.contract_version != gate.contract_version
            or quote.schema_version != gate.schema_version
            or quote.contract_resolution != gate.contract_resolution
            or quote.execution_freshness_seconds != gate.execution_freshness_seconds
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if quote.source.startswith("qmt-bridge:"):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_UNVERIFIED)
        try:
            expected_deadline = quote.snapshot_at + timedelta(
                seconds=gate.execution_freshness_seconds
            )
        except OverflowError:
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
        if quote.freshness_deadline != expected_deadline:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
        if as_of >= expected_deadline:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.STALE)
        return quote


def _validate_request(asset_code: str, as_of: datetime) -> str:
    """Require a canonical asset token and timezone-aware knowledge cutoff."""

    if type(asset_code) is not str or not asset_code.strip():
        raise InvalidInputError("asset_code is required")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise InvalidInputError("as_of must be timezone-aware")
    return asset_code.strip().upper()


__all__ = [
    "EXECUTION_QUOTE_DATASET",
    "ExecutionQuoteBlockReason",
    "ExecutionQuotePublicationGate",
    "ExecutionQuoteUnavailable",
    "GetExecutionQuoteUseCase",
]
