"""Assemble the authorized raw-captured calendar snapshot workflow."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from django.db import connections, models, router
from django.db.backends.base.base import BaseDatabaseWrapper

from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_PROVIDER,
    CalendarCaptureConfiguration,
    CalendarCaptureConfigurationError,
    SelectCalendarCaptureConfigurationUseCase,
)
from apps.data_center.application.calendar_publication_operations import (
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    CaptureExchangeCalendarSnapshotUseCase,
)
from apps.data_center.application.exchange_calendar import IngestExchangeCalendarSnapshotUseCase
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.infrastructure.calendar_capture_configuration_repository import (
    DjangoCalendarCaptureConfigurationRepository,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
    SchemaFingerprintModel,
)
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_client import (
    create_tushare_pro_client,
)
from apps.data_center.infrastructure.tushare_exchange_calendar_source import (
    TushareCalendarClientPort,
    TushareExchangeCalendarSource,
)
from core.exceptions import ConfigurationError
from shared.config.secrets import AppSecrets, get_secrets
from shared.config.tushare import TUSHARE_REQUEST_MODE_VALUES

_DEFAULT_ALIAS = "default"
_OPERATIONAL_MODELS: tuple[type[models.Model], ...] = (
    RawPayloadModel,
    SchemaFingerprintModel,
    ExchangeCalendarSnapshotFactModel,
)


class CalendarSnapshotCaptureComposition:
    """Capture exact Tushare calendar bytes under the caller's transaction."""

    def __init__(
        self,
        capture: CaptureExchangeCalendarSnapshotUseCase,
        *,
        outer_atomic_block: object,
        dataset_key: str,
    ) -> None:
        """Bind a configured capture use case to one active outer transaction."""

        self._capture = capture
        self._outer_atomic_block = outer_atomic_block
        self.dataset_key = dataset_key

    def execute(
        self,
        intent: CaptureExchangeCalendarSnapshotIntent,
    ) -> CapturedExchangeCalendarSnapshot:
        """Fetch, retain, parse, and persist while the original caller transaction lives."""

        connection = connections[_DEFAULT_ALIAS]
        _require_same_outer_transaction(connection, self._outer_atomic_block)
        return self._capture.execute(intent)


