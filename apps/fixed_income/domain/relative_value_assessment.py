"""Composite R5 relative-value research input, policy, and result seals."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum

from apps.fixed_income.domain.curve_relative_value import (
    BondMasterEvidence,
    CashFlowEvidence,
    CurveRelativeValueAssessment,
    CurveRelativeValueEvidence,
    CurveRelativeValuePolicy,
    CurveRelativeValueStatus,
    evaluate_curve_relative_value,
    seal_curve_liquidity_results,
)
from apps.fixed_income.domain.evidence import (
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityPremiumAssessment,
    LiquidityPremiumEvidence,
    LiquidityPremiumPolicy,
    LiquidityPremiumStatus,
    evaluate_liquidity_premium,
)
from apps.fixed_income.domain.rating_migration import (
    RatingMigrationAssessment,
    RatingMigrationEvidence,
    RatingMigrationPolicy,
    RatingMigrationStatus,
    evaluate_rating_migration,
)
from apps.fixed_income.domain.spread_history import (
    ExpectedObservationCalendar,
    SpreadAssessmentStatus,
    SpreadPercentileAssessment,
    SpreadPercentileEvidence,
    SpreadPercentilePolicy,
    evaluate_spread_percentile,
)


class R5Component(str, Enum):
    """Ordered components of one composite R5 assessment."""

    SPREAD_PERCENTILE = "spread_percentile"
    RATING_MIGRATION = "rating_migration"
    LIQUIDITY_PREMIUM = "liquidity_premium"
    CURVE_RELATIVE_VALUE = "curve_relative_value"


_COMPONENT_ORDER = tuple(sorted(R5Component, key=lambda item: item.value))


class R5ComponentStatus(str, Enum):
    """Normalized availability of one child result."""

    AVAILABLE = "available"
    BLOCKED = "blocked"
    MISSING = "missing"


class R5RelativeValueStatus(str, Enum):
    """Overall research-only availability state."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class R5RelativeValueBlockerCode(str, Enum):
    """Stable composite/provider failure reasons."""

    INPUT_SET_MISSING = "fixed_income.r5.input_set.missing"
    POLICY_SET_MISSING = "fixed_income.r5.policy_set.missing"
    LOCATOR_MISMATCH = "fixed_income.r5.locator.mismatch"
    EXACT_EVIDENCE_MISSING = "fixed_income.r5.exact_evidence.missing"
    EXACT_EVIDENCE_MISMATCH = "fixed_income.r5.exact_evidence.mismatch"
    INPUT_SET_FROM_FUTURE = "fixed_income.r5.input_set.from_future"
    INPUT_SET_STALE = "fixed_income.r5.input_set.stale"
    POLICY_SET_INACTIVE = "fixed_income.r5.policy_set.inactive"
    CURRENCY_MISMATCH = "fixed_income.r5.currency.mismatch"
    CHILD_BLOCKED = "fixed_income.r5.child.blocked"
    CHILD_HASH_MISMATCH = "fixed_income.r5.child.hash_mismatch"


@dataclass(frozen=True)
class R5RelativeValueBlocker:
    """Stable composite blocker with bounded detail."""

    code: R5RelativeValueBlockerCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, R5RelativeValueBlockerCode):
            raise ValueError("R5RelativeValueBlocker.code is invalid")
        require_token(
            self.detail.replace(" ", "_"),
            "R5RelativeValueBlocker.detail",
            maximum=240,
        )


def _canonical_exact_evidence(
    evidence_items: tuple[ExactEvidence, ...],
) -> tuple[ExactEvidence, ...]:
    by_locator: dict[tuple[str, str], ExactEvidence] = {}
    for evidence in evidence_items:
        key = (evidence.evidence_id, evidence.version)
        existing = by_locator.get(key)
        if existing is not None and existing.seal_hash != evidence.seal_hash:
            raise ValueError("one exact locator cannot identify two evidence seals")
        by_locator[key] = evidence
    return tuple(
        sorted(
            by_locator.values(),
            key=lambda item: (item.evidence_id, item.version, item.seal_hash),
        )
    )


