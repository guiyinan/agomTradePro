"""Focused tests for publication-bound exact daily price source reads."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.data_center.application.price_response_capture import (
    ExactPriceBarRequestScope,
    ExactPriceBarValues,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.application.published_price_source import (
    PublishedPriceSourceFact,
    PublishedPriceSourceResult,
    ReadPublishedPriceSource,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
)
from apps.data_center.domain.raw_landing import RawPayload

TRADE_DATE = date(2026, 10, 26)
ASSET_CODE = "600000.SH"
PUBLICATION_ID = "ca8e468a-8083-41a8-89b4-49c1372ab074"
PUBLICATION_RUN_ID = "d7cf2eb3-2e33-4bd9-9f9b-010e3b315b34"
INGESTED_RUN_ID = "80996917-c07c-4f07-a913-65c5e74416bf"
AUDIT_ID = "41"
PUBLICATION_KEY = "current"
COMPOSITION_CUTOFF = datetime(2026, 10, 26, 8, tzinfo=UTC)

EXPECTED_VALUES = ExactPriceBarValues(
    open=Decimal("10.12345678901234567890"),
    high=Decimal("12.75"),
    low=Decimal("9.5"),
    close=Decimal("12.5"),
    volume=Decimal("25000"),
    amount=Decimal("123450.0000000000000001"),
)


class _PayloadStore:
    """Keep the value emitted by the production raw-payload retainer."""

    def __init__(self) -> None:
        self.payload: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        self.payload = payload
        return payload


@dataclass
class _Fixture:
    scope: ExactPriceBarRequestScope
    response_reference: ProviderResponsePayloadReference
    raw_payload: RawPayload
    member: PublicationMember
    publication: CanonicalPublication
    fact: PublishedPriceSourceFact
    audit: RawAudit
    audit_reference: CandidateRawAuditReference
    manifest: CandidateRawAuditManifest
    observed_at: datetime
    cutoff: datetime


class _MemoryRepository:
    """Minimal typed read port with observable calls for fail-closed tests."""

    def __init__(self, fixture: _Fixture) -> None:
        self.facts: tuple[PublishedPriceSourceFact, ...] = (fixture.fact,)
        self.manifest: CandidateRawAuditManifest | None = fixture.manifest
        self.audits: dict[str, RawAudit] = {fixture.audit.raw_audit_id: fixture.audit}
        self.payloads: dict[str, RawPayload] = {
            fixture.response_reference.payload_hash: fixture.raw_payload
        }
        self.calls: list[str] = []

    def read_facts(
        self, *, asset_code: str, trade_date: date, fact_pks: tuple[str, ...]
    ) -> tuple[PublishedPriceSourceFact, ...]:
        self.calls.append("facts")
        return self.facts

    def read_manifest(self, publication_id: str) -> CandidateRawAuditManifest | None:
        self.calls.append("manifest")
        return self.manifest

    def read_audit(self, raw_audit_id: str) -> RawAudit | None:
        self.calls.append("audit")
        return self.audits.get(raw_audit_id)

    def read_payload(self, payload_hash: str) -> RawPayload | None:
        self.calls.append("payload")
        return self.payloads.get(payload_hash)


def _make_fixture(*, redact_volume: bool = False, response_delay_minutes: int = 1) -> _Fixture:
    """Build real, hash-bound publication and provider evidence for one session."""

    scope = ExactPriceBarRequestScope(
        provider_id=19,
        provider_name="tushare",
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code=ASSET_CODE,
        trade_date=TRADE_DATE,
    )
    observed_at = cn_market_session_close_utc(TRADE_DATE)
    response_completed_at = observed_at + timedelta(minutes=response_delay_minutes)
    volume_token = '"250"' if redact_volume else "250"
    body = (
        '{"code":0,"data":{"fields":["ts_code","trade_date","open","high",'
        '"low","close","vol","amount"],"items":[["600000.SH","20261026",'
        "10.12345678901234567890,12.75,9.5,12.5,"
        f'{volume_token},123.4500000000000000001]],"has_more":false}}}}'
    ).encode()
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=response_completed_at,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    store = _PayloadStore()
    response_reference = RetainProviderResponsePayloadUseCase(store).execute(
        capture,
        provider_name=scope.provider_name,
        dataset_key=scope.dataset_key,
        api_name=scope.api_name,
        request_params=scope.request_params(),
        sensitive_values=("250",) if redact_volume else (),
        run_id=PUBLICATION_RUN_ID,
    )
    retained_payload = store.payload
    assert retained_payload is not None

    publication_as_of = observed_at + timedelta(minutes=4)
    publication_published_at = observed_at + timedelta(minutes=5)
    fact_fetched_at = observed_at + timedelta(minutes=2)
    member = PublicationMember(
        member_id="member-1",
        publication_id=PUBLICATION_ID,
        dataset_key="equity.price.bar",
        natural_key=f"{ASSET_CODE}:{TRADE_DATE.isoformat()}",
        source="tushare",
        source_record_id=f"{ASSET_CODE}:{TRADE_DATE:%Y%m%d}",
        fact_table="data_center_price_bar",
        fact_pk="101",
        observed_at=observed_at,
        raw_payload_hash=response_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        fetched_at=fact_fetched_at,
        fact_content_hash="a" * 64,
    )
    reference = member_reference(member)
    selected_publication_hash = publication_hash((reference,))
    publication = CanonicalPublication(
        publication_id=PUBLICATION_ID,
        dataset_key="equity.price.bar",
        publication_key=PUBLICATION_KEY,
        policy_version="daily-price-policy-v1",
        state=PublicationState.PUBLISHED,
        selected_source="tushare",
        publication_hash=selected_publication_hash,
        coverage=CoverageSnapshot(
            coverage_id="coverage-1",
            publication_id=PUBLICATION_ID,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=publication_as_of,
        ),
        member_count=1,
        as_of=publication_as_of,
        published_at=publication_published_at,
        run_id=PUBLICATION_RUN_ID,
    )
    fact = PublishedPriceSourceFact(
        asset_code=ASSET_CODE,
        trade_date=TRADE_DATE,
        frequency="1d",
        adjustment=PriceAdjustment.NONE,
        values=EXPECTED_VALUES,
        ingested_run_id=INGESTED_RUN_ID,
        reference=reference,
    )
    audit = RawAudit(
        provider_name="tushare",
        capability="historical_price",
        request_params={"exact_price_request_scope": scope.to_payload()},
        status="ok",
        row_count=1,
        fetched_at=observed_at + timedelta(minutes=3),
        extra={
            "source_type": "tushare",
            "provider_response_request_scope": scope.to_payload(),
            "provider_response_payload_reference": response_reference.to_payload(),
        },
        response_payload_hash=response_reference.payload_hash,
        redacted=True,
        raw_audit_id=AUDIT_ID,
        run_id=PUBLICATION_RUN_ID,
        ingested_run_id=INGESTED_RUN_ID,
    )
    audit = replace(audit, content_hash=raw_audit_content_hash(audit))
    audit_reference = CandidateRawAuditReference(
        raw_audit_id=AUDIT_ID,
        version="1",
        content_hash=audit.content_hash,
        provider_name="tushare",
        capability="historical_price",
        run_id=PUBLICATION_RUN_ID,
        ingested_run_id=INGESTED_RUN_ID,
    )
    manifest = CandidateRawAuditManifest.create(
        publication_id=PUBLICATION_ID,
        publication_hash=selected_publication_hash,
        run_id=PUBLICATION_RUN_ID,
        dataset_key="equity.price.bar",
        publication_key=PUBLICATION_KEY,
        task_attempt_id="task-attempt-1",
        raw_audits=(audit_reference,),
        manifest_id="19d6dc1a-4a53-4c3b-8d80-6da584e274f3",
    )
    return _Fixture(
        scope=scope,
        response_reference=response_reference,
        raw_payload=retained_payload,
        member=member,
        publication=publication,
        fact=fact,
        audit=audit,
        audit_reference=audit_reference,
        manifest=manifest,
        observed_at=observed_at,
        cutoff=observed_at + timedelta(minutes=10),
    )


def _read(
    fixture: _Fixture,
    repository: _MemoryRepository | None = None,
    *,
    cutoff: datetime | None = None,
    publication: CanonicalPublication | None = None,
    members: tuple[PublicationMember, ...] | None = None,
) -> tuple[PublishedPriceSourceResult, _MemoryRepository]:
    """Exercise the pure use case with caller-selected persisted evidence."""

    selected_repository = repository or _MemoryRepository(fixture)
    result = ReadPublishedPriceSource(selected_repository).execute(
        asset_code=ASSET_CODE,
        trade_date=TRADE_DATE,
        knowledge_cutoff=cutoff or fixture.cutoff,
        publication=publication or fixture.publication,
        members=members or (fixture.member,),
        freshness_status="fresh",
    )
    return result, selected_repository


def test_reads_one_hash_bound_price_bar_with_exact_decimals() -> None:
    fixture = _make_fixture()

    result, repository = _read(fixture)

    assert result.evidence is not None
    assert result.blocked_reason == ""
    assert result.must_not_use_for_decision is False
    assert result.freshness_status == "fresh"
    assert result.evidence.values == EXPECTED_VALUES
    assert type(result.evidence.values.open) is Decimal
    assert result.evidence.available_at == fixture.response_reference.response_completed_at
    assert result.evidence.fact_recorded_at == fixture.member.fetched_at
    assert result.evidence.publication_as_of == fixture.publication.as_of
    assert result.evidence.raw_payload_reference == fixture.response_reference
    assert result.evidence.raw_audit_reference == fixture.audit_reference
    assert result.evidence.volume_unit == "shares"
    assert result.evidence.amount_unit == "CNY"
    assert repository.calls == ["facts", "manifest", "audit", "payload"]


def test_rejects_member_outside_the_publication_before_reading_facts() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    out_of_scope = replace(fixture.member, dataset_key="equity.quote.snapshot")

    result, repository = _read(fixture, repository, members=(out_of_scope,))

    assert result.evidence is None
    assert result.blocked_reason == "price_source_member_scope_invalid"
    assert result.must_not_use_for_decision is True
    assert repository.calls == []


def test_missing_original_payload_blocks_without_replacement() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.payloads.clear()
    result, _ = _read(fixture, repository)
    assert result.evidence is None
    assert result.blocked_reason == "price_source_raw_missing_or_changed"


def test_exact_decimal_difference_is_not_accepted_with_float_tolerance() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.facts = (
        replace(
            fixture.fact, values=replace(fixture.fact.values, close=Decimal("12.500000000000001"))
        ),
    )
    result, _ = _read(fixture, repository)
    assert result.evidence is None
    assert result.blocked_reason == "price_source_decimal_values_mismatch"


@pytest.mark.parametrize("response_delay_minutes", [6, 11])
def test_late_response_cannot_be_backdated_to_the_publication_or_cutoff(
    response_delay_minutes: int,
) -> None:
    fixture = _make_fixture(response_delay_minutes=response_delay_minutes)
    result, _ = _read(fixture)
    assert result.evidence is None
    assert result.blocked_reason == "price_source_response_time_invalid"


def test_rejects_fact_scope_that_differs_from_the_selected_member() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.facts = (replace(fixture.fact, asset_code="600001.SH"),)

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_fact_scope_or_content_mismatch"
    assert repository.calls == ["facts"]


def test_rejects_a_valid_manifest_bound_to_another_publication_hash() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.manifest = CandidateRawAuditManifest.create(
        publication_id=fixture.publication.publication_id,
        publication_hash="b" * 64,
        run_id=fixture.publication.run_id,
        dataset_key=fixture.publication.dataset_key,
        publication_key=fixture.publication.publication_key,
        task_attempt_id="task-attempt-1",
        raw_audits=(fixture.audit_reference,),
        manifest_id="1fac7250-d8b9-4d73-9900-75b7aeb3bb33",
    )

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_manifest_identity_mismatch"
    assert repository.calls == ["facts", "manifest"]


def test_rejects_audit_content_that_no_longer_matches_its_manifest_hash() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.audits[AUDIT_ID] = replace(fixture.audit, row_count=2)

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_audit_identity_or_content_mismatch"
    assert repository.calls == ["facts", "manifest", "audit"]


def test_rejects_duplicate_selected_audit_references() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    second_reference = replace(fixture.audit_reference, raw_audit_id="42")
    repository.manifest = CandidateRawAuditManifest.create(
        publication_id=fixture.publication.publication_id,
        publication_hash=fixture.publication.publication_hash,
        run_id=fixture.publication.run_id,
        dataset_key=fixture.publication.dataset_key,
        publication_key=fixture.publication.publication_key,
        task_attempt_id="task-attempt-1",
        raw_audits=(fixture.audit_reference, second_reference),
        manifest_id="95f0e94e-f35a-4fd0-8bc1-624948060340",
    )

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_audit_missing_or_ambiguous"
    assert repository.calls == ["facts", "manifest"]


def test_rejects_a_retained_body_changed_after_its_hash_was_bound() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    tampered_payload = dict(fixture.raw_payload.payload)
    tampered_payload["retained_response_json"] = str(
        tampered_payload["retained_response_json"]
    ).replace("12.5", "12.6")
    repository.payloads[fixture.response_reference.payload_hash] = replace(
        fixture.raw_payload, payload=tampered_payload
    )

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_raw_missing_or_changed"
    assert repository.calls == ["facts", "manifest", "audit", "payload"]


def test_blocks_redacted_response_when_original_body_is_not_retained() -> None:
    fixture = _make_fixture(redact_volume=True)
    assert fixture.response_reference.original_body_retained is False

    result, repository = _read(fixture)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_original_body_unavailable"
    assert repository.calls == ["facts", "manifest", "audit", "payload"]


def test_blocks_publication_published_after_the_knowledge_cutoff() -> None:
    fixture = _make_fixture()
    late_cutoff = fixture.publication.published_at - timedelta(seconds=1)

    result, repository = _read(fixture, cutoff=late_cutoff)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_not_known"
    assert repository.calls == []


def test_blocks_publication_as_of_after_its_publish_time() -> None:
    fixture = _make_fixture()
    publication = replace(
        fixture.publication,
        as_of=fixture.publication.published_at + timedelta(seconds=1),
    )
    result, repository = _read(fixture, publication=publication)
    assert result.evidence is None
    assert result.blocked_reason == "price_source_publication_time_invalid"
    assert repository.calls == []


def test_blocks_ambiguous_fact_selection() -> None:
    fixture = _make_fixture()
    repository = _MemoryRepository(fixture)
    repository.facts = (fixture.fact, fixture.fact)

    result, repository = _read(fixture, repository)

    assert result.evidence is None
    assert result.blocked_reason == "price_source_fact_missing_or_ambiguous"
    assert repository.calls == ["facts"]


@contextmanager
def _database_free_publication_snapshot(_dataset_key: str) -> Iterator[None]:
    """Replace the established snapshot context while testing composition gates."""

    yield None


def _composition_request() -> dict[str, object]:
    """Return valid public composition inputs without opening source repositories."""

    return {
        "asset_code": ASSET_CODE,
        "trade_date": TRADE_DATE,
        "knowledge_cutoff": COMPOSITION_CUTOFF,
        "publication_key": PUBLICATION_KEY,
    }


@pytest.mark.parametrize(
    ("gate", "expected_reason"),
    [
        (None, "canonical_publication_missing"),
        (
            {
                "must_not_use_for_decision": True,
                "blocked_reason": "publication_policy_blocked",
            },
            "publication_policy_blocked",
        ),
    ],
)
def test_missing_or_blocked_gate_does_not_open_price_source_repository(
    monkeypatch: pytest.MonkeyPatch,
    gate: dict[str, object] | None,
    expected_reason: str,
) -> None:
    from apps.data_center import publication_read_composition
    from apps.data_center import published_price_source_composition as composition

    monkeypatch.setattr(
        publication_read_composition,
        "consistent_publication_read",
        _database_free_publication_snapshot,
    )
    monkeypatch.setattr(composition, "get_current_publication_gate", lambda *args, **kwargs: gate)

    def repository_must_not_be_opened() -> object:
        raise AssertionError("blocked publication gate must short-circuit repository access")

    monkeypatch.setattr(
        composition, "get_canonical_publication_repository", repository_must_not_be_opened
    )
    result = composition.read_published_price_source(**_composition_request())

    assert result.evidence is None
    assert result.blocked_reason == expected_reason


def test_invalid_public_request_is_blocked_before_snapshot_or_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.data_center import publication_read_composition
    from apps.data_center import published_price_source_composition as composition

    def database_must_not_be_opened(_dataset_key: str) -> object:
        raise AssertionError("invalid request must stop before opening a snapshot")

    def snapshot_must_not_be_read(*args: object, **kwargs: object) -> PublishedPriceSourceResult:
        raise AssertionError("invalid request must stop before reading a publication snapshot")

    monkeypatch.setattr(
        publication_read_composition,
        "consistent_publication_read",
        database_must_not_be_opened,
    )
    monkeypatch.setattr(composition, "_read_source_snapshot", snapshot_must_not_be_read)

    result = composition.read_published_price_source(
        "600000.sh",
        trade_date=TRADE_DATE,
        knowledge_cutoff=datetime(2026, 10, 26, 8, tzinfo=UTC),
        publication_key=PUBLICATION_KEY,
    )

    assert result.evidence is None
    assert result.blocked_reason == "price_source_request_invalid"


def test_publication_identity_drift_at_gate_blocks_before_price_source_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.data_center import publication_read_composition
    from apps.data_center import published_price_source_composition as composition

    fixture = _make_fixture()

    class _PublicationRepository:
        def get_current(self, dataset_key: str, publication_key: str) -> CanonicalPublication:
            return replace(fixture.publication, publication_hash="c" * 64)

        def list_members(self, publication_id: str) -> list[PublicationMember]:
            raise AssertionError("drifted gate identity must stop before reading members")

    monkeypatch.setattr(
        publication_read_composition,
        "consistent_publication_read",
        _database_free_publication_snapshot,
    )
    monkeypatch.setattr(
        composition,
        "get_current_publication_gate",
        lambda *args, **kwargs: {
            "must_not_use_for_decision": False,
            "publication_id": fixture.publication.publication_id,
            "publication_hash": fixture.publication.publication_hash,
            "freshness_status": "fresh",
        },
    )
    monkeypatch.setattr(
        composition,
        "get_canonical_publication_repository",
        lambda: _PublicationRepository(),
    )

    def price_repository_must_not_be_opened() -> object:
        raise AssertionError("gate identity mismatch must stop before price repository access")

    monkeypatch.setattr(
        composition,
        "DjangoPublishedPriceSourceRepository",
        price_repository_must_not_be_opened,
    )
    result = composition.read_published_price_source(**_composition_request())

    assert result.evidence is None
    assert result.blocked_reason == "price_source_publication_identity_mismatch"
