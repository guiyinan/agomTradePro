"""Real governed exchange-calendar setup for the ASH07 Owner acceptance test.

This test-only adapter uses the existing Data Center catalog UOW, Provider API,
Config Center runtime patch, session/CSRF Workbench routes, and public execution
calendar reader. It writes only to the isolated Native PostgreSQL test database.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_runtime_profile,
    get_active_runtime_value,
)
from apps.data_center.application.calendar_catalog_bootstrap import (
    CalendarCatalogBootstrapRows,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.raw_landing_public import get_retained_raw_payload
from apps.data_center.calendar_catalog_bootstrap_composition import (
    build_calendar_catalog_bootstrap_use_case,
)
from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.data_center.domain.provider_response import (
    ProviderResponseTransport,
    canonical_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_configured_execution_calendar_reader,
)
from shared.config.secrets import clear_secrets_cache, get_secrets
from tests.component.data_center import test_calendar_operations_http as calendar_http
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime

_DATASET_KEY = "data_center.exchange_calendar_snapshot"
_EXCHANGE = "SSE"
_TIMEZONE_NAME = "Asia/Shanghai"
_TIMEZONE_KEY = "config_center.market.exchange_timezone_map"
_PROVIDER_PATH = "/api/data-center/providers/"
_WORKBENCH_SCOPE_PATH = "/api/data-center/exchange-calendars/workbench/scope/"
_WORKBENCH_PREPARE_PATH = "/api/data-center/exchange-calendars/workbench/prepare/"
_WORKBENCH_CONFIRM_PATH = "/api/data-center/exchange-calendars/workbench/confirm/"
_WORKBENCH_CURRENT_PATH = "/api/data-center/exchange-calendars/workbench/current/"
_PROJECTION_FILES = (
    ("dataset_contracts.json", "contracts", "contracts"),
    ("provider_bindings.json", "bindings", "bindings"),
    ("publication_policies.json", "policies", "policies"),
    ("data_ownership_contracts.json", "datasets", "owners"),
)
_ORIGIN = "https://testserver"


def publish_real_calendar_for_acceptance(
    *,
    business_date: date,
    coverage_start: date,
    coverage_end: date,
) -> RealCalendarPublicationLease:
    """Capture and publish one real current Tushare calendar through public APIs.

    The caller owns lease cleanup so the temporary Tushare provider remains
    active while the simulated-risk consumer reads the just-published reference.
    All dates are explicit; this helper does not infer weekdays or calendar days.
    """

    _require_isolated_test_database()
    _validate_coverage(business_date, coverage_start, coverage_end)
    _ensure_calendar_catalog()
    _ensure_runtime_timezone()

    client: APIClient | None = None
    csrf_token: str | None = None
    previous_provider_ids: tuple[int, ...] = ()
    created_provider_id: int | None = None
    try:
        with override_settings(ROOT_URLCONF=calendar_http.__name__):
            client, publisher, csrf_token = calendar_http._client_for_user(
                f"ash07-real-calendar-owner-{uuid4().hex}"
            )
            if csrf_token is None:
                raise AssertionError("calendar test session did not acquire a CSRF token")
            publisher.is_staff = True
            publisher.save(update_fields=("is_staff",))

            clear_secrets_cache()
            try:
                secrets = get_secrets()
                source = secrets.data_sources
                if (
                    type(source.tushare_token) is not str
                    or not source.tushare_token
                    or source.tushare_token.strip() != source.tushare_token
                    or type(source.tushare_request_mode) is not str
                    or type(source.tushare_http_url) not in (str, type(None))
                ):
                    raise AssertionError("central Tushare configuration is unavailable")
                previous_provider_ids = _active_tushare_provider_ids(client)
                for old_provider_id in previous_provider_ids:
                    _set_provider_active(client, csrf_token, old_provider_id, False)
                provider_id = _create_test_provider(
                    client,
                    csrf_token,
                    token=source.tushare_token,
                    request_mode=source.tushare_request_mode,
                    http_url=source.tushare_http_url or "",
                )
                created_provider_id = provider_id
            finally:
                clear_secrets_cache()

            response_age_limit_seconds = _selected_response_age_limit(client, provider_id)
            _prepare_and_confirm(
                client,
                csrf_token,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
            )
            current_payload = _read_current_calendar(client)
            as_of = timezone.now().astimezone(UTC)
            verified = _read_exact_execution_evidence(
                business_date=business_date,
                coverage_start=coverage_start,
                current_payload=current_payload,
                as_of=as_of,
            )
            publication = verified.evidence.publication
            if publication is None:
                raise AssertionError("current execution reader returned no publication binding")
            return RealCalendarPublicationLease(
                as_of=as_of,
                business_date=business_date,
                dataset_key=verified.evidence.snapshot.raw_reference.dataset_key,
                exchange=verified.evidence.snapshot.exchange,
                timezone_name=publication.timezone_name,
                calendar_response_max_age_seconds=response_age_limit_seconds,
                snapshot=verified.evidence.snapshot,
                publication_id=publication.publication_id,
                publication_hash=publication.publication_hash,
                raw_body=verified.raw_body,
                raw_body_sha256=verified.evidence.snapshot.raw_reference.body_sha256,
                raw_payload_hash=verified.evidence.snapshot.raw_reference.payload_hash,
                calendar_evidence=verified.evidence,
                market_session=verified.evidence.current_open_session(as_of),
                next_open_session=verified.evidence.release_session(business_date, 1),
                _client=client,
                _csrf_token=csrf_token,
                _created_provider_id=provider_id,
                _previous_provider_ids=previous_provider_ids,
                _root_urlconf=calendar_http.__name__,
            )
    except Exception:
        if client is not None and csrf_token is not None:
            _restore_provider_scope(
                client,
                csrf_token,
                created_provider_id=created_provider_id,
                previous_provider_ids=previous_provider_ids,
                root_urlconf=calendar_http.__name__,
            )
        raise


@dataclass(slots=True)
class RealCalendarPublicationLease:
    """Verified calendar evidence plus public-API cleanup for test providers."""

    as_of: datetime
    business_date: date
    dataset_key: str
    exchange: str
    timezone_name: str
    calendar_response_max_age_seconds: int
    snapshot: ExchangeCalendarSnapshot
    publication_id: str
    publication_hash: str
    raw_body: bytes = field(repr=False)
    raw_body_sha256: str
    raw_payload_hash: str
    calendar_evidence: ExecutionCalendarEvidence
    market_session: date
    next_open_session: date
    _client: APIClient = field(repr=False)
    _csrf_token: str = field(repr=False)
    _created_provider_id: int = field(repr=False)
    _previous_provider_ids: tuple[int, ...] = field(repr=False)
    _root_urlconf: str = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Restore test-database provider activation through the public API."""

        if self._closed:
            return
        _restore_provider_scope(
            self._client,
            self._csrf_token,
            created_provider_id=self._created_provider_id,
            previous_provider_ids=self._previous_provider_ids,
            root_urlconf=self._root_urlconf,
        )
        self._closed = True


