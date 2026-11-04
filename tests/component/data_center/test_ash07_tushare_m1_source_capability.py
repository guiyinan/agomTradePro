"""Opt-in real-source smoke coverage for the bounded ASH07 M1 Tushare lane.

This is source-capability evidence only. It does not exercise risk admission,
industry membership, vendor quote state, or a complete ASH07 financial journey.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, date
from pathlib import Path
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_runtime_profile,
    get_active_runtime_value,
)
from apps.config_center.domain.runtime_config import RuntimeConfigProfile
from apps.data_center.application.interface_services import save_provider_settings_payload
from apps.data_center.application.m1_reference_price_batch_publication import (
    M1ReferencePriceBatchPublicationResult,
)
from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.raw_landing_public import get_retained_raw_payload
from apps.data_center.domain.control_plane import CanonicalPublication
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
)
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    ReferenceCloseReadResult,
)
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    PublishedClosePriceReader,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.ash07_native_runtime_role import isolated_ash07_runtime_role
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    OwnerAccountSeed,
    audit_runtime_patch,
    create_owner_account_seed,
    issue_current_owner_audit_selector,
    publish_current_owner_policy,
)
from tests.support.ash07_owner_m1_price_batch import publish_and_verify_tushare_close_batch
from tests.support.ash07_real_calendar_publication import (
    RealCalendarPublicationLease,
    publish_real_calendar_for_acceptance,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TARGET_SESSION = date(2026, 11, 3)
_CALENDAR_DATE = date(2026, 11, 4)
_BANK_ASSETS = ("600036.SH", "601398.SH")
_ARTIFACT_PURPOSE = "ash07_tushare_m1_source_capability_only"


@pytest.fixture
def actual_runtime_role(transactional_db: None, tmp_path: Path) -> Iterator[dict[str, object]]:
    """Restore management identity before pytest performs its database flush."""

    del transactional_db
    _require_isolated_database()
    with isolated_ash07_runtime_role(tmp_path / "runtime-role") as report:
        yield report


@pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_ASH07_M1_SOURCE_CAPABILITY") != "1",
    reason="opt in only for the isolated real Tushare source-capability smoke",
)
@override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls")
def test_ash07_nov03_tushare_m1_publication_source_capability_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actual_runtime_role: dict[str, object],
) -> None:
    """Publish and read two Nov 03 Tushare bars under real calendar and V3 audit scope."""

    _require_isolated_database()
    assert actual_runtime_role["runtime_acl_verified"] is True
    cutoff = timezone.now().astimezone(UTC)
    local_cutoff = cutoff.astimezone(_SHANGHAI)
    if local_cutoff.date() != _CALENDAR_DATE:
        pytest.skip("this source-only candidate is scoped to the actual Nov 04 date")
    # Production readers require Nov 03 to be the actual latest completed
    # session. That rule also applies intraday; the candidate is rejected once
    # the published/provider-backed calendars select a different session.

    _archive_retention_attempts(monkeypatch, tmp_path)

    # The full canonical catalog must precede the candidate-only calendar row;
    # the calendar helper then adds its exact catalog candidate through the UOW.
    call_command("initialize_data_center_catalog", verbosity=0)
    configure_critical_runtime()
    provider_policy = save_provider_settings_payload(
        default_source="tushare",
        enable_failover=False,
        failover_tolerance=0.01,
        actor="ash07-source-capability-test",
    )
    if provider_policy.get("status") != "active":
        raise AssertionError("explicit test Tushare provider routing is not active")
    calendar = publish_real_calendar_for_acceptance(
        business_date=_CALENDAR_DATE,
        coverage_start=_TARGET_SESSION,
        coverage_end=date(2026, 11, 6),
    )
    try:
        _assert_real_calendar(calendar)
        if latest_completed_cn_market_session(timezone.now().astimezone(UTC)) != _TARGET_SESSION:
            raise AssertionError("published calendar does not select Nov 03 as latest completed")

        owner_seed = create_owner_account_seed()
        publish_current_owner_policy(owner_seed)
        current_local_time = timezone.now().astimezone(_SHANGHAI)
        if current_local_time.date() != _CALENDAR_DATE:
            pytest.skip("the source capture requires the actual Nov 04 calendar date")
        selector = issue_current_owner_audit_selector(owner_seed)

        # This is the final ConfigCenter write. The patch merges with the real
        # SSE timezone and leaves the source-only risk policy fail-closed.
        activate_runtime_profile_patch(
            environment=owner_seed.environment,
            patch=audit_runtime_patch(selector),
            actor="ash07-m1-source-capability-test",
            reason="require the current real V3 Account authority for M1 activation",
        )
        profile_before = _assert_required_runtime(owner_seed, selector)

        # The helper uses the active real Tushare ProviderConfig, SDK, normal
        # server clock, required Audit factory, one exact batch CAS, and public
        # PublishedClosePriceReader. No quote or industry input is admitted here.
        publication = publish_and_verify_tushare_close_batch(
            asset_codes=_BANK_ASSETS,
            target_trade_date=_TARGET_SESSION,
        )
        profile_after = get_active_runtime_profile(owner_seed.environment)
        if (
            profile_after is None
            or profile_after.profile_id != profile_before.profile_id
            or profile_after.version != profile_before.version
        ):
            raise AssertionError("runtime profile changed after the final audit selector write")

        read_rows = _verify_public_close_reads(publication)
        audit_summary = _verify_required_publication_audit(publication.publication.publication_id)
        artifact_path = _archive_source_evidence(
            calendar=calendar,
            owner_seed=owner_seed,
            selector=selector,
            publication=publication,
            read_rows=read_rows,
            audit_summary=audit_summary,
            profile_id=profile_before.profile_id,
            profile_version=profile_before.version,
        )
        assert artifact_path.is_file()
    finally:
        calendar.close()


def _archive_retention_attempts(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """Observe real retention without changing captures, clocks, or return values.

    Keep verified, credential-safe originals before any later transaction rollback
    or test cleanup. Attempt evidence does not establish persistent publication.
    """

    original = RetainProviderResponsePayloadUseCase.execute
    output = directory / "retention-attempts"
    output.mkdir()

    def retain(
        self: RetainProviderResponsePayloadUseCase,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: Mapping[str, object],
        sensitive_values: tuple[str, ...] = (),
        run_id: str | None = None,
    ) -> ProviderResponsePayloadReference:
        reference = original(
            self,
            capture,
            provider_name=provider_name,
            dataset_key=dataset_key,
            api_name=api_name,
            request_params=request_params,
            sensitive_values=sensitive_values,
            run_id=run_id,
        )
        row = get_retained_raw_payload(payload_hash=reference.payload_hash)
        if row is None or not reference.verifies(row):
            raise AssertionError("retention attempt does not verify its exact persisted row")
        metadata = reference.to_payload()
        metadata["evidence_scope"] = "retention attempt; later transaction may roll back"
        if reference.original_body_retained:
            body_text = row.payload.get("retained_response_json")
            if type(body_text) is not str:
                raise AssertionError("original response text is missing")
            body = body_text.encode("utf-8")
            if hashlib.sha256(body).hexdigest() != reference.body_sha256:
                raise AssertionError("original response body differs from its reference")
            name = f"{reference.payload_id}.original.json"
            (output / name).write_bytes(body)
            metadata["original_file"] = name
        (output / f"{reference.payload_id}.receipt.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return reference

    monkeypatch.setattr(RetainProviderResponsePayloadUseCase, "execute", retain)


def _require_isolated_database() -> None:
    """Refuse this source-writing test outside its guarded native test database."""

    if connection.vendor != "postgresql":
        raise AssertionError("real Tushare capability requires isolated Native PostgreSQL")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE", "")).strip().endswith(".production"):
        raise AssertionError("source capability test refuses production settings")
    assert_native_postgres_test_database()


def _assert_real_calendar(calendar: RealCalendarPublicationLease) -> None:
    """Require the helper's published SSE chain and honest calendar clock fields."""

    if (
        calendar.business_date != _CALENDAR_DATE
        or calendar.dataset_key != "data_center.exchange_calendar_snapshot"
        or calendar.exchange != "SSE"
        or calendar.timezone_name != "Asia/Shanghai"
        or calendar.snapshot.source_published_at is not None
        or hashlib.sha256(calendar.raw_body).hexdigest() != calendar.raw_body_sha256
    ):
        raise AssertionError("real published SSE calendar identity or source clock changed")


