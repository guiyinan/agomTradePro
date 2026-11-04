"""Replay binding contracts for persisted Scenario impacts and their summaries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    PortfolioPressureProjection,
    RunPortfolioExitPressureCommand,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    PortfolioExitPressureRunResult,
    RunPortfolioExitPressureUseCase,
)
from apps.risk_center.application.portfolio_pressure_report import (
    bind_portfolio_pressure_evidence_hash,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.application.scenario_dtos import (
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
)
from apps.risk_center.application.scenario_impact_context import ScenarioImpactContext
from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitPressurePosition,
    PortfolioExitPressureAssessment,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_snapshot import AccountSnapshot, HeldPosition
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    PortfolioExposure,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    evaluate_scenario,
    scenario_run_snapshot_hash,
)
from apps.simulated_trading.application.portfolio_risk_pressure_runner import (
    _read_existing_pressure_report,
    _scenario_impact_template_matches,
)
from core.exceptions import DuplicateResourceError

_ACTOR_ID = 731
_ACCOUNT_ID = 246
_AS_OF = datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
_SNAPSHOT_ID = f"simulated-account:{_ACCOUNT_ID}:pressure-replay-snapshot"
_ASSET_CODE = "600036.SH"
_SECURITY_ID = "SH.TEST.600036"
_IDEMPOTENCY_KEY = "pressure-replay-binding-contract"
_MARKET_EVIDENCE_ID = "synthetic-market:record-1"

_RETAINED_IMPACT: dict[str, object] = {
    "initial_value": "120000",
    "final_value": "116000",
    "total_return": "-0.03333333333333333333333333333",
    "result_hash": "a" * 64,
}
_PUBLIC_IMPACT: dict[str, object] = {
    "scope": "portfolio_snapshot_net_asset_value",
    "scope_label": "全组合净值（含现金）",
    "initial_value": "120000",
    "final_value": "116000",
    "value_unit": "CNY",
    "total_return": "-0.03333333333333333333333333333",
    "total_return_unit": "fraction",
    "scenario_result_hash": "a" * 64,
    "hypothetical": True,
    "market_observation": False,
}


def test_replay_accepts_only_a_truly_absent_legacy_public_summary() -> None:
    """Old templates may omit the optional summary, but not replace it with null."""

    assert _scenario_impact_template_matches(
        report_details={"scenario": {"revision_id": "legacy-revision"}},
        retained_impact=_RETAINED_IMPACT,
        money_unit="CNY",
    )


@pytest.mark.parametrize("malformed", [None, "not-an-object", []])
def test_replay_rejects_present_untyped_public_summaries(malformed: object) -> None:
    """A present null, string, or list must fail closed instead of using legacy mode."""

    assert not _scenario_impact_template_matches(
        report_details={"scenario_impact": malformed},
        retained_impact=_RETAINED_IMPACT,
        money_unit="CNY",
    )


def test_replay_accepts_a_complete_summary_bound_to_the_saved_impact() -> None:
    """The exact supported public fields and saved result digest must match."""

    assert _scenario_impact_template_matches(
        report_details={"scenario_impact": _PUBLIC_IMPACT},
        retained_impact=_RETAINED_IMPACT,
        money_unit="CNY",
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("scenario_result_hash", "b" * 64),
        ("value_unit", "USD"),
        ("total_return_unit", "percent"),
        ("unexpected", "extra"),
    ],
)
def test_replay_rejects_public_hash_unit_or_field_changes(field: str, value: object) -> None:
    """Hash, unit and field-set edits cannot change the saved result on replay."""

    changed = dict(_PUBLIC_IMPACT)
    changed[field] = value
    assert not _scenario_impact_template_matches(
        report_details={"scenario_impact": changed},
        retained_impact=_RETAINED_IMPACT,
        money_unit="CNY",
    )


def test_replay_redacts_saved_amounts_when_the_account_unit_is_unknown() -> None:
    """The retained amount is not public without a trustworthy money unit."""

    unknown_unit = {
        **_PUBLIC_IMPACT,
        "initial_value": None,
        "final_value": None,
        "value_unit": None,
        "total_return": None,
        "total_return_unit": None,
    }
    assert _scenario_impact_template_matches(
        report_details={"scenario_impact": unknown_unit},
        retained_impact=_RETAINED_IMPACT,
        money_unit=None,
    )


def test_runner_replays_a_complete_self_consistent_saved_scenario_evidence() -> None:
    """The retry path returns the exact persisted public report from its evidence row."""

    result, evidence, repository = _run_saved_evidence(_scenario_revision("revision-a", "-0.2"))

    replayed = _read_existing_pressure_report(
        repository=repository,
        actor_user_id=_ACTOR_ID,
        account_id=_ACCOUNT_ID,
        scenario_revision_id="revision-a",
        idempotency_key=_IDEMPOTENCY_KEY,
    )

    assert replayed is not None
    assert replayed == bind_portfolio_pressure_evidence_hash(
        result.public_report_template,
        evidence.result_hash,
    )
    replay_check = replayed["checks"][-1]
    assert replay_check["details"]["run_evidence_result_hash"] == evidence.result_hash


@pytest.mark.parametrize(
    "corruption",
    ("result_revision", "impact_revision", "assessment_impact"),
)
def test_runner_rejects_rehashed_cross_revision_scenario_evidence(corruption: str) -> None:
    """A recomputed outer digest cannot make mismatched persisted Scenario objects agree."""

    result_a, evidence_a, _ = _run_saved_evidence(_scenario_revision("revision-a", "-0.2"))
    result_b, evidence_b, _ = _run_saved_evidence(_scenario_revision("revision-b", "-0.1"))
    changed = _cross_bound_evidence(
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        assessment_a=result_a.assessment,
        impact_b=result_b.assessment.scenario_result_hash,
        corruption=corruption,
    )
    repository = _EvidenceRepository()
    repository.save_run_evidence(changed)

    with pytest.raises(DuplicateResourceError):
        _read_existing_pressure_report(
            repository=repository,
            actor_user_id=_ACTOR_ID,
            account_id=_ACCOUNT_ID,
            scenario_revision_id="revision-a",
            idempotency_key=_IDEMPOTENCY_KEY,
        )


class _EvidenceRepository:
    """In-memory implementation of the existing evidence reader/writer port."""

    def __init__(self) -> None:
        self._records: dict[str, ScenarioRunEvidence] = {}

    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        """Retain one exact immutable evidence value for the use-case fixture."""

        existing = self._records.get(evidence.run_id)
        if existing is not None and existing != evidence:
            raise ValueError("scenario run id already exists with different evidence")
        self._records[evidence.run_id] = evidence
        return evidence

    def get_run_evidence(self, run_id: str) -> ScenarioRunEvidence | None:
        """Return the retained evidence under its exact deterministic run identifier."""

        return self._records.get(run_id)


class _FixedPressureClock:
    """Supply the fixed server cutoff used by both typed snapshots."""

    def now(self) -> datetime:
        """Return the scenario-run cutoff."""

        return _AS_OF


class _ScenarioPreview:
    """Produce a real typed ScenarioImpactContext for one immutable revision."""

    def __init__(self, revision: ScenarioRevision) -> None:
        self._revision = revision

    def execute_with_context(self, request: ScenarioRunRequestDTO) -> ScenarioImpactContext:
        """Evaluate the selected revision against the same typed portfolio snapshot."""

        if request.scenario_revision_id != self._revision.revision_id:
            raise ValueError("preview fixture received another Scenario revision")
        snapshot = PortfolioSnapshotDTO(
            snapshot_id=_SNAPSHOT_ID,
            account_id=f"simulated-account:{_ACCOUNT_ID}",
            as_of_time=_AS_OF - timedelta(minutes=1),
            net_asset_value=Decimal("120000"),
            cash_value=Decimal("0"),
            positions=(
                PortfolioPositionDTO(
                    asset_code=_ASSET_CODE,
                    market_value=Decimal("120000"),
                ),
            ),
        )
        market_data = ScenarioMarketDataDTO(
            return_series=(),
            evidence_ids=(_MARKET_EVIDENCE_ID,),
            observed_at=_AS_OF - timedelta(minutes=2),
            published_at=_AS_OF - timedelta(minutes=1),
        )
        impact = evaluate_scenario(
            self._revision,
            exposures=(PortfolioExposure(asset_code=_ASSET_CODE, weight=Decimal("1")),),
            initial_value=Decimal("120000"),
            return_series=(),
        )
        return ScenarioImpactContext(
            request=request,
            revision=self._revision,
            snapshot=snapshot,
            market_data=market_data,
            impact=impact,
        )


class _ScenarioProjectionProvider:
    """Return the account projection only for its owner, cutoff, and revision."""

    def __init__(self, revision: ScenarioRevision, original_report_json: str) -> None:
        self._revision = revision
        self._original_report_json = original_report_json

    def get_pressure_projection(
        self,
        *,
        actor_user_id: int,
        account_id: int,
        scenario_revision_id: str,
        as_of_time: datetime,
    ) -> PortfolioPressureProjection | None:
        """Return only the exact fixture identity requested by the use case."""

        if (
            actor_user_id != _ACTOR_ID
            or account_id != _ACCOUNT_ID
            or scenario_revision_id != self._revision.revision_id
            or as_of_time != _AS_OF
        ):
            return None
        account_snapshot = AccountSnapshot(
            account_id=_ACCOUNT_ID,
            owner_user_id=_ACTOR_ID,
            snapshot_id=_SNAPSHOT_ID,
            read_at=_AS_OF - timedelta(minutes=1),
            cash=Decimal("0"),
            money_unit="CNY",
            holdings=(
                HeldPosition(
                    asset_code=_ASSET_CODE,
                    quantity=Decimal("10000"),
                    available_quantity=Decimal("10000"),
                    security_id=_SECURITY_ID,
                ),
            ),
            active_orders=(),
            executed_usage=(),
            active_orders_complete=True,
            execution_session=_AS_OF.date(),
            executed_usage_complete=True,
        )
        return PortfolioPressureProjection(
            portfolio_snapshot_id=_SNAPSHOT_ID,
            allocation_policy_version="test-allocation-v1",
            code_version="test-pressure-code-v1",
            scenario_revision_id=self._revision.revision_id,
            scenario_revision_hash=self._revision.content_hash,
            positions=(
                ExitPressurePosition(
                    asset_code=_ASSET_CODE,
                    quantity=Decimal("10000"),
                    quantity_unit="share",
                    market_value=Decimal("120000"),
                    pending_sell_quantity=Decimal("0"),
                    capacity_windows=(),
                ),
            ),
            source_evidence_ids=(_MARKET_EVIDENCE_ID,),
            source_evidence=(),
            account_snapshot=account_snapshot,
            identity_bindings=(
                PortfolioRiskIdentityBinding(
                    asset_code=_ASSET_CODE,
                    ledger_security_id=_SECURITY_ID,
                    source_security_id=_SECURITY_ID,
                    basis="ledger",
                ),
            ),
            native_account_limits=PortfolioRiskNativeAccountLimits(
                max_single_weight=Decimal("0.2"),
                max_total_weight=Decimal("0.95"),
                reason_codes=(),
                basis="simulated_account_percent_fields",
            ),
            money_unit_basis="native_simulated_ledger_config",
            original_report_json=self._original_report_json,
            scenario_label="Typed replay fixture",
        )


def _run_saved_evidence(
    revision: ScenarioRevision,
) -> tuple[PortfolioExitPressureRunResult, ScenarioRunEvidence, _EvidenceRepository]:
    """Persist one full pressure run using the real Risk use case and serializers."""

    original_report_json = canonical_portfolio_risk_json(_base_report())
    repository = _EvidenceRepository()
    use_case = RunPortfolioExitPressureUseCase(
        preview=_ScenarioPreview(revision),
        run_evidence_repository=repository,
        projection_provider=_ScenarioProjectionProvider(revision, original_report_json),
        clock=_FixedPressureClock(),
    )
    result = use_case.execute(
        RunPortfolioExitPressureCommand(
            actor_user_id=_ACTOR_ID,
            account_id=_ACCOUNT_ID,
            scenario_version_id=revision.revision_id,
            idempotency_key=_IDEMPOTENCY_KEY,
            confirmed=True,
        )
    )
    evidence = repository.get_run_evidence(result.evidence.run_id)
    assert evidence is not None
    return result, evidence, repository


def _scenario_revision(revision_id: str, magnitude: str) -> ScenarioRevision:
    """Build two real immutable shock revisions with distinct content hashes."""

    version = 1 if revision_id == "revision-a" else 2
    return ScenarioRevision(
        revision_id=revision_id,
        scenario_key="typed-replay-binding-test",
        version=version,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="asset",
                    target=_ASSET_CODE,
                    shock_kind="return",
                    magnitude=Decimal(magnitude),
                    unit=ShockUnit.PERCENT,
                    horizon_days=1,
                ),
            ),
            correlation_assumption="Not applicable to a single explicit shock.",
        ),
        assumptions=("Synthetic, deterministic replay-binding contract case.",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="Exercise persisted replay identity checks.",
        created_at=_AS_OF - timedelta(days=1),
    )


def _base_report() -> dict[str, object]:
    """Return a complete typed-compatible report before the pressure check is added."""

    return {
        "account_id": _ACCOUNT_ID,
        "as_of": _AS_OF.isoformat(),
        "outcome": "unknown",
        "policy_version": "test-risk-profile@1",
        "resource_snapshot_hash": "sha256:" + "b" * 64,
        "checks": [
            {
                "dimension": "industry_exposure",
                "status": "unknown",
                "reason_codes": ["SYNTHETIC_SOURCE_BOUNDARY"],
                "summary": "Synthetic source boundary.",
                "details": {},
            }
        ],
        "sources": [],
        "freshness": "unknown",
        "reliability": "unknown",
        "must_not_use_for_decision": True,
        "scope": "simulation_only",
        "must_not_execute": True,
    }


def _cross_bound_evidence(
    *,
    evidence_a: ScenarioRunEvidence,
    evidence_b: ScenarioRunEvidence,
    assessment_a: PortfolioExitPressureAssessment,
    impact_b: str,
    corruption: str,
) -> ScenarioRunEvidence:
    """Corrupt one relationship, then recompute the enclosing evidence digest."""

    result_a = _json_object(evidence_a.result_snapshot_json)
    result_b = _json_object(evidence_b.result_snapshot_json)
    if corruption == "result_revision":
        result_a["scenario_revision"] = result_b["scenario_revision"]
    elif corruption == "impact_revision":
        result_a["scenario_impact"] = result_b["scenario_impact"]
        result_a["assessment"] = result_b["assessment"]
        details_a = _pressure_details(result_a)
        details_b = _pressure_details(result_b)
        for key in ("scenario_result_hash", "scenario_impact", "pressure_result_hash"):
            details_a[key] = details_b[key]
    elif corruption == "assessment_impact":
        assessment_value = _json_object(
            canonical_portfolio_risk_json({"assessment": assessment_a})
        )["assessment"]
        assessment = cast(dict[str, object], assessment_value)
        assessment["scenario_result_hash"] = impact_b
        assessment["result_hash"] = _assessment_hash(assessment)
        result_a["assessment"] = assessment
        _pressure_details(result_a)["pressure_result_hash"] = assessment["result_hash"]
    else:
        raise AssertionError(f"unsupported replay corruption: {corruption}")

    result_json = canonical_portfolio_risk_json(result_a)
    input_json = evidence_a.input_snapshot_json
    assert input_json is not None
    return replace(
        evidence_a,
        result_snapshot_json=result_json,
        result_hash=scenario_run_snapshot_hash(
            input_snapshot_json=input_json,
            result_snapshot_json=result_json,
        ),
    )


def _assessment_hash(assessment: dict[str, object]) -> str:
    """Recompute the actual assessment digest after changing its Scenario link."""

    return portfolio_risk_content_hash(
        {
            "scenario_revision_id": assessment["scenario_revision_id"],
            "scenario_revision_hash": assessment["scenario_revision_hash"],
            "portfolio_snapshot_id": assessment["portfolio_snapshot_id"],
            "portfolio_snapshot_hash": assessment["portfolio_snapshot_hash"],
            "as_of_time": assessment["as_of_time"],
            "allocation_policy_version": assessment["allocation_policy_version"],
            "code_version": assessment["code_version"],
            "scenario_market_data_hash": assessment["scenario_market_data_hash"],
            "source_manifest_hash": assessment["source_manifest_hash"],
            "scenario_result_hash": assessment["scenario_result_hash"],
            "status": assessment["status"],
            "source_evidence_ids": assessment["source_evidence_ids"],
            "findings": assessment["findings"],
        }
    )


def _pressure_details(snapshot: dict[str, object]) -> dict[str, object]:
    """Return the persisted public pressure detail object from one result snapshot."""

    template = _object(snapshot["public_report_template"])
    checks = cast(list[object], template["checks"])
    pressure_checks = tuple(
        _object(item) for item in checks if _object(item).get("dimension") == "exit_pressure"
    )
    assert len(pressure_checks) == 1
    return _object(pressure_checks[0]["details"])


def _json_object(value: str | None) -> dict[str, object]:
    """Decode one stored evidence JSON object while retaining typed test values."""

    assert value is not None
    decoded: object = json.loads(value)
    return _object(decoded)


def _object(value: object) -> dict[str, object]:
    """Narrow decoded JSON objects for the corruption regression fixture."""

    assert isinstance(value, dict)
    return cast(dict[str, object], value)
