"""Ordinary-owner NAV coverage using a real published raw daily close.

Owner, calendar publication, retained-price qualification, posting, tax, and
balance checks use production compositions.
The market notice and exact captured price response are explicitly synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.m1_reference_price_publication import (
    M1ReferencePricePublicationCommand,
)
from apps.data_center.application.price_response_capture import (
    CapturedPriceBarResponse,
    ExactPriceBarRequestScope,
)
from apps.data_center.application.public_published_queries import get_published_price_bar_source
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.market_time import latest_closed_cn_market_session
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.m1_reference_price_publication_composition import (
    build_m1_reference_price_publication_use_case,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.corporate_action_nav_mark_composition import (
    CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY,
    build_corporate_action_nav_raw_mark_reader,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.models import PositionModel
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_fixture import (
    FormalCalendarFixture,
    persist_auto_uow_formal_calendar,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
    recover_owner_workflow_operator_authority,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.ash07_owner_m1_price_batch import ensure_m1_price_publication_catalog
from tests.support.simulated_tax_model_native_context import _TIMEZONE
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

_API_ROOT = "/api/simulated-trading/accounts/{account_id}/corporate-actions/"
_CONSENT_ROOT = "/api/simulated-trading/accounts/{account_id}/corporate-action-consent/"
_WORKFLOW_URLCONF = "tests.support.ash05_owner_workflow_test_urls"
_NAV_SCHEMA = "simulated.corporate_action.nav_raw_mark_configuration.v1"
_NAV_POLICY_SCHEMA = "simulated-corporate-action-nav-raw-mark-policy.v1"
_NAV_PURPOSE = "simulated_corporate_action_nav_raw_mark"
_PRICE_CLOSE = Decimal("11.47")


class _SyntheticExactDailyPriceProvider:
    """Return one exact synthetic Tushare-shaped response through Data Center."""

    def __init__(self, *, provider_id: int, provider_name: str) -> None:
        self._provider_id = provider_id
        self._provider_name = provider_name

    def provider_name(self) -> str:
        """Return the exact name persisted in the provider configuration row."""
        return self._provider_name

    def supports(self, capability: DataCapability) -> bool:
        """Expose only the historical-price capability used by this publication."""
        return capability is DataCapability.HISTORICAL_PRICE

    def fetch_price_history(self, asset_code: str, start: date, end: date) -> list[PriceBar]:
        """Reject the historical fallback; this test requires the exact daily path."""
        del asset_code, start, end
        raise AssertionError("the NAV fixture must use one exact daily capture")

    def fetch_price_bar_with_capture(
        self, asset_code: str, target_trade_date: date
    ) -> CapturedPriceBarResponse:
        """Return captured response bytes for the production exact-price validator."""
        completed_at = timezone.now().astimezone(UTC)
        scope = ExactPriceBarRequestScope(
            provider_id=self._provider_id,
            provider_name=self._provider_name,
            dataset_key="equity.price.bar",
            api_name="daily",
            asset_code=asset_code,
            trade_date=target_trade_date,
        )
        payload: dict[str, object] = {
            "code": 0,
            "msg": "",
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ],
                "items": [
                    [
                        asset_code,
                        target_trade_date.strftime("%Y%m%d"),
                        11.4,
                        11.5,
                        11.3,
                        11.47,
                        200,
                        2100,
                    ]
                ],
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        capture = ProviderResponseCapture(
            body=body,
            payload=parse_provider_response_json(body),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=completed_at,
            status_code=200,
            content_type="application/json",
            transport=ProviderResponseTransport.DIRECT,
        )
        bar = PriceBar(
            asset_code=asset_code,
            bar_date=target_trade_date,
            open=11.4,
            high=11.5,
            low=11.3,
            close=float(_PRICE_CLOSE),
            volume=20_000.0,
            amount=2_100_000.0,
            freq="1d",
            adjustment=PriceAdjustment.NONE,
            source="tushare",
            fetched_at=completed_at,
        )
        return CapturedPriceBarResponse(request_scope=scope, bar=bar, capture=capture)


def _post(
    world: OwnerWorkflowNativeWorld,
    path: str,
    body: dict[str, object],
    *,
    expected_status: int = 200,
) -> dict[str, object]:
    """Call one real Session/CSRF JSON endpoint and validate its response contract."""
    response = world.owner.client.post(
        path,
        body,
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=world.owner.csrf_token,
    )
    if response.status_code != expected_status:
        raise AssertionError("unexpected owner HTTP status")
    assert response.headers.get("Content-Type", "").startswith("application/json")
    payload = response.json()
    if not (isinstance(payload, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    return payload


def _read(world: OwnerWorkflowNativeWorld) -> dict[str, object]:
    """Read the actual owner-scoped balance and retained receipt endpoint."""
    response = world.owner.client.get(
        _API_ROOT.format(account_id=world.account_id),
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=world.owner.csrf_token,
    )
    if response.status_code != 200:
        raise AssertionError("unexpected owner HTTP status")
    assert response.headers.get("Content-Type", "").startswith("application/json")
    payload = response.json()
    if not (isinstance(payload, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    return payload


def _refresh(world: OwnerWorkflowNativeWorld) -> dict[str, object]:
    """Refresh actual owner evidence, renewing only the separate test operator."""
    if CorporateActionPostingModel.objects.filter(account_id=world.account_id).exists():
        recover_owner_workflow_operator_authority(world)
    payload = _post(
        world,
        _API_ROOT.format(account_id=world.account_id) + "refresh/",
        {"account_id": world.account_id, "confirmed": True},
    )
    assert payload.get("outcome") == "success", payload.get("blocking_reason")
    return payload


def _select_cash_and_tax_capabilities(world: OwnerWorkflowNativeWorld) -> None:
    """Obtain explicit V3 cash, assessment, and withholding consent from the owner."""
    path = _CONSENT_ROOT.format(account_id=world.account_id)
    prepared = _post(
        world,
        path + "prepare/",
        {
            "cash_dividend": True,
            "share_distribution": False,
            "rights_not_exercised": False,
            "tax_assessment": True,
            "tax_withholding": True,
        },
    )
    expected = sorted(
        [
            Capability.CASH_STAGE_WRITE.value,
            Capability.TAX_ASSESS.value,
            Capability.TAX_WITHHOLD.value,
        ]
    )
    assert prepared.get("selected_capabilities") == expected
    continuation = prepared.get("continuation")
    if not (isinstance(continuation, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    inputs = continuation.get("input")
    if not (isinstance(inputs, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    token = inputs.get("consent_token")
    if not (isinstance(token, str) and token.startswith("v3.")):
        raise AssertionError("owner response or sealed continuation is unavailable")
    confirmed = _post(
        world,
        path,
        {"consent_token": token, "confirmed": True},
    )
    assert confirmed.get("selected_capabilities") == expected


def _perform_operation(
    world: OwnerWorkflowNativeWorld,
    *,
    event_id: str,
    action: str,
    settlement_date: date | None = None,
) -> dict[str, object]:
    """Prepare and confirm server-derived financial facts through the owner API."""
    body: dict[str, object] = {"event_id": event_id, "action": action}
    if settlement_date is not None:
        body["settlement_date"] = settlement_date.isoformat()
    path = _API_ROOT.format(account_id=world.account_id)
    prepared = _post(world, path + "prepare/", body)
    assert prepared.get("outcome") == "success", prepared.get("blocking_reason")
    continuation = prepared.get("continuation")
    if not (isinstance(continuation, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    inputs = continuation.get("input")
    if not (isinstance(inputs, dict)):
        raise AssertionError("owner response or sealed continuation is unavailable")
    token = inputs.get("continuation_token")
    if not (isinstance(token, str) and token):
        raise AssertionError("owner response or sealed continuation is unavailable")
    completed = _post(
        world,
        path + "confirm/",
        {
            "account_id": str(world.account_id),
            "continuation_token": token,
            "confirmed": True,
        },
    )
    assert completed.get("outcome") == "success", completed.get("blocking_reason")
    return completed


def _event_id(world: OwnerWorkflowNativeWorld, refreshed: dict[str, object]) -> str:
    """Select the single current synthetic notice returned by the real owner source path."""
    events = refreshed.get("events")
    assert isinstance(events, list) and len(events) == 1
    event = events[0]
    assert isinstance(event, dict)
    assert event.get("asset_code") == world.asset_code
    identifier = event.get("event_id")
    assert isinstance(identifier, str) and identifier
    return identifier


def _publish_synthetic_raw_close(
    *, world: OwnerWorkflowNativeWorld, calendar: FormalCalendarFixture
) -> date:
    """Capture, retain, stage, and activate one synthetic exact daily close."""
    open_sessions = frozenset(day.calendar_date for day in calendar.snapshot.days if day.is_open)
    trade_date = latest_closed_cn_market_session(
        timezone.now().astimezone(UTC), open_sessions=open_sessions
    )
    assert trade_date is not None
    ensure_m1_price_publication_catalog()
    provider_name = f"ASH05 synthetic NAV Tushare {uuid4().hex}"
    provider_row = ProviderConfigModel._default_manager.create(
        name=provider_name,
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={"synthetic_fixture": True},
        description="Synthetic exact daily bar for ASH-05 owner NAV validation.",
    )
    assert provider_row.pk is not None
    provider_id = int(provider_row.pk)
    provider_repository = ProviderConfigRepository()
    provider_registry = ProviderRegistry()
    provider_registry.register(
        _SyntheticExactDailyPriceProvider(
            provider_id=provider_id,
            provider_name=provider_name,
        ),
        priority=1,
        provider_id=provider_id,
        source_type="tushare",
    )
    publication = build_m1_reference_price_publication_use_case(
        provider_repository=provider_repository,
        provider_registry=provider_registry,
        environment="development",
    ).execute(
        M1ReferencePricePublicationCommand(
            provider_id=provider_id,
            asset_code=world.asset_code,
            target_trade_date=trade_date,
        )
    )
    assert publication.publication.selected_source == "tushare"
    result = get_published_price_bar_source(
        world.asset_code,
        trade_date=trade_date,
        knowledge_cutoff=timezone.now().astimezone(UTC),
        publication_key=publication.publication.publication_key,
    )
    assert result.evidence is not None, result.blocked_reason
    assert result.evidence.publication_id == publication.publication.publication_id
    assert result.evidence.trade_date == trade_date
    assert result.evidence.source == "tushare"
    assert result.evidence.values.close == _PRICE_CLOSE
    assert result.evidence.source_observed_at is None
    assert (
        result.evidence.local_known_at
        == result.evidence.raw_payload_reference.response_completed_at
    )
    return trade_date


def _runtime_asset_type(world: OwnerWorkflowNativeWorld) -> str:
    """Resolve the explicit active simulated asset type from current source identity."""
    classification = build_current_reference_classification_reader(
        runtime_environment="development"
    ).resolve_simulated_instrument_classification(
        security_id=world.security_id,
        asset_code=world.asset_code,
        as_of=timezone.now().astimezone(UTC),
    )
    assert classification is not None
    return classification.simulated_asset_type


def _query(world: OwnerWorkflowNativeWorld) -> SimulatedCorporateActionNavRawMarkQuery:
    """Bind the real owner and the current explicitly classified instrument."""
    return SimulatedCorporateActionNavRawMarkQuery(
        physical_account_id=world.account_id,
        canonical_account_id=world.canonical_account_id,
        owner_user_id=int(world.owner.owner.pk),
        security_id=world.security_id,
        asset_code=world.asset_code,
        asset_type=_runtime_asset_type(world),
    )


def _activate_raw_mark_policy(
    *,
    world: OwnerWorkflowNativeWorld,
    publication_key: str,
) -> None:
    """Activate one explicit finite NAV-only price policy in Config Center."""
    now = timezone.now().astimezone(UTC)
    policy = SimulatedCorporateActionNavRawMarkPolicy(
        schema_version=_NAV_POLICY_SCHEMA,
        purpose=_NAV_PURPOSE,
        policy_id=f"ash05-nav-{uuid4().hex}",
        version="1",
        source="tushare",
        publication_key=publication_key,
        frequency="1d",
        adjustment="none",
        observation_basis="daily_interval_end",
        currency="CNY",
        supported_asset_types=(_runtime_asset_type(world),),
        freshness_window_seconds=604_800,
    )
    activate_runtime_profile_patch(
        environment="development",
        patch={
            CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY: {
                "schema": _NAV_SCHEMA,
                "policy": policy.to_payload(),
                "valid_from": (now - timedelta(seconds=1)).isoformat(),
                "valid_until": (now + timedelta(hours=2)).isoformat(),
            }
        },
        actor="ash05-synthetic-owner-nav-test",
        reason="explicit finite raw-price-only NAV source policy for one simulated owner scope",
    )


def _amount(payload: dict[str, object], name: str) -> Decimal:
    value = payload.get(name)
    assert type(value) is str, name
    return Decimal(value)


def _assert_nav_identity(
    *,
    world: OwnerWorkflowNativeWorld,
    payload: dict[str, object],
    trade_date: date,
) -> Decimal:
    """Reconcile public owner NAV to raw close, physical quantity, cash, rights, and tax."""
    assert payload.get("freshness_status") == "qualified_closed_session_valuation"
    assert payload.get("reliability_status") == "original_ledger_and_current_sources_verified"
    marked = build_corporate_action_nav_raw_mark_reader(
        runtime_environment="development",
        calendar_dataset_key=world.calendar_dataset_key,
    ).read_current_mark(_query(world))
    assert marked is not None
    assert marked.query.physical_account_id == world.account_id
    assert marked.query.canonical_account_id == world.canonical_account_id
    assert marked.query.owner_user_id == world.owner.owner.pk
    assert marked.trade_date == trade_date
    assert marked.calendar.snapshot.exchange == "SZSE"
    assert marked.source_evidence.publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert marked.source_evidence.source == "tushare"
    assert marked.source_observed_at is None
    assert (
        marked.source_evidence.local_known_at
        == marked.source_evidence.raw_payload_reference.response_completed_at
    )
    assert marked.source_evidence.local_known_at <= marked.checked_at
    assert marked.must_not_use_for_decision is True

    position = PositionModel._default_manager.get(
        account_id=world.account_id,
        asset_code=world.asset_code,
    )
    assert position.quantity == Decimal("70.000000")
    assert position.current_price is not None
    assert Decimal(position.current_price) != marked.price
    cash = _amount(payload, "book_cash")
    receivable = _amount(payload, "dividend_receivable")
    tax = _amount(payload, "tax_payable")
    with localcontext() as context:
        context.prec = 96
        expected = cash + Decimal(position.quantity) * marked.price + receivable - tax
    actual = _amount(payload, "net_asset_value")
    assert actual == expected
    dates = payload.get("valuation_trade_dates")
    assert dates == [trade_date.isoformat()]
    return actual


def test_owner_nav_requires_current_raw_close_policy_and_full_tax_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Show missing NAV evidence blocks, then reconcile current raw close and tax debt."""
    if connection.vendor != "postgresql":
        pytest.skip("the ordinary-owner NAV journey needs the assigned migrated PostgreSQL DB")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF), isolated_task_channels():
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        szse_calendar = persist_auto_uow_formal_calendar(
            as_of=timezone.now().astimezone(UTC),
            exchange="SZSE",
            timezone_name=_TIMEZONE,
            live_clock=True,
            require_current_open_session=False,
        )
        assert szse_calendar.dataset_key == world.calendar_dataset_key
        activate_runtime_profile_patch(
            environment="development",
            patch={
                "config_center.market.exchange_timezone_map": {
                    "SZ": _TIMEZONE,
                    "SZSE": _TIMEZONE,
                }
            },
            actor="ash05-synthetic-owner-nav-calendar-scope",
            reason="retain both explicit source-exchange and rule-market calendar timezones",
        )
        trade_date = _publish_synthetic_raw_close(world=world, calendar=szse_calendar)

        refreshed = _refresh(world)
        event_id = _event_id(world, refreshed)
        _select_cash_and_tax_capabilities(world)
        _perform_operation(world, event_id=event_id, action="cash_entitlement")

        _refresh(world)
        _select_cash_and_tax_capabilities(world)
        _perform_operation(world, event_id=event_id, action="cash_payment")

        _refresh(world)
        _select_cash_and_tax_capabilities(world)
        _perform_operation(
            world,
            event_id=event_id,
            action="tax_assess",
            settlement_date=world.settlement_date,
        )

        _refresh(world)
        _select_cash_and_tax_capabilities(world)
        _perform_operation(
            world,
            event_id=event_id,
            action="tax_recognize",
            settlement_date=world.settlement_date,
        )

        query = _query(world)
        from apps.simulated_trading.corporate_action_nav_mark_composition import (
            ConfiguredCorporateActionNavRawMarkPolicyReader,
        )

        unconfigured = ConfiguredCorporateActionNavRawMarkPolicyReader(
            environment="development"
        ).read_policy(query=query, as_of=timezone.now().astimezone(UTC))
        assert unconfigured is None
        before_policy = _read(world)
        assert before_policy.get("tax_coverage_status") == "complete"
        assert before_policy.get("net_asset_value") is None
        assert type(before_policy.get("book_cash")) is str
        assert type(before_policy.get("spendable_cash")) is str
        assert type(before_policy.get("dividend_receivable")) is str
        assert _amount(before_policy, "tax_payable") > 0
        legacy_position = PositionModel._default_manager.get(
            account_id=world.account_id,
            asset_code=world.asset_code,
        )
        assert legacy_position.current_price is not None
        assert before_policy.get("must_not_use_for_decision") is True

        _activate_raw_mark_policy(
            world=world,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        _refresh(world)
        recognized = _read(world)
        assert recognized.get("tax_coverage_status") == "complete"
        assert _amount(recognized, "tax_payable") > 0
        assert _amount(recognized, "dividend_receivable") == Decimal("0.00")
        assert _amount(recognized, "spendable_cash") == max(
            Decimal("0"), _amount(recognized, "book_cash") - _amount(recognized, "tax_payable")
        )
        nav_before_collect = _assert_nav_identity(
            world=world,
            payload=recognized,
            trade_date=trade_date,
        )

        _refresh(world)
        _select_cash_and_tax_capabilities(world)
        _perform_operation(
            world,
            event_id=event_id,
            action="tax_collect",
            settlement_date=world.settlement_date,
        )
        _refresh(world)
        collected = _read(world)
        assert collected.get("tax_coverage_status") == "complete"
        assert _amount(collected, "tax_payable") == Decimal("0.00")
        nav_after_collect = _assert_nav_identity(
            world=world,
            payload=collected,
            trade_date=trade_date,
        )
        assert nav_after_collect == nav_before_collect

        _activate_raw_mark_policy(
            world=world,
            publication_key=f"ash05-no-current-price-publication-{uuid4().hex}",
        )
        _refresh(world)
        missing_source = _read(world)
        assert missing_source.get("tax_coverage_status") == "complete"
        assert type(missing_source.get("book_cash")) is str
        assert type(missing_source.get("spendable_cash")) is str
        assert missing_source.get("net_asset_value") is None
        assert missing_source.get("must_not_use_for_decision") is True
        assert (
            PositionModel._default_manager.get(
                account_id=world.account_id,
                asset_code=world.asset_code,
            ).current_price
            is not None
        )
