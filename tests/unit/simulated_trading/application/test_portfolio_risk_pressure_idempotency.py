"""Replay and collision contracts for persisted simulated pressure reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    RunPortfolioExitPressureCommand,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    portfolio_pressure_run_id,
)
from apps.risk_center.application.portfolio_pressure_report import (
    bind_portfolio_pressure_evidence_hash,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    build_portfolio_risk_order_admission,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.domain.scenarios import (
    ScenarioDefinitionStatus,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    scenario_run_snapshot_hash,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_pressure_runner import (
    PortfolioRiskPressureRunnerService,
)
from core.exceptions import DuplicateResourceError

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
ACCOUNT_ID = 42
ACTOR_ID = 77
SCENARIO_ID = "scenario-revision-8"
IDEMPOTENCY_KEY = "pressure-key-8"
SNAPSHOT_ID = f"simulated-account:{ACCOUNT_ID}:" + ("e" * 64)
ALLOCATION_POLICY_VERSION = "portfolio-risk-binding:" + ("b" * 64)


def _base_report(as_of: datetime) -> PortfolioRiskReportPayload:
    """Return one complete report whose fields are visibly distinguishable by cutoff."""

    baseline_check: PortfolioRiskCheckPayload = {
        "dimension": "baseline_risk",
        "status": "allowed",
        "reason_codes": [],
        "summary": "账户基础限制已核对",
        "details": {"basis": "source_bound"},
    }
    return {
        "account_id": ACCOUNT_ID,
        "as_of": as_of.isoformat(),
        "outcome": "allowed",
        "policy_version": "profile@7",
        "resource_snapshot_hash": portfolio_risk_content_hash(
            {
                "scenario_revision_id": SCENARIO_ID,
                "account_id": ACCOUNT_ID,
                "as_of": as_of,
            }
        ),
        "checks": [baseline_check],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
        "order_admission": build_portfolio_risk_order_admission(
            subjects=(("pressure-replay-order", "buy"),),
            checks=(baseline_check,),
            must_not_use_for_decision=False,
            subject_id="pressure-replay-subject",
        ),
    }


def _pressure_report_template(
    *,
    base_report: PortfolioRiskReportPayload,
    run_id: str,
    snapshot_hash: str,
    status: str = "partial",
) -> PortfolioRiskReportPayload:
    """Make the result template stored inside Scenario evidence, before its own hash."""

    pressure_check = {
        "dimension": "exit_pressure",
        "status": status,
        "reason_codes": ["TEST_PRESSURE_RESULT"],
        "summary": "测试压力报告",
        "details": {
            "scenario": {
                "label": "连续跌停压力",
                "revision_id": SCENARIO_ID,
                "version": 8,
                "content_sha256": "c" * 64,
            },
            "scenario_result_hash": "d" * 64,
            "pressure_result_hash": "f" * 64,
            "run_evidence_id": run_id,
            "run_evidence_persisted": True,
            "portfolio_snapshot_id": SNAPSHOT_ID,
            "portfolio_snapshot_hash": snapshot_hash,
            "capacity_findings": [],
            "capacity_windows": [],
            "source_evidence_ids": ["capacity:record-1", "market:record-1"],
            "scope": "simulation_only",
            "must_not_execute": True,
            "execution_permitted": False,
        },
    }
    return {
        **base_report,
        "checks": [*base_report["checks"], pressure_check],
        "outcome": status,
        "must_not_use_for_decision": base_report["must_not_use_for_decision"]
        or status in {"unknown", "partial"},
    }


def _saved_evidence(
    *,
    as_of: datetime,
    scenario_revision_id: str = SCENARIO_ID,
    include_original_report: bool = True,
) -> ScenarioRunEvidence:
    """Build one content-valid record using the same persisted evidence schemas."""

    run_id = portfolio_pressure_run_id(
        actor_user_id=ACTOR_ID,
        account_id=ACCOUNT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    base = _base_report(as_of)
    original_report_json = canonical_portfolio_risk_json(base) if include_original_report else None
    command = {
        "actor_user_id": ACTOR_ID,
        "account_id": ACCOUNT_ID,
        "scenario_version_id": scenario_revision_id,
        "idempotency_key": IDEMPOTENCY_KEY,
        "confirmed": True,
    }
    request = {
        "scenario_revision_id": scenario_revision_id,
        "portfolio_snapshot_id": SNAPSHOT_ID,
        "as_of_time": as_of,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
        "code_version": "server-source-sha256:" + ("9" * 64),
    }
    projection = {
        "portfolio_snapshot_id": SNAPSHOT_ID,
        "scenario_revision_id": scenario_revision_id,
        "scenario_revision_hash": "c" * 64,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
        "account_snapshot": {
            "account_id": ACCOUNT_ID,
            "owner_user_id": ACTOR_ID,
            "snapshot_id": SNAPSHOT_ID,
        },
        "original_report_json": original_report_json,
    }
    revision = {
        "revision_id": scenario_revision_id,
        "content_hash": "c" * 64,
    }
    input_payload = {
        "schema": "simulated-account-pressure-input.v1",
        "command": command,
        "request": request,
        "scenario_context": {"revision": revision},
        "account_projection": projection,
        "original_report_json": original_report_json,
        "pressure_input": {"scenario_revision_id": scenario_revision_id},
    }
    snapshot_hash = "b" * 64
    result_payload: dict[str, object] = {
        "schema": "simulated-account-pressure-result.v1",
        "scenario_revision": revision,
        "scenario_impact": {"result_hash": "d" * 64},
        "assessment": {"result_hash": "f" * 64},
    }
    if include_original_report:
        result_payload["public_report_template"] = _pressure_report_template(
            base_report=base,
            run_id=run_id,
            snapshot_hash=snapshot_hash,
        )
    input_json = canonical_portfolio_risk_json(input_payload)
    result_json = canonical_portfolio_risk_json(result_payload)
    result_hash = scenario_run_snapshot_hash(
        input_snapshot_json=input_json,
        result_snapshot_json=result_json,
    )
    return ScenarioRunEvidence(
        run_id=run_id,
        scenario_revision_id=scenario_revision_id,
        portfolio_snapshot_id=SNAPSHOT_ID,
        portfolio_snapshot_hash=snapshot_hash,
        as_of_time=as_of,
        data_evidence_ids=("capacity:record-1", "market:record-1"),
        result_hash=result_hash,
        allocation_policy_version=ALLOCATION_POLICY_VERSION,
        code_version="server-source-sha256:" + ("9" * 64),
        must_not_use_for_decision=True,
        blocked_reason="portfolio_pressure_report_not_decision_usable",
        created_at=as_of,
        input_snapshot_json=input_json,
        result_snapshot_json=result_json,
    )


class _EvidenceRepository:
    """In-memory test double for the existing immutable Scenario evidence port."""

    def __init__(self, evidence: ScenarioRunEvidence | None = None) -> None:
        self.evidence = evidence
        self.reads = 0

    def get_run_evidence(self, run_id: str) -> ScenarioRunEvidence | None:
        """Return the row only when its deterministic identity matches."""

        self.reads += 1
        if self.evidence is not None and self.evidence.run_id == run_id:
            return self.evidence
        return None


class _Clock:
    """Provide a server clock later than either prepared account snapshot."""

    def now(self) -> datetime:
        """Return the current test clock."""

        return NOW + timedelta(seconds=5)


@dataclass(frozen=True)
class _Projection:
    """Minimal immutable value that supports the runner's report binding."""

    scenario_revision_id: str
    scenario_revision_hash: str
    positions: tuple[object, ...]
    original_report_json: str | None = None
    scenario_label: str | None = None


