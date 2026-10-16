"""Configured calendar capture over the existing retained-response workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import pytest
from django.db import transaction
from django.test import override_settings

from apps.config_center.models import ConfigCenterSecretModel
from apps.data_center import calendar_snapshot_capture_composition as composition
from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_CAPABILITY,
    CALENDAR_CAPTURE_VALIDATOR_KEY,
    CalendarCaptureConfigurationError,
)
from apps.data_center.application.calendar_publication_operations import (
    CaptureExchangeCalendarSnapshotIntent,
)
from apps.data_center.calendar_snapshot_capture_composition import compose_calendar_snapshot_capture
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.calendar_capture_configuration_repository import (
    DjangoCalendarCaptureConfigurationRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
    SchemaFingerprintModel,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.tushare_client import TUSHARE_REQUEST_MODE_UNIFIED_RELAY
from shared.config.secrets import AppSecrets, DataSourceSecrets
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.config_center", "apps.data_center"],
)

DATASET_KEY = "data_center.exchange_calendar_snapshot"
CONTRACT_VERSION = "2.0"
SCHEMA_VERSION = "1.0"
TOKEN = "calendar-source-fixture-token"
HTTP_URL = "https://calendar.example.test/pro"
REQUEST_MODE = TUSHARE_REQUEST_MODE_UNIFIED_RELAY


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the catalog, provider, and exact raw/fact tables under test."""

    models = (
        ConfigCenterSecretModel,
        DatasetContractModel,
        DatasetProviderBindingModel,
        DatasetPublicationPolicyModel,
        ProviderConfigModel,
        RawPayloadModel,
        SchemaFingerprintModel,
        ExchangeCalendarSnapshotFactModel,
    )
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(models):
            yield


def _write_runtime_configuration(
    *,
    provider_count: int = 1,
    validator_key: str = CALENDAR_CAPTURE_VALIDATOR_KEY,
) -> tuple[int, ...]:
    """Persist one exact catalog selection and an explicit Tushare transport."""

    DatasetContractModel.objects.create(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=[
            {
                "name": "calendar_date",
                "type": "date",
                "unit": None,
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        calendar_response_max_age_seconds=900,
        active=True,
    )
    DatasetPublicationPolicyModel.objects.create(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version="calendar-v1",
        member_codec_version="calendar-nullable-member-v1",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "fact_content_hash"],
        retention_days=3650,
        active=True,
    )
    DatasetProviderBindingModel.objects.create(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
        priority=10,
        validator_key=validator_key,
        enabled=True,
    )
    provider_ids: list[int] = []
    for index in range(provider_count):
        saved = ProviderConfigRepository().save(
            ProviderConfig(
                id=None,
                name=f"calendar-capture-{index}",
                source_type="tushare",
                is_active=True,
                priority=10 + index,
                api_key=TOKEN if index == 0 else f"other-token-{index}",
                api_secret="",
                http_url=HTTP_URL,
                api_endpoint="",
                extra_config={"tushare_request_mode": REQUEST_MODE},
                description="fixture only",
            )
        )
        assert saved.id is not None
        provider_ids.append(saved.id)
    return tuple(provider_ids)


def _central_secrets(
    *,
    token: str = TOKEN,
    http_url: str | None = HTTP_URL,
    request_mode: str = REQUEST_MODE,
) -> AppSecrets:
    """Build only the explicit central Tushare values used by this fixture."""

    return AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token=token,
            fred_api_key="",
            tushare_http_url=http_url,
            tushare_request_mode=request_mode,
        )
    )


def _calendar_body() -> bytes:
    """Return one full-date Tushare response using the frozen source schema."""

    return (
        b'{"code":0,"msg":null,"data":{'
        b'"fields":["exchange","cal_date","is_open","pretrade_date"],'
        b'"items":[["SSE","20261015",1,"20261014"],'
        b'["SSE","20261016",0,"20261015"]]}}'
    )