def compose_calendar_snapshot_capture(
    *,
    known_at: datetime,
    using: str = _DEFAULT_ALIAS,
    configuration_repository: DjangoCalendarCaptureConfigurationRepository | None = None,
    provider_config_repository: ProviderConfigRepository | None = None,
) -> CalendarSnapshotCaptureComposition:
    """Build the one-source capture workflow from exact active runtime metadata.

    The caller must already own the authorized outer transaction and must run
    the returned composition before that same transaction commits. This
    function does not open a transaction, request a credential, or contact a
    provider.
    """

    connection = _require_caller_outer_transaction(using)
    _require_operational_model_routes(using)
    if provider_config_repository is not None and configuration_repository is not None:
        raise _blocked("CALENDAR_CAPTURE_REPOSITORY_CONFIGURATION_INVALID")
    repository = configuration_repository or DjangoCalendarCaptureConfigurationRepository(
        provider_config_repository
    )
    try:
        configuration = SelectCalendarCaptureConfigurationUseCase(repository).execute(
            known_at=known_at,
            using=using,
        )
        provider = repository.get_provider_config(configuration.provider_id, using=using)
        if provider is None:
            raise _blocked("CALENDAR_CAPTURE_PROVIDER_CONFIGURATION_MISSING")
        central_secrets = get_secrets()
        _verify_provider_matches_central(provider, central_secrets, configuration)
    except CalendarCaptureConfigurationError:
        raise
    except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise _blocked("CALENDAR_CAPTURE_PROVIDER_CONFIGURATION_UNAVAILABLE") from error

    raw_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(raw_repository)
    try:
        client = create_tushare_pro_client(
            token=central_secrets.data_sources.tushare_token,
            http_url=central_secrets.data_sources.tushare_http_url,
            request_mode=central_secrets.data_sources.tushare_request_mode,
            provider_id=configuration.provider_id,
            dataset_key=configuration.dataset.value,
            provider_response_handler=retainer.execute,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise _blocked("CALENDAR_CAPTURE_TUSHARE_TRANSPORT_UNAVAILABLE") from error
    if not callable(getattr(client, "trade_cal", None)):
        raise _blocked("CALENDAR_CAPTURE_TUSHARE_CLIENT_INVALID")
    if not isinstance(configuration.dataset.value, str):
        raise _blocked("CALENDAR_CAPTURE_DATASET_INVALID")

    source = TushareExchangeCalendarSource(
        cast(TushareCalendarClientPort, client),
        raw_repository,
        dataset_key=configuration.dataset.value,
    )
    snapshot_repository = DjangoExchangeCalendarSnapshotRepository()
    ingest = IngestExchangeCalendarSnapshotUseCase(source, snapshot_repository)
    capture = CaptureExchangeCalendarSnapshotUseCase(ingest)
    if not connection.atomic_blocks:
        raise _blocked("CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED")
    outer_block = connection.atomic_blocks[0]
    return CalendarSnapshotCaptureComposition(
        capture,
        outer_atomic_block=outer_block,
        dataset_key=configuration.dataset.value,
    )


def _verify_provider_matches_central(
    provider: object,
    secrets: AppSecrets,
    configuration: CalendarCaptureConfiguration,
) -> None:
    """Require exact provider type, transport, endpoint, and credential agreement."""

    provider_id = getattr(provider, "id", None)
    source_type = getattr(provider, "source_type", None)
    is_active = getattr(provider, "is_active", None)
    api_key = getattr(provider, "api_key", None)
    api_secret = getattr(provider, "api_secret", None)
    http_url = getattr(provider, "http_url", None)
    extra_config = getattr(provider, "extra_config", None)
    if (
        type(provider_id) is not int
        or provider_id != configuration.provider_id
        or source_type != CALENDAR_CAPTURE_PROVIDER
        or is_active is not True
        or type(api_key) is not str
        or type(api_secret) is not str
        or api_secret
        or not isinstance(extra_config, Mapping)
    ):
        raise _blocked("CALENDAR_CAPTURE_PROVIDER_CONFIGURATION_INVALID")
    raw_mode = extra_config.get("tushare_request_mode")
    central = secrets.data_sources
    if (
        type(raw_mode) is not str
        or raw_mode not in TUSHARE_REQUEST_MODE_VALUES
        or type(central.tushare_request_mode) is not str
        or central.tushare_request_mode not in TUSHARE_REQUEST_MODE_VALUES
        or type(central.tushare_token) is not str
        or not central.tushare_token
        or central.tushare_token.strip() != central.tushare_token
    ):
        raise _blocked("CALENDAR_CAPTURE_PROVIDER_CONFIGURATION_INVALID")
    normalized_provider_url = _optional_url(http_url)
    normalized_secret_url = _optional_url(central.tushare_http_url)
    if not _constant_time_equal(api_key, central.tushare_token):
        raise _blocked("CALENDAR_CAPTURE_SECRET_SNAPSHOT_MISMATCH")
    if not _constant_time_equal(raw_mode, central.tushare_request_mode):
        raise _blocked("CALENDAR_CAPTURE_TRANSPORT_SNAPSHOT_MISMATCH")
    if not _constant_time_equal(normalized_provider_url, normalized_secret_url):
        raise _blocked("CALENDAR_CAPTURE_ENDPOINT_SNAPSHOT_MISMATCH")


def _optional_url(value: object) -> str:
    """Narrow an optional stored endpoint without exposing its value."""

    if value is None or value == "":
        return ""
    if type(value) is not str:
        raise _blocked("CALENDAR_CAPTURE_ENDPOINT_INVALID")
    return value


def _constant_time_equal(left: str, right: str) -> bool:
    """Compare configuration strings without an early-exit secret comparison."""

    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise _blocked("CALENDAR_CAPTURE_PROVIDER_CONFIGURATION_INVALID") from error


def _require_caller_outer_transaction(using: str) -> BaseDatabaseWrapper:
    """Reject missing or non-operational transaction context before selection."""

    if type(using) is not str or using != _DEFAULT_ALIAS:
        raise _blocked("CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED")
    connection = connections[using]
    if (
        connection.alias != _DEFAULT_ALIAS
        or not connection.in_atomic_block
        or connection.get_autocommit()
        or not connection.atomic_blocks
    ):
        raise _blocked("CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED")
    return connection


def _require_same_outer_transaction(
    connection: BaseDatabaseWrapper,
    expected_outer_block: object,
) -> None:
    """Prevent a configured service from being invoked after its fence ends."""

    if (
        connection.alias != _DEFAULT_ALIAS
        or not connection.in_atomic_block
        or connection.get_autocommit()
        or not connection.atomic_blocks
        or connection.atomic_blocks[0] is not expected_outer_block
    ):
        raise _blocked("CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED")


def _require_operational_model_routes(using: str) -> None:
    """Ensure RawPayload and calendar facts share the fixed default database."""

    for model in _OPERATIONAL_MODELS:
        read_alias = router.db_for_read(model) or _DEFAULT_ALIAS
        write_alias = router.db_for_write(model) or _DEFAULT_ALIAS
        if read_alias != using or write_alias != using:
            raise _blocked("CALENDAR_CAPTURE_DATABASE_ALIAS_MISMATCH")


def _blocked(code: str) -> CalendarCaptureConfigurationError:
    """Create a stable configuration failure without disclosing URLs or tokens."""

    return CalendarCaptureConfigurationError(
        "Exchange calendar capture is blocked by runtime configuration",
        code=code,
    )


__all__ = [
    "CalendarSnapshotCaptureComposition",
    "compose_calendar_snapshot_capture",
]
