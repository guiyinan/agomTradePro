"""Owner-session replay evidence for synthetic halt, limit-down, and liquidity stress.

This is an isolated candidate. The two-bank positions, industry membership, capacity
numbers, execution-session state, calendar dates, and Scenario shocks are synthetic
test inputs. The test uses the real Owner session API, Scenario calculation, ORM run
evidence repository, public report, and TUI projector. It does not represent market
observations, trading permission, an order, or a fill.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.domain.portfolio_capacity import CapacityValue
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    ScenarioDefinition,
    ScenarioDefinitionStatus,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)
from apps.risk_center.infrastructure.scenario_repositories import DjangoScenarioRepository
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadRequest,
    PortfolioRiskCalendarReadResult,
)
from apps.terminal.application.tui_portfolio_risk_result import project_portfolio_risk_result
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading import (
    test_owner_session_sector_scenario_impact as sector_case,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _freeze_auto_fixture_knowledge_clocks as _freeze_auto_fixture_knowledge_clocks,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_owner_order_submission_api import (
    public_order_context as public_order_context,
)
from tests.component.simulated_trading.test_owner_order_submission_tui_browser import (
    _install_synthetic_risk_service,
    _read_scenario_run_evidence,
    _scenario_run_evidence_count,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.ash07_owner_session import ordinary_owner_session_client
from tests.unit.simulated_trading import test_portfolio_risk_service as synthetic_risk_fixtures


@dataclass(frozen=True, slots=True)
class _ExitStressCase:
    """One explicitly synthetic exit assumption and its expected windows."""

    label: str
    shock_kind: str
    magnitude: Decimal
    horizon_days: int
    expected_future_capacity: tuple[Decimal, ...]
    expected_residual: Decimal
    reason_code: str


_EXIT_STRESS_CASES = (
    _ExitStressCase(
        label="合成停牌假设（C07 因子，未来一日）",
        shock_kind="exit_halt",
        magnitude=Decimal("-1"),
        horizon_days=1,
        expected_future_capacity=(Decimal("0"),),
        expected_residual=Decimal("600"),
        reason_code="SCENARIO_EXIT_HALT_ASSUMED",
    ),
    _ExitStressCase(
        label="合成连续跌停假设（C07 因子，未来两日）",
        shock_kind="exit_limit_down_lock",
        magnitude=Decimal("-1"),
        horizon_days=2,
        expected_future_capacity=(Decimal("0"), Decimal("0")),
        expected_residual=Decimal("600"),
        reason_code="SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED",
    ),
    _ExitStressCase(
        label="合成流动性下降假设（C07 因子，未来容量减半）",
        shock_kind="exit_liquidity_change",
        magnitude=Decimal("-0.5"),
        horizon_days=1,
        expected_future_capacity=(Decimal("200"),),
        expected_residual=Decimal("400"),
        reason_code="SCENARIO_EXIT_LIQUIDITY_CHANGE_ASSUMED",
    ),
)


class _ConstrainedSyntheticAssetsReader(sector_case._SameIndustryAssetsReader):
    """Retain the existing exact source bindings with a small test-only capacity."""

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Use 1,000 synthetic shares across the existing two-session window."""

        result = super().read_assets(request)
        assets = []
        for item in result.assets:
            observation = item.capacity_observation
            if observation is None:
                raise AssertionError("each synthetic bank needs its typed capacity window")
            assets.append(
                replace(
                    item,
                    capacity_observation=replace(
                        observation,
                        volume=CapacityValue(Decimal("1000"), "share"),
                    ),
                )
            )
        return replace(result, assets=tuple(assets))


class _SyntheticFutureCalendarReader:
    """Supply three explicitly synthetic candidate sessions for future windows."""

    def read_calendar(
        self, request: PortfolioRiskCalendarReadRequest
    ) -> PortfolioRiskCalendarReadResult:
        """Return the requested session and two synthetic subsequent sessions."""

        open_sessions = tuple(
            request.requested_session + timedelta(days=offset) for offset in range(3)
        )
        evidence = canonical_portfolio_risk_json(
            {
                "fixture": "ASH07 synthetic exit-stress calendar",
                "requested_session": request.requested_session,
                "open_sessions": open_sessions,
                "asset_pairs": tuple(
                    (item.asset_code, item.security_id) for item in request.requested_assets
                ),
            }
        )
        return PortfolioRiskCalendarReadResult(
            requested_session_qualified=True,
            open_sessions=open_sessions,
            reason_codes=(),
            canonical_evidence_json=evidence,
            evidence_hash=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            valid_until=request.as_of + timedelta(hours=1),
        )


