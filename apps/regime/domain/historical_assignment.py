"""Canonical Regime-owned historical assignment evidence for R3 OOS research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


def _token(value: object, name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be an exact bounded token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value.lower()


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _decimal(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RegimeAssignmentFactRole(StrEnum):
    """Canonical source roles required for every historical assignment."""

    ACTUAL = "actual"
    GROWTH = "growth"
    INFLATION = "inflation"


@dataclass(frozen=True, slots=True)
class RegimeAssignmentCell:
    """One exhaustive growth/inflation sign cell in a versioned policy."""

    growth_above_threshold: bool
    inflation_above_threshold: bool
    regime_code: str

    def __post_init__(self) -> None:
        if (
            type(self.growth_above_threshold) is not bool
            or type(self.inflation_above_threshold) is not bool
        ):
            raise ValueError("Regime assignment cell flags must be exact booleans")
        _token(self.regime_code, "RegimeAssignmentCell.regime_code")

    @property
    def content_hash(self) -> str:
        """Return the canonical cell seal."""

        return _hash(
            {
                "schema": "regime-assignment-cell.v1",
                "growth_above_threshold": self.growth_above_threshold,
                "inflation_above_threshold": self.inflation_above_threshold,
                "regime_code": self.regime_code,
            }
        )


@dataclass(frozen=True, slots=True)
class RegimeAssignmentPolicy:
    """Versioned assignment policy with an external source-contract seal."""

    policy_id: str
    policy_version: str
    source_contract_id: str
    source_contract_version: str
    source_contract_hash: str
    growth_threshold: Decimal
    inflation_threshold: Decimal
    cells: tuple[RegimeAssignmentCell, ...]

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        source_contract_id: str,
        source_contract_version: str,
        source_contract_hash: str,
        growth_threshold: Decimal,
        inflation_threshold: Decimal,
        cells: tuple[RegimeAssignmentCell, ...],
    ) -> RegimeAssignmentPolicy:
        """Create and validate a complete four-cell assignment policy."""

        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            source_contract_id=source_contract_id,
            source_contract_version=source_contract_version,
            source_contract_hash=source_contract_hash.lower(),
            growth_threshold=growth_threshold,
            inflation_threshold=inflation_threshold,
            cells=cells,
        )

    def __post_init__(self) -> None:
        for value, name in (
            (self.policy_id, "policy_id"),
            (self.policy_version, "policy_version"),
            (self.source_contract_id, "source_contract_id"),
            (self.source_contract_version, "source_contract_version"),
        ):
            _token(value, f"RegimeAssignmentPolicy.{name}")
        _digest(self.source_contract_hash, "RegimeAssignmentPolicy.source_contract_hash")
        _decimal(self.growth_threshold, "RegimeAssignmentPolicy.growth_threshold")
        _decimal(self.inflation_threshold, "RegimeAssignmentPolicy.inflation_threshold")
        if type(self.cells) is not tuple or any(
            type(item) is not RegimeAssignmentCell for item in self.cells
        ):
            raise ValueError("Regime assignment policy cells must be exact")
        for item in self.cells:
            RegimeAssignmentCell.__post_init__(item)
        keys = tuple(
            (item.growth_above_threshold, item.inflation_above_threshold) for item in self.cells
        )
        expected = ((False, False), (False, True), (True, False), (True, True))
        if keys != expected or len({item.regime_code for item in self.cells}) != 4:
            raise ValueError("Regime assignment policy must define four ordered unique cells")

    @property
    def content_hash(self) -> str:
        """Return the complete policy and source-contract seal."""

        return _hash(
            {
                "schema": "regime-historical-assignment-policy.v1",
                "identity": [self.policy_id, self.policy_version],
                "source_contract": [
                    self.source_contract_id,
                    self.source_contract_version,
                    self.source_contract_hash.lower(),
                ],
                "thresholds": [
                    _decimal_text(self.growth_threshold),
                    _decimal_text(self.inflation_threshold),
                ],
                "cells": [item.content_hash for item in self.cells],
            }
        )

    def assign(self, *, growth: Decimal, inflation: Decimal) -> str:
        """Derive one regime code from exact source values."""

        growth_high = _decimal(growth, "growth") >= self.growth_threshold
        inflation_high = _decimal(inflation, "inflation") >= self.inflation_threshold
        for item in self.cells:
            if (
                item.growth_above_threshold is growth_high
                and item.inflation_above_threshold is inflation_high
            ):
                return item.regime_code
        raise ValueError("Regime assignment policy is incomplete")

    def validated_copy(self) -> RegimeAssignmentPolicy:
        """Return a fresh exact-type copy after live validation."""

        return RegimeAssignmentPolicy.create(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            source_contract_id=self.source_contract_id,
            source_contract_version=self.source_contract_version,
            source_contract_hash=self.source_contract_hash,
            growth_threshold=self.growth_threshold,
            inflation_threshold=self.inflation_threshold,
            cells=tuple(
                RegimeAssignmentCell(
                    item.growth_above_threshold,
                    item.inflation_above_threshold,
                    item.regime_code,
                )
                for item in self.cells
            ),
        )


@dataclass(frozen=True, slots=True)
class RegimeAssignmentSourceRule:
    """Exact Data Center PIT fact identity rule for one row and role."""

    role: RegimeAssignmentFactRole
    dataset_key: str
    business_key: str
    expected_unit: str

    def __post_init__(self) -> None:
        if type(self.role) is not RegimeAssignmentFactRole:
            raise ValueError("Regime assignment source role is invalid")
        for value, name in (
            (self.dataset_key, "dataset_key"),
            (self.business_key, "business_key"),
            (self.expected_unit, "expected_unit"),
        ):
            _token(value, f"RegimeAssignmentSourceRule.{name}", maximum=255)

    @property
    def content_hash(self) -> str:
        """Return the exact source rule seal."""

        return _hash(
            {
                "schema": "regime-assignment-source-rule.v1",
                "role": self.role.value,
                "dataset_key": self.dataset_key,
                "business_key": self.business_key,
                "expected_unit": self.expected_unit,
            }
        )


@dataclass(frozen=True, slots=True)
class RegimeAssignmentExpectedRow:
    """One preregistered OOS row and its complete canonical fact rules."""

    fold_id: str
    row_id: str
    observation_at: datetime
    source_rules: tuple[RegimeAssignmentSourceRule, ...]

    def __post_init__(self) -> None:
        _token(self.fold_id, "RegimeAssignmentExpectedRow.fold_id")
        _token(self.row_id, "RegimeAssignmentExpectedRow.row_id")
        _aware(self.observation_at, "RegimeAssignmentExpectedRow.observation_at")
        if type(self.source_rules) is not tuple or any(
            type(item) is not RegimeAssignmentSourceRule for item in self.source_rules
        ):
            raise ValueError("Regime assignment source rules must be exact")
        for item in self.source_rules:
            RegimeAssignmentSourceRule.__post_init__(item)
        roles = tuple(item.role for item in self.source_rules)
        if roles != tuple(RegimeAssignmentFactRole):
            raise ValueError("Regime assignment row must define all ordered source roles")
        identities = tuple((item.dataset_key, item.business_key) for item in self.source_rules)
        if len(set(identities)) != len(identities):
            raise ValueError("Regime assignment row source identities must be unique")

    @property
    def content_hash(self) -> str:
        """Return the complete row-rule seal."""

        return _hash(
            {
                "schema": "regime-assignment-expected-row.v1",
                "identity": [self.fold_id, self.row_id],
                "observation_at": _utc_text(self.observation_at),
                "source_rules": [item.content_hash for item in self.source_rules],
            }
        )


@dataclass(frozen=True, slots=True)
class HistoricalRegimeAssignmentDefinition:
    """Regime-owner definition binding policy, artifact, PIT manifest, and OOS rows."""

    definition_id: str
    definition_version: str
    artifact_id: str
    artifact_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    policy: RegimeAssignmentPolicy
    rows: tuple[RegimeAssignmentExpectedRow, ...]
    registered_at: datetime
    valid_until: datetime
    owner: str = "regime"
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        definition_id: str,
        definition_version: str,
        artifact_id: str,
        artifact_hash: str,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        policy: RegimeAssignmentPolicy,
        rows: tuple[RegimeAssignmentExpectedRow, ...],
        registered_at: datetime,
        valid_until: datetime,
    ) -> HistoricalRegimeAssignmentDefinition:
        """Create a complete immutable owner definition."""

        return cls(
            definition_id=definition_id,
            definition_version=definition_version,
            artifact_id=artifact_id.lower(),
            artifact_hash=artifact_hash.lower(),
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash.lower(),
            policy=policy,
            rows=rows,
            registered_at=registered_at,
            valid_until=valid_until,
        )

    def __post_init__(self) -> None:
        if self.owner != "regime":
            raise ValueError("Historical assignment definition owner must be Regime")
        for value, name in (
            (self.definition_id, "definition_id"),
            (self.definition_version, "definition_version"),
            (self.pit_manifest_id, "pit_manifest_id"),
        ):
            _token(value, f"HistoricalRegimeAssignmentDefinition.{name}")
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
        ):
            _digest(value, f"HistoricalRegimeAssignmentDefinition.{name}")
        if type(self.policy) is not RegimeAssignmentPolicy:
            raise ValueError("Historical assignment policy type differs")
        RegimeAssignmentPolicy.__post_init__(self.policy)
        if (
            type(self.rows) is not tuple
            or not self.rows
            or any(type(item) is not RegimeAssignmentExpectedRow for item in self.rows)
        ):
            raise ValueError("Historical assignment rows must be exact and non-empty")
        for item in self.rows:
            RegimeAssignmentExpectedRow.__post_init__(item)
        keys = tuple((item.fold_id, item.row_id) for item in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Historical assignment rows must be ordered and unique")
        source_keys = tuple(
            (rule.dataset_key, rule.business_key) for row in self.rows for rule in row.source_rules
        )
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("Historical assignment source facts must be globally unique")
        _aware(self.registered_at, "HistoricalRegimeAssignmentDefinition.registered_at")
        _aware(self.valid_until, "HistoricalRegimeAssignmentDefinition.valid_until")
        if not self.registered_at < self.valid_until:
            raise ValueError("Historical assignment definition validity window is invalid")
        if self.registered_at > min(item.observation_at for item in self.rows):
            raise ValueError("Historical assignment definition must precede OOS observations")
        if not all(
            (
                self.research_only,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("Historical assignment definition must remain research-only")

    @property
    def content_hash(self) -> str:
        """Return the complete definition seal."""

        return _hash(
            {
                "schema": "regime-historical-assignment-definition.v1",
                "authority": [self.owner, self.definition_id, self.definition_version],
                "artifact": [self.artifact_id, self.artifact_hash],
                "pit_manifest": [self.pit_manifest_id, self.pit_manifest_hash],
                "policy": [self.policy.policy_version, self.policy.content_hash],
                "rows": [item.content_hash for item in self.rows],
                "window": [_utc_text(self.registered_at), _utc_text(self.valid_until)],
                "research_only": True,
                "must_not_publish_current": True,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this owner definition is active at one PIT cutoff."""

        _aware(as_of, "HistoricalRegimeAssignmentDefinition.as_of")
        return self.registered_at <= as_of < self.valid_until

    def validated_copy(self) -> HistoricalRegimeAssignmentDefinition:
        """Return a fresh exact-type copy after live validation."""

        return HistoricalRegimeAssignmentDefinition.create(
            definition_id=self.definition_id,
            definition_version=self.definition_version,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            policy=self.policy.validated_copy(),
            rows=tuple(
                RegimeAssignmentExpectedRow(
                    fold_id=row.fold_id,
                    row_id=row.row_id,
                    observation_at=row.observation_at,
                    source_rules=tuple(
                        RegimeAssignmentSourceRule(
                            role=rule.role,
                            dataset_key=rule.dataset_key,
                            business_key=rule.business_key,
                            expected_unit=rule.expected_unit,
                        )
                        for rule in row.source_rules
                    ),
                )
                for row in self.rows
            ),
            registered_at=self.registered_at,
            valid_until=self.valid_until,
        )