def _assert_required_runtime(
    seed: OwnerAccountSeed,
    selector: SystemAuditAuthorityBundleSelector,
) -> RuntimeConfigProfile:
    """Confirm required Audit and SSE timezone survive the final merged profile write."""

    now = timezone.now().astimezone(UTC)
    profile = get_active_runtime_profile(seed.environment)
    if profile is None:
        raise AssertionError("final development ConfigCenter profile is unavailable")
    audit_mode = get_active_runtime_value(
        environment=seed.environment,
        definition_key="audit.system_event.mode",
        as_of=now,
    )
    outbox_enabled = get_active_runtime_value(
        environment=seed.environment,
        definition_key="audit.system_event.outbox_enabled",
        as_of=now,
    )
    configured_selector = get_active_runtime_value(
        environment=seed.environment,
        definition_key="audit.system_event.authority_selector",
        as_of=now,
    )
    timezone_map = get_active_runtime_value(
        environment=seed.environment,
        definition_key="config_center.market.exchange_timezone_map",
        as_of=now,
    )
    selector_payload = _selector_payload(selector)
    if (
        audit_mode != "required"
        or outbox_enabled is not True
        or configured_selector != selector_payload
        or type(timezone_map) is not dict
        or timezone_map.get("SSE") != "Asia/Shanghai"
    ):
        raise AssertionError("required Audit selector or published SSE timezone is not active")
    return profile


