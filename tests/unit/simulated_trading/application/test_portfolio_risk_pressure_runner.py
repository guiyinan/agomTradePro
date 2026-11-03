"""Contract tests for the prepared-context Scenario pressure runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.domain.portfolio_exit_pressure import ExitPressureStatus
from apps.risk_center.domain.scenarios import ScenarioDefinitionStatus, ScenarioRevisionStatus
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_pressure_runner import (
    PortfolioRiskPressureRunnerService,
)

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)


def _prepared(*, policy_binding: str | None = "b" * 64) -> PreparedPortfolioRisk:
    """Return the minimum frozen consumer context used by the runner contract."""

    report: PortfolioRiskReportPayload = {
        "account_id": 42,
        "as_of": NOW.isoformat(),
        "outcome": "allowed",
        "policy_version": "industry@7",
        "resource_snapshot_hash": "sha256:" + "a" * 64,
        "checks": [],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    context = SimpleNamespace(
        actor_user_id=77,
        snapshot=SimpleNamespace(account_id=42, owner_user_id=77, snapshot_id="acct-snapshot"),
        resources=SimpleNamespace(
            native_account_limits=SimpleNamespace(),
            money_unit_basis="native_simulated_ledger_config",
        ),
        policy=SimpleNamespace(profile_key="industry", profile_version=7),
        policy_binding_sha256=policy_binding,
        identity_bindings=("identity-proof",),
        assessment=SimpleNamespace(),
        assets=SimpleNamespace(),
        calendar=SimpleNamespace(
            requested_session_qualified=True,
            open_sessions=(date(2026, 11, 3), date(2026, 11, 4)),
            canonical_evidence_json='{"schema":"calendar-test"}',
        ),
        as_of=NOW,
        business_date=date(2026, 11, 3),
        report=report,
    )
    return cast(PreparedPortfolioRisk, context)


def _summary() -> SimpleNamespace:
    """Provide one active definition with its exact approved revision identity."""

    revision = SimpleNamespace(
        revision_id="scenario-revision-8",
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
    return SimpleNamespace(definition=definition, revision=revision)


class _Clock:
    """Return a current server time after the already prepared cutoff."""

    def now(self) -> datetime:
        """Return one aware timestamp for the anti-regression check."""

        return NOW + timedelta(seconds=1)


class _EmptyEvidenceRepository:
    """Model the reader port before a pressure run has any saved evidence."""

    def get_run_evidence(self, run_id: str) -> None:
        """Return no prior record for a first run."""

        return None


@dataclass(frozen=True)
class _Projection:
    """Minimal immutable projection accepted by dataclasses.replace in the runner."""

    scenario_revision_id: str
    scenario_revision_hash: str
    positions: tuple[object, ...]
    original_report_json: str | None = None
    scenario_label: str | None = None


class _PressureUseCase:
    """Exercise the exact providers and fixed clock supplied by the runner."""

    def __init__(self, *, snapshot: object, projection: object) -> None:
        self.snapshot = snapshot
        self.projection = projection
        self.calls = 0

    def execute(self, command: object) -> SimpleNamespace:
        """Read each retained projection once and return one persisted-result shape."""

        self.calls += 1
        assert self.snapshot.get_snapshot("pressure-snapshot", as_of_time=NOW) is not None
        assert self.snapshot.get_snapshot("different-snapshot", as_of_time=NOW) is None
        projected = self.projection.get_pressure_projection(
            actor_user_id=77,
            account_id=42,
            scenario_revision_id="scenario-revision-8",
            as_of_time=NOW,
        )
        assert projected is not None
        assert (
            self.projection.get_pressure_projection(
                actor_user_id=77,
                account_id=42,
                scenario_revision_id="different-revision",
                as_of_time=NOW,
            )
            is None
        )
        assert command.scenario_version_id == "scenario-revision-8"
        assessment = SimpleNamespace(
            status=ExitPressureStatus.LIMITED,
            scenario_result_hash="d" * 64,
            result_hash="e" * 64,
            findings=(
                SimpleNamespace(
                    asset_code="600000.SH",
                    status=ExitPressureStatus.LIMITED,
                    quantity_unit="shares",
                    current_quantity=Decimal("100"),
                    pending_sell_quantity=Decimal("10"),
                    hypothetical_exitable_quantity=Decimal("60"),
                    stress_window_residual_quantity=Decimal("40"),
                    exit_sessions_required=None,
                    reason_codes=("SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED",),
                    source_evidence_ids=("capacity-source:record-1",),
                ),
            ),
        )
        evidence = SimpleNamespace(
            run_id="run-evidence-id",
            result_hash="f" * 64,
            portfolio_snapshot_id="pressure-snapshot",
            portfolio_snapshot_hash="1" * 64,
            data_evidence_ids=("capacity-source:record-1", "published-market:record-9"),
        )
        report_payload = {
            "account_id": 42,
            "as_of": NOW.isoformat(),
            "outcome": "partial",
            "policy_version": "industry@7",
            "resource_snapshot_hash": "sha256:" + "a" * 64,
            "checks": [
                {
                    "dimension": "exit_pressure",
                    "status": "partial",
                    "reason_codes": ["SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED"],
                    "summary": "模拟退出容量有限",
                    "details": {
                        "run_evidence_id": evidence.run_id,
                        "run_evidence_persisted": True,
                        "capacity_windows": [
                            {
                                "asset_code": "600000.SH",
                                "quantity_unit": "shares",
                                "windows": [
                                    {
                                        "session_date": "2026-11-04",
                                        "exitable_quantity": "0",
                                        "reason_codes": ["SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED"],
                                        "source_evidence_ids": ["capacity-source:record-1"],
                                    }
                                ],
                            }
                        ],
                        "scope": "simulation_only",
                        "must_not_execute": True,
                        "execution_permitted": False,
                    },
                }
            ],
            "sources": [],
            "freshness": "qualified_snapshot",
            "reliability": "source_bound",
            "must_not_use_for_decision": True,
            "scope": "simulation_only",
            "must_not_execute": True,
        }
        return SimpleNamespace(
            assessment=assessment,
            evidence=evidence,
            public_report_template=report_payload,
        )


class _Factory:
    """Capture the providers and fixed cutoff that the factory receives."""

    def __init__(self) -> None:
        self.use_case: _PressureUseCase | None = None
        self.clock: object | None = None

    def build(
        self, *, portfolio_provider: object, projection_provider: object, clock: object
    ) -> _PressureUseCase:
        """Return a fake Scenario use case while retaining the exact injected ports."""

        self.use_case = _PressureUseCase(
            snapshot=portfolio_provider, projection=projection_provider
        )
        self.clock = clock
        assert self.clock.now() == NOW
        return self.use_case


def test_pressure_runner_uses_one_prepared_projection_and_returns_evidence(monkeypatch) -> None:
    """A completed run keeps its exact revision, calendar and non-executable findings."""

    import apps.simulated_trading.application.portfolio_risk_pressure_runner as runner_module

    summary = _summary()
    monkeypatch.setattr(runner_module, "list_scenarios", lambda: (summary,))
    projection = _Projection(
        scenario_revision_id="scenario-revision-8",
        scenario_revision_hash=summary.revision.content_hash,
        positions=(
            SimpleNamespace(
                asset_code="600000.SH",
                quantity_unit="shares",
                capacity_windows=(
                    SimpleNamespace(
                        session_date=date(2026, 11, 4),
                        exitable_quantity=Decimal("0"),
                        reason_codes=("SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED",),
                        source_evidence_ids=("capacity-source:record-1",),
                    ),
                ),
            ),
        ),
    )
    portfolio_snapshot = SimpleNamespace(
        snapshot_id="pressure-snapshot",
        account_id="42",
        as_of_time=NOW,
    )
    builder_calls: list[dict[str, object]] = []

    def build(**values: object) -> SimpleNamespace:
        builder_calls.append(values)
        return SimpleNamespace(
            projection=projection,
            portfolio_snapshot=portfolio_snapshot,
            reason_codes=(),
        )

    monkeypatch.setattr(runner_module, "build_portfolio_pressure_projection", build)
    factory = _Factory()
    runtime = cast(
        PortfolioRiskRuntime,
        SimpleNamespace(
            pressure_factory=factory,
            pressure_evidence_repository=_EmptyEvidenceRepository(),
        ),
    )
    runner = PortfolioRiskPressureRunnerService(
        runtime=runtime,
        code_version="server-source-sha256:" + ("9" * 64),
        clock=cast(PortfolioRiskClock, _Clock()),
    )

    result = runner.run(
        prepared=_prepared(),
        scenario_identifier="scenario-revision-8",
        idempotency_key="pressure-run-8",
    )

    assert len(builder_calls) == 1
    assert builder_calls[0]["open_sessions"] == (date(2026, 11, 3), date(2026, 11, 4))
    assert builder_calls[0]["calendar_evidence_json"] == '{"schema":"calendar-test"}'
    assert builder_calls[0]["as_of_time"] == NOW
    assert builder_calls[0]["risk_policy_version"] == "industry@7"
    assert builder_calls[0]["policy_binding_sha256"] == "b" * 64
    assert builder_calls[0]["allocation_policy_version"] == ("portfolio-risk-binding:" + "b" * 64)
    assert factory.use_case is not None and factory.use_case.calls == 1
    check = result["checks"][-1]
    assert check["dimension"] == "exit_pressure"
    assert check["status"] == "partial"
    assert check["details"]["run_evidence_id"] == "run-evidence-id"
    assert check["details"]["run_evidence_persisted"] is True
    assert check["details"]["must_not_execute"] is True
    assert check["details"]["capacity_windows"][0]["windows"][0]["exitable_quantity"] == "0"
    assert result["outcome"] == "partial"
    assert result["scope"] == "simulation_only"
    assert result["must_not_execute"] is True


def test_pressure_runner_reports_unknown_when_policy_binding_is_missing(monkeypatch) -> None:
    """Missing policy identity cannot produce a Scenario run or a positive result."""

    import apps.simulated_trading.application.portfolio_risk_pressure_runner as runner_module

    monkeypatch.setattr(runner_module, "list_scenarios", lambda: (_summary(),))

    def unexpected_build(**values: object) -> None:
        raise AssertionError("a missing policy binding must stop before projection construction")

    monkeypatch.setattr(runner_module, "build_portfolio_pressure_projection", unexpected_build)
    factory = _Factory()
    runtime = cast(
        PortfolioRiskRuntime,
        SimpleNamespace(
            pressure_factory=factory,
            pressure_evidence_repository=_EmptyEvidenceRepository(),
        ),
    )
    runner = PortfolioRiskPressureRunnerService(
        runtime=runtime,
        code_version="server-source-sha256:" + ("9" * 64),
        clock=cast(PortfolioRiskClock, _Clock()),
    )

    result = runner.run(
        prepared=_prepared(policy_binding=None),
        scenario_identifier="scenario-revision-8",
        idempotency_key="pressure-run-8",
    )

    check = result["checks"][-1]
    assert check["status"] == "unknown"
    assert check["reason_codes"] == ["PORTFOLIO_PRESSURE_POLICY_BINDING_UNKNOWN"]
    assert check["details"]["run_evidence_persisted"] is False
    assert result["must_not_use_for_decision"] is True
    assert factory.use_case is None
