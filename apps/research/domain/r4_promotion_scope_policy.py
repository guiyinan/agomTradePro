"""Stable R4 promotion scope and pre-registered Research policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain.macro_factor_risk import (
    MacroRiskCandidateKind,
)

_ALL_R4_METHODS = tuple(sorted(MacroRiskCandidateKind, key=lambda item: item.value))


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if not value or len(value) > maximum or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    _require_finite(value, "canonical Decimal")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "canonical datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class R4PromotionPolicyStatus(str, Enum):
    """Research-owner policy availability."""

    ACTIVE = "active"


@dataclass(frozen=True)
class R4PromotionScope:
    """Stable semantic scope containing no exact artifact hash or version."""

    scope_id: str
    owner: str
    capability: str
    purpose: str
    study_family_id: str
    target_method: MacroRiskCandidateKind
    universe_policy_id: str
    factor_policy_id: str
    split_policy_id: str
    cost_semantics_id: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_family_id: str,
        universe_policy_id: str,
        factor_policy_id: str,
        split_policy_id: str,
        cost_semantics_id: str,
    ) -> R4PromotionScope:
        """Create one canonical Research-owned R4 semantic stream scope."""

        digest = _hash_payload(
            _scope_payload(
                owner="research",
                capability="r4",
                purpose="macro_risk_method_research",
                study_family_id=study_family_id,
                target_method=MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
                universe_policy_id=universe_policy_id,
                factor_policy_id=factor_policy_id,
                split_policy_id=split_policy_id,
                cost_semantics_id=cost_semantics_id,
            )
        )
        return cls(
            scope_id=f"r4p:{digest}",
            owner="research",
            capability="r4",
            purpose="macro_risk_method_research",
            study_family_id=study_family_id,
            target_method=MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
            universe_policy_id=universe_policy_id,
            factor_policy_id=factor_policy_id,
            split_policy_id=split_policy_id,
            cost_semantics_id=cost_semantics_id,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R4 promotion scope_id")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
        ):
            raise ValueError("R4 promotion scope authority is invalid")
        if self.target_method is not MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY:
            raise ValueError("R4 promotion target must be macro-factor risk parity")
        for field_name, value in (
            ("study_family_id", self.study_family_id),
            ("universe_policy_id", self.universe_policy_id),
            ("factor_policy_id", self.factor_policy_id),
            ("split_policy_id", self.split_policy_id),
            ("cost_semantics_id", self.cost_semantics_id),
        ):
            _require_token(value, f"R4 promotion scope {field_name}")
        _require_hash(self.content_hash, "R4 promotion scope content_hash")
        expected = r4_promotion_scope_hash(self)
        if self.content_hash != expected or self.scope_id != f"r4p:{expected}":
            raise ValueError("R4 promotion scope identity or content hash mismatch")


def _scope_payload(
    *,
    owner: str,
    capability: str,
    purpose: str,
    study_family_id: str,
    target_method: MacroRiskCandidateKind,
    universe_policy_id: str,
    factor_policy_id: str,
    split_policy_id: str,
    cost_semantics_id: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-scope.v1",
        "authority": [owner, capability, purpose],
        "study_family_id": study_family_id,
        "target_method": target_method.value,
        "semantic_ids": [
            universe_policy_id,
            factor_policy_id,
            split_policy_id,
            cost_semantics_id,
        ],
    }


def r4_promotion_scope_hash(scope: R4PromotionScope) -> str:
    """Recompute one stable R4 semantic scope hash."""

    return _hash_payload(
        _scope_payload(
            owner=scope.owner,
            capability=scope.capability,
            purpose=scope.purpose,
            study_family_id=scope.study_family_id,
            target_method=scope.target_method,
            universe_policy_id=scope.universe_policy_id,
            factor_policy_id=scope.factor_policy_id,
            split_policy_id=scope.split_policy_id,
            cost_semantics_id=scope.cost_semantics_id,
        )
    )


@dataclass(frozen=True)
class R4PromotionStudyRegistration:
    """Pre-registered exact-to-semantic mapping used to validate Portfolio records."""

    study_family_id: str
    study_id: str
    universe_policy_id: str
    asset_codes: tuple[str, ...]
    factor_policy_id: str
    factor_codes: tuple[str, ...]
    split_policy_id: str
    split_policy_version: str
    cost_semantics_id: str
    cost_semantics_version: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_family_id: str,
        study_id: str,
        universe_policy_id: str,
        asset_codes: tuple[str, ...],
        factor_policy_id: str,
        factor_codes: tuple[str, ...],
        split_policy_id: str,
        split_policy_version: str,
        cost_semantics_id: str,
        cost_semantics_version: str,
    ) -> R4PromotionStudyRegistration:
        """Seal an explicit registration; no mapping is inferred at evaluation time."""

        values = (
            study_family_id,
            study_id,
            universe_policy_id,
            asset_codes,
            factor_policy_id,
            factor_codes,
            split_policy_id,
            split_policy_version,
            cost_semantics_id,
            cost_semantics_version,
        )
        digest = _hash_payload(_registration_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("study_family_id", self.study_family_id),
            ("study_id", self.study_id),
            ("universe_policy_id", self.universe_policy_id),
            ("factor_policy_id", self.factor_policy_id),
            ("split_policy_id", self.split_policy_id),
            ("split_policy_version", self.split_policy_version),
            ("cost_semantics_id", self.cost_semantics_id),
            ("cost_semantics_version", self.cost_semantics_version),
        ):
            _require_token(value, f"R4 study registration {field_name}")
        for label, values in (
            ("asset_codes", self.asset_codes),
            ("factor_codes", self.factor_codes),
        ):
            if not values or values != tuple(sorted(set(values))):
                raise ValueError(f"R4 study registration {label} must be unique and ordered")
            for value in values:
                _require_token(value, f"R4 study registration {label}")
        _require_hash(self.content_hash, "R4 study registration content_hash")
        if self.content_hash != r4_promotion_study_registration_hash(self):
            raise ValueError("R4 study registration content hash mismatch")


def _registration_payload(
    study_family_id: str,
    study_id: str,
    universe_policy_id: str,
    asset_codes: tuple[str, ...],
    factor_policy_id: str,
    factor_codes: tuple[str, ...],
    split_policy_id: str,
    split_policy_version: str,
    cost_semantics_id: str,
    cost_semantics_version: str,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-study-registration.v1",
        "study": [study_family_id, study_id],
        "universe": [universe_policy_id, list(asset_codes)],
        "factor": [factor_policy_id, list(factor_codes)],
        "split": [split_policy_id, split_policy_version],
        "cost": [cost_semantics_id, cost_semantics_version],
    }


def r4_promotion_study_registration_hash(
    registration: R4PromotionStudyRegistration,
) -> str:
    """Recompute one pre-registered exact-to-semantic mapping hash."""

    return _hash_payload(
        _registration_payload(
            registration.study_family_id,
            registration.study_id,
            registration.universe_policy_id,
            registration.asset_codes,
            registration.factor_policy_id,
            registration.factor_codes,
            registration.split_policy_id,
            registration.split_policy_version,
            registration.cost_semantics_id,
            registration.cost_semantics_version,
        )
    )


@dataclass(frozen=True)
class R4PromotionPolicy:
    """Research-owned pre-registered gates for one stable R4 scope."""

    policy_id: str
    policy_version: str
    owner: str
    capability: str
    purpose: str
    scope: R4PromotionScope
    registration: R4PromotionStudyRegistration
    status: R4PromotionPolicyStatus
    required_methods: tuple[MacroRiskCandidateKind, ...]
    reference_methods: tuple[MacroRiskCandidateKind, ...]
    minimum_fold_count: int
    minimum_regime_coverage_ratio: Decimal
    minimum_relative_net_return: Decimal
    maximum_relative_drawdown_increase: Decimal
    maximum_relative_volatility_increase: Decimal
    maximum_relative_cost_increase: Decimal
    decision_validity_seconds: int
    approved_at: datetime
    recorded_at: datetime
    active_from: datetime
    active_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        scope: R4PromotionScope,
        registration: R4PromotionStudyRegistration,
        required_methods: tuple[MacroRiskCandidateKind, ...],
        reference_methods: tuple[MacroRiskCandidateKind, ...],
        minimum_fold_count: int,
        minimum_regime_coverage_ratio: Decimal,
        minimum_relative_net_return: Decimal,
        maximum_relative_drawdown_increase: Decimal,
        maximum_relative_volatility_increase: Decimal,
        maximum_relative_cost_increase: Decimal,
        decision_validity_seconds: int,
        approved_at: datetime,
        recorded_at: datetime,
        active_from: datetime,
        active_until: datetime,
    ) -> R4PromotionPolicy:
        """Seal explicit policy values without any implicit threshold."""

        values = (
            policy_id,
            policy_version,
            "research",
            "r4",
            "macro_risk_method_research",
            scope,
            registration,
            R4PromotionPolicyStatus.ACTIVE,
            required_methods,
            reference_methods,
            minimum_fold_count,
            minimum_regime_coverage_ratio,
            minimum_relative_net_return,
            maximum_relative_drawdown_increase,
            maximum_relative_volatility_increase,
            maximum_relative_cost_increase,
            decision_validity_seconds,
            approved_at,
            recorded_at,
            active_from,
            active_until,
        )
        digest = _hash_payload(_policy_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R4 promotion policy_id")
        _require_token(self.policy_version, "R4 promotion policy_version")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
            or self.status is not R4PromotionPolicyStatus.ACTIVE
        ):
            raise ValueError("R4 promotion policy authority or status is invalid")
        if (
            self.scope.owner != self.owner
            or self.scope.capability != self.capability
            or self.scope.purpose != self.purpose
            or self.registration.study_family_id != self.scope.study_family_id
            or self.registration.study_id != self.scope.study_family_id
            or self.registration.universe_policy_id != self.scope.universe_policy_id
            or self.registration.factor_policy_id != self.scope.factor_policy_id
            or self.registration.split_policy_id != self.scope.split_policy_id
            or self.registration.cost_semantics_id != self.scope.cost_semantics_id
        ):
            raise ValueError("R4 promotion policy registration does not match its stable scope")
        if self.required_methods != _ALL_R4_METHODS:
            raise ValueError("R4 promotion policy must require the complete three-method family")
        expected_references = tuple(
            item for item in _ALL_R4_METHODS if item is not self.scope.target_method
        )
        if self.reference_methods != expected_references:
            raise ValueError("R4 promotion references must be all non-target required methods")
        if isinstance(self.minimum_fold_count, bool) or self.minimum_fold_count < 2:
            raise ValueError("R4 promotion minimum_fold_count must be at least two")
        _require_finite(
            self.minimum_regime_coverage_ratio,
            "minimum_regime_coverage_ratio",
        )
        if not Decimal("0") < self.minimum_regime_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum_regime_coverage_ratio must be within (0, 1]")
        _require_finite(self.minimum_relative_net_return, "minimum_relative_net_return")
        if self.minimum_relative_net_return < 0:
            raise ValueError("minimum_relative_net_return cannot be negative")
        for threshold_name, threshold_value in (
            (
                "maximum_relative_drawdown_increase",
                self.maximum_relative_drawdown_increase,
            ),
            (
                "maximum_relative_volatility_increase",
                self.maximum_relative_volatility_increase,
            ),
            ("maximum_relative_cost_increase", self.maximum_relative_cost_increase),
        ):
            _require_finite(threshold_value, threshold_name)
            if threshold_value < 0:
                raise ValueError(f"{threshold_name} cannot be negative")
        if (
            isinstance(self.decision_validity_seconds, bool)
            or not 1 <= self.decision_validity_seconds <= 31_536_000
        ):
            raise ValueError("decision_validity_seconds must be within one year")
        for clock_name, clock_value in (
            ("approved_at", self.approved_at),
            ("recorded_at", self.recorded_at),
            ("active_from", self.active_from),
            ("active_until", self.active_until),
        ):
            _require_aware(clock_value, f"R4 promotion policy {clock_name}")
        if not self.approved_at <= self.recorded_at <= self.active_from < self.active_until:
            raise ValueError("R4 promotion policy receipt/active window is invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R4 promotion policy must remain research-only")
        _require_hash(self.content_hash, "R4 promotion policy content_hash")
        if self.content_hash != r4_promotion_policy_hash(self):
            raise ValueError("R4 promotion policy content hash mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this owner receipt is known and active at ``as_of``."""

        _require_aware(as_of, "R4 promotion policy as_of")
        return self.recorded_at <= as_of and self.active_from <= as_of < self.active_until