@dataclass(frozen=True, slots=True)
class _VerifiedExecutionEvidence:
    """Exact public-reader evidence and its independently checked original bytes."""

    evidence: ExecutionCalendarEvidence
    raw_body: bytes = field(repr=False)


def _require_isolated_test_database() -> None:
    """Refuse all writes unless Django is connected to the guarded Native test DB."""

    if connection.vendor != "postgresql":
        raise AssertionError("real calendar acceptance requires isolated Native PostgreSQL")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE", "")).strip().endswith(".production"):
        raise AssertionError("real calendar acceptance refuses production settings")
    assert_native_postgres_test_database()


def _validate_coverage(business_date: date, start: date, end: date) -> None:
    """Require exact date inputs and complete explicit coverage around the session."""

    if any(type(value) is not date for value in (business_date, start, end)):
        raise TypeError("calendar business date and coverage bounds must be exact dates")
    if start > business_date or end < business_date or start > end:
        raise ValueError("calendar coverage must explicitly include the business date")


def _repository_root() -> Path:
    """Resolve the checkout root from this test-support module."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "manage.py").is_file() and (parent / "apps").is_dir():
            return parent
    raise AssertionError("repository root could not be resolved")


def _ensure_calendar_catalog() -> None:
    """Create only the exact candidate catalog key through its public UOW."""

    root = _repository_root()
    rows = _calendar_catalog_candidate_rows(root)
    use_case = build_calendar_catalog_bootstrap_use_case(using="default")
    preview = use_case.preview(rows)
    if preview.outcome not in {"ready", "already_configured"}:
        raise AssertionError(f"calendar catalog preview blocked: {preview.reason_code}")
    result = use_case.execute(rows)
    if result.outcome not in {"created", "already_configured"}:
        raise AssertionError(f"calendar catalog UOW blocked: {result.reason_code}")


def _calendar_catalog_candidate_rows(root: Path) -> CalendarCatalogBootstrapRows:
    """Read and validate the exact ignored R55 projection before the typed UOW."""

    from apps.data_center.management.commands.initialize_data_center_catalog import (
        _load_bindings,
        _load_contracts,
        _load_owners,
        _load_policies,
    )

    overlay = root / ".tmp" / "ash07-risk-20261104" / "calendar-source"
    candidate = overlay / "isolated-candidate-r55"
    additions = _read_json_object(overlay / "catalog-additions.json")
    if additions.get("candidate_only") is not True:
        raise AssertionError("calendar catalog data must remain candidate-only")
    identity = additions.get("dataset_identity_basis")
    if type(identity) is not dict or identity.get("dataset_key") != _DATASET_KEY:
        raise AssertionError("calendar catalog candidate identity is not exact")

    expected_additions = additions.get("contracts")
    addition_bindings = additions.get("bindings")
    addition_policies = additions.get("policies")
    addition_owners = additions.get("owners")
    addition_values = (expected_additions, addition_bindings, addition_policies, addition_owners)
    if any(type(items) is not list or len(items) != 1 for items in addition_values):
        raise AssertionError("calendar candidate must contain one target row per catalog owner")

    for (filename, array_name, _owner_name), addition_rows in zip(
        _PROJECTION_FILES, addition_values, strict=True
    ):
        projection = _read_json_object(candidate / filename)
        if projection.get("schema_version") != "1.0":
            raise AssertionError(f"calendar projection schema changed: {filename}")
        raw_rows = projection.get(array_name)
        if type(raw_rows) is not list:
            raise AssertionError(f"calendar projection rows are invalid: {filename}")
        target_rows = [
            cast(dict[str, object], row)
            for row in raw_rows
            if type(row) is dict and row.get("dataset_key") == _DATASET_KEY
        ]
        addition_row = cast(dict[str, object], addition_rows[0])
        if len(target_rows) != 1 or _canonical_bytes(target_rows[0]) != _canonical_bytes(
            addition_row
        ):
            raise AssertionError(
                f"calendar projection changed from the exact candidate: {filename}"
            )

    contracts = _load_contracts(candidate / "dataset_contracts.json")
    matching_contracts = [row for row in contracts if row.key.value == _DATASET_KEY]
    if len(matching_contracts) != 1:
        raise AssertionError("calendar Dataset Contract is missing or ambiguous")
    contract_map = {row.key.value: row for row in contracts}
    bindings = [
        row
        for row in _load_bindings(candidate / "provider_bindings.json", contract_map)
        if row.dataset.value == _DATASET_KEY
    ]
    policies = [
        row
        for row in _load_policies(candidate / "publication_policies.json", contract_map)
        if row.dataset.value == _DATASET_KEY
    ]
    owners = [
        row
        for row in _load_owners(candidate / "data_ownership_contracts.json", contract_map)
        if row.dataset_key == _DATASET_KEY
    ]
    if len(bindings) != 1 or len(policies) != 1 or len(owners) != 1:
        raise AssertionError("calendar binding, policy and owner rows must each be unique")
    return CalendarCatalogBootstrapRows(
        contract=matching_contracts[0],
        binding=bindings[0],
        policy=policies[0],
        owner=owners[0],
    )


def _ensure_runtime_timezone() -> None:
    """Merge SSE into the active Config Center map without replacing other exchanges."""

    environment = "development"
    if get_active_runtime_profile(environment) is None:
        configure_critical_runtime()
    now = timezone.now().astimezone(UTC)
    current = get_active_runtime_value(
        environment=environment,
        definition_key=_TIMEZONE_KEY,
        as_of=now,
    )
    if current is None:
        timezone_map: dict[str, str] = {}
    elif type(current) is dict and all(
        type(key) is str and type(value) is str for key, value in current.items()
    ):
        timezone_map = dict(cast(dict[str, str], current))
    else:
        raise AssertionError("active exchange timezone map is invalid")
    prior_other_exchanges = {key: value for key, value in timezone_map.items() if key != _EXCHANGE}
    timezone_map[_EXCHANGE] = _TIMEZONE_NAME
    activate_runtime_profile_patch(
        environment=environment,
        patch={_TIMEZONE_KEY: timezone_map},
        actor="ash07-real-calendar-owner-test",
        reason="merge the isolated test database SSE timezone for a real calendar capture",
    )
    active = get_active_runtime_value(
        environment=environment,
        definition_key=_TIMEZONE_KEY,
        as_of=timezone.now().astimezone(UTC),
    )
    if type(active) is not dict or active.get(_EXCHANGE) != _TIMEZONE_NAME:
        raise AssertionError("SSE timezone was not published through Config Center")
    active_map = cast(dict[str, object], active)
    if {
        key: value for key, value in active_map.items() if key != _EXCHANGE
    } != prior_other_exchanges:
        raise AssertionError("timezone setup changed another exchange mapping")


def _active_tushare_provider_ids(client: APIClient) -> tuple[int, ...]:
    """Read active Tushare IDs so cleanup can restore them after any partial update."""

    response = client.get(_PROVIDER_PATH, secure=True, HTTP_ORIGIN=_ORIGIN)
    body = _response_object(response, 200)
    raw_rows = body.get("results")
    if type(raw_rows) is not list:
        raise AssertionError("Provider API returned no typed provider list")
    provider_ids: list[int] = []
    for value in raw_rows:
        if type(value) is not dict:
            raise AssertionError("Provider API returned a malformed row")
        row = cast(dict[str, object], value)
        if row.get("source_type") != "tushare" or row.get("is_active") is not True:
            continue
        provider_id = row.get("id")
        if type(provider_id) is not int or provider_id < 1:
            raise AssertionError("active Tushare provider has no exact ID")
        provider_ids.append(provider_id)
    exact_ids = tuple(sorted(set(provider_ids)))
    return exact_ids


def _create_test_provider(
    client: APIClient,
    csrf_token: str,
    *,
    token: str,
    request_mode: str,
    http_url: str,
) -> int:
    """Create one active test-database provider using the central secret value."""

    response = client.post(
        _PROVIDER_PATH,
        {
            "name": f"ash07-real-calendar-{uuid4().hex}",
            "source_type": "tushare",
            "is_active": True,
            "priority": 100,
            "api_key": token,
            "api_secret": "",
            "http_url": http_url,
            "api_endpoint": "",
            "tushare_request_mode": request_mode,
            "description": "ASH07 isolated real calendar acceptance only",
        },
        format="json",
        secure=True,
        HTTP_ORIGIN=_ORIGIN,
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    body = _response_object(response, 201)
    provider_id = body.get("id")
    if type(provider_id) is not int or provider_id < 1:
        raise AssertionError("Provider API did not return a new provider identity")
    if body.get("has_api_key") is not True or body.get("source_type") != "tushare":
        raise AssertionError("Provider API did not retain a configured Tushare credential")
    return provider_id


def _set_provider_active(
    client: APIClient,
    csrf_token: str,
    provider_id: int,
    active: bool,
) -> None:
    """Update only one provider's active flag through the existing Provider API."""

    response = client.patch(
        f"{_PROVIDER_PATH}{provider_id}/",
        {"is_active": active},
        format="json",
        secure=True,
        HTTP_ORIGIN=_ORIGIN,
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    if response.status_code != 200:
        raise AssertionError(f"Provider API activation update failed: {response.status_code}")


def _selected_response_age_limit(client: APIClient, provider_id: int) -> int:
    """Require Workbench to select the exact provider and its explicit age cap."""

    response = client.get(_WORKBENCH_SCOPE_PATH, secure=True, HTTP_ORIGIN=_ORIGIN)
    body = _response_object(response, 200)
    data = _nested_object(body, "data")
    if data.get("metadata_status") != "metadata_selected":
        raise AssertionError("calendar Workbench did not select active catalog metadata")
    if (
        data.get("secret_runtime_status") != "not_checked"
        or data.get("current_pointer_status") != "not_scoped"
    ):
        raise AssertionError("calendar scope endpoint unexpectedly exposed runtime credentials")
    metadata = _nested_object(data, "metadata")
    if (
        metadata.get("dataset_key") != _DATASET_KEY
        or metadata.get("provider_id") != provider_id
        or metadata.get("provider") != "tushare"
        or metadata.get("capability") != "exchange_calendar"
        or metadata.get("validator_key") != "exchange_calendar.tushare.trade_cal.full_date.v1"
    ):
        raise AssertionError("calendar Workbench selected a different provider binding")
    response_age_limit = metadata.get("calendar_response_max_age_seconds")
    if type(response_age_limit) is not int or response_age_limit < 1:
        raise AssertionError("calendar response-age policy is not explicitly configured")
    return response_age_limit


def _prepare_and_confirm(
    client: APIClient,
    csrf_token: str,
    *,
    coverage_start: date,
    coverage_end: date,
) -> None:
    """Use the actual session/CSRF Workbench prepare and confirmation endpoints."""

    prepared_response = client.post(
        _WORKBENCH_PREPARE_PATH,
        {
            "exchange": _EXCHANGE,
            "coverage_start": coverage_start.isoformat(),
            "coverage_end": coverage_end.isoformat(),
        },
        format="json",
        secure=True,
        HTTP_ORIGIN=_ORIGIN,
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    prepared = _response_object(prepared_response, 201)
    continuation = _nested_object(prepared, "continuation")
    if continuation.get("action_key") != "data-center.calendar-workbench-confirm":
        raise AssertionError("calendar Workbench continuation action changed")
    confirmation_input = _nested_object(continuation, "input")
    token = confirmation_input.get("confirmation_token")
    if type(token) is not str or not token:
        raise AssertionError("calendar Workbench did not return its opaque continuation")
    preview = _nested_object(prepared, "data")
    if (
        preview.get("publication_status") != "preview"
        or preview.get("must_not_use_for_decision") is not True
        or preview.get("source_published_at") is not None
        or preview.get("exchange") != _EXCHANGE
        or preview.get("coverage_start") != coverage_start.isoformat()
        or preview.get("coverage_end") != coverage_end.isoformat()
    ):
        raise AssertionError("calendar preview changed its reference-only clock semantics")

    confirmed_response = client.post(
        _WORKBENCH_CONFIRM_PATH,
        {"confirmation_token": token},
        format="json",
        secure=True,
        HTTP_ORIGIN=_ORIGIN,
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    if confirmed_response.status_code not in (200, 201):
        raise AssertionError(
            f"calendar Workbench confirmation failed: {confirmed_response.status_code}"
        )
    confirmed = _response_object(confirmed_response, confirmed_response.status_code)
    published = _nested_object(confirmed, "data")
    if (
        published.get("publication_status") != "published"
        or published.get("must_not_use_for_decision") is not True
        or published.get("source_published_at") is not None
    ):
        raise AssertionError("calendar confirmation lost reference-only or unknown-clock semantics")


def _read_current_calendar(client: APIClient) -> dict[str, object]:
    """Read the current publication through the public Workbench current route."""

    response = client.get(
        _WORKBENCH_CURRENT_PATH,
        {"exchange": _EXCHANGE},
        secure=True,
        HTTP_ORIGIN=_ORIGIN,
    )
    body = _response_object(response, 200)
    data = _nested_object(body, "data")
    if data.get("configuration_status") != "metadata_selected":
        raise AssertionError("calendar current read did not select metadata")
    if data.get("current_status") != "published" or data.get("blocked_reason") is not None:
        raise AssertionError("calendar current read did not return the published member")
    current = _nested_object(data, "current")
    freshness = _nested_object(current, "freshness")
    if (
        current.get("source_published_at") is not None
        or current.get("must_not_use_for_decision") is not True
        or freshness.get("source_observed_at") is not None
        or freshness.get("source_available_at") is not None
        or freshness.get("source_time_status") != "not_provided"
    ):
        raise AssertionError(
            "calendar response acquisition time must not fill source publication time"
        )
    return current


def _read_exact_execution_evidence(
    *,
    business_date: date,
    coverage_start: date,
    current_payload: dict[str, object],
    as_of: datetime,
) -> _VerifiedExecutionEvidence:
    """Verify the consumer's exact current member and its retained RawPayload."""

    reader = build_configured_execution_calendar_reader(runtime_environment="development")
    evidence = reader.get_effective_execution_calendar(
        exchange=_EXCHANGE,
        as_of=as_of,
        coverage_start=coverage_start,
    )
    if type(evidence) is not ExecutionCalendarEvidence:
        raise AssertionError("simulated-calendar consumer returned no exact published evidence")
    evidence.validate_for(as_of)
    if evidence.current_open_session(as_of) != business_date:
        raise AssertionError("real published calendar does not mark the candidate session open")
    current_days = _nested_list(current_payload, "calendar_days")
    reported_day = next(
        (
            cast(dict[str, object], row)
            for row in current_days
            if type(row) is dict and row.get("calendar_date") == business_date.isoformat()
        ),
        None,
    )
    if reported_day is None or reported_day.get("is_open") is not True:
        raise AssertionError("public Workbench current response does not mark the date open")

    publication = evidence.publication
    if publication is None or publication.timezone_name != _TIMEZONE_NAME:
        raise AssertionError("execution calendar evidence is not bound to the active SSE timezone")
    if not publication.reference_valid_from <= as_of < publication.reference_valid_until:
        raise AssertionError("published calendar is outside its real reference-validity window")
    if evidence.snapshot.source_published_at is not None:
        raise AssertionError("unknown vendor publication time was replaced with a local clock")
    raw_reference = evidence.snapshot.raw_reference
    if raw_reference.dataset_key != _DATASET_KEY or raw_reference.provider_name != "tushare":
        raise AssertionError("published calendar raw source identity differs from the catalog")

    raw = get_retained_raw_payload(payload_hash=raw_reference.payload_hash)
    if type(raw) is not RawPayload:
        raise AssertionError(
            "exact retained Tushare RawPayload is unavailable in the test database"
        )
    response_reference = _response_reference(raw)
    if not response_reference.verifies(raw):
        raise AssertionError("retained Tushare response failed its content and record digests")
    if (
        raw.payload_id != raw_reference.payload_id
        or raw.payload_hash != raw_reference.payload_hash
        or raw_payload_record_digest(raw) != raw_reference.record_digest
        or response_reference.body_sha256 != raw_reference.body_sha256
        or response_reference.retained_content_sha256 != raw_reference.retained_content_sha256
        or response_reference.response_completed_at != raw_reference.response_completed_at
        or response_reference.provider_name != raw_reference.provider_name
        or response_reference.dataset_key != raw_reference.dataset_key
        or response_reference.transport.value != raw_reference.transport
        or raw.payload.get("request_params_sha256")
        != hashlib.sha256(
            canonical_provider_response_json(raw.request_params).encode("utf-8")
        ).hexdigest()
        or raw_reference.request_scope_sha256
        != exchange_calendar_request_scope_hash(
            evidence.snapshot.exchange,
            evidence.snapshot.coverage_start,
            evidence.snapshot.coverage_end,
        )
    ):
        raise AssertionError("calendar snapshot and retained raw response identities differ")
    expected_request_params = {
        "exchange": evidence.snapshot.exchange,
        "start_date": evidence.snapshot.coverage_start.strftime("%Y%m%d"),
        "end_date": evidence.snapshot.coverage_end.strftime("%Y%m%d"),
    }
    if (
        set(raw.request_params) not in ({"fields", "params"}, {"api_name", "fields", "params"})
        or raw.request_params.get("api_name", "trade_cal") != "trade_cal"
        or raw.request_params.get("fields") != "exchange,cal_date,is_open,pretrade_date"
        or raw.request_params.get("params") != expected_request_params
    ):
        raise AssertionError("retained calendar request differs from the exact unfiltered scope")
    if (
        raw_reference.original_body_retained is not True
        or raw_reference.retained_content_sha256 != raw_reference.body_sha256
        or evidence.snapshot.first_seen_at != raw_reference.response_completed_at
        or raw.fetched_at != raw_reference.response_completed_at
        or evidence.snapshot.recorded_at < evidence.snapshot.first_seen_at
    ):
        raise AssertionError("local response, recorded and snapshot knowledge clocks were changed")
    retained_response = raw.payload.get("retained_response_json")
    if type(retained_response) is not str:
        raise AssertionError("retained calendar response is not original UTF-8 JSON text")
    original_body_sha256 = hashlib.sha256(retained_response.encode("utf-8")).hexdigest()
    if original_body_sha256 != raw_reference.body_sha256:
        raise AssertionError("retained UTF-8 response bytes differ from original body SHA-256")
    if raw.payload_hash == f"sha256:{raw_reference.body_sha256}":
        raise AssertionError("RawPayload manifest identity was confused with original body hash")
    if evidence.snapshot.record_digest == raw_reference.record_digest:
        raise AssertionError("snapshot record digest was confused with RawPayload record digest")

    api_as_of = _parse_aware_utc(current_payload.get("as_of"))
    if (
        api_as_of is None
        or api_as_of > as_of
        or not publication.reference_valid_from <= api_as_of < publication.reference_valid_until
    ):
        raise AssertionError("public current response has no valid server-owned cutoff")
    if (
        current_payload.get("exchange") != evidence.snapshot.exchange
        or current_payload.get("coverage_start") != evidence.snapshot.coverage_start.isoformat()
        or current_payload.get("coverage_end") != evidence.snapshot.coverage_end.isoformat()
        or current_payload.get("first_seen_at") != _utc_text(evidence.snapshot.first_seen_at)
        or current_payload.get("response_expires_at")
        != _utc_text(publication.reference_valid_until)
        or _canonical_bytes(_nested_list(current_payload, "calendar_days"))
        != _canonical_bytes([day.to_payload() for day in evidence.snapshot.days])
    ):
        raise AssertionError("public current response differs from exact consumer evidence")
    return _VerifiedExecutionEvidence(evidence=evidence, raw_body=retained_response.encode("utf-8"))


def _response_reference(raw: RawPayload) -> ProviderResponsePayloadReference:
    """Rebuild the public response reference solely from one exact RawPayload."""

    payload = raw.payload
    body_hash = payload.get("response_body_sha256")
    retained_hash = payload.get("retained_content_sha256")
    body_retained = payload.get("original_body_retained")
    encoding = payload.get("retained_content_encoding")
    body_size = payload.get("response_body_size_bytes")
    transport = payload.get("transport")
    if (
        type(body_hash) is not str
        or type(retained_hash) is not str
        or type(body_retained) is not bool
        or type(encoding) is not str
        or type(body_size) is not int
        or type(transport) is not str
    ):
        raise AssertionError("RawPayload response receipt is incomplete")
    try:
        reference = ProviderResponsePayloadReference(
            payload_id=raw.payload_id,
            payload_hash=raw.payload_hash,
            record_digest=raw_payload_record_digest(raw),
            body_sha256=body_hash,
            retained_content_sha256=retained_hash,
            original_body_retained=body_retained,
            retained_content_encoding=encoding,
            body_size_bytes=body_size,
            response_completed_at=raw.fetched_at,
            provider_name=raw.provider_name,
            dataset_key=raw.dataset_key,
            transport=ProviderResponseTransport(transport),
            run_id=raw.run_id,
        )
    except (TypeError, ValueError) as error:
        raise AssertionError("RawPayload response receipt is invalid") from error
    return reference


def _restore_provider_scope(
    client: APIClient,
    csrf_token: str,
    *,
    created_provider_id: int | None,
    previous_provider_ids: tuple[int, ...],
    root_urlconf: str,
) -> None:
    """Restore only active flags through the public Provider API after the read."""

    with override_settings(ROOT_URLCONF=root_urlconf):
        if created_provider_id is not None:
            _set_provider_active(client, csrf_token, created_provider_id, False)
        for provider_id in previous_provider_ids:
            _set_provider_active(client, csrf_token, provider_id, True)


def _response_object(response: Any, expected_status: int) -> dict[str, object]:
    """Narrow one HTTP JSON object without echoing request or secret material."""

    if response.status_code != expected_status:
        raise AssertionError(f"calendar/provider API returned {response.status_code}")
    content_type = response.get("Content-Type", "")
    if not isinstance(content_type, str) or not content_type.startswith("application/json"):
        raise AssertionError("calendar/provider API did not return JSON")
    value = response.json()
    if type(value) is not dict:
        raise AssertionError("calendar/provider API returned a non-object response")
    return cast(dict[str, object], value)


def _nested_object(value: dict[str, object], key: str) -> dict[str, object]:
    """Return one exact nested JSON object or reject malformed response data."""

    result = value.get(key)
    if type(result) is not dict:
        raise AssertionError(f"calendar/provider API response is missing {key}")
    return cast(dict[str, object], result)


def _nested_list(value: dict[str, object], key: str) -> list[object]:
    """Return one exact nested JSON list or reject malformed response data."""

    result = value.get(key)
    if type(result) is not list:
        raise AssertionError(f"calendar/provider API response is missing {key}")
    return cast(list[object], result)


def _read_json_object(path: Path) -> dict[str, object]:
    """Load one exact UTF-8 JSON object from the ignored catalog candidate."""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise AssertionError(f"calendar catalog candidate is not an object: {path.name}")
    return cast(dict[str, object], value)


def _canonical_bytes(value: object) -> bytes:
    """Encode one candidate value for exact projection comparison."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parse_aware_utc(value: object) -> datetime | None:
    """Parse only an explicit aware UTC JSON timestamp without inventing a zone."""

    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    """Match the public Workbench's exact UTC JSON representation."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ("RealCalendarPublicationLease", "publish_real_calendar_for_acceptance")
