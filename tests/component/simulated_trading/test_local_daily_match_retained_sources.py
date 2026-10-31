"""Real retained-source qualification and producer integration for local daily matches."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.domain.price_limit_publication_audit import (
    PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center import instrument_reference_snapshot_composition
from apps.data_center.application.formal_exchange_calendar_publication import (
    PublishExchangeCalendarSnapshotUseCase,
)
from apps.data_center.application.instrument_reference_capture import CaptureInvocationMode
from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationScope,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.qmt_daily_status import QmtDailyStatusState
from apps.data_center.infrastructure import (
    instrument_reference_capture_composition,
    provider_response_capture,
    tushare_client,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.data_center.infrastructure.models import AssetMasterModel, ProviderConfigModel
from apps.data_center.infrastructure.price_limit_snapshot_repository import (
    DjangoPriceLimitSnapshotRepository,
)
from apps.data_center.price_limit_publication_operations_composition import (
    read_published_price_limit_reference,
)
from apps.data_center.qmt_bridge_composition import read_qmt_daily_status
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import ExecutionCalendarEvidence
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.local_daily_match_composition import (
    build_local_daily_match_event_reader,
    build_record_local_daily_match_use_case,
)
from apps.simulated_trading.local_daily_simulation_policy_composition import (
    LOCAL_DAILY_SIMULATION_POLICY_KEY,
)
from tests.component.data_center import (
    test_formal_calendar_publication_postgres as calendar_postgres,
)
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as calendar_source,
)
from tests.component.data_center import test_m1_reference_price_publication_activation as m1_price
from tests.component.data_center import test_price_limit_publication_operations as limit_operations
from tests.component.data_center import test_price_limit_snapshot_repository as limit_source
from tests.component.simulated_trading import test_execution_settlement_uow as settlement_uow
from tests.component.simulated_trading import (
    test_order_reservation_fill_repository as fill_repository,
)
from tests.component.simulated_trading import (
    test_order_reservation_repository as reservation_repository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _account_financial_state,
    _harness_with_source_exchange,
    _ledger_counts,
    _reservation_unfilled,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.integration.data_center import test_qmt_bridge as qmt_bridge
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime
from tests.unit.data_center.test_formal_price_limit_publication import (
    _contract as _price_limit_contract,
)
from tests.unit.data_center.test_formal_price_limit_publication import (
    _policy as _price_limit_policy,
)
from tests.unit.data_center.test_instrument_reference_capture_provider import (
    _ConfigRepository,
)
from tests.unit.data_center.test_instrument_reference_capture_use_case import _mapping_record
from tests.unit.data_center.test_tushare_provider_response_capture import _Response

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "apps.audit",
            "apps.config_center",
            "apps.data_center",
            "apps.simulated_trading",
        ],
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="retained publication and owner-bound QMT composition requires PostgreSQL",
    ),
]

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ASSET_CODE = "600000.SH"
_PROVIDER_NAME = "Tushare Pro"
_PRICE_LIMIT_BASE = "/api/data-center/price-limits/publication/"


def _previous_fixture_session_date() -> date:
    """Choose the previous weekday as this test's synthetic historical session."""
    today = timezone.now().astimezone(_SHANGHAI).date()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


_SESSION_DATE = _previous_fixture_session_date()
_RESERVATION_AS_OF = datetime.combine(_SESSION_DATE, time(9, 30), tzinfo=_SHANGHAI).astimezone(UTC)


def _fixture_reservation_calendar_dates() -> tuple[date, date, set[date]]:
    """Build synthetic open-session dates around the dynamically selected fixture session.

    Weekend runs also treat the run date itself as open so apply-time clocks
    always land inside the synthetic calendar instead of drifting to dates the
    exact-current readers reject as future or stale.
    """
    previous_session = _SESSION_DATE - timedelta(days=1)
    while previous_session.weekday() >= 5:
        previous_session -= timedelta(days=1)
    open_sessions = {previous_session, _SESSION_DATE}
    cursor = _SESSION_DATE
    while len(open_sessions) < 4:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            open_sessions.add(cursor)
    today = timezone.now().astimezone(_SHANGHAI).date()
    if today.weekday() >= 5 and today not in open_sessions:
        open_sessions.add(today)
    return previous_session, max(cursor, today), open_sessions