def _prepared(as_of: datetime = NOW) -> PreparedPortfolioRisk:
    """Build a current owner context that differs from a previous cutoff report."""

    report = _base_report(as_of)
    return cast(
        PreparedPortfolioRisk,
        SimpleNamespace(
            actor_user_id=ACTOR_ID,
            snapshot=SimpleNamespace(
                account_id=ACCOUNT_ID,
                owner_user_id=ACTOR_ID,
                snapshot_id=SNAPSHOT_ID,
            ),
            report=report,
            as_of=as_of,
            resources=SimpleNamespace(native_account_limits=object()),
            policy=SimpleNamespace(profile_key="profile", profile_version=7),
            policy_binding_sha256="b" * 64,
            identity_bindings=(),
            assessment=object(),
            assets=object(),
            calendar=SimpleNamespace(
                requested_session_qualified=False,
                open_sessions=(),
                canonical_evidence_json=None,
            ),
        ),
    )


def _runner(
    repository: _EvidenceRepository, *, factory: object | None = None
) -> PortfolioRiskPressureRunnerService:
    """Assemble the runner against its existing read/write evidence dependency."""

    runtime = cast(
        PortfolioRiskRuntime,
        SimpleNamespace(
            pressure_evidence_repository=repository,
            pressure_factory=factory,
        ),
    )
    return PortfolioRiskPressureRunnerService(
        runtime=runtime,
        code_version="server-source-sha256:" + ("9" * 64),
        clock=cast(PortfolioRiskClock, _Clock()),
    )