@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_factory_captures_retains_parses_and_saves_under_exact_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real composition uses selected catalog identity and RawPayload retention."""

    provider_ids = _write_runtime_configuration()
    monkeypatch.setattr(composition, "get_secrets", lambda: _central_secrets())
    response = _Response(_calendar_body())
    session = _Session(response)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    known_at = datetime.now(UTC) + timedelta(seconds=1)
    intent = CaptureExchangeCalendarSnapshotIntent(
        exchange="SSE",
        coverage_start=date(2026, 10, 15),
        coverage_end=date(2026, 10, 16),
    )

    with transaction.atomic(using="default"):
        with transaction.atomic(using="default"):
            configured = compose_calendar_snapshot_capture(known_at=known_at)
        assert configured.dataset_key == DATASET_KEY
        assert session.calls == []
        captured = configured.execute(intent)

    fact = ExchangeCalendarSnapshotFactModel.objects.get(
        snapshot_id=captured.snapshot_reference.snapshot_id
    )
    raw = RawPayloadModel.objects.get(payload_id=fact.raw_payload_id)
    assert raw.dataset_key == DATASET_KEY
    assert raw.provider_name == "tushare"
    assert raw.payload["retained_response_json"].encode("utf-8") == _calendar_body()
    assert raw.payload["response_body_sha256"] == sha256(_calendar_body()).hexdigest()
    assert fact.source_published_at is None
    assert fact.first_seen_at == raw.fetched_at
    assert fact.recorded_at >= fact.first_seen_at
    assert len(session.calls) == 1
    assert response.closed is True
    assert len(provider_ids) == 1


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("missing_dataset", "CALENDAR_CAPTURE_DATASET_MISSING"),
        ("missing_policy", "CALENDAR_CAPTURE_POLICY_MISSING"),
        ("bad_validator", "CALENDAR_CAPTURE_VALIDATOR_UNSUPPORTED"),
        ("ambiguous_provider", "CALENDAR_CAPTURE_PROVIDER_INSTANCE_AMBIGUOUS"),
        ("wrong_token", "CALENDAR_CAPTURE_SECRET_SNAPSHOT_MISMATCH"),
        ("wrong_url", "CALENDAR_CAPTURE_ENDPOINT_SNAPSHOT_MISMATCH"),
        ("wrong_transport", "CALENDAR_CAPTURE_TRANSPORT_SNAPSHOT_MISMATCH"),
    ],
)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_invalid_or_ambiguous_configuration_blocks_before_outbound_http(
    failure: str,
    code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every selector or secret mismatch has zero provider side effects."""

    if failure != "missing_dataset":
        _write_runtime_configuration(
            provider_count=2 if failure == "ambiguous_provider" else 1,
            validator_key=(
                "unregistered" if failure == "bad_validator" else CALENDAR_CAPTURE_VALIDATOR_KEY
            ),
        )
        if failure == "missing_policy":
            DatasetPublicationPolicyModel.objects.all().delete()
    response = _Response(_calendar_body())
    session = _Session(response)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    secrets = {
        "wrong_token": _central_secrets(token="different-fixture-token"),
        "wrong_url": _central_secrets(http_url="https://other.example.test/pro"),
        "wrong_transport": _central_secrets(request_mode="rest_path"),
    }.get(failure, _central_secrets())
    monkeypatch.setattr(composition, "get_secrets", lambda: secrets)

    with transaction.atomic(using="default"):
        with pytest.raises(CalendarCaptureConfigurationError) as raised:
            compose_calendar_snapshot_capture(known_at=datetime.now(UTC) + timedelta(seconds=1))

    assert raised.value.code == code
    assert session.calls == []
    assert RawPayloadModel.objects.count() == 0
    assert ExchangeCalendarSnapshotFactModel.objects.count() == 0


@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="calendar-capture-component-key")
def test_composed_service_cannot_outlive_the_configuration_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The returned composition is bound to the caller's exact outer block."""

    _write_runtime_configuration()
    monkeypatch.setattr(composition, "get_secrets", lambda: _central_secrets())
    response = _Response(_calendar_body())
    session = _Session(response)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    intent = CaptureExchangeCalendarSnapshotIntent(
        exchange="SSE",
        coverage_start=date(2026, 10, 15),
        coverage_end=date(2026, 10, 16),
    )

    with transaction.atomic(using="default"):
        configured = compose_calendar_snapshot_capture(
            known_at=datetime.now(UTC) + timedelta(seconds=1)
        )

    with transaction.atomic(using="default"):
        with pytest.raises(CalendarCaptureConfigurationError) as raised:
            configured.execute(intent)

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
    assert session.calls == []
    assert RawPayloadModel.objects.count() == 0


def test_factory_rejects_nondefault_alias_before_configuration_reads() -> None:
    """RawPayload, provider metadata, and calendar facts use one fixed alias."""

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        compose_calendar_snapshot_capture(known_at=datetime.now(UTC), using="replica")

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED"


def test_configuration_repository_requires_the_callers_transaction() -> None:
    """The selector never creates its own transaction or silently reads outside it."""

    repository = DjangoCalendarCaptureConfigurationRepository()

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        repository.load_candidates(using="default")

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"


def test_configuration_repository_rejects_split_router_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every catalog row must use the one operational database alias."""

    repository = DjangoCalendarCaptureConfigurationRepository()
    monkeypatch.setattr(
        "apps.data_center.infrastructure.calendar_capture_configuration_repository.router.db_for_read",
        lambda model, **hints: "replica" if model is DatasetContractModel else "default",
    )

    with transaction.atomic(using="default"):
        with pytest.raises(CalendarCaptureConfigurationError) as raised:
            repository.load_candidates(using="default")

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_ALIAS_MISMATCH"


def test_configuration_repository_rejects_non_integer_provider_id() -> None:
    """A boolean provider ID cannot pass Python's bool-is-int relationship."""

    repository = DjangoCalendarCaptureConfigurationRepository()

    with transaction.atomic(using="default"):
        with pytest.raises(CalendarCaptureConfigurationError) as raised:
            repository.get_provider_config(True, using="default")

    assert raised.value.code == "CALENDAR_CAPTURE_PROVIDER_ID_INVALID"