@pytest.fixture(autouse=True)
def _align_reused_reservation_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Align reused reservation clocks and typed fixture identity to the synthetic session."""
    for module in (settlement_uow, reservation_repository, fill_repository):
        monkeypatch.setattr(module, "AS_OF", _RESERVATION_AS_OF)

    original_calendar = settlement_uow._calendar
    calendar_start, calendar_end, open_sessions = _fixture_reservation_calendar_dates()

    def session_calendar(
        *,
        as_of: datetime,
        open_dates: set[date],
        exchange: str = "SH",
        start: date | None = None,
        end: date | None = None,
    ) -> ExecutionCalendarEvidence:
        """Use the local synthetic session window, independent of wall-clock dates."""
        del open_dates, start, end
        return original_calendar(
            as_of=as_of,
            open_dates=open_sessions,
            exchange=exchange,
            start=calendar_start,
            end=calendar_end,
        )

    monkeypatch.setattr(settlement_uow, "_calendar", session_calendar)
    monkeypatch.setattr(reservation_repository, "_calendar", session_calendar)
    monkeypatch.setattr(fill_repository, "_calendar", session_calendar)

    original_identity_reader = settlement_uow._IdentityReader.get_execution_instrument_identity

    def session_identity_reader(
        reader: settlement_uow._IdentityReader,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Keep the genuine typed fixture identity valid through the local producer clock."""
        evidence = original_identity_reader(
            reader,
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(
            evidence,
            identity_valid_until=_RESERVATION_AS_OF + timedelta(days=7),
        )

    monkeypatch.setattr(
        settlement_uow._IdentityReader,
        "get_execution_instrument_identity",
        session_identity_reader,
    )


@pytest.fixture
def local_match_reservation_harness(
    reservation_harness: _Harness,
) -> Iterator[_Harness]:
    """Clean match rows before the dependent reservation fixture drops its table."""
    with isolated_schema((LocalDailyMatchModel,)):
        yield reservation_harness


class _FixedCaptureClock:
    """Return a same-session local response-completion time for currency capture."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        """Expose this fixture session's Beijing close without freezing persistence clocks."""
        value = datetime.combine(_SESSION_DATE, time(15, 0), tzinfo=_SHANGHAI).astimezone(UTC)
        return value if tz is None else value.astimezone(tz)


class _StockBasicSession:
    """Replace only the stock-basic HTTP transport with one exact fixture response."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.trust_env = True
        self.proxies: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def mount(self, _scheme: str, _adapter: object) -> None:
        """Accept the production client's adapter configuration without network I/O."""

    def close(self) -> None:
        """Record normal transport cleanup."""
        self.closed = True

    def post(self, _url: str, **kwargs: object) -> _Response:
        """Return the exact requested stock-basic columns through the normal capture path."""
        self.calls.append(kwargs)
        raw_request = kwargs.get("json")
        if type(raw_request) is not dict:
            raise AssertionError("stock-basic request body must be an exact JSON object")
        request_body = cast(dict[str, object], raw_request)
        raw_fields = request_body.get("fields")
        if type(raw_fields) is not str:
            raise AssertionError("stock-basic request fields must be explicit text")
        fields = raw_fields.split(",")
        row: dict[str, object] = {
            "ts_code": _ASSET_CODE,
            "name": "Fixture security",
            "exchange": "SSE",
            "market": "fixture-market",
            "list_status": "L",
            "list_date": "20200101",
            "delist_date": None,
            "curr_type": "CNY",
        }
        body = json.dumps(
            {
                "code": 0,
                "msg": "",
                "data": {"fields": fields, "items": [[row[field] for field in fields]]},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return _Response(body)

    def get(self, _url: str, **kwargs: object) -> _Response:
        """Reject unexpected GET traffic in this transport fixture."""
        del kwargs
        raise AssertionError("stock-basic capture must use its declared POST route")


class _WallClock:
    """Provide the real local server clock to the durable producer."""

    def now(self) -> datetime:
        """Return the current aware UTC instant."""
        return timezone.now().astimezone(UTC)


@pytest.fixture
def price_limit_manager(settings: Any, monkeypatch: pytest.MonkeyPatch) -> APIClient:
    """Authenticate a real narrow publication manager for the test-only market fact."""
    settings.ROOT_URLCONF = limit_operations.__name__
    settings.SECURE_SSL_REDIRECT = False
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    user = get_user_model().objects.create_user(
        username=f"local-daily-limit-{uuid4().hex}", password="test-only-limit-password"
    )
    create_permissions(
        apps.get_app_config("data_center"),
        verbosity=0,
        interactive=False,
        using=connection.alias,
    )
    permission = Permission.objects.get(
        content_type__app_label="data_center",
        content_type__model="pricelimitsnapshotfactmodel",
        codename="publish_price_limit",
    )
    user.user_permissions.add(permission)
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(username=user.username, password="test-only-limit-password")
    assert client.get("/_test/csrf/").status_code == 200
    from apps.data_center.infrastructure.catalog_runtime_repositories import (
        DatasetContractRepository,
        PublicationPolicyRepository,
    )

    DatasetContractRepository().save(_price_limit_contract())
    PublicationPolicyRepository().save(_price_limit_policy())
    return client


def _capture_currency_snapshot(
    monkeypatch: pytest.MonkeyPatch, *, provider_id: int
) -> InstrumentReferenceSnapshotRecord:
    """Run public mapping, capture, original-body retention and exact snapshot readback."""
    session = _StockBasicSession()
    provider = ProviderConfig(
        id=provider_id,
        name=_PROVIDER_NAME,
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="fixture-only-token",
        api_secret="",
        http_url="https://market.example.test/pro",
        api_endpoint="",
        extra_config={"tushare_request_mode": "unified_relay"},
        description="Local captured-source fixture; no external request is allowed",
    )
    provider_repository = _ConfigRepository(provider)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    monkeypatch.setattr(
        instrument_reference_capture_composition,
        "get_provider_config_repository",
        lambda: provider_repository,
    )
    monkeypatch.setattr(tushare_client, "datetime", _FixedCaptureClock)
    monkeypatch.setattr(provider_response_capture, "datetime", _FixedCaptureClock)
    mapping = instrument_reference_snapshot_composition.save_instrument_reference_mapping(
        _mapping_record().content
    )
    result = instrument_reference_snapshot_composition.capture_instrument_reference_snapshot(
        capture_id=uuid4(),
        provider_configuration_id=provider_id,
        mapping_record_id=mapping.mapping_record_id,
        exchange_scope=("SSE",),
        list_status_scope=("L",),
        actor_provenance="local-daily-match-component",
        mode=CaptureInvocationMode.NORMAL,
        include_currency=True,
    )
    assert result.status.value == "completed"
    assert result.snapshot is not None
    assert provider_id in provider_repository.requested_ids
    assert len(session.calls) == 1
    classification = result.snapshot.content.classify_security(_ASSET_CODE)
    assert classification is not None
    assert classification.source_currency == "CNY"
    assert classification.source_exchange == "SSE"
    assert result.snapshot.content.must_not_use_for_decision is True
    assert result.snapshot.content.must_not_execute is True
    return result.snapshot


def _publish_price_limit(
    client: APIClient,
    *,
    provider_id: int,
    provider_name: str,
) -> str:
    """Capture and publish one exact same-provider effective-day price-limit snapshot."""
    candidate, _raw_repository = limit_source._candidate(
        lower_price="10.000000",
        upper_price="11.800000",
        asset_code=_ASSET_CODE,
        effective_trade_date=_SESSION_DATE,
        provider_id=provider_id,
        provider_name=provider_name,
        response_completed_at=timezone.now().astimezone(UTC),
    )
    snapshot = DjangoPriceLimitSnapshotRepository().save(candidate)
    scope: dict[str, object] = {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "asset_code": _ASSET_CODE,
        "effective_trade_date": _SESSION_DATE.isoformat(),
    }
    preview = limit_operations._post(
        client,
        "preview",
        {**scope, "action": "publish", "snapshot_id": snapshot.snapshot_id},
    )
    assert preview.status_code == 200, preview.data
    committed = limit_operations._post(
        client,
        "confirm",
        {"confirmation_token": preview.data["confirmation_token"]},
    )
    assert committed.status_code == 200, committed.data
    assert committed.data["must_not_use_for_decision"] is True
    assert committed.data["must_not_execute"] is True
    return cast(str, committed.data["publication_id"])


def _publish_calendar(monkeypatch: pytest.MonkeyPatch) -> str:
    """Publish a synthetic weekday calendar around its selected SSE fixture date."""
    start, end, open_dates = _fixture_reservation_calendar_dates()
    previous_open = start - timedelta(days=1)
    rows: list[list[object]] = []
    for offset in range((end - start).days + 1):
        current = start + timedelta(days=offset)
        is_open = current in open_dates
        rows.append(
            [
                "SSE",
                current.strftime("%Y%m%d"),
                1 if is_open else 0,
                previous_open.strftime("%Y%m%d"),
            ]
        )
        if is_open:
            previous_open = current
    monkeypatch.setattr(calendar_source, "_START", start)
    monkeypatch.setattr(calendar_source, "_END", end)
    monkeypatch.setattr(calendar_source, "_PROVIDER_ROWS", rows)
    _snapshot, _test_audit, _clock, _test_principal, request = calendar_source._ready()
    _owner, proof = calendar_postgres._actual_publisher(f"local-daily-calendar-{uuid4().hex}")
    authority = DjangoCalendarPublisherAuthorityRepository(using="default")
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=calendar_postgres._real_audit_bridge(),
        using="default",
    )
    published = calendar_postgres._authorized_publish(
        authority=authority,
        use_case=PublishExchangeCalendarSnapshotUseCase(repository),
        proof=proof,
        request=request,
    )
    assert published.record.seal.snapshot.exchange == "SSE"
    assert any(
        day.calendar_date == _SESSION_DATE and day.is_open
        for day in published.record.seal.snapshot.days
    )
    return calendar_source._DATASET.value


def _create_qmt_binding_and_upload(owner: object) -> str:
    """Create a real owner-bound QMT session and retain one signed daily-status batch."""
    asset, _created = AssetMasterModel._default_manager.get_or_create(
        code=_ASSET_CODE,
        defaults={"name": "Fixture security", "asset_type": "equity", "exchange": "SSE"},
    )
    assert asset.exchange == "SSE"
    admin = get_user_model().objects.create_user(
        username=f"local-daily-qmt-admin-{uuid4().hex}", is_staff=True
    )
    provider = ProviderConfigModel._default_manager.create(
        name=f"local-daily-qmt-{uuid4().hex}", source_type="qmt", is_active=True
    )
    client = APIClient()
    client.force_authenticate(owner)
    created = client.post(
        qmt_bridge.BASE + "bindings/",
        {"agent_id": "local-qmt-daily-fixture", "assets": [_ASSET_CODE]},
        format="json",
    )
    assert created.status_code == 200, created.data
    binding = cast(dict[str, object], created.data["data"])
    client.force_authenticate(None)
    paired = client.post(
        qmt_bridge.BASE + "pair/",
        {
            "pairing_code": binding["pairing_code"],
            "agent_id": "local-qmt-daily-fixture",
        },
        format="json",
    )
    assert paired.status_code == 200, paired.data
    pair = cast(dict[str, object], paired.data["data"])
    qmt_bridge.approve(client, admin, provider, pair)
    batch: dict[str, object] = {
        "batch_id": str(uuid4()),
        "kind": "daily_status",
        "schema_version": "qmt-native-daily-status.v1",
        "collected_at": (timezone.now().astimezone(UTC) - timedelta(seconds=1)).isoformat(),
        "request_start": _SESSION_DATE.isoformat(),
        "request_end": _SESSION_DATE.isoformat(),
        "samples": [
            {"asset_code": _ASSET_CODE, "bar_date": _SESSION_DATE.isoformat(), "suspend_flag": 0}
        ],
    }
    uploaded = qmt_bridge.signed(client, pair, "batches", batch)
    assert uploaded.status_code == 200, uploaded.data
    assert uploaded.data["data"]["stored"] == 1
    return cast(str, pair["binding_id"])


def _runtime_environment() -> str:
    """Select the active test deployment environment using the project's setting name."""
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return "production" if settings_module.endswith(".production") else "development"


def _activate_daily_policy(*, runtime_environment: str, policy: LocalDailySimulationPolicy) -> None:
    """Activate the typed purpose-specific policy and SSE calendar timezone in Config Center."""
    activate_runtime_profile_patch(
        environment=runtime_environment,
        patch={
            "config_center.market.exchange_timezone_map": {"SSE": "Asia/Shanghai"},
            LOCAL_DAILY_SIMULATION_POLICY_KEY: policy.to_payload(),
        },
        actor="local-daily-match-component",
        reason="exercise the retained-source daily simulation contract",
    )


def _make_policy(*, provider_id: int, snapshot_id: str) -> LocalDailySimulationPolicy:
    """Build the exact configured CNY/unadjusted/SSE daily simulation policy."""
    return LocalDailySimulationPolicy(
        schema_version="local-daily-simulation-policy.v1",
        purpose="historical_daily_simulation",
        policy_id="local-daily-retained-source-component",
        version="1",
        price_publication_key=m1_price.M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        provider_configuration_id=provider_id,
        provider_name=_PROVIDER_NAME,
        instrument_snapshot_id=snapshot_id,
        currency="CNY",
        frequency="1d",
        adjustment="none",
        volume_unit="shares",
        participation_rate=Decimal("0.5"),
        share_step=Decimal("100"),
        allowed_qmt_suspend_flags=(0,),
        currency_basis="same_session_stock_basic_capture",
        qmt_status_basis="owner_authenticated_normalized_daily_status",
        limit_price_basis="same_provider_cny_listing_native",
    )


def _make_command(
    *, harness: _Harness, order_key: str, operation_key: str, binding_id: str
) -> LocalDailyMatchCommand:
    """Address a real accepted reservation and one exact QMT binding."""
    account = harness.account
    return LocalDailyMatchCommand(
        account_id=cast(int, account.pk),
        user_id=harness.user_id,
        order_idempotency_key=order_key,
        operation_key=operation_key,
        session_date=_SESSION_DATE,
        qmt_binding_id=binding_id,
    )


def test_retained_sources_qualify_one_real_local_daily_match_without_ledger_effects(
    local_match_reservation_harness: _Harness,
    price_limit_manager: APIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Join real retained source reads to one durable match and fail closed on scope damage."""
    assert_native_postgres_test_database()
    configure_critical_runtime()
    runtime_environment = _runtime_environment()

    harness = _harness_with_source_exchange(local_match_reservation_harness, "SSE")
    intent = _intent_for(
        harness,
        key=f"local-daily-order-{uuid4().hex}",
        quantity=Decimal("100"),
        price=Decimal("11.50"),
    )
    harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=_RESERVATION_AS_OF)
    assert type(harness.account.pk) is int
    assert type(harness.account.user_id) is int
    assert _SESSION_DATE == _RESERVATION_AS_OF.astimezone(_SHANGHAI).date()
    accepted = SimulatedOrderReservationModel._default_manager.get(
        account=harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert accepted.status == SimulatedOrderReservationModel.STATUS_ACTIVE

    price_use_case, price_source, provider_id, _activation = m1_price._build_m1_test_use_case()
    price_result = price_use_case.execute(
        m1_price.M1ReferencePricePublicationCommand(
            provider_id=provider_id,
            asset_code=_ASSET_CODE,
            target_trade_date=_SESSION_DATE,
        )
    )
    assert price_result.sync_result.status == "success"
    assert (
        price_result.publication.publication_key == m1_price.M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    )
    assert price_source.calls == [(_ASSET_CODE, _SESSION_DATE)]

    currency_snapshot = _capture_currency_snapshot(monkeypatch, provider_id=provider_id)
    calendar_dataset_key = _publish_calendar(monkeypatch)
    limit_publication_id = _publish_price_limit(
        price_limit_manager,
        provider_id=provider_id,
        provider_name=_PROVIDER_NAME,
    )
    owner = get_user_model().objects.get(pk=harness.user_id)
    qmt_binding_id = _create_qmt_binding_and_upload(owner)
    qmt_status = read_qmt_daily_status(
        owner_id=harness.user_id,
        binding_id=qmt_binding_id,
        asset_code=_ASSET_CODE,
        bar_date=_SESSION_DATE,
        as_of=timezone.now().astimezone(UTC),
    )
    assert qmt_status.state is QmtDailyStatusState.NORMAL
    assert qmt_status.suspend_flag == 0
    assert qmt_status.source_observed_at is None and qmt_status.source_available_at is None
    assert qmt_status.must_not_use_for_decision is True and qmt_status.must_not_execute is True

    original_policy = _make_policy(
        provider_id=provider_id,
        snapshot_id=str(currency_snapshot.snapshot_id),
    )
    _activate_daily_policy(runtime_environment=runtime_environment, policy=original_policy)
    producer = build_record_local_daily_match_use_case(
        runtime_environment=runtime_environment,
        calendar_dataset_key=calendar_dataset_key,
        clock=_WallClock(),
    )
    command = _make_command(
        harness=harness,
        order_key=intent.idempotency_key,
        operation_key=f"local-daily-positive-{uuid4().hex}",
        binding_id=qmt_binding_id,
    )
    before_counts = _ledger_counts(harness.account)
    before_financial_state = _account_financial_state(harness.account)

    decision = producer.execute(command)

    assert decision.result.outcome is LocalMatchOutcome.MATCHED
    assert decision.result.matched_quantity == Decimal("100.000000")
    assert decision.result.matched_price == Decimal("11.4700")
    assert decision.event is not None
    assert decision.event.observation_basis == "daily_interval_end"
    assert decision.event.source_observed_at is None
    assert decision.event.source_available_at is None
    assert decision.event.occurred_at == decision.event.interval_end_at
    assert decision.event.interval_end_at is not None
    assert decision.event.local_known_at is not None
    stored_event = build_local_daily_match_event_reader().read_event(
        account_id=command.account_id,
        user_id=command.user_id,
        order_idempotency_key=command.order_idempotency_key,
        source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
        fill_event_id=command.operation_key,
        as_of=timezone.now().astimezone(UTC),
    )
    assert stored_event == decision.event
    assert (
        LocalDailyMatchModel._default_manager.filter(
            account=harness.account,
            reservation=accepted,
            operation_key=command.operation_key,
        ).count()
        == 1
    )
    assert _ledger_counts(harness.account) == before_counts
    assert _account_financial_state(harness.account) == before_financial_state
    _reservation_unfilled(accepted)
    assert SystemAuditEventModel._default_manager.filter(
        event_type=PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT,
        publication_id=limit_publication_id,
    ).exists()
    assert (
        read_published_price_limit_reference(
            scope=PriceLimitPublicationScope(
                provider_id=provider_id,
                provider_name=_PROVIDER_NAME,
                asset_code=_ASSET_CODE,
                effective_trade_date=_SESSION_DATE,
            ),
            as_of=timezone.now().astimezone(UTC),
        )
        is not None
    )

    wrong_provider_policy = LocalDailySimulationPolicy.from_payload(
        {
            **original_policy.to_payload(),
            "version": "2",
            "provider_configuration_id": provider_id + 1000,
        }
    )
    _activate_daily_policy(runtime_environment=runtime_environment, policy=wrong_provider_policy)
    wrong_provider_command = _make_command(
        harness=harness,
        order_key=intent.idempotency_key,
        operation_key=f"local-daily-wrong-provider-{uuid4().hex}",
        binding_id=qmt_binding_id,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as wrong_provider:
        producer.execute(wrong_provider_command)
    assert wrong_provider.value.code == "LOCAL_DAILY_MATCH_PRICE_SCOPE_MISMATCH"
    assert LocalDailyMatchModel._default_manager.count() == 1
    assert _ledger_counts(harness.account) == before_counts
    assert _account_financial_state(harness.account) == before_financial_state

    _activate_daily_policy(runtime_environment=runtime_environment, policy=original_policy)
    other_owner = get_user_model().objects.create_user(
        username=f"local-daily-qmt-other-owner-{uuid4().hex}"
    )
    foreign_binding_id = _create_qmt_binding_and_upload(other_owner)
    foreign_qmt_command = _make_command(
        harness=harness,
        order_key=intent.idempotency_key,
        operation_key=f"local-daily-foreign-qmt-{uuid4().hex}",
        binding_id=foreign_binding_id,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as foreign_qmt:
        producer.execute(foreign_qmt_command)
    assert foreign_qmt.value.code == "LOCAL_DAILY_MATCH_QMT_STATUS_UNQUALIFIED"
    assert LocalDailyMatchModel._default_manager.count() == 1
    assert _ledger_counts(harness.account) == before_counts
    assert _account_financial_state(harness.account) == before_financial_state

    limit_event = SystemAuditEventModel._default_manager.get(
        event_type=PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT,
        publication_id=limit_publication_id,
    )
    outbox = SystemAuditOutboxModel._default_manager.get(event_id=limit_event.event_id)
    outbox_table = connection.ops.quote_name(SystemAuditOutboxModel._meta.db_table)
    outbox_field = SystemAuditOutboxModel._meta.get_field("outbox_id")
    outbox_identity = outbox_field.get_db_prep_value(outbox.outbox_id, connection)
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {outbox_table} WHERE outbox_id=%s", [outbox_identity])
        assert cursor.rowcount == 1
    damaged_limit_command = _make_command(
        harness=harness,
        order_key=intent.idempotency_key,
        operation_key=f"local-daily-damaged-limit-{uuid4().hex}",
        binding_id=qmt_binding_id,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as damaged_limit:
        producer.execute(damaged_limit_command)
    assert damaged_limit.value.code == "LOCAL_DAILY_MATCH_SOURCE_INVALID"
    assert LocalDailyMatchModel._default_manager.count() == 1
    assert _ledger_counts(harness.account) == before_counts
    assert _account_financial_state(harness.account) == before_financial_state
