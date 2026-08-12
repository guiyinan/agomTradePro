"""Immutable Research ledger record for one authoritative R3 runner spec."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class PersistedMacroFactorRunnerSpecRecord:
    """One append-only spec plus the server time proving preregistration."""

    spec: MacroFactorRunnerSpec
    ledger_recorded_at: datetime
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    record_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        spec: MacroFactorRunnerSpec,
        ledger_recorded_at: datetime,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Revalidate the complete spec before sealing its ledger knowledge time."""

        return cls(
            spec=spec.validated_copy(),
            ledger_recorded_at=ledger_recorded_at,
        )

    def __post_init__(self) -> None:
        _require_aware(self.ledger_recorded_at, "ledger_recorded_at")
        validated_spec = self.spec.validated_copy()
        if validated_spec != self.spec:
            raise ValueError("runner spec changed during ledger validation")
        if self.spec.registered_at > self.ledger_recorded_at:
            raise ValueError("runner spec cannot be owner-registered in the future")
        first_selection = min(fold.selection_as_of for fold in self.spec.plan.outer_folds)
        if self.ledger_recorded_at >= first_selection:
            raise ValueError("runner spec ledger record must be before nested-CV selection")
        if not all(
            (
                self.research_only,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("runner spec ledger cannot grant publication or execution authority")
        object.__setattr__(self, "record_hash", _hash_payload(self.canonical_header))

    @property
    def canonical_header(self) -> dict[str, object]:
        """Return the exact server-sealed ledger header."""

        return {
            "schema": "research.r3.macro-factor-runner-spec-record.v1",
            "spec_id": self.spec.run_key,
            "spec_version": self.spec.run_version,
            "spec_content_hash": self.spec.content_hash.lower(),
            "spec_registered_at": _utc_text(self.spec.registered_at),
            "ledger_recorded_at": _utc_text(self.ledger_recorded_at),
            "first_selection_at": _utc_text(
                min(fold.selection_as_of for fold in self.spec.plan.outer_folds)
            ),
            "last_evaluation_at": _utc_text(
                max(fold.evaluation_as_of for fold in self.spec.plan.outer_folds)
            ),
            "calculated_at": _utc_text(self.spec.calculated_at),
            "research_only": self.research_only,
            "must_not_publish_current": self.must_not_publish_current,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    def validated_copy(self) -> PersistedMacroFactorRunnerSpecRecord:
        """Rebuild the record and verify its stored seal live."""

        validated = PersistedMacroFactorRunnerSpecRecord(
            spec=self.spec.validated_copy(),
            ledger_recorded_at=self.ledger_recorded_at,
            research_only=self.research_only,
            must_not_publish_current=self.must_not_publish_current,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        if self.record_hash.lower() != validated.record_hash.lower():
            raise ValueError("runner spec ledger record_hash does not match content")
        return validated


__all__ = ["PersistedMacroFactorRunnerSpecRecord"]