def collect_r5_publication_evidence(
    *,
    spread: SpreadPercentileEvidence,
    rating: RatingMigrationEvidence,
    liquidities: tuple[LiquidityPremiumEvidence, ...],
    curve: CurveRelativeValueEvidence,
) -> tuple[ExactEvidence, ...]:
    """Collect every nested Publication that Application must reread exactly."""

    spread_publications = (
        spread.target.publication,
        *(item.publication for item in spread.reference_observations),
    )
    rating_publications = (
        rating.taxonomy.evidence,
        *(item.origin_publication for item in rating.transitions),
        *(item.terminal_publication for item in rating.transitions),
    )
    liquidity_publications = tuple(
        measure.publication for liquidity in liquidities for measure in liquidity.measures
    )
    curve_publications = (
        *(item.evidence for item in curve.capacities),
        *(item.evidence for item in curve.liquidity_capacities),
    )
    return _canonical_exact_evidence(
        (
            *spread_publications,
            *rating_publications,
            *liquidity_publications,
            *curve_publications,
        )
    )


@dataclass(frozen=True)
class R5RelativeValuePolicySet:
    """Exact versioned policy set for all four R5 child assessments."""

    policy_set_id: str
    policy_set_version: str
    spread_policy: SpreadPercentilePolicy
    rating_policy: RatingMigrationPolicy
    liquidity_policy: LiquidityPremiumPolicy
    curve_policy: CurveRelativeValuePolicy
    source: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.policy_set_id, "R5RelativeValuePolicySet.policy_set_id")
        require_token(
            self.policy_set_version,
            "R5RelativeValuePolicySet.policy_set_version",
        )
        if self.source.role is not EvidenceRole.POLICY:
            raise ValueError("R5 policy set requires Research policy evidence")
        if (
            self.source.evidence_id != self.policy_set_id
            or self.source.version != self.policy_set_version
            or self.source.subject_id != self.policy_set_id
            or self.source.curve_role != "r5_relative_value_policy_set"
        ):
            raise ValueError("R5 policy-set source identity mismatch")
        child_hashes = self.child_policy_hashes
        if not set(child_hashes).issubset(set(self.source.upstream_hashes)):
            raise ValueError("R5 policy-set source must attest every child policy hash")
        if self.source.content_hash != self.raw_manifest_hash:
            raise ValueError("R5 policy-set content hash must equal policy manifest")

    @property
    def child_policy_hashes(self) -> tuple[str, ...]:
        """Return canonical child policy hashes."""

        return tuple(
            sorted(
                (
                    self.spread_policy.policy_hash,
                    self.rating_policy.policy_hash,
                    self.liquidity_policy.policy_hash,
                    self.curve_policy.policy_hash,
                )
            )
        )

    @property
    def raw_manifest_hash(self) -> str:
        """Hash policy-set identity and the exact child policy versions/content."""

        return canonical_hash(
            {
                "policy_set_id": self.policy_set_id,
                "policy_set_version": self.policy_set_version,
                "spread_policy_hash": self.spread_policy.policy_hash,
                "rating_policy_hash": self.rating_policy.policy_hash,
                "liquidity_policy_hash": self.liquidity_policy.policy_hash,
                "curve_policy_hash": self.curve_policy.policy_hash,
            }
        )

    @property
    def policy_set_hash(self) -> str:
        """Hash the child manifest and exact Research owner seal."""

        return canonical_hash(
            {
                "raw_manifest_hash": self.raw_manifest_hash,
                "source_hash": self.source.seal_hash,
            }
        )