def _save_approved_exit_revision(case: _ExitStressCase) -> str:
    """Persist one test-only approved revision through the existing repository."""

    now = django_timezone.now()
    scenario_key = f"ash07-test-exit-stress-{uuid4().hex}"
    repository = DjangoScenarioRepository()
    definition = ScenarioDefinition(
        scenario_key=scenario_key,
        name=case.label,
        category="ASH07_TEST_ONLY",
        owner="tests",
        status=ScenarioDefinitionStatus.ACTIVE,
        description=("合成 C07 假设，用于核对退出能力说明；不代表市场事实，也不生成交易或成交。"),
        created_at=now,
    )
    revision = ScenarioRevision(
        revision_id=str(uuid4()),
        scenario_key=scenario_key,
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="factor",
                    target=sector_case._FACTOR_CODE,
                    shock_kind="return",
                    magnitude=Decimal("-0.20"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=1,
                ),
                ParametricShock(
                    target_kind="factor",
                    target=sector_case._FACTOR_CODE,
                    shock_kind=case.shock_kind,
                    magnitude=case.magnitude,
                    unit=ShockUnit.PERCENT,
                    horizon_days=case.horizon_days,
                ),
            ),
            correlation_assumption=(
                "两家合成银行证券共享 C07；压力冲击和退出假设均仅用于软件验收。"
            ),
        ),
        assumptions=(
            "C07 -20% 和退出约束均为显式测试假设，不是行情、交易所状态或市场预测。",
            "任何假设容量都不是订单、成交或持仓释放。",
        ),
        source_type=ScenarioSourceType.SEED,
        created_by="ash07-owner-exit-stress-test",
        change_reason="exercise persisted owner-facing exit-stress evidence",
        effective_at=now - timedelta(seconds=1),
        created_at=now,
    )
    repository.save_definition(definition)
    return repository.save_revision(revision).revision_id


def _find_pressure_check(report: dict[str, object]) -> dict[str, object]:
    """Return the single typed pressure check from one public JSON report."""

    checks = report.get("checks")
    if type(checks) is not list:
        raise AssertionError("the Owner report must retain a checks list")
    matches = [
        item for item in checks if type(item) is dict and item.get("dimension") == "exit_pressure"
    ]
    if len(matches) != 1:
        raise AssertionError("each pressure run must return exactly one exit-pressure check")
    return cast(dict[str, object], matches[0])


def _assert_case_report(
    *,
    report: dict[str, object],
    case: _ExitStressCase,
    revision_id: str,
    account_id: int,
) -> None:
    """Assert public per-asset constrained quantities and original assumption reasons."""

    assert report["account_id"] == account_id
    assert report["scope"] == "simulation_only"
    assert report["must_not_execute"] is True
    check = _find_pressure_check(report)
    details_value = check.get("details")
    if type(details_value) is not dict:
        raise AssertionError("exit-pressure check has no public detail object")
    details = cast(dict[str, object], details_value)
    scenario = details.get("scenario")
    if type(scenario) is not dict:
        raise AssertionError("Scenario identity is absent from public pressure details")
    assert scenario["label"] == case.label
    assert scenario["revision_id"] == revision_id
    assert details["scope"] == "simulation_only"
    assert details["must_not_execute"] is True
    assert details["execution_permitted"] is False

    raw_findings = details.get("capacity_findings")
    raw_windows = details.get("capacity_windows")
    if type(raw_findings) is not list or type(raw_windows) is not list:
        raise AssertionError("public pressure report must include capacity findings and windows")
    findings = {item["asset_code"]: item for item in raw_findings if type(item) is dict}
    windows = {item["asset_code"]: item for item in raw_windows if type(item) is dict}
    expected_assets = {item[0] for item in sector_case._BANKS}
    assert set(findings) == expected_assets
    assert set(windows) == expected_assets
    for asset_code in expected_assets:
        finding = findings[asset_code]
        assert finding["status"] == "limited"
        assert Decimal(finding["current_quantity"]) == Decimal("1000")
        assert Decimal(finding["hypothetical_exitable_quantity"]) == (
            Decimal("1000") - case.expected_residual
        )
        assert Decimal(finding["stress_window_residual_quantity"]) == case.expected_residual
        assert finding["exit_sessions_required"] is None
        assert case.reason_code in finding["reason_codes"]

        asset_windows = windows[asset_code]["windows"]
        assert type(asset_windows) is list
        assert len(asset_windows) == 1 + len(case.expected_future_capacity)
        assert Decimal(asset_windows[0]["exitable_quantity"]) == Decimal("400")
        future_windows = asset_windows[1:]
        assert (
            tuple(Decimal(item["exitable_quantity"]) for item in future_windows)
            == case.expected_future_capacity
        )
        assert all(case.reason_code in item["reason_codes"] for item in future_windows)
        assert all(item["source_evidence_ids"] for item in future_windows)

    assert case.reason_code in check["reason_codes"]


@pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
@override_settings(ROOT_URLCONF="tests.support.ash07_owner_acceptance_test_urls")
def test_owner_session_persists_and_replays_halt_limit_down_and_liquidity_stress(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    preserve_account_authority_generation: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save all three synthetic exit cases through the ordinary Owner API session."""

    del preserve_account_authority_generation
    context, _market_calls = public_order_context
    account = context.account
    account_id = cast(int, account.pk)
    owner_id = context.owner_id
    user_model = get_user_model()
    owner = user_model._default_manager.get(pk=owner_id)
    assert owner.is_active is True
    assert owner.is_staff is False
    assert owner.is_superuser is False
    approver = user_model._default_manager.create_user(
        username=f"ash07-exit-approver-{uuid4().hex}",
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )
    profile, _created = AccountProfileModel._default_manager.update_or_create(
        user_id=owner_id,
        defaults={
            "display_name": f"ASH-07 exit-stress Owner {owner_id}",
            "rbac_role": "owner",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "agreement_accepted_at": django_timezone.now(),
            "approval_status": "approved",
            "approved_at": django_timezone.now(),
            "approved_by": approver,
        },
    )
    assert profile.rbac_role == "owner"
    assert profile.approval_status == "approved"
    assert profile.user_agreement_accepted is True
    assert profile.risk_warning_acknowledged is True
    assert profile.approved_by_id == approver.pk
    assert profile.approved_by_id != owner_id
    assert account.cash_known is True

    base_configuration = synthetic_risk_fixtures._configuration()
    positions = sector_case._seed_two_bank_positions(account)
    assert len(positions) == 2
    monkeypatch.setattr(
        synthetic_risk_fixtures,
        "_configuration",
        lambda *, close_mode=False: sector_case._multi_bank_configuration(base_configuration),
    )
    monkeypatch.setattr(synthetic_risk_fixtures, "_AssetsReader", _ConstrainedSyntheticAssetsReader)
    monkeypatch.setattr(synthetic_risk_fixtures, "_CalendarReader", _SyntheticFutureCalendarReader)
    market_data = sector_case._SyntheticFactorMarketData()
    _install_synthetic_risk_service(
        monkeypatch=monkeypatch,
        account_id=account_id,
        owner_id=owner_id,
        asset_code=sector_case._BANKS[0][0],
        security_id=sector_case._BANKS[0][1],
        scenario_market_data_provider=market_data,
    )

    revisions = tuple((case, _save_approved_exit_revision(case)) for case in _EXIT_STRESS_CASES)
    client, csrf_token = ordinary_owner_session_client(owner_id)
    assert csrf_token
    scenarios_url = reverse(
        "api_simulated_trading:portfolio-pressure-scenarios",
        kwargs={"account_id": account_id},
    )
    report_url = reverse(
        "api_simulated_trading:portfolio-risk-report",
        kwargs={"account_id": account_id},
    )
    pressure_url = reverse(
        "api_simulated_trading:portfolio-pressure-run",
        kwargs={"account_id": account_id},
    )
    evidence_before = _scenario_run_evidence_count()
    ledger_before = sector_case._ledger_state(account_id)

    options = client.get(scenarios_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert options.status_code == 200, options.content
    option_payload = options.json()
    assert option_payload["scope"] == "simulation_only"
    assert option_payload["read_only"] is True
    assert all(
        any(item["value"] == revision_id for item in option_payload["options"])
        for _case, revision_id in revisions
    )
    base_report = client.get(report_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert base_report.status_code == 200, base_report.content
    assert all(item["dimension"] != "exit_pressure" for item in base_report.json()["checks"])
    assert _scenario_run_evidence_count() == evidence_before

    for case, revision_id in revisions:
        run_count_before = _scenario_run_evidence_count()
        reads_before = len(market_data.reads)
        idempotency_key = f"ash07-exit-stress-{uuid4().hex}"
        headers = {
            "secure": True,
            "HTTP_IDEMPOTENCY_KEY": idempotency_key,
            "HTTP_X_CSRFTOKEN": csrf_token,
            "HTTP_ORIGIN": "https://testserver",
        }
        response = client.post(
            pressure_url,
            {"scenario_version_id": revision_id, "confirmed": True},
            format="json",
            **headers,
        )
        assert response.status_code == 200, response.content
        assert response["Content-Type"].startswith("application/json")
        report = cast(dict[str, object], response.json())
        _assert_case_report(
            report=report,
            case=case,
            revision_id=revision_id,
            account_id=account_id,
        )

        check = _find_pressure_check(report)
        details = cast(dict[str, object], check["details"])
        run_id = cast(str, details["run_evidence_id"])
        assert details["run_evidence_persisted"] is True
        evidence = _read_scenario_run_evidence(run_id)
        assert evidence is not None
        assert evidence.scenario_revision_id == revision_id
        assert evidence.input_snapshot_json is not None
        assert evidence.result_snapshot_json is not None
        assert evidence.result_hash
        assert details["run_evidence_result_hash"] == evidence.result_hash
        saved_inputs = json.loads(evidence.input_snapshot_json)
        saved_results = json.loads(evidence.result_snapshot_json)
        saved_results_hash = saved_results["assessment"]["result_hash"]
        assert details["pressure_result_hash"] == saved_results_hash
        assert saved_inputs["command"]["scenario_version_id"] == revision_id
        assert saved_results["scenario_revision"]["revision_id"] == revision_id
        stored_assessment = saved_results["assessment"]
        assert stored_assessment["result_hash"] == saved_results_hash
        assert stored_assessment["status"] == "limited"
        stored_findings = {item["asset_code"]: item for item in stored_assessment["findings"]}
        assert set(stored_findings) == {item[0] for item in sector_case._BANKS}
        for finding in stored_findings.values():
            assert case.reason_code in finding["reason_codes"]
            assert Decimal(finding["stress_window_residual_quantity"]) == case.expected_residual
            assert Decimal(finding["unreleased_exposure_quantity"]) == Decimal("1000")

        pressure_positions = {
            item["asset_code"]: item for item in saved_inputs["pressure_input"]["positions"]
        }
        assert set(pressure_positions) == {item[0] for item in sector_case._BANKS}
        for pressure_position in pressure_positions.values():
            windows = pressure_position["capacity_windows"]
            assert case.reason_code in tuple(
                reason for window in windows for reason in window["reason_codes"]
            )

        assert _scenario_run_evidence_count() == run_count_before + 1
        assert len(market_data.reads) == reads_before + 1
        assert sector_case._ledger_state(account_id) == ledger_before

        tui_projection = project_portfolio_risk_result(report, http_status=200)
        assert tui_projection is not None
        rendered = json.dumps(tui_projection, ensure_ascii=False)
        assert f"情景名称：{case.label}" in rendered
        assert "情景版本：1" in rendered
        assert revision_id not in rendered
        assert "是否为假设情景：是" in rendered
        assert "是否为市场观察：否" in rendered

        frozen_hashes = (
            evidence.result_hash,
            evidence.input_snapshot_json,
            evidence.result_snapshot_json,
        )
        replay_at = django_timezone.now() + timedelta(seconds=2)
        with monkeypatch.context() as replay_clock:
            replay_clock.setattr(django_timezone, "now", lambda replay_at=replay_at: replay_at)
            replay = client.post(
                pressure_url,
                {"scenario_version_id": revision_id, "confirmed": True},
                format="json",
                **headers,
            )
        assert replay.status_code == 200, replay.content
        assert replay.json() == report
        replayed = _read_scenario_run_evidence(run_id)
        assert replayed == evidence
        assert frozen_hashes == (
            replayed.result_hash,
            replayed.input_snapshot_json,
            replayed.result_snapshot_json,
        )
        assert _scenario_run_evidence_count() == run_count_before + 1
        assert len(market_data.reads) == reads_before + 1
        assert sector_case._ledger_state(account_id) == ledger_before

    assert _scenario_run_evidence_count() == evidence_before + len(_EXIT_STRESS_CASES)