def _selector_payload(selector: SystemAuditAuthorityBundleSelector) -> dict[str, object]:
    """Return only the non-secret identifiers and hashes in the V3 selector."""

    values = {
        "actor_source_id": selector.actor_source_id,
        "actor_source_version": selector.actor_source_version,
        "actor_content_hash": selector.actor_content_hash,
        "scope_source_id": selector.scope_source_id,
        "scope_source_version": selector.scope_source_version,
        "scope_content_hash": selector.scope_content_hash,
        "scope_schema": selector.scope_schema,
    }
    if any(type(value) is not str or not value for value in values.values()):
        raise AssertionError("actual V3 selector is missing a non-secret source identity")
    return cast(dict[str, object], values)


def _verify_public_close_reads(
    publication: M1ReferencePriceBatchPublicationResult,
) -> tuple[dict[str, object], ...]:
    """Read both securities through the public M1 adapter at the normal cutoff."""

    cutoff = timezone.now().astimezone(UTC)
    if latest_completed_cn_market_session(cutoff) != _TARGET_SESSION:
        raise AssertionError("Nov 03 ceased to be the latest completed session during reads")
    result_publication = publication.publication
    reader = PublishedClosePriceReader()
    rows: list[dict[str, object]] = []
    for asset_code in _BANK_ASSETS:
        read: ReferenceCloseReadResult = reader.read(asset_code=asset_code, cutoff=cutoff)
        price_result = read.price_result
        price_publication = read.publication
        if (
            read.blocked_reason is not None
            or price_result is None
            or price_result.price <= 0
            or price_result.as_of != _TARGET_SESSION
            or price_publication is None
            or price_publication.bar_date != _TARGET_SESSION
            or price_publication.publication_id != result_publication.publication_id
            or price_publication.publication_hash != result_publication.publication_hash
            or price_publication.publication_key != result_publication.publication_key
        ):
            raise AssertionError(
                f"public close reader did not return the shared batch: {asset_code}"
            )
        rows.append(
            {
                "asset_code": asset_code,
                "bar_date": price_publication.bar_date.isoformat(),
                "publication_id": price_publication.publication_id,
                "publication_hash": price_publication.publication_hash,
                "publication_key": price_publication.publication_key,
                "price": str(price_result.price),
                "price_as_of": price_result.as_of.isoformat(),
                "vendor_published_at": None,
                "vendor_available_at": None,
                "vendor_valid_until": None,
                "clock_note": "local capture completion is knowledge time, not a vendor source clock",
            }
        )
    return tuple(rows)