@dataclass(frozen=True)
class R5RelativeValueInputSet:
    """Fixed-income-owned composite of exact child and owner evidence."""

    input_set_id: str
    input_set_version: str
    currency: str
    spread_evidence: SpreadPercentileEvidence
    spread_calendar: ExpectedObservationCalendar
    rating_evidence: RatingMigrationEvidence
    liquidity_evidences: tuple[LiquidityPremiumEvidence, ...]
    curve_evidence: CurveRelativeValueEvidence
    source: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.input_set_id, "R5RelativeValueInputSet.input_set_id")
        require_token(self.input_set_version, "R5RelativeValueInputSet.input_set_version")
        require_token(self.currency, "R5RelativeValueInputSet.currency", maximum=12)
        if self.source.role is not EvidenceRole.FIXED_INCOME_INPUT_SET:
            raise ValueError("R5 composite requires fixed_income-owned input-set evidence")
        if (
            self.source.evidence_id != self.input_set_id
            or self.source.version != self.input_set_version
            or self.source.subject_id != self.input_set_id
            or self.source.currency != self.currency
            or self.source.curve_role != "r5_relative_value_input_set"
        ):
            raise ValueError("R5 input-set source identity mismatch")
        liquidity_subjects = tuple(item.subject_id for item in self.liquidity_evidences)
        if liquidity_subjects != tuple(sorted(set(liquidity_subjects))):
            raise ValueError("R5 liquidity evidence subjects must be unique and canonical")
        curve_liquidity_graph = tuple(
            (item.subject_id, item.evidence_hash) for item in self.curve_evidence.liquidity_inputs
        )
        input_liquidity_graph = tuple(
            (item.subject_id, item.evidence_hash) for item in self.liquidity_evidences
        )
        if not input_liquidity_graph or input_liquidity_graph != curve_liquidity_graph:
            raise ValueError("R5 liquidity inputs must exactly equal the curve liquidity graph")
        child_sources = (
            self.spread_evidence.source,
            self.rating_evidence.source,
            *(item.source for item in self.liquidity_evidences),
            self.curve_evidence.source,
        )
        if self.source.observed_at != max(item.observed_at for item in child_sources):
            raise ValueError("R5 input-set observed_at must preserve latest source clock")
        if self.source.available_at != max(item.available_at for item in child_sources):
            raise ValueError("R5 input-set available_at must preserve latest availability")
        if self.source.valid_until != min(item.valid_until for item in child_sources):
            raise ValueError("R5 input-set validity cannot outlive a child source")
        if not set(self.child_input_hashes).issubset(set(self.source.upstream_hashes)):
            raise ValueError("R5 input-set source must attest every child input hash")
        if self.source.content_hash != self.raw_manifest_hash:
            raise ValueError("R5 input-set content hash must equal child manifest")

    @property
    def publications(self) -> tuple[ExactEvidence, ...]:
        """Return canonical nested Publications for authoritative rereads."""

        return collect_r5_publication_evidence(
            spread=self.spread_evidence,
            rating=self.rating_evidence,
            liquidities=self.liquidity_evidences,
            curve=self.curve_evidence,
        )

    @property
    def owner_exact_sources(self) -> tuple[ExactEvidence, ...]:
        """Return every nested exact PIT/owner seal requiring authoritative reread."""

        return _canonical_exact_evidence(
            (
                self.spread_evidence.source,
                self.rating_evidence.source,
                self.rating_evidence.cohort.evidence,
                *(item.source for item in self.liquidity_evidences),
                self.curve_evidence.source,
                self.curve_evidence.cash_funding.evidence,
                *(item.source for item in self.curve_evidence.legs),
            )
        )

    @property
    def bond_masters(self) -> tuple[BondMasterEvidence, ...]:
        """Return exact curve-leg BondMaster owner records."""

        return self.curve_evidence.bond_masters

    @property
    def cash_flows(self) -> tuple[CashFlowEvidence, ...]:
        """Return exact curve-leg CashFlow owner records."""

        return self.curve_evidence.cash_flows

    @property
    def calendars(self) -> tuple[ExactEvidence, ...]:
        """Return exact spread and trading Calendar owner seals."""

        return _canonical_exact_evidence(
            (
                self.spread_calendar.evidence,
                self.curve_evidence.trading_calendar.evidence,
            )
        )

    @property
    def child_input_hashes(self) -> tuple[str, ...]:
        """Return canonical hashes of all four child evidence graphs and calendar."""

        return tuple(
            sorted(
                (
                    self.spread_evidence.evidence_hash,
                    self.spread_calendar.calendar_hash,
                    self.rating_evidence.evidence_hash,
                    *(item.evidence_hash for item in self.liquidity_evidences),
                    self.curve_evidence.evidence_hash,
                )
            )
        )

    @property
    def raw_manifest_hash(self) -> str:
        """Hash child graphs and every owner-reread identity without the source seal."""

        return canonical_hash(
            {
                "input_set_id": self.input_set_id,
                "input_set_version": self.input_set_version,
                "currency": self.currency,
                "spread_evidence_hash": self.spread_evidence.evidence_hash,
                "spread_calendar_hash": self.spread_calendar.calendar_hash,
                "rating_evidence_hash": self.rating_evidence.evidence_hash,
                "liquidity_evidence_hashes": tuple(
                    (item.subject_id, item.evidence_hash) for item in self.liquidity_evidences
                ),
                "curve_evidence_hash": self.curve_evidence.evidence_hash,
                "publication_seals": tuple(item.seal_hash for item in self.publications),
                "bond_master_hashes": tuple(item.master_hash for item in self.bond_masters),
                "cash_flow_hashes": tuple(item.schedule_hash for item in self.cash_flows),
                "calendar_seals": tuple(item.seal_hash for item in self.calendars),
                "owner_exact_source_seals": tuple(
                    item.seal_hash for item in self.owner_exact_sources
                ),
            }
        )

    @property
    def input_set_hash(self) -> str:
        """Hash the complete fixed-income input manifest and owner seal."""

        return canonical_hash(
            {
                "raw_manifest_hash": self.raw_manifest_hash,
                "source_hash": self.source.seal_hash,
            }
        )


