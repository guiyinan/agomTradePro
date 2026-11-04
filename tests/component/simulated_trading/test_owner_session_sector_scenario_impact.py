"""Exercise a multi-holding industry Scenario through the normal owner API session.

All portfolio source records, the factor membership, Scenario market envelope,
and calendar/capacity facts in this fixture are explicitly synthetic. The test
checks the real owner service, portfolio projection, Scenario calculation,
public report rendering, and ORM evidence replay; it is not market-source
acceptance and it does not represent an executed trade. Its approved Owner
profile is an explicit test fixture, not a real approval claim.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskSourceReference
from apps.risk_center.application.scenario_dtos import ScenarioMarketDataDTO
from apps.risk_center.domain.portfolio_capacity import CapacityValue, CapacityWindowObservation
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
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
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.terminal.application.tui_portfolio_risk_result import project_portfolio_risk_result
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    persisted_source_snapshot as persisted_source_snapshot,
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

_BANKS = (
    ("600036.SH", "SSE:600036", "招商银行"),
    ("601398.SH", "SSE:601398", "工商银行"),
)
_FACTOR_CODE = "C07"
_INDUSTRY_PURPOSE = "ash07_portfolio_exposure"


class _SameIndustryAssetsReader:
    """Return fully typed, test-only sources for both exact bank identities."""

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Bind every requested holding to the policy's exact synthetic source references."""

        reference_by_key = {
            (reference.kind, reference.asset_code, reference.security_id): reference
            for reference in request.policy.source_references
        }
        inputs: list[PortfolioRiskAssetInputs] = []
        evidence_rows: list[PortfolioRiskSourceEvidence] = []
        resolved_identities: set[tuple[str, str]] = set()
        for identity in request.requested_assets:
            valuation_pins = tuple(
                reference
                for reference in request.policy.source_references
                if reference.kind == "valuation" and reference.asset_code == identity.asset_code
            )
            if len(valuation_pins) != 1:
                raise AssertionError("each fixture holding requires one explicit valuation pin")
            resolved_security_id = valuation_pins[0].security_id
            if identity.security_id is not None and identity.security_id != resolved_security_id:
                raise AssertionError("known ledger identity conflicts with its source pin")
            bank = next(
                (
                    item
                    for item in _BANKS
                    if (item[0], item[1]) == (identity.asset_code, resolved_security_id)
                ),
                None,
            )
            if bank is None:
                raise AssertionError("the owner fixture requested an unconfigured bank identity")
            refs = {
                kind: reference_by_key[(kind, identity.asset_code, resolved_security_id)]
                for kind in (
                    "valuation",
                    "industry_membership",
                    "capacity_window",
                    "execution_session_state",
                )
            }
            valid_until = request.as_of + timedelta(hours=1)
            valuation = _source_evidence(
                reference=refs["valuation"],
                purpose=_INDUSTRY_PURPOSE,
                as_of=request.as_of,
                valid_until=valid_until,
                effective_on=request.business_date,
            )
            membership_evidence = _source_evidence(
                reference=refs["industry_membership"],
                purpose=_INDUSTRY_PURPOSE,
                as_of=request.as_of,
                valid_until=valid_until,
                effective_on=request.business_date,
                decision_date_cutoff=request.business_date,
            )
            membership = IndustryMembership(
                taxonomy_id=request.policy.industry_policy.taxonomy_id,
                taxonomy_kind="industry",
                provider_id=request.policy.industry_policy.provider_id,
                provider_version=request.policy.industry_policy.provider_version,
                industry_code=_FACTOR_CODE,
                effective_from=request.business_date,
                effective_end_state=EffectiveEndState.OPEN,
                source_evidence=membership_evidence,
            )
            window_end = request.execution_session - timedelta(days=1)
            capacity_evidence = _source_evidence(
                reference=refs["capacity_window"],
                purpose=request.capacity_requested_purpose,
                as_of=request.as_of,
                valid_until=valid_until,
                effective_on=window_end,
            )
            state_evidence = _source_evidence(
                reference=refs["execution_session_state"],
                purpose=request.capacity_requested_purpose,
                as_of=request.as_of,
                valid_until=valid_until,
                effective_on=request.execution_session,
            )
            capacity = CapacityWindowObservation(
                asset_code=identity.asset_code,
                security_id=resolved_security_id,
                window_kind=request.policy.capacity_policy.window_kind,
                window_start=window_end - timedelta(days=3),
                window_end=window_end,
                window_sessions=request.policy.capacity_policy.window_sessions,
                volume=CapacityValue(Decimal("1000000"), "share"),
                amount=CapacityValue(Decimal("10000000"), "CNY"),
                execution_session_suspended=False,
                execution_session_state_date=request.execution_session,
                execution_session_state_evidence=state_evidence,
                source_evidence=capacity_evidence,
            )
            inputs.append(
                PortfolioRiskAssetInputs(
                    asset_code=identity.asset_code,
                    security_id=resolved_security_id,
                    kind=PortfolioAssetKind.EQUITY,
                    price=Decimal("10"),
                    quantity_unit="share",
                    price_unit="CNY",
                    valuation_evidence=valuation,
                    industry_membership=membership,
                    etf_report=None,
                    capacity_observation=capacity,
                )
            )
            evidence_rows.extend(
                (valuation, membership_evidence, capacity_evidence, state_evidence)
            )
            resolved_identities.add((identity.asset_code, resolved_security_id))
        bindings = tuple(
            reference
            for reference in request.policy.source_references
            if (reference.asset_code, reference.security_id) in resolved_identities
        )
        return PortfolioRiskAssetsReadResult(
            status="complete",
            assets=tuple(inputs),
            all_source_evidence=tuple(evidence_rows),
            reason_codes=(),
            policy_snapshot_id=request.policy.snapshot_id,
            policy_snapshot_hash=request.policy.snapshot_hash,
            source_reference_bindings=bindings,
        )