def test_retry_with_new_cutoff_returns_original_saved_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh preparation cannot replace the report saved for the same command key."""

    import apps.simulated_trading.application.portfolio_risk_pressure_runner as runner_module

    prior_as_of = NOW - timedelta(minutes=3)
    evidence = _saved_evidence(as_of=prior_as_of)
    repository = _EvidenceRepository(evidence)
    monkeypatch.setattr(
        runner_module,
        "list_scenarios",
        lambda: pytest.fail("a replay must not re-resolve current Scenario activation"),
    )
    result = _runner(repository).run(
        prepared=_prepared(NOW),
        scenario_identifier=SCENARIO_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )

    expected_template = _pressure_report_template(
        base_report=_base_report(prior_as_of),
        run_id=evidence.run_id,
        snapshot_hash=evidence.portfolio_snapshot_hash,
    )
    assert result == bind_portfolio_pressure_evidence_hash(
        expected_template,
        evidence.result_hash,
    )
    assert result["as_of"] == prior_as_of.isoformat()
    assert result["resource_snapshot_hash"] == _base_report(prior_as_of)["resource_snapshot_hash"]
    assert repository.reads == 1
    assert evidence.allocation_policy_version == ALLOCATION_POLICY_VERSION
    assert result["order_admission"] == _base_report(prior_as_of)["order_admission"]


def test_same_key_with_different_scenario_is_a_conflict() -> None:
    """A request cannot replay evidence created for a different immutable revision."""

    repository = _EvidenceRepository(_saved_evidence(as_of=NOW))

    with pytest.raises(DuplicateResourceError):
        _runner(repository).run(
            prepared=_prepared(NOW),
            scenario_identifier="different-revision",
            idempotency_key=IDEMPOTENCY_KEY,
        )


def test_concurrent_insert_winner_is_read_back_after_content_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a same actor/account/key/scenario winner is returned after a save race."""

    import apps.simulated_trading.application.portfolio_risk_pressure_runner as runner_module

    repository = _EvidenceRepository()
    prior_as_of = NOW - timedelta(seconds=2)
    winning_evidence = _saved_evidence(as_of=prior_as_of)

    class _ConcurrentUseCase:
        def execute(self, command: RunPortfolioExitPressureCommand) -> None:
            assert command.scenario_version_id == SCENARIO_ID
            repository.evidence = winning_evidence
            raise DuplicateResourceError(message="concurrent evidence already won")

    class _Factory:
        def build(self, **kwargs: object) -> _ConcurrentUseCase:
            return _ConcurrentUseCase()

    revision = SimpleNamespace(
        revision_id=SCENARIO_ID,
        version=8,
        content_hash="c" * 64,
        status=ScenarioRevisionStatus.APPROVED,
        created_at=NOW - timedelta(days=1),
        effective_at=None,
    )
    definition = SimpleNamespace(
        status=ScenarioDefinitionStatus.ACTIVE,
        created_at=NOW - timedelta(days=10),
        name="连续跌停压力",
    )
    monkeypatch.setattr(
        runner_module,
        "list_scenarios",
        lambda: (SimpleNamespace(definition=definition, revision=revision),),
    )
    monkeypatch.setattr(
        runner_module,
        "build_portfolio_pressure_projection",
        lambda **kwargs: SimpleNamespace(
            projection=_Projection(
                scenario_revision_id=SCENARIO_ID,
                scenario_revision_hash=revision.content_hash,
                positions=(),
                original_report_json=None,
                scenario_label=None,
            ),
            portfolio_snapshot=SimpleNamespace(
                snapshot_id=SNAPSHOT_ID,
                account_id=str(ACCOUNT_ID),
                as_of_time=NOW,
            ),
            reason_codes=(),
        ),
    )
    result = _runner(repository, factory=_Factory()).run(
        prepared=_prepared(NOW),
        scenario_identifier=SCENARIO_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert result["as_of"] == prior_as_of.isoformat()
    pressure_check = next(
        check for check in result["checks"] if check["dimension"] == "exit_pressure"
    )
    assert pressure_check["details"]["run_evidence_id"] == winning_evidence.run_id
    assert repository.reads == 2


def test_legacy_evidence_without_original_report_fails_closed() -> None:
    """An old row without its original public report is never recomputed as a replay."""

    repository = _EvidenceRepository(_saved_evidence(as_of=NOW, include_original_report=False))

    with pytest.raises(DuplicateResourceError, match="无法安全复原"):
        _runner(repository).run(
            prepared=_prepared(NOW),
            scenario_identifier=SCENARIO_ID,
            idempotency_key=IDEMPOTENCY_KEY,
        )
