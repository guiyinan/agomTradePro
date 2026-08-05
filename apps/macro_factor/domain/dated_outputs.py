"""Typed external and persisted dated macro-factor outputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from apps.macro_factor.domain.entities import FactorOutputRole

from ._runner_support import (
    canonical_json,
    decimal_text,
    require_aware,
    require_finite,
    require_positive,
    require_sha256,
    require_token,
    utc_text,
)


@dataclass(frozen=True)
class ExternalDatedFactorOutput:
    """Typed current/forward output returned in the canonical external artifact."""

    output_role: FactorOutputRole
    observation_date: date
    target_period_start: date
    target_period_end: date
    horizon_periods: int
    horizon_unit: str
    knowledge_as_of: datetime
    valid_until: datetime
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.output_role, FactorOutputRole):
            raise ValueError("ExternalDatedFactorOutput.output_role is invalid")
        require_aware(self.knowledge_as_of, "ExternalDatedFactorOutput.knowledge_as_of")
        require_aware(self.valid_until, "ExternalDatedFactorOutput.valid_until")
        require_finite(self.value, "ExternalDatedFactorOutput.value")
        require_token(self.horizon_unit, "ExternalDatedFactorOutput.horizon_unit")
        require_token(self.unit, "ExternalDatedFactorOutput.unit")
        if self.target_period_start > self.target_period_end:
            raise ValueError("dated output target period is invalid")
        if self.observation_date > self.knowledge_as_of.date():
            raise ValueError("dated output observation cannot follow knowledge_as_of")
        if self.valid_until <= self.knowledge_as_of:
            raise ValueError("dated output valid_until must follow knowledge_as_of")
        if self.output_role is FactorOutputRole.CURRENT_STATE:
            if self.horizon_periods != 0:
                raise ValueError("current-state output requires horizon_periods=0")
            if self.target_period_end > self.knowledge_as_of.date():
                raise ValueError("current-state target cannot follow knowledge_as_of")
        else:
            require_positive(self.horizon_periods, "ExternalDatedFactorOutput.horizon_periods")
            if self.target_period_start <= self.knowledge_as_of.date():
                raise ValueError("forward target must follow knowledge_as_of")

    def canonical_payload(self) -> dict[str, object]:
        """Return stable typed output content."""

        return {
            "output_role": self.output_role.value,
            "observation_date": self.observation_date.isoformat(),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "horizon_periods": self.horizon_periods,
            "horizon_unit": self.horizon_unit,
            "knowledge_as_of": utc_text(self.knowledge_as_of),
            "valid_until": utc_text(self.valid_until),
            "value": decimal_text(self.value),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class DatedMacroFactorOutput:
    """Immutable dated output bound to one complete run artifact."""

    output_id: str
    artifact_id: str
    artifact_hash: str
    factor_version: str
    target_code: str
    output_role: FactorOutputRole
    observation_date: date
    target_period_start: date
    target_period_end: date
    horizon_periods: int
    horizon_unit: str
    knowledge_as_of: datetime
    produced_at: datetime
    valid_until: datetime
    value: Decimal
    unit: str
    pit_manifest_id: str
    pit_manifest_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.output_role, FactorOutputRole):
            raise ValueError("DatedMacroFactorOutput.output_role is invalid")
        for token_value, token_name in (
            (self.factor_version, "factor_version"),
            (self.target_code, "target_code"),
            (self.horizon_unit, "horizon_unit"),
            (self.unit, "unit"),
            (self.pit_manifest_id, "pit_manifest_id"),
        ):
            require_token(token_value, f"DatedMacroFactorOutput.{token_name}")
        require_finite(self.value, "DatedMacroFactorOutput.value")
        for digest_value, digest_name in (
            (self.output_id, "output_id"),
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
        ):
            require_sha256(digest_value, f"DatedMacroFactorOutput.{digest_name}")
        for timestamp_value, timestamp_name in (
            (self.knowledge_as_of, "knowledge_as_of"),
            (self.produced_at, "produced_at"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(
                timestamp_value,
                f"DatedMacroFactorOutput.{timestamp_name}",
            )
        if self.knowledge_as_of > self.produced_at:
            raise ValueError("dated output knowledge_as_of cannot follow produced_at")
        if self.valid_until <= self.produced_at:
            raise ValueError("dated output valid_until must follow produced_at")
        if self.target_period_start > self.target_period_end:
            raise ValueError("dated output target period is invalid")
        if self.observation_date > self.knowledge_as_of.date():
            raise ValueError("dated output observation cannot follow knowledge_as_of")
        if self.output_role is FactorOutputRole.CURRENT_STATE:
            if self.horizon_periods != 0:
                raise ValueError("current-state output requires horizon_periods=0")
            if self.target_period_end > self.knowledge_as_of.date():
                raise ValueError("current-state target cannot follow knowledge_as_of")
        else:
            require_positive(self.horizon_periods, "DatedMacroFactorOutput.horizon_periods")
            if self.target_period_start <= self.knowledge_as_of.date():
                raise ValueError("forward target must follow knowledge_as_of")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("macro-factor outputs must remain research-only and blocked")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the immutable ledger payload."""

        return {
            "output_id": self.output_id,
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "factor_version": self.factor_version,
            "target_code": self.target_code,
            "output_role": self.output_role.value,
            "observation_date": self.observation_date.isoformat(),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "horizon_periods": self.horizon_periods,
            "horizon_unit": self.horizon_unit,
            "knowledge_as_of": utc_text(self.knowledge_as_of),
            "produced_at": utc_text(self.produced_at),
            "valid_until": utc_text(self.valid_until),
            "value": decimal_text(self.value),
            "unit": self.unit,
            "pit_manifest_id": self.pit_manifest_id,
            "pit_manifest_hash": self.pit_manifest_hash,
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    @property
    def canonical_json(self) -> str:
        """Return canonical JSON for append-only persistence."""

        return canonical_json(self.canonical_payload)

    @property
    def content_hash(self) -> str:
        """Seal the dated output."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


__all__ = ["DatedMacroFactorOutput", "ExternalDatedFactorOutput"]