class _SyntheticFactorMarketData:
    """Provide only a synthetic protocol envelope for the explicit factor assumption."""

    def __init__(self) -> None:
        self.reads: list[tuple[str, ...]] = []

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        """Return no market return series; the approved test Scenario carries the shock."""

        if revision.scenario_type is not ScenarioType.PARAMETRIC_SHOCK:
            raise AssertionError("the selected test Scenario must be parametric")
        self.reads.append(asset_codes)
        business_date = as_of_time.date()
        return ScenarioMarketDataDTO(
            return_series=(),
            evidence_ids=(f"synthetic-factor-envelope:{revision.revision_id}",),
            observed_at=None,
            published_at=as_of_time - timedelta(seconds=1),
            must_not_use_for_decision=False,
            blocked_reason="",
            observed_on=business_date - timedelta(days=1),
            observation_precision=SourceObservationPrecision.DATE,
        )


def _source_evidence(
    *,
    reference: PortfolioRiskSourceReference,
    purpose: str,
    as_of: datetime,
    valid_until: datetime,
    effective_on: date,
    decision_date_cutoff: date | None = None,
) -> PortfolioRiskSourceEvidence:
    """Create one explicit synthetic evidence row without claiming vendor provenance."""

    return synthetic_risk_fixtures._source_evidence(
        record_id=reference.source_record_id,
        purpose=purpose,
        as_of=as_of,
        valid_until=valid_until,
        effective_on=effective_on,
        decision_date_cutoff=decision_date_cutoff,
        precision=SourceObservationPrecision.TIMESTAMP,
    )


def _multi_bank_configuration(base: dict[str, object]) -> dict[str, object]:
    """Build the approved test profile shape with exact source pins for both banks."""

    configuration = cast(dict[str, object], json.loads(json.dumps(base)))
    configuration["account_ids"] = [synthetic_risk_fixtures._ACCOUNT_ID]
    source_references: list[dict[str, str]] = []
    for bank_index, (asset_code, security_id, _name) in enumerate(_BANKS):
        for kind_index, kind in enumerate(
            ("valuation", "industry_membership", "capacity_window", "execution_session_state")
        ):
            digest = hashlib.sha256(f"test-manifest:{asset_code}:{kind}".encode()).hexdigest()
            source_references.append(
                {
                    "kind": kind,
                    "asset_code": asset_code,
                    "security_id": security_id,
                    "raw_payload_hash": f"sha256:{digest}",
                    "source_record_id": f"synthetic-{bank_index}-{kind_index}-{kind}",
                }
            )
    configuration["source_references"] = source_references
    return configuration