def _policy_payload(
    policy_id: str,
    policy_version: str,
    owner: str,
    capability: str,
    purpose: str,
    scope: R4PromotionScope,
    registration: R4PromotionStudyRegistration,
    status: R4PromotionPolicyStatus,
    required_methods: tuple[MacroRiskCandidateKind, ...],
    reference_methods: tuple[MacroRiskCandidateKind, ...],
    minimum_fold_count: int,
    minimum_regime_coverage_ratio: Decimal,
    minimum_relative_net_return: Decimal,
    maximum_relative_drawdown_increase: Decimal,
    maximum_relative_volatility_increase: Decimal,
    maximum_relative_cost_increase: Decimal,
    decision_validity_seconds: int,
    approved_at: datetime,
    recorded_at: datetime,
    active_from: datetime,
    active_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-policy.v1",
        "identity": [policy_id, policy_version, owner, capability, purpose],
        "scope": [scope.scope_id, scope.content_hash],
        "registration": registration.content_hash,
        "status": status.value,
        "methods": [
            [item.value for item in required_methods],
            [item.value for item in reference_methods],
        ],
        "gates": {
            "minimum_fold_count": minimum_fold_count,
            "minimum_regime_coverage_ratio": _decimal_text(minimum_regime_coverage_ratio),
            "minimum_relative_net_return": _decimal_text(minimum_relative_net_return),
            "maximum_relative_drawdown_increase": _decimal_text(maximum_relative_drawdown_increase),
            "maximum_relative_volatility_increase": _decimal_text(
                maximum_relative_volatility_increase
            ),
            "maximum_relative_cost_increase": _decimal_text(maximum_relative_cost_increase),
        },
        "decision_validity_seconds": decision_validity_seconds,
        "window": [
            _utc_text(approved_at),
            _utc_text(recorded_at),
            _utc_text(active_from),
            _utc_text(active_until),
        ],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r4_promotion_policy_hash(policy: R4PromotionPolicy) -> str:
    """Recompute one exact pre-registered R4 policy hash."""

    return _hash_payload(
        _policy_payload(
            policy.policy_id,
            policy.policy_version,
            policy.owner,
            policy.capability,
            policy.purpose,
            policy.scope,
            policy.registration,
            policy.status,
            policy.required_methods,
            policy.reference_methods,
            policy.minimum_fold_count,
            policy.minimum_regime_coverage_ratio,
            policy.minimum_relative_net_return,
            policy.maximum_relative_drawdown_increase,
            policy.maximum_relative_volatility_increase,
            policy.maximum_relative_cost_increase,
            policy.decision_validity_seconds,
            policy.approved_at,
            policy.recorded_at,
            policy.active_from,
            policy.active_until,
        )
    )


__all__ = [
    "R4PromotionPolicy",
    "R4PromotionPolicyStatus",
    "R4PromotionScope",
    "R4PromotionStudyRegistration",
    "r4_promotion_policy_hash",
    "r4_promotion_scope_hash",
    "r4_promotion_study_registration_hash",
]