@dataclass(frozen=True, slots=True)
class PersistedHistoricalRegimeAssignmentDefinition:
    """Regime ledger receipt for an owner-authored definition."""

    definition: HistoricalRegimeAssignmentDefinition
    ledger_recorded_at: datetime

    @classmethod
    def create(
        cls,
        *,
        definition: HistoricalRegimeAssignmentDefinition,
        ledger_recorded_at: datetime,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Create one persisted definition receipt."""

        return cls(definition=definition.validated_copy(), ledger_recorded_at=ledger_recorded_at)

    def __post_init__(self) -> None:
        if type(self.definition) is not HistoricalRegimeAssignmentDefinition:
            raise ValueError("Persisted historical definition type differs")
        HistoricalRegimeAssignmentDefinition.__post_init__(self.definition)
        _aware(self.ledger_recorded_at, "PersistedHistoricalDefinition.ledger_recorded_at")
        if (
            not self.definition.registered_at
            <= self.ledger_recorded_at
            < self.definition.valid_until
        ):
            raise ValueError("Persisted historical definition clock is invalid")

    @property
    def content_hash(self) -> str:
        """Return the persisted definition receipt seal."""

        return _hash(
            {
                "schema": "regime-historical-assignment-definition-receipt.v1",
                "definition_hash": self.definition.content_hash,
                "ledger_recorded_at": _utc_text(self.ledger_recorded_at),
            }
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the receipt was known and definition active at cutoff."""

        _aware(as_of, "PersistedHistoricalDefinition.as_of")
        return self.ledger_recorded_at <= as_of and self.definition.is_active_at(as_of)

    def validated_copy(self) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Return a fresh exact-type copy after live validation."""

        return PersistedHistoricalRegimeAssignmentDefinition.create(
            definition=self.definition,
            ledger_recorded_at=self.ledger_recorded_at,
        )


@dataclass(frozen=True, slots=True)
class RegimeOOSPrediction:
    """One exact OOS prediction projected from a Macro Factor artifact."""

    fold_id: str
    row_id: str
    predicted_value: Decimal

    def __post_init__(self) -> None:
        _token(self.fold_id, "RegimeOOSPrediction.fold_id")
        _token(self.row_id, "RegimeOOSPrediction.row_id")
        _decimal(self.predicted_value, "RegimeOOSPrediction.predicted_value")


@dataclass(frozen=True, slots=True)
class RegimeArtifactOOSProjection:
    """Narrow exact Macro Factor artifact projection consumed by Regime."""

    artifact_id: str
    artifact_hash: str
    source_result_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    predictions: tuple[RegimeOOSPrediction, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.source_result_hash, "source_result_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
        ):
            _digest(value, f"RegimeArtifactOOSProjection.{name}")
        _token(self.pit_manifest_id, "RegimeArtifactOOSProjection.pit_manifest_id")
        if (
            type(self.predictions) is not tuple
            or not self.predictions
            or any(type(item) is not RegimeOOSPrediction for item in self.predictions)
        ):
            raise ValueError("Regime artifact predictions must be exact and non-empty")
        for item in self.predictions:
            RegimeOOSPrediction.__post_init__(item)
        keys = tuple((item.fold_id, item.row_id) for item in self.predictions)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Regime artifact predictions must be ordered and unique")

    @property
    def content_hash(self) -> str:
        """Return the narrow artifact projection seal."""

        return _hash(
            {
                "schema": "macro-factor-regime-oos-projection.v1",
                "artifact": [self.artifact_id, self.artifact_hash, self.source_result_hash],
                "pit_manifest": [self.pit_manifest_id, self.pit_manifest_hash],
                "predictions": [
                    [item.fold_id, item.row_id, _decimal_text(item.predicted_value)]
                    for item in self.predictions
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class CanonicalRegimeSourceFact:
    """One immutable Data Center PIT fact selected for historical assignment."""

    role: RegimeAssignmentFactRole
    dataset_key: str
    business_key: str
    fact_id: str
    fact_version: str
    content_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    effective_at: datetime
    available_at: datetime
    owner_recorded_at: datetime
    value: Decimal
    unit: str
    verified: bool

    def __post_init__(self) -> None:
        if type(self.role) is not RegimeAssignmentFactRole:
            raise ValueError("Canonical Regime source fact role is invalid")
        for value, name in (
            (self.dataset_key, "dataset_key"),
            (self.business_key, "business_key"),
            (self.fact_id, "fact_id"),
            (self.fact_version, "fact_version"),
            (self.pit_manifest_id, "pit_manifest_id"),
            (self.unit, "unit"),
        ):
            _token(value, f"CanonicalRegimeSourceFact.{name}", maximum=255)
        _digest(self.content_hash, "CanonicalRegimeSourceFact.content_hash")
        _digest(self.pit_manifest_hash, "CanonicalRegimeSourceFact.pit_manifest_hash")
        for clock_value, name in (
            (self.effective_at, "effective_at"),
            (self.available_at, "available_at"),
            (self.owner_recorded_at, "owner_recorded_at"),
        ):
            _aware(clock_value, f"CanonicalRegimeSourceFact.{name}")
        if not self.effective_at <= self.available_at <= self.owner_recorded_at:
            raise ValueError("Canonical Regime source fact clocks are invalid")
        _decimal(self.value, "CanonicalRegimeSourceFact.value")
        if type(self.verified) is not bool or not self.verified:
            raise ValueError("Canonical Regime source fact must be verified")

    @property
    def evidence_hash(self) -> str:
        """Return the full source fact and knowledge-clock seal."""

        return _hash(
            {
                "schema": "data-center-regime-source-fact.v1",
                "role": self.role.value,
                "identity": [
                    self.dataset_key,
                    self.business_key,
                    self.fact_id,
                    self.fact_version,
                    self.content_hash.lower(),
                ],
                "pit_manifest": [self.pit_manifest_id, self.pit_manifest_hash.lower()],
                "clocks": [
                    _utc_text(self.effective_at),
                    _utc_text(self.available_at),
                    _utc_text(self.owner_recorded_at),
                ],
                "value": [_decimal_text(self.value), self.unit],
                "verified": True,
            }
        )


@dataclass(frozen=True, slots=True)
class HistoricalRegimeAssignment:
    """One derived assignment with exact prediction, actual, and regime fact seals."""

    fold_id: str
    row_id: str
    observation_at: datetime
    predicted_value: Decimal
    actual_value: Decimal
    actual_fact: CanonicalRegimeSourceFact
    growth_fact: CanonicalRegimeSourceFact
    inflation_fact: CanonicalRegimeSourceFact
    regime_code: str
    regime_version: str
    regime_content_hash: str

    def __post_init__(self) -> None:
        _token(self.fold_id, "HistoricalRegimeAssignment.fold_id")
        _token(self.row_id, "HistoricalRegimeAssignment.row_id")
        _aware(self.observation_at, "HistoricalRegimeAssignment.observation_at")
        _decimal(self.predicted_value, "HistoricalRegimeAssignment.predicted_value")
        _decimal(self.actual_value, "HistoricalRegimeAssignment.actual_value")
        expected_roles = (
            (self.actual_fact, RegimeAssignmentFactRole.ACTUAL),
            (self.growth_fact, RegimeAssignmentFactRole.GROWTH),
            (self.inflation_fact, RegimeAssignmentFactRole.INFLATION),
        )
        for fact, role in expected_roles:
            if type(fact) is not CanonicalRegimeSourceFact or fact.role is not role:
                raise ValueError("Historical assignment fact role differs")
            CanonicalRegimeSourceFact.__post_init__(fact)
        if self.actual_value != self.actual_fact.value:
            raise ValueError("Historical assignment actual differs from canonical fact")
        _token(self.regime_code, "HistoricalRegimeAssignment.regime_code")
        _token(self.regime_version, "HistoricalRegimeAssignment.regime_version")
        _digest(self.regime_content_hash, "HistoricalRegimeAssignment.regime_content_hash")

    @property
    def content_hash(self) -> str:
        """Return the complete derived assignment seal."""

        return _hash(
            {
                "schema": "regime-historical-assignment.v1",
                "prediction": [self.fold_id, self.row_id, _decimal_text(self.predicted_value)],
                "observation_at": _utc_text(self.observation_at),
                "actual": [_decimal_text(self.actual_value), self.actual_fact.evidence_hash],
                "inputs": [self.growth_fact.evidence_hash, self.inflation_fact.evidence_hash],
                "regime": [
                    self.regime_code,
                    self.regime_version,
                    self.regime_content_hash.lower(),
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class HistoricalRegimeAssignmentReceipt:
    """Append-only Regime receipt over exhaustive artifact OOS assignments."""

    receipt_id: str
    receipt_version: str
    definition_id: str
    definition_version: str
    definition_content_hash: str
    artifact_id: str
    artifact_hash: str
    source_result_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    pit_as_of: datetime
    recorded_at: datetime
    assignments: tuple[HistoricalRegimeAssignment, ...]
    owner: str = "regime"
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if self.owner != "regime":
            raise ValueError("Historical assignment receipt owner must be Regime")
        for value, name in (
            (self.receipt_id, "receipt_id"),
            (self.definition_content_hash, "definition_content_hash"),
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.source_result_hash, "source_result_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
        ):
            _digest(value, f"HistoricalRegimeAssignmentReceipt.{name}")
        for value, name in (
            (self.receipt_version, "receipt_version"),
            (self.definition_id, "definition_id"),
            (self.definition_version, "definition_version"),
            (self.pit_manifest_id, "pit_manifest_id"),
        ):
            _token(value, f"HistoricalRegimeAssignmentReceipt.{name}")
        _aware(self.pit_as_of, "HistoricalRegimeAssignmentReceipt.pit_as_of")
        _aware(self.recorded_at, "HistoricalRegimeAssignmentReceipt.recorded_at")
        if self.pit_as_of > self.recorded_at:
            raise ValueError("Historical assignment receipt clock is invalid")
        if (
            type(self.assignments) is not tuple
            or not self.assignments
            or any(type(item) is not HistoricalRegimeAssignment for item in self.assignments)
        ):
            raise ValueError("Historical assignment receipt must be exhaustive")
        for item in self.assignments:
            HistoricalRegimeAssignment.__post_init__(item)
        keys = tuple((item.fold_id, item.row_id) for item in self.assignments)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Historical assignments must be ordered and unique")
        if not all(
            (
                self.research_only,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("Historical assignment receipt must remain research-only")

    @classmethod
    def create(
        cls,
        *,
        definition_record: PersistedHistoricalRegimeAssignmentDefinition,
        artifact: RegimeArtifactOOSProjection,
        facts: tuple[CanonicalRegimeSourceFact, ...],
        pit_as_of: datetime,
        recorded_at: datetime,
    ) -> HistoricalRegimeAssignmentReceipt:
        """Derive exhaustive assignments from exact owner evidence."""

        definition_record = definition_record.validated_copy()
        definition = definition_record.definition
        RegimeArtifactOOSProjection.__post_init__(artifact)
        _aware(pit_as_of, "HistoricalRegimeAssignmentReceipt.create.pit_as_of")
        _aware(recorded_at, "HistoricalRegimeAssignmentReceipt.create.recorded_at")
        if not definition_record.is_active_at(pit_as_of) or pit_as_of > recorded_at:
            raise ValueError("Historical assignment definition or cutoff is inactive")
        if (
            artifact.artifact_id != definition.artifact_id
            or artifact.artifact_hash != definition.artifact_hash
            or artifact.pit_manifest_id != definition.pit_manifest_id
            or artifact.pit_manifest_hash != definition.pit_manifest_hash
        ):
            raise ValueError("Historical assignment artifact differs from definition")
        row_keys = tuple((item.fold_id, item.row_id) for item in definition.rows)
        prediction_by_key = {(item.fold_id, item.row_id): item for item in artifact.predictions}
        if set(prediction_by_key) != set(row_keys):
            raise ValueError("Historical assignment artifact OOS coverage differs")
        if type(facts) is not tuple or any(
            type(item) is not CanonicalRegimeSourceFact for item in facts
        ):
            raise ValueError("Historical assignment source facts must be exact")
        fact_by_identity: dict[tuple[str, str], CanonicalRegimeSourceFact] = {}
        for fact in facts:
            CanonicalRegimeSourceFact.__post_init__(fact)
            identity = (fact.dataset_key, fact.business_key)
            if identity in fact_by_identity:
                raise ValueError("Historical assignment source facts contain a fork")
            if (
                fact.pit_manifest_id != definition.pit_manifest_id
                or fact.pit_manifest_hash != definition.pit_manifest_hash
                or fact.available_at > pit_as_of
                or fact.owner_recorded_at > pit_as_of
            ):
                raise ValueError("Historical assignment source fact is outside PIT scope")
            fact_by_identity[identity] = fact
        expected_fact_count = sum(len(row.source_rules) for row in definition.rows)
        if len(fact_by_identity) != expected_fact_count:
            raise ValueError("Historical assignment source fact coverage is incomplete")
        assignments: list[HistoricalRegimeAssignment] = []
        for row in definition.rows:
            selected: dict[RegimeAssignmentFactRole, CanonicalRegimeSourceFact] = {}
            for rule in row.source_rules:
                selected_fact = fact_by_identity.get((rule.dataset_key, rule.business_key))
                if (
                    selected_fact is None
                    or selected_fact.role is not rule.role
                    or selected_fact.unit != rule.expected_unit
                    or selected_fact.effective_at != row.observation_at
                ):
                    raise ValueError("Historical assignment source fact differs from rule")
                selected[rule.role] = selected_fact
            actual = selected[RegimeAssignmentFactRole.ACTUAL]
            growth = selected[RegimeAssignmentFactRole.GROWTH]
            inflation = selected[RegimeAssignmentFactRole.INFLATION]
            if (
                growth.available_at > row.observation_at
                or inflation.available_at > row.observation_at
            ):
                raise ValueError("Historical assignment inputs contain future knowledge")
            prediction = prediction_by_key[(row.fold_id, row.row_id)]
            assignments.append(
                HistoricalRegimeAssignment(
                    fold_id=row.fold_id,
                    row_id=row.row_id,
                    observation_at=row.observation_at,
                    predicted_value=prediction.predicted_value,
                    actual_value=actual.value,
                    actual_fact=actual,
                    growth_fact=growth,
                    inflation_fact=inflation,
                    regime_code=definition.policy.assign(
                        growth=growth.value,
                        inflation=inflation.value,
                    ),
                    regime_version=definition.policy.policy_version,
                    regime_content_hash=definition.policy.content_hash,
                )
            )
        ordered = tuple(sorted(assignments, key=lambda item: (item.fold_id, item.row_id)))
        receipt_id = _hash(
            {
                "schema": "regime-historical-assignment-receipt-id.v1",
                "definition_hash": definition.content_hash,
                "artifact": [artifact.artifact_id, artifact.artifact_hash],
                "pit_as_of": _utc_text(pit_as_of),
            }
        )
        return cls(
            receipt_id=receipt_id,
            receipt_version="regime-historical-assignment-receipt.v1",
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            definition_content_hash=definition.content_hash,
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.artifact_hash,
            source_result_hash=artifact.source_result_hash,
            pit_manifest_id=artifact.pit_manifest_id,
            pit_manifest_hash=artifact.pit_manifest_hash,
            pit_as_of=pit_as_of,
            recorded_at=recorded_at,
            assignments=ordered,
        )

    @property
    def content_hash(self) -> str:
        """Return the complete receipt and assignment seal."""

        return _hash(
            {
                "schema": "regime-historical-assignment-receipt.v1",
                "identity": [self.receipt_id, self.receipt_version],
                "definition": [
                    self.definition_id,
                    self.definition_version,
                    self.definition_content_hash.lower(),
                ],
                "artifact": [self.artifact_id, self.artifact_hash, self.source_result_hash],
                "pit_manifest": [self.pit_manifest_id, self.pit_manifest_hash],
                "clock": [_utc_text(self.pit_as_of), _utc_text(self.recorded_at)],
                "assignments": [item.content_hash for item in self.assignments],
                "owner": self.owner,
                "research_only": True,
                "must_not_publish_current": True,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )

    def validated_copy(self) -> HistoricalRegimeAssignmentReceipt:
        """Return a fresh strict receipt by reconstructing every nested value."""

        copied = HistoricalRegimeAssignmentReceipt(
            receipt_id=self.receipt_id,
            receipt_version=self.receipt_version,
            definition_id=self.definition_id,
            definition_version=self.definition_version,
            definition_content_hash=self.definition_content_hash,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            source_result_hash=self.source_result_hash,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            pit_as_of=self.pit_as_of,
            recorded_at=self.recorded_at,
            assignments=tuple(
                HistoricalRegimeAssignment(
                    fold_id=item.fold_id,
                    row_id=item.row_id,
                    observation_at=item.observation_at,
                    predicted_value=item.predicted_value,
                    actual_value=item.actual_value,
                    actual_fact=item.actual_fact,
                    growth_fact=item.growth_fact,
                    inflation_fact=item.inflation_fact,
                    regime_code=item.regime_code,
                    regime_version=item.regime_version,
                    regime_content_hash=item.regime_content_hash,
                )
                for item in self.assignments
            ),
        )
        if copied.content_hash != self.content_hash:
            raise ValueError("Historical assignment receipt live seal differs")
        return copied


__all__ = [
    "CanonicalRegimeSourceFact",
    "HistoricalRegimeAssignment",
    "HistoricalRegimeAssignmentDefinition",
    "HistoricalRegimeAssignmentReceipt",
    "PersistedHistoricalRegimeAssignmentDefinition",
    "RegimeArtifactOOSProjection",
    "RegimeAssignmentCell",
    "RegimeAssignmentExpectedRow",
    "RegimeAssignmentFactRole",
    "RegimeAssignmentPolicy",
    "RegimeAssignmentSourceRule",
    "RegimeOOSPrediction",
]