@dataclass(frozen=True)
class R5ComponentSeal:
    """Normalized child status/hash/blocker projection."""

    component: R5Component
    status: R5ComponentStatus
    input_hash: str | None
    output_hash: str | None
    policy_hash: str | None
    blocker_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.component, R5Component) or not isinstance(
            self.status,
            R5ComponentStatus,
        ):
            raise ValueError("R5 component seal enums are invalid")
        for name in ("input_hash", "output_hash", "policy_hash"):
            value = getattr(self, name)
            if value is not None:
                require_sha256(value, f"R5ComponentSeal.{name}")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("component blocker codes must be unique and canonical")
        if self.status is R5ComponentStatus.AVAILABLE and (
            self.input_hash is None
            or self.output_hash is None
            or self.policy_hash is None
            or self.blocker_codes
        ):
            raise ValueError("available component seal is incomplete")
        if self.status is R5ComponentStatus.MISSING and (
            self.input_hash is not None
            or self.output_hash is not None
            or self.policy_hash is not None
        ):
            raise ValueError("missing component cannot publish placeholder hashes")


@dataclass(frozen=True)
class R5RelativeValueAssessment:
    """Composite seal binding all four R5 child results and safety semantics."""

    assessment_id: str
    input_set_id: str
    input_set_version: str
    policy_set_id: str
    policy_set_version: str
    status: R5RelativeValueStatus
    evaluated_at: datetime
    input_set_hash: str | None
    policy_set_hash: str | None
    input_hash: str
    output_hash: str
    component_seals: tuple[R5ComponentSeal, ...]
    spread_result: SpreadPercentileAssessment | None
    rating_result: RatingMigrationAssessment | None
    liquidity_results: tuple[LiquidityPremiumAssessment, ...]
    curve_result: CurveRelativeValueAssessment | None
    spread_policy_hash: str | None
    rating_policy_hash: str | None
    liquidity_policy_hash: str | None
    curve_component_policy_hash: str | None
    blockers: tuple[R5RelativeValueBlocker, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        for name in (
            "assessment_id",
            "input_set_id",
            "input_set_version",
            "policy_set_id",
            "policy_set_version",
        ):
            require_token(str(getattr(self, name)), f"R5RelativeValueAssessment.{name}")
        require_aware(self.evaluated_at, "R5RelativeValueAssessment.evaluated_at")
        for name in (
            "input_set_hash",
            "policy_set_hash",
            "spread_policy_hash",
            "rating_policy_hash",
            "liquidity_policy_hash",
            "curve_component_policy_hash",
        ):
            value = getattr(self, name)
            if value is not None:
                require_sha256(value, f"R5RelativeValueAssessment.{name}")
        require_sha256(self.input_hash, "R5RelativeValueAssessment.input_hash")
        require_sha256(self.output_hash, "R5RelativeValueAssessment.output_hash")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("composite R5 assessment must remain research-only")
        if tuple(item.component for item in self.component_seals) != _COMPONENT_ORDER:
            raise ValueError("component seals must exactly cover canonical R5 order")
        if self.component_seals != self.calculated_component_seals:
            raise ValueError("component seals do not match child results")
        liquidity_subjects = tuple(item.subject_id for item in self.liquidity_results)
        if liquidity_subjects != tuple(sorted(set(liquidity_subjects))):
            raise ValueError("liquidity results must be unique and canonical")
        if self.curve_result is not None and (
            self.curve_result.liquidity_result_seals
            != seal_curve_liquidity_results(self.liquidity_results)
        ):
            raise ValueError("curve-consumed liquidity results differ from composite results")
        expected_policy_hashes = {
            R5Component.SPREAD_PERCENTILE: self.spread_policy_hash,
            R5Component.RATING_MIGRATION: self.rating_policy_hash,
            R5Component.LIQUIDITY_PREMIUM: self.liquidity_policy_hash,
            R5Component.CURVE_RELATIVE_VALUE: self.curve_component_policy_hash,
        }
        if any(
            seal.status is not R5ComponentStatus.MISSING
            and seal.policy_hash != expected_policy_hashes[seal.component]
            for seal in self.component_seals
        ):
            raise ValueError("component policy seals do not match expected policies")
        child_results = (
            self.spread_result,
            self.rating_result,
            *self.liquidity_results,
            self.curve_result,
        )
        if any(
            result is not None and result.evaluated_at != self.evaluated_at
            for result in child_results
        ):
            raise ValueError("all child results must use the composite cutoff")
        if self.blockers != tuple(
            sorted(set(self.blockers), key=lambda item: (item.code.value, item.detail))
        ):
            raise ValueError("composite blockers must be unique and canonical")
        if self.status is R5RelativeValueStatus.AVAILABLE:
            if (
                self.blockers
                or self.input_set_hash is None
                or self.policy_set_hash is None
                or any(
                    item.status is not R5ComponentStatus.AVAILABLE for item in self.component_seals
                )
            ):
                raise ValueError("available composite assessment is incomplete")
        elif not self.blockers:
            raise ValueError("blocked composite assessment requires blockers")
        if self.output_hash != self.calculated_output_hash:
            raise ValueError("composite R5 output hash mismatch")

    @property
    def calculated_component_seals(self) -> tuple[R5ComponentSeal, ...]:
        """Recompute normalized seals from the four child result objects."""

        return tuple(
            sorted(
                (
                    _spread_seal(self.spread_result),
                    _rating_seal(self.rating_result),
                    _liquidity_seal(self.liquidity_results),
                    _curve_seal(self.curve_result),
                ),
                key=lambda item: item.component.value,
            )
        )

    @property
    def calculated_output_hash(self) -> str:
        """Recompute child seals, blockers, IDs, and all safety fields."""

        return canonical_hash(
            {
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name != "output_hash"
            }
        )


def _child_seal(
    *,
    component: R5Component,
    available: bool,
    input_hash: str,
    output_hash: str,
    policy_hash: str,
    blocker_codes: tuple[str, ...],
) -> R5ComponentSeal:
    return R5ComponentSeal(
        component=component,
        status=(R5ComponentStatus.AVAILABLE if available else R5ComponentStatus.BLOCKED),
        input_hash=input_hash,
        output_hash=output_hash,
        policy_hash=policy_hash,
        blocker_codes=tuple(sorted(set(blocker_codes))),
    )


def _missing_seal(component: R5Component) -> R5ComponentSeal:
    return R5ComponentSeal(
        component=component,
        status=R5ComponentStatus.MISSING,
        input_hash=None,
        output_hash=None,
        policy_hash=None,
        blocker_codes=(),
    )


def _spread_seal(result: SpreadPercentileAssessment | None) -> R5ComponentSeal:
    if result is None:
        return _missing_seal(R5Component.SPREAD_PERCENTILE)
    return _child_seal(
        component=R5Component.SPREAD_PERCENTILE,
        available=result.status is SpreadAssessmentStatus.AVAILABLE,
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        policy_hash=result.policy_hash,
        blocker_codes=tuple(item.code.value for item in result.blockers),
    )


def _rating_seal(result: RatingMigrationAssessment | None) -> R5ComponentSeal:
    if result is None:
        return _missing_seal(R5Component.RATING_MIGRATION)
    return _child_seal(
        component=R5Component.RATING_MIGRATION,
        available=result.status is RatingMigrationStatus.AVAILABLE,
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        policy_hash=result.policy_hash,
        blocker_codes=tuple(item.code.value for item in result.blockers),
    )


def _liquidity_seal(
    results: tuple[LiquidityPremiumAssessment, ...],
) -> R5ComponentSeal:
    if not results:
        return _missing_seal(R5Component.LIQUIDITY_PREMIUM)
    result_seals = seal_curve_liquidity_results(results)
    policy_hashes = {item.policy_hash for item in result_seals}
    if len(policy_hashes) != 1:
        raise ValueError("liquidity results must use exactly one policy")
    policy_hash = next(iter(policy_hashes))
    return _child_seal(
        component=R5Component.LIQUIDITY_PREMIUM,
        available=all(result.status is LiquidityPremiumStatus.AVAILABLE for result in results),
        input_hash=canonical_hash(
            {
                "liquidity_inputs": tuple(
                    (item.subject_id, item.input_hash, item.policy_hash) for item in result_seals
                )
            }
        ),
        output_hash=canonical_hash({"liquidity_results": result_seals}),
        policy_hash=policy_hash,
        blocker_codes=tuple(
            f"{result.subject_id}:{blocker.code.value}"
            for result in results
            for blocker in result.blockers
        ),
    )


def _curve_seal(result: CurveRelativeValueAssessment | None) -> R5ComponentSeal:
    if result is None:
        return _missing_seal(R5Component.CURVE_RELATIVE_VALUE)
    return _child_seal(
        component=R5Component.CURVE_RELATIVE_VALUE,
        available=result.status is CurveRelativeValueStatus.AVAILABLE,
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        policy_hash=result.policy_hash,
        blocker_codes=tuple(item.code.value for item in result.blockers),
    )


def r5_relative_value_input_hash(
    *,
    assessment_id: str,
    input_set_id: str,
    input_set_version: str,
    policy_set_id: str,
    policy_set_version: str,
    evaluated_at: datetime,
    input_set_hash: str | None,
    policy_set_hash: str | None,
) -> str:
    """Hash command IDs, cutoff, and optional exact provider graph hashes."""

    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "assessment_id": assessment_id,
            "input_set_id": input_set_id,
            "input_set_version": input_set_version,
            "policy_set_id": policy_set_id,
            "policy_set_version": policy_set_version,
            "evaluated_at": evaluated_at,
            "input_set_hash": input_set_hash,
            "policy_set_hash": policy_set_hash,
        }
    )