def _verify_required_publication_audit(publication_id: str) -> dict[str, object]:
    """Require the M1 activation's actual required-mode SystemAudit event and outbox row."""

    events = SystemAuditEventModel._default_manager.using("default").filter(
        event_type="data.publication.published",
        publication_id=publication_id,
    )
    if events.count() != 1:
        raise AssertionError("M1 activation did not append exactly one publication audit event")
    event = events.get()
    if (
        not SystemAuditOutboxModel._default_manager.using("default")
        .filter(event_id=event.event_id)
        .exists()
    ):
        raise AssertionError("required M1 publication audit event has no durable outbox row")
    return {
        "event_id": event.event_id,
        "event_content_hash": event.content_hash,
        "event_type": event.event_type,
        "schema": event.detail_schema,
        "outcome": event.outcome,
        "recorded_at": event.recorded_at.isoformat(),
        "outbox_present": True,
    }


def _archive_source_evidence(
    *,
    calendar: RealCalendarPublicationLease,
    owner_seed: OwnerAccountSeed,
    selector: SystemAuditAuthorityBundleSelector,
    publication: M1ReferencePriceBatchPublicationResult,
    read_rows: tuple[dict[str, object], ...],
    audit_summary: dict[str, object],
    profile_id: str,
    profile_version: int,
) -> Path:
    """Write safe M1 originals and exact identities to one ignored run directory."""

    repository_root = _repository_root()
    run_directory = (
        repository_root / ".tmp" / "ash07-risk-20261104" / "m1-source-capability-runs" / uuid4().hex
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    if hashlib.sha256(calendar.raw_body).hexdigest() != calendar.raw_body_sha256:
        raise AssertionError("calendar helper raw bytes do not match the verified SHA-256")
    calendar_payload = get_retained_raw_payload(payload_hash=calendar.raw_payload_hash)
    if type(calendar_payload) is not RawPayload:
        raise AssertionError("exact retained calendar RawPayload is missing")
    calendar_response = _response_reference(calendar_payload)
    calendar_retained_text = calendar_payload.payload.get("retained_response_json")
    if (
        not calendar_response.verifies(calendar_payload)
        or not calendar_response.original_body_retained
        or type(calendar_retained_text) is not str
        or calendar_retained_text.encode("utf-8") != calendar.raw_body
    ):
        raise AssertionError("calendar original bytes differ from its retained capture")
    (run_directory / "sse-calendar-original.json").write_bytes(calendar.raw_body)

    publication_value: CanonicalPublication = publication.publication
    sync_results = publication.sync_results
    if type(sync_results) is not tuple or len(sync_results) != 2:
        raise AssertionError("M1 batch result is not an exact two-member publication")
    manifest = DjangoCandidateRawAuditManifestRepository(using="default").validate(
        publication_value.publication_id
    )
    if (
        manifest.publication_hash != publication_value.publication_hash
        or manifest.raw_audit_count != 2
        or {item.raw_audit_id for item in manifest.raw_audits}
        != {
            item.raw_audit_reference.raw_audit_id
            for item in sync_results
            if item.raw_audit_reference is not None
        }
    ):
        raise AssertionError("M1 RawAudit manifest does not exactly bind both sync results")

    raw_evidence: list[dict[str, object]] = []
    for sync_result in sync_results:
        if len(sync_result.stored_asset_codes) != 1 or sync_result.raw_audit_reference is None:
            raise AssertionError("M1 sync omitted an exact asset or RawAudit identity")
        asset_code = sync_result.stored_asset_codes[0]
        raw_reference = sync_result.raw_audit_reference
        raw_audit = RawAuditModel._default_manager.using("default").get(
            pk=int(raw_reference.raw_audit_id)
        )
        if (
            raw_audit.content_hash != raw_reference.content_hash
            or str(raw_audit.run_id) != raw_reference.run_id
            or str(raw_audit.ingested_run_id) != raw_reference.ingested_run_id
            or not raw_audit.response_payload_hash
            or raw_audit.provider_name != sync_result.provider_name
            or raw_audit.extra.get("source_type") != "tushare"
        ):
            raise AssertionError(f"persisted RawAudit differs from its sync receipt: {asset_code}")
        payload = get_retained_raw_payload(payload_hash=raw_audit.response_payload_hash)
        if type(payload) is not RawPayload:
            raise AssertionError(f"exact retained Tushare RawPayload is missing: {asset_code}")
        if payload.provider_name != raw_audit.provider_name:
            raise AssertionError(f"RawPayload provider differs from RawAudit: {asset_code}")
        response = _response_reference(payload)
        retained_text = payload.payload.get("retained_response_json")
        if (
            not response.verifies(payload)
            or not response.original_body_retained
            or type(retained_text) is not str
        ):
            raise AssertionError(f"the exact provider original cannot be archived: {asset_code}")
        raw_body = retained_text.encode("utf-8")
        body_sha256 = hashlib.sha256(raw_body).hexdigest()
        if body_sha256 != response.body_sha256 or len(raw_body) != response.body_size_bytes:
            raise AssertionError(
                f"retained provider original differs from its capture: {asset_code}"
            )
        filename = f"tushare-daily-{asset_code.replace('.', '-')}-{body_sha256[:12]}.json"
        (run_directory / filename).write_bytes(raw_body)
        raw_evidence.append(
            {
                "asset_code": asset_code,
                "provider": raw_audit.provider_name,
                "capability": raw_audit.capability,
                "raw_audit_id": raw_reference.raw_audit_id,
                "raw_audit_version": raw_reference.version,
                "raw_audit_content_hash": raw_reference.content_hash,
                "run_id": raw_reference.run_id,
                "ingested_run_id": raw_reference.ingested_run_id,
                "raw_payload_hash": payload.payload_hash,
                "raw_payload_record_digest": raw_payload_record_digest(payload),
                "response_body_sha256": response.body_sha256,
                "response_body_size_bytes": response.body_size_bytes,
                "response_completed_at_local_knowledge_time": (
                    response.response_completed_at.isoformat()
                ),
                "response_transport": response.transport.value,
                "retained_encoding": response.retained_content_encoding,
                "original_file": filename,
                "original_file_sha256": body_sha256,
                "vendor_published_at": None,
                "vendor_available_at": None,
                "vendor_valid_until": None,
            }
        )

    if {item["asset_code"] for item in raw_evidence} != set(_BANK_ASSETS):
        raise AssertionError("archived RawAudit originals do not match the two declared banks")
    manifest_payload: dict[str, object] = {
        "purpose": _ARTIFACT_PURPOSE,
        "not_an_ash07_financial_acceptance": True,
        "runtime_clock": "django_timezone.now_without_test_patch",
        "business_date": _CALENDAR_DATE.isoformat(),
        "latest_completed_session": _TARGET_SESSION.isoformat(),
        "calendar": {
            "dataset_key": calendar.dataset_key,
            "exchange": calendar.exchange,
            "business_date": calendar.business_date.isoformat(),
            "coverage_start": _TARGET_SESSION.isoformat(),
            "coverage_end": date(2026, 11, 6).isoformat(),
            "publication_id": calendar.publication_id,
            "publication_hash": calendar.publication_hash,
            "raw_payload_hash": calendar.raw_payload_hash,
            "raw_body_sha256": calendar.raw_body_sha256,
            "source_published_at": None,
            "response_completed_at_local_knowledge_time": (
                calendar_response.response_completed_at.isoformat()
            ),
            "raw_file": "sse-calendar-original.json",
        },
        "owner": {
            "account_id": owner_seed.account.pk,
            "owner_user_id": owner_seed.owner.pk,
            "test_role": "staff + rbac admin; AccountProfile approval pending",
            "ordinary_risk_owner_acceptance": False,
            "binding_id": owner_seed.binding.binding_id,
            "binding_version": owner_seed.binding.binding_version,
            "binding_content_hash": owner_seed.binding.content_hash,
        },
        "system_audit": {
            "mode": "required",
            "outbox_enabled": True,
            "selector": _selector_payload(selector),
            "publication_event": audit_summary,
        },
        "runtime_profile": {
            "environment": owner_seed.environment,
            "profile_id": profile_id,
            "version": profile_version,
            "no_profile_write_after_m1_before_public_close_reads": True,
        },
        "publication": {
            "dataset_key": publication_value.dataset_key,
            "publication_key": publication_value.publication_key,
            "publication_id": publication_value.publication_id,
            "publication_hash": publication_value.publication_hash,
            "selected_source": publication_value.selected_source,
            "member_count": publication_value.member_count,
            "raw_audit_manifest_id": manifest.manifest_id,
            "raw_audit_manifest_hash": manifest.manifest_hash,
            "raw_audit_count": manifest.raw_audit_count,
        },
        "public_published_close_reads": list(read_rows),
        "raw_audits": raw_evidence,
        "excluded_inputs": ["risk quotes", "industry membership", "portfolio financial admission"],
    }
    manifest_path = run_directory / "source-capability-evidence.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _response_reference(payload: RawPayload) -> ProviderResponsePayloadReference:
    """Rebuild a provider response reference from its exact retained payload row."""

    envelope = payload.payload
    body_sha256 = envelope.get("response_body_sha256")
    retained_sha256 = envelope.get("retained_content_sha256")
    original_retained = envelope.get("original_body_retained")
    encoding = envelope.get("retained_content_encoding")
    body_size = envelope.get("response_body_size_bytes")
    transport = envelope.get("transport")
    if (
        type(body_sha256) is not str
        or type(retained_sha256) is not str
        or type(original_retained) is not bool
        or type(encoding) is not str
        or type(body_size) is not int
        or type(transport) is not str
        or type(envelope.get("response_completed_at")) is not str
    ):
        raise AssertionError("retained Tushare response receipt is incomplete")
    try:
        return ProviderResponsePayloadReference(
            payload_id=payload.payload_id,
            payload_hash=payload.payload_hash,
            record_digest=raw_payload_record_digest(payload),
            body_sha256=body_sha256,
            retained_content_sha256=retained_sha256,
            original_body_retained=original_retained,
            retained_content_encoding=encoding,
            body_size_bytes=body_size,
            response_completed_at=payload.fetched_at,
            provider_name=payload.provider_name,
            dataset_key=payload.dataset_key,
            transport=ProviderResponseTransport(transport),
            run_id=payload.run_id,
        )
    except (TypeError, ValueError) as error:
        raise AssertionError("retained Tushare response receipt is malformed") from error


def _repository_root() -> Path:
    """Find the ignored test's checkout root without relying on the working directory."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "manage.py").is_file() and (parent / "apps").is_dir():
            return parent
    raise AssertionError("repository root could not be located")