def _save_approved_factor_revision() -> str:
    """Persist one isolated approved test Scenario through the real repository."""

    now = django_timezone.now()
    scenario_key = f"ash07-test-sector-factor-{uuid4().hex}"
    repository = DjangoScenarioRepository()
    definition = ScenarioDefinition(
        scenario_key=scenario_key,
        name="两家银行同步行业下跌（测试假设）",
        category="ASH07_TEST_ONLY",
        owner="tests",
        status=ScenarioDefinitionStatus.ACTIVE,
        description="显式 C07 因子冲击测试；不是市场观察或预测。",
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
                    target=_FACTOR_CODE,
                    shock_kind="return",
                    magnitude=Decimal("-0.20"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=1,
                ),
            ),
            correlation_assumption="同一测试行业内的两只股票同步承受相同假设冲击",
        ),
        assumptions=("仅为显式测试假设；幅度不是市场事实，不会生成交易或成交。",),
        source_type=ScenarioSourceType.SEED,
        created_by="ash07-owner-session-test",
        change_reason="exercise ordinary owner Scenario explanation and evidence replay",
        effective_at=now - timedelta(seconds=1),
        created_at=now,
    )
    repository.save_definition(definition)
    return repository.save_revision(revision).revision_id


def _seed_two_bank_positions(account: SimulatedAccountModel) -> tuple[PositionModel, ...]:
    """Create two test-owned holdings whose membership is explicitly supplied below."""

    positions = tuple(
        PositionModel._default_manager.create(
            account=account,
            asset_code=asset_code,
            asset_name=name,
            asset_type="equity",
            quantity=Decimal("1000"),
            available_quantity=Decimal("1000"),
            available_quantity_known=True,
            avg_cost=Decimal("9"),
            total_cost=Decimal("9000"),
            cost_basis_known=True,
            current_price=Decimal("10"),
            market_value=Decimal("10000"),
            valuation_known=True,
            unrealized_pnl=Decimal("1000"),
            unrealized_pnl_pct=11.1111,
            first_buy_date=django_timezone.localdate() - timedelta(days=1),
            first_buy_date_known=True,
        )
        for asset_code, _security_id, name in _BANKS
    )
    account.current_market_value = sum((item.market_value for item in positions), Decimal("0"))
    account.total_value = account.current_cash + account.current_market_value
    account.save(update_fields=("current_market_value", "total_value"))
    return positions


def _ledger_state(account_id: int) -> dict[str, object]:
    """Snapshot only cash, positions, orders, reservations, and trades."""

    account = SimulatedAccountModel._default_manager.get(pk=account_id)
    positions = tuple(
        PositionModel._default_manager.filter(account_id=account_id)
        .order_by("asset_code")
        .values_list("asset_code", "quantity", "available_quantity", "market_value")
    )
    return {
        "cash": str(account.current_cash),
        "market_value": str(account.current_market_value),
        "total_value": str(account.total_value),
        "positions": tuple(tuple(str(value) for value in row) for row in positions),
        "trade_count": SimulatedTradeModel._default_manager.filter(account_id=account_id).count(),
        "reservation_count": SimulatedOrderReservationModel._default_manager.filter(
            account_id=account_id
        ).count(),
    }


@pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
@override_settings(ROOT_URLCONF="tests.support.ash07_owner_acceptance_test_urls")
def test_owner_session_shows_synchronized_sector_impact_and_replays_exact_evidence(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    preserve_account_authority_generation: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose a same-factor two-bank result through the authenticated report and replay."""

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
        username=f"ash07-sector-approver-{uuid4().hex}",
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )
    profile, _created = AccountProfileModel._default_manager.update_or_create(
        user_id=owner_id,
        defaults={
            "display_name": f"ASH-07 Scenario owner {owner_id}",
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
    original_configuration = synthetic_risk_fixtures._configuration
    base_configuration = original_configuration()
    positions = _seed_two_bank_positions(account)
    assert len(positions) == 2
    monkeypatch.setattr(
        synthetic_risk_fixtures,
        "_configuration",
        lambda *, close_mode=False: _multi_bank_configuration(base_configuration),
    )
    monkeypatch.setattr(synthetic_risk_fixtures, "_AssetsReader", _SameIndustryAssetsReader)
    market_data = _SyntheticFactorMarketData()
    _install_synthetic_risk_service(
        monkeypatch=monkeypatch,
        account_id=account_id,
        owner_id=owner_id,
        asset_code=_BANKS[0][0],
        security_id=_BANKS[0][1],
        scenario_market_data_provider=market_data,
    )
    revision_id = _save_approved_factor_revision()

    client, csrf_token = ordinary_owner_session_client(owner_id)
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
    ledger_before = _ledger_state(account_id)

    options = client.get(scenarios_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert options.status_code == 200, options.content
    option_payload = options.json()
    assert option_payload["scope"] == "simulation_only"
    assert option_payload["read_only"] is True
    assert any(item["value"] == revision_id for item in option_payload["options"])
    base_report = client.get(report_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert base_report.status_code == 200, base_report.content
    assert all(check["dimension"] != "exit_pressure" for check in base_report.json()["checks"])
    assert _scenario_run_evidence_count() == evidence_before

    idempotency_key = f"ash07-sector-{uuid4().hex}"
    response = client.post(
        pressure_url,
        {"scenario_version_id": revision_id, "confirmed": True},
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 200, response.content
    assert response["Content-Type"].startswith("application/json")
    report = response.json()
    assert report["scope"] == "simulation_only"
    assert report["must_not_execute"] is True
    pressure_check = next(item for item in report["checks"] if item["dimension"] == "exit_pressure")
    details = pressure_check["details"]
    scenario_details = details["scenario"]
    assert scenario_details["label"] == "两家银行同步行业下跌（测试假设）"
    assert scenario_details["revision_id"] == revision_id
    assert scenario_details["version"] == 1
    assert "假设" in pressure_check["summary"]
    assert "不代表市场观察或已成交结果" in pressure_check["summary"]
    run_id = cast(str, details["run_evidence_id"])
    evidence = _read_scenario_run_evidence(run_id)
    assert evidence is not None
    assert evidence.scenario_revision_id == revision_id
    assert evidence.input_snapshot_json is not None
    assert evidence.result_snapshot_json is not None
    inputs = json.loads(evidence.input_snapshot_json)
    results = json.loads(evidence.result_snapshot_json)
    snapshot_positions = {
        item["asset_code"]: dict(item["attributes"])
        for item in inputs["scenario_context"]["snapshot"]["positions"]
    }
    assert set(snapshot_positions) == {item[0] for item in _BANKS}
    assert all(
        snapshot_positions[asset_code][f"factor_loading:{_FACTOR_CODE}"] == "1"
        for asset_code, _security_id, _name in _BANKS
    )
    impact = results["scenario_impact"]
    assert Decimal(impact["initial_value"]) == Decimal("120000")
    assert Decimal(impact["initial_value"]) == account.current_cash + sum(
        (Decimal("10000") for _item in _BANKS),
        Decimal("0"),
    )
    expected_return = sum(
        (
            Decimal("10000") / Decimal(impact["initial_value"]) * Decimal("-0.20")
            for _asset_code, _security_id, _name in _BANKS
        ),
        Decimal("0"),
    )
    # Compounding adds/subtracts one at the working Decimal precision. Bound
    # that representational rounding; money and saved/public values stay exact.
    rounding_bound = Decimal("1").scaleb(1 - getcontext().prec)
    assert abs(Decimal(impact["total_return"]) - expected_return) <= rounding_bound
    assert Decimal(impact["final_value"]) == Decimal("116000")
    public_impact = details["scenario_impact"]
    assert public_impact == {
        "scope": "portfolio_snapshot_net_asset_value",
        "scope_label": "全组合净值（含现金）",
        "initial_value": impact["initial_value"],
        "final_value": impact["final_value"],
        "value_unit": "CNY",
        "total_return": impact["total_return"],
        "total_return_unit": "fraction",
        "scenario_result_hash": impact["result_hash"],
        "hypothetical": True,
        "market_observation": False,
    }
    assert details["scenario_result_hash"] == impact["result_hash"]
    assert details["run_evidence_persisted"] is True
    assert details["run_evidence_result_hash"] == evidence.result_hash
    assert len(market_data.reads) == 1
    assert _scenario_run_evidence_count() == evidence_before + 1
    assert _ledger_state(account_id) == ledger_before

    tui_projection = project_portfolio_risk_result(report, http_status=200)
    assert tui_projection is not None
    rendered = json.dumps(tui_projection, ensure_ascii=False)
    assert "情景名称：两家银行同步行业下跌（测试假设）" in rendered
    assert revision_id not in rendered
    assert "情景版本：1" in rendered
    assert f"情景最终组合净值：{impact['final_value']}" in rendered
    assert "影响范围：全组合净值（含现金）" in rendered
    assert f"情景组合回报比例：{impact['total_return']}" in rendered
    assert "组合金额单位：CNY" in rendered
    assert "是否为假设情景：是" in rendered
    assert "是否为市场观察：否" in rendered

    replay_at = django_timezone.now() + timedelta(seconds=2)
    monkeypatch.setattr(django_timezone, "now", lambda: replay_at)
    replay = client.post(
        pressure_url,
        {"scenario_version_id": revision_id, "confirmed": True},
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="https://testserver",
    )
    assert replay.status_code == 200, replay.content
    assert replay.json() == report
    assert len(market_data.reads) == 1
    assert _scenario_run_evidence_count() == evidence_before + 1
    assert _read_scenario_run_evidence(run_id) == evidence
    assert _ledger_state(account_id) == ledger_before