def _make_assessment(
    *,
    assessment_id: str,
    input_set_id: str,
    input_set_version: str,
    policy_set_id: str,
    policy_set_version: str,
    status: R5RelativeValueStatus,
    evaluated_at: datetime,
    input_set_hash: str | None,
    policy_set_hash: str | None,
    spread_result: SpreadPercentileAssessment | None,
    rating_result: RatingMigrationAssessment | None,
    liquidity_results: tuple[LiquidityPremiumAssessment, ...],
    curve_result: CurveRelativeValueAssessment | None,
    spread_policy_hash: str | None,
    rating_policy_hash: str | None,
    liquidity_policy_hash: str | None,
    curve_component_policy_hash: str | None,
    blockers: tuple[R5RelativeValueBlocker, ...],
) -> R5RelativeValueAssessment:
    input_hash = r5_relative_value_input_hash(
        assessment_id=assessment_id,
        input_set_id=input_set_id,
        input_set_version=input_set_version,
        policy_set_id=policy_set_id,
        policy_set_version=policy_set_version,
        evaluated_at=evaluated_at,
        input_set_hash=input_set_hash,
        policy_set_hash=policy_set_hash,
    )
    component_seals = tuple(
        sorted(
            (
                _spread_seal(spread_result),
                _rating_seal(rating_result),
                _liquidity_seal(liquidity_results),
                _curve_seal(curve_result),
            ),
            key=lambda item: item.component.value,
        )
    )
    values: dict[str, object] = {
        "assessment_id": assessment_id,
        "input_set_id": input_set_id,
        "input_set_version": input_set_version,
        "policy_set_id": policy_set_id,
        "policy_set_version": policy_set_version,
        "status": status,
        "evaluated_at": evaluated_at,
        "input_set_hash": input_set_hash,
        "policy_set_hash": policy_set_hash,
        "input_hash": input_hash,
        "component_seals": component_seals,
        "spread_result": spread_result,
        "rating_result": rating_result,
        "liquidity_results": liquidity_results,
        "curve_result": curve_result,
        "spread_policy_hash": spread_policy_hash,
        "rating_policy_hash": rating_policy_hash,
        "liquidity_policy_hash": liquidity_policy_hash,
        "curve_component_policy_hash": curve_component_policy_hash,
        "blockers": blockers,
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    return R5RelativeValueAssessment(
        output_hash=canonical_hash(values),
        assessment_id=assessment_id,
        input_set_id=input_set_id,
        input_set_version=input_set_version,
        policy_set_id=policy_set_id,
        policy_set_version=policy_set_version,
        status=status,
        evaluated_at=evaluated_at,
        input_set_hash=input_set_hash,
        policy_set_hash=policy_set_hash,
        input_hash=input_hash,
        component_seals=component_seals,
        spread_result=spread_result,
        rating_result=rating_result,
        liquidity_results=liquidity_results,
        curve_result=curve_result,
        spread_policy_hash=spread_policy_hash,
        rating_policy_hash=rating_policy_hash,
        liquidity_policy_hash=liquidity_policy_hash,
        curve_component_policy_hash=curve_component_policy_hash,
        blockers=blockers,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


def blocked_r5_relative_value_assessment(
    *,
    assessment_id: str,
    input_set_id: str,
    input_set_version: str,
    policy_set_id: str,
    policy_set_version: str,
    evaluated_at: datetime,
    blocker: R5RelativeValueBlocker,
    input_set_hash: str | None = None,
    policy_set_hash: str | None = None,
) -> R5RelativeValueAssessment:
    """Build a missing-evidence composite without zero hashes or derived placeholders."""

    return _make_assessment(
        assessment_id=assessment_id,
        input_set_id=input_set_id,
        input_set_version=input_set_version,
        policy_set_id=policy_set_id,
        policy_set_version=policy_set_version,
        status=R5RelativeValueStatus.BLOCKED,
        evaluated_at=evaluated_at,
        input_set_hash=input_set_hash,
        policy_set_hash=policy_set_hash,
        spread_result=None,
        rating_result=None,
        liquidity_results=(),
        curve_result=None,
        spread_policy_hash=None,
        rating_policy_hash=None,
        liquidity_policy_hash=None,
        curve_component_policy_hash=None,
        blockers=(blocker,),
    )


def evaluate_r5_relative_value(
    *,
    assessment_id: str,
    input_set: R5RelativeValueInputSet,
    policy_set: R5RelativeValuePolicySet,
    evaluated_at: datetime,
) -> R5RelativeValueAssessment:
    """Evaluate all four children and fail the composite closed on any blocker."""

    require_aware(evaluated_at, "evaluated_at")
    spread_result = evaluate_spread_percentile(
        input_set.spread_evidence,
        policy=policy_set.spread_policy,
        calendar=input_set.spread_calendar,
        evaluated_at=evaluated_at,
    )
    rating_result = evaluate_rating_migration(
        input_set.rating_evidence,
        policy=policy_set.rating_policy,
        evaluated_at=evaluated_at,
    )
    liquidity_results = tuple(
        evaluate_liquidity_premium(
            evidence,
            policy=policy_set.liquidity_policy,
            evaluated_at=evaluated_at,
        )
        for evidence in input_set.liquidity_evidences
    )
    curve_result = evaluate_curve_relative_value(
        input_set.curve_evidence,
        policy=policy_set.curve_policy,
        liquidity_policy=policy_set.liquidity_policy,
        evaluated_at=evaluated_at,
    )
    blockers: list[R5RelativeValueBlocker] = []
    input_reason = input_set.source.usability_reason(evaluated_at)
    if input_reason == "evidence_from_future":
        blockers.append(
            R5RelativeValueBlocker(
                R5RelativeValueBlockerCode.INPUT_SET_FROM_FUTURE,
                "input set from future",
            )
        )
    elif input_reason == "evidence_stale":
        blockers.append(
            R5RelativeValueBlocker(
                R5RelativeValueBlockerCode.INPUT_SET_STALE,
                "input set stale",
            )
        )
    if policy_set.source.usability_reason(evaluated_at) is not None:
        blockers.append(
            R5RelativeValueBlocker(
                R5RelativeValueBlockerCode.POLICY_SET_INACTIVE,
                "policy set inactive",
            )
        )
    if (
        input_set.spread_evidence.currency != input_set.currency
        or any(
            evidence.currency != input_set.currency for evidence in input_set.liquidity_evidences
        )
        or input_set.curve_evidence.currency != input_set.currency
    ):
        blockers.append(
            R5RelativeValueBlocker(
                R5RelativeValueBlockerCode.CURRENCY_MISMATCH,
                "child currencies differ from input set",
            )
        )
    for component, child_status in (
        (R5Component.SPREAD_PERCENTILE, spread_result.status.value),
        (R5Component.RATING_MIGRATION, rating_result.status.value),
        (
            R5Component.LIQUIDITY_PREMIUM,
            (
                "available"
                if all(
                    result.status is LiquidityPremiumStatus.AVAILABLE
                    for result in liquidity_results
                )
                else "blocked"
            ),
        ),
        (R5Component.CURVE_RELATIVE_VALUE, curve_result.status.value),
    ):
        if child_status != "available":
            blockers.append(
                R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.CHILD_BLOCKED,
                    f"{component.value} child blocked",
                )
            )
    expected_curve_liquidity_seals = seal_curve_liquidity_results(liquidity_results)
    if curve_result.liquidity_result_seals != expected_curve_liquidity_seals:
        blockers.append(
            R5RelativeValueBlocker(
                R5RelativeValueBlockerCode.CHILD_HASH_MISMATCH,
                "curve liquidity result graph differs from composite graph",
            )
        )
    curve_component_policy_hash = canonical_hash(
        {
            "curve_policy_hash": policy_set.curve_policy.policy_hash,
            "liquidity_policy_hash": policy_set.liquidity_policy.policy_hash,
        }
    )
    for actual, expected, label in (
        (spread_result.policy_hash, policy_set.spread_policy.policy_hash, "spread"),
        (rating_result.policy_hash, policy_set.rating_policy.policy_hash, "rating"),
        (
            _liquidity_seal(liquidity_results).policy_hash,
            policy_set.liquidity_policy.policy_hash,
            "liquidity",
        ),
        (curve_result.policy_hash, curve_component_policy_hash, "curve"),
    ):
        if actual != expected:
            blockers.append(
                R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.CHILD_HASH_MISMATCH,
                    f"{label} child policy hash mismatch",
                )
            )
    unique_blockers = tuple(sorted(set(blockers), key=lambda item: (item.code.value, item.detail)))
    return _make_assessment(
        assessment_id=assessment_id,
        input_set_id=input_set.input_set_id,
        input_set_version=input_set.input_set_version,
        policy_set_id=policy_set.policy_set_id,
        policy_set_version=policy_set.policy_set_version,
        status=(
            R5RelativeValueStatus.BLOCKED if unique_blockers else R5RelativeValueStatus.AVAILABLE
        ),
        evaluated_at=evaluated_at,
        input_set_hash=input_set.input_set_hash,
        policy_set_hash=policy_set.policy_set_hash,
        spread_result=spread_result,
        rating_result=rating_result,
        liquidity_results=liquidity_results,
        curve_result=curve_result,
        spread_policy_hash=policy_set.spread_policy.policy_hash,
        rating_policy_hash=policy_set.rating_policy.policy_hash,
        liquidity_policy_hash=policy_set.liquidity_policy.policy_hash,
        curve_component_policy_hash=curve_component_policy_hash,
        blockers=unique_blockers,
    )


__all__ = [
    "R5Component",
    "R5ComponentSeal",
    "R5ComponentStatus",
    "R5RelativeValueAssessment",
    "R5RelativeValueBlocker",
    "R5RelativeValueBlockerCode",
    "R5RelativeValueInputSet",
    "R5RelativeValuePolicySet",
    "R5RelativeValueStatus",
    "blocked_r5_relative_value_assessment",
    "collect_r5_publication_evidence",
    "evaluate_r5_relative_value",
    "r5_relative_value_input_hash",
]
