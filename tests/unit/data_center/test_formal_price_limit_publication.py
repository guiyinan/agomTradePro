from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TypeVar, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

import apps.data_center.domain.formal_price_limit_publication as publication_domain
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationError,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationMemberEvidence,
    PriceLimitPublicationPointerExpectation,
    PriceLimitPublicationTimelineEvent,
    create_price_limit_formal_publication_seal,
    price_limit_publication_key,
)
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitRawReference,
    PriceLimitSnapshot,
    PriceLimitSnapshotCandidate,
    PriceLimitSnapshotReference,
    make_price_limit_snapshot,
    price_limit_request_scope_hash,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.publication_member_codec import (
    PriceLimitNullableMemberCodecVersion,
)

_NOW = datetime(2026, 10, 29, 2, 0, tzinfo=UTC)
_EFFECTIVE_DATE = date(2026, 10, 28)
_DATASET = DatasetKey("equity.price.limit", "1.0", "1.0")
_CONTRACT_RECORDED_AT = _NOW - timedelta(days=3)
_POLICY_RECORDED_AT = _NOW - timedelta(days=2)
_T = TypeVar("_T")


def _unsafe_replace(instance: _T, **changes: object) -> _T:
    """Build a deliberately corrupted frozen DTO for explicit revalidation tests."""

    corrupted = object.__new__(type(instance))
    for data_field in dataclass_fields(instance):
        replacement = changes.get(data_field.name, getattr(instance, data_field.name))
        object.__setattr__(corrupted, data_field.name, replacement)
    return cast(_T, corrupted)


def _contract(**changes: object) -> DatasetContract:
    fields = (
        DatasetFieldContract(
            name="lower_limit_price",
            value_type="decimal",
            unit="provider_native_price",
            nullable=False,
            zero_allowed=False,
            minimum=0.01,
        ),
        DatasetFieldContract(
            name="upper_limit_price",
            value_type="decimal",
            unit="provider_native_price",
            nullable=False,
            zero_allowed=False,
            minimum=0.01,
        ),
        DatasetFieldContract(
            name="currency",
            value_type="string",
            unit=None,
            nullable=True,
            zero_allowed=False,
        ),
    )
    return DatasetContract(
        key=_DATASET,
        owner="data_center",
        frequency="daily",
        decision_critical=False,
        fields=fields,
        freshness_seconds=None,
        comparable_group=None,
        execution_freshness_seconds=None,
        calendar_response_max_age_seconds=None,
        **changes,
    )


def _policy(**changes: object) -> PublicationPolicy:
    return PublicationPolicy(
        dataset=_DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "payload_hash",
            "raw_payload_hash",
            "source_record_id",
            "fetched_at",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="price-limit-policy-v1",
        member_codec_version=PriceLimitNullableMemberCodecVersion.V1,
        **changes,
    )


def _snapshot(
    *,
    provider_id: int = 7,
    provider_name: str = "tushare",
    asset_code: str = "600000.SH",
    effective_trade_date: date = _EFFECTIVE_DATE,
    lower_limit_price: Decimal = Decimal("9.123400"),
    upper_limit_price: Decimal = Decimal("11.456700"),
    response_completed_at: datetime = _NOW - timedelta(minutes=5),
    recorded_at: datetime = _NOW - timedelta(minutes=4),
    payload_marker: str = "1",
) -> PriceLimitSnapshot:
    payload_hash = "sha256:" + payload_marker * 64
    raw_reference = PriceLimitRawReference(
        payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
        payload_hash=payload_hash,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        original_body_retained=True,
        retained_content_encoding="exact_original_utf8_json",
        body_size_bytes=128,
        response_completed_at=response_completed_at,
        provider_name=provider_name,
        dataset_key="equity.price.limit",
        transport=ProviderResponseTransport.DIRECT,
        request_scope_sha256=price_limit_request_scope_hash(
            provider_id=provider_id,
            provider_name=provider_name,
            asset_code=asset_code,
            effective_trade_date=effective_trade_date,
        ),
    )
    candidate = PriceLimitSnapshotCandidate(
        asset_code=asset_code,
        effective_trade_date=effective_trade_date,
        provider_id=provider_id,
        provider_name=provider_name,
        lower_limit_price=lower_limit_price,
        upper_limit_price=upper_limit_price,
        raw_reference=raw_reference,
    )
    return make_price_limit_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at,
    )


def _seal(
    snapshot: PriceLimitSnapshot | None = None,
    *,
    contract: DatasetContract | None = None,
    policy: PublicationPolicy | None = None,
    contract_recorded_at: datetime = _CONTRACT_RECORDED_AT,
    policy_recorded_at: datetime = _POLICY_RECORDED_AT,
    fact_content_hash: str = "4" * 64,
) -> PriceLimitFormalPublicationSeal:
    return create_price_limit_formal_publication_seal(
        dataset_contract=contract or _contract(),
        contract_recorded_at=contract_recorded_at,
        policy=policy or _policy(),
        policy_recorded_at=policy_recorded_at,
        snapshot=snapshot or _snapshot(),
        fact_content_hash=fact_content_hash,
    )


def _record(
    seal: PriceLimitFormalPublicationSeal | None = None,
    *,
    publication_id: str | None = None,
    first_published_at: datetime = _NOW,
    first_activation_id: str = "activation-1",
) -> PriceLimitFormalPublicationRecord:
    return PriceLimitFormalPublicationRecord(
        seal=seal or _seal(),
        publication_id=publication_id or str(uuid4()),
        first_published_at=first_published_at,
        first_activation_id=first_activation_id,
    )


def _first_event(record: PriceLimitFormalPublicationRecord) -> PriceLimitPublicationTimelineEvent:
    seal = record.seal
    return PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FIRST_PUBLISH,
        event_id=record.first_activation_id,
        dataset_key=seal.dataset_contract.key.value,
        publication_key=seal.publication_key,
        previous_publication_id=None,
        previous_publication_hash=None,
        target_publication_id=record.publication_id,
        target_publication_hash=seal.publication_hash,
        transitioned_at=record.first_published_at,
    )


def _pointer(
    record: PriceLimitFormalPublicationRecord,
    *,
    activation_id: str | None = None,
    updated_at: datetime | None = None,
) -> PriceLimitPublicationPointerExpectation:
    return PriceLimitPublicationPointerExpectation(
        dataset_key=record.seal.dataset_contract.key.value,
        publication_key=record.seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        activation_id=activation_id or record.first_activation_id,
        updated_at=updated_at or record.first_published_at,
    )


def test_seal_binds_full_contract_policy_member_and_snapshot_without_claiming_source_clocks() -> (
    None
):
    snapshot = _snapshot()
    seal = _seal(snapshot)

    assert seal.dataset_contract == _contract()
    assert seal.contract_recorded_at == _CONTRACT_RECORDED_AT
    assert seal.policy == _policy()
    assert seal.policy_identity == seal.policy.identity
    assert seal.policy_recorded_at == _POLICY_RECORDED_AT
    assert seal.snapshot_reference == snapshot.reference()
    assert seal.member_evidence.fact_content_hash == "4" * 64
    assert seal.member_evidence.raw_payload_hash == snapshot.candidate.raw_reference.body_sha256
    assert seal.member_evidence.raw_payload_hash != snapshot.reference().raw_payload_hash
    assert seal.member_evidence.fetched_at == snapshot.candidate.response_completed_at
    assert seal.member_evidence.observed_at is None
    assert seal.member_evidence.available_at is None
    assert seal.member_evidence.source_published_at is None
    assert seal.currency is None
    assert seal.observed_at is None
    assert seal.source_available_at is None
    assert seal.source_published_at is None
    assert seal.must_not_use_for_decision is True
    assert seal.must_not_execute is True
    assert seal.coverage_scope == "single_explicit_provider_security_date"
    assert "as_of" not in seal.to_payload()


def test_seal_hash_binds_exact_dataset_contract_policy_and_database_fact_digest() -> None:
    baseline = _seal()
    changed_contract = _seal(contract=replace(_contract(), owner="other-owner"))
    changed_policy = _seal(policy=replace(_policy(), minimum_coverage_ratio=0.75))
    changed_fact = _seal(fact_content_hash="5" * 64)

    assert changed_contract.publication_hash != baseline.publication_hash
    assert changed_policy.publication_hash != baseline.publication_hash
    assert changed_fact.publication_hash != baseline.publication_hash
    assert changed_fact.member_manifest_hash != baseline.member_manifest_hash


def test_publication_key_binds_complete_provider_security_and_effective_date_scope() -> None:
    first = _snapshot()
    same_security_other_day = _snapshot(effective_trade_date=date(2026, 10, 27))
    other_provider = _snapshot(provider_id=8)
    other_security = _snapshot(asset_code="000001.SZ")

    first_key = price_limit_publication_key(first.reference())
    assert first_key.startswith("price-limit:")
    assert price_limit_publication_key(same_security_other_day.reference()) != first_key
    assert price_limit_publication_key(other_provider.reference()) != first_key
    assert price_limit_publication_key(other_security.reference()) != first_key
    with pytest.raises(PriceLimitPublicationError):
        price_limit_publication_key(cast(PriceLimitSnapshotReference, object()))


def test_member_evidence_builds_generic_member_without_confusing_local_snapshot_with_vendor_record() -> (
    None
):
    seal = _seal()
    member = seal.member_evidence.to_publication_member(
        publication_id=str(uuid4()),
        member_id=str(uuid4()),
    )

    assert member.dataset_key == "equity.price.limit"
    assert member.source_record_id == seal.snapshot_reference.snapshot_id
    assert member.source_record_id != seal.snapshot_reference.raw_payload_id
    assert member.fact_table == "data_center_price_limit_snapshot_fact"
    assert member.fact_pk == seal.snapshot_reference.snapshot_id
    assert member.revision_number == 1
    assert member.observed_at is None
    assert member.available_at is None
    assert member.source_published_at is None
    assert member.fetched_at == seal.snapshot.candidate.response_completed_at
    assert member.raw_payload_hash == seal.snapshot.candidate.raw_reference.body_sha256
    assert member.raw_payload_scope == "record_response_body"
    assert member.fact_content_hash == "4" * 64
    assert member.quality_status == "reference_only"


def test_seal_rejects_wrong_dataset_policy_snapshot_scope_or_fact_digest() -> None:
    snapshot = _snapshot()
    with pytest.raises(PriceLimitPublicationError):
        _seal(contract=replace(_contract(), key=DatasetKey("equity.price.bar", "1", "1")))
    with pytest.raises(PriceLimitPublicationError):
        _seal(policy=replace(_policy(), member_codec_version=None))
    with pytest.raises(ValueError):
        _seal(policy=replace(_policy(), required_evidence=("observed_at",)))
    with pytest.raises(PriceLimitPublicationError):
        _seal(snapshot, fact_content_hash="sha256:" + "4" * 64)


def test_record_rejects_publication_before_catalog_knowledge_time() -> None:
    snapshot = _snapshot()
    seal = _seal(
        snapshot,
        contract_recorded_at=_NOW + timedelta(seconds=30),
    )
    with pytest.raises(PriceLimitPublicationError):
        _record(seal, first_published_at=_NOW + timedelta(seconds=20))


def test_record_requires_publication_after_all_source_and_catalog_knowledge() -> None:
    seal = _seal()
    with pytest.raises(PriceLimitPublicationError):
        _record(seal, first_published_at=seal.snapshot.recorded_at - timedelta(microseconds=1))


@pytest.mark.parametrize("value", [None, "", " padded", "padded ", "x" * 301, "bad\x01text"])
def test_text_guard_rejects_invalid_identity_tokens(value: object) -> None:
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._require_text(value, "test")


@pytest.mark.parametrize("value", [None, "sha256:" + "a" * 64, "A" * 64, "a" * 63])
def test_bare_digest_guard_rejects_wrong_hash_namespace(value: object) -> None:
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._require_digest(value, "test")


def test_uuid_utc_activation_and_json_guards_reject_malformed_values() -> None:
    invalid_uuids: tuple[object, ...] = (None, "not-a-uuid", str(uuid4()).upper())
    for value in invalid_uuids:
        with pytest.raises(PriceLimitPublicationError):
            publication_domain._require_uuid(value, "test")

    invalid_times: tuple[object, ...] = (
        None,
        datetime(2026, 10, 29, 2, 0),
        datetime(2026, 10, 29, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    for value in invalid_times:
        with pytest.raises(PriceLimitPublicationError):
            publication_domain._require_utc(value, "test")

    with pytest.raises(PriceLimitPublicationError):
        publication_domain._require_activation_id("has space", "test")
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._canonical_hash({"non_finite": float("nan")})
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._canonical_hash({"not_json": object()})


def test_contract_serializers_revalidate_complete_nested_contracts() -> None:
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_key_payload(cast(DatasetKey, object()))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_key_payload(_unsafe_replace(_DATASET, value=""))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._field_contract_payload(cast(DatasetFieldContract, object()))

    field = _contract().fields[0]
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._field_contract_payload(_unsafe_replace(field, nullable=1))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._field_contract_payload(_unsafe_replace(field, minimum=float("nan")))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._field_contract_payload(_unsafe_replace(field, source_contracts=[]))

    with pytest.raises(PriceLimitPublicationError):
        publication_domain._contract_optional_positive_int(0, "age")
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._contract_optional_positive_int(True, "age")
    assert publication_domain._contract_optional_positive_int(None, "age") is None
    assert publication_domain._contract_optional_positive_int(1, "age") == 1

    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_contract_payload(cast(DatasetContract, object()))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_contract_payload(
            _unsafe_replace(_contract(), fields=[_contract().fields[0]])
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_contract_payload(
            _unsafe_replace(_contract(), decision_critical=1)
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._dataset_contract_payload(
            _unsafe_replace(_contract(), comparable_group=" ")
        )
    assert publication_domain._dataset_contract_payload(_contract())["fields"]


def test_policy_serializer_rechecks_version_codec_and_exact_field_types() -> None:
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(cast(PublicationPolicy, object()))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(
            _unsafe_replace(_policy(), minimum_coverage_ratio=True)
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(_unsafe_replace(_policy(), allow_partial=1))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(
            _unsafe_replace(_policy(), required_evidence=["source"])
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(
            _unsafe_replace(_policy(), retention_days=True)
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._publication_policy_payload(
            _unsafe_replace(_policy(), policy_version="legacy")
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"codec_version": "price-limit-nullable-member-v1"},
        {"publication_key": "wrong"},
        {"natural_key": "wrong"},
        {"source": "other"},
        {"source_record_id": str(uuid4())},
        {"fact_pk": str(uuid4())},
        {"fact_table": "data_center_price_bar"},
        {"observed_at": _NOW},
        {"available_at": _NOW},
        {"source_published_at": _NOW},
        {"revision_number": 2},
        {"revision_number": True},
        {"raw_payload_scope": "batch_response_body"},
        {"raw_payload_hash": "sha256:" + "a" * 64},
        {"fact_content_hash": "sha256:" + "a" * 64},
        {"fetched_at": datetime(2026, 10, 29, 2, 0)},
    ],
)
def test_member_evidence_rejects_wrong_fact_scope_clocks_or_digest_domain(
    changes: dict[str, object],
) -> None:
    evidence = _seal().member_evidence
    with pytest.raises(PriceLimitPublicationError):
        replace(evidence, **changes)


def test_member_evidence_rejects_wrong_reference_and_only_local_snapshot_identity() -> None:
    evidence = _seal().member_evidence
    with pytest.raises(PriceLimitPublicationError):
        replace(evidence, snapshot_reference=object())
    with pytest.raises(PriceLimitPublicationError):
        replace(
            evidence,
            snapshot_reference=_unsafe_replace(
                evidence.snapshot_reference, request_scope_sha256="0" * 64
            ),
        )
    with pytest.raises(PriceLimitPublicationError):
        replace(
            evidence,
            source_record_id=evidence.snapshot_reference.raw_payload_id,
        )
    with pytest.raises(PriceLimitPublicationError):
        evidence.to_publication_member(publication_id="bad", member_id=str(uuid4()))
    with pytest.raises(PriceLimitPublicationError):
        publication_domain.price_limit_member_manifest_hash(
            cast(PriceLimitPublicationMemberEvidence, object()), _policy()
        )
    with pytest.raises(PriceLimitPublicationError):
        publication_domain._member_evidence(cast(PriceLimitSnapshot, object()), "4" * 64)


def test_seal_revalidation_rejects_nested_changes_and_bad_hash_namespaces() -> None:
    seal = _seal()
    corruptions: tuple[dict[str, object], ...] = (
        {"dataset_contract": object()},
        {"contract_recorded_at": datetime(2026, 10, 29, 2, 0)},
        {"policy": object()},
        {"policy_recorded_at": datetime(2026, 10, 29, 2, 0)},
        {"snapshot": object()},
        {"snapshot_reference": object()},
        {"member_evidence": object()},
        {"member_manifest_hash": "sha256:" + "a" * 64},
        {"member_manifest_hash": "a" * 64},
        {"publication_hash": "sha256:" + "b" * 64},
        {"publication_hash": "b" * 64},
    )
    for changes in corruptions:
        with pytest.raises(PriceLimitPublicationError):
            _unsafe_replace(seal, **changes).validate()

    bad_member = _unsafe_replace(seal.member_evidence, fact_content_hash="5" * 64)
    with pytest.raises(PriceLimitPublicationError):
        _unsafe_replace(seal, member_evidence=bad_member).validate()
    bad_reference = _unsafe_replace(seal.snapshot_reference, snapshot_id=str(uuid4()))
    with pytest.raises(PriceLimitPublicationError):
        _unsafe_replace(seal, snapshot_reference=bad_reference).validate()
    mismatched_member = _unsafe_replace(seal.member_evidence, quality_status="accepted")
    with pytest.raises(PriceLimitPublicationError):
        _unsafe_replace(seal, member_evidence=mismatched_member).validate()
    mismatched_contract = _unsafe_replace(
        _contract(), key=DatasetKey("equity.price.limit", "2.0", "1.0")
    )
    with pytest.raises(PriceLimitPublicationError):
        _unsafe_replace(seal, dataset_contract=mismatched_contract).validate()
    with pytest.raises(PriceLimitPublicationError):
        create_price_limit_formal_publication_seal(
            dataset_contract=_contract(),
            contract_recorded_at=_CONTRACT_RECORDED_AT,
            policy=replace(_policy(), dataset=DatasetKey("equity.price.limit", "2.0", "1.0")),
            policy_recorded_at=_POLICY_RECORDED_AT,
            snapshot=seal.snapshot,
            fact_content_hash="4" * 64,
        )
    with pytest.raises(PriceLimitPublicationError):
        create_price_limit_formal_publication_seal(
            dataset_contract=_contract(),
            contract_recorded_at=_CONTRACT_RECORDED_AT,
            policy=_policy(),
            policy_recorded_at=_POLICY_RECORDED_AT,
            snapshot=cast(PriceLimitSnapshot, object()),
            fact_content_hash="4" * 64,
        )


def test_record_and_pointer_guards_reject_malformed_identity_or_time() -> None:
    record = _record()
    invalid_record_changes = (
        {"seal": object()},
        {"publication_id": "not-a-uuid"},
        {"first_published_at": datetime(2026, 10, 29, 2, 0)},
        {"first_activation_id": "bad activation"},
        {"first_published_at": _NOW - timedelta(days=4)},
    )
    for changes in invalid_record_changes:
        with pytest.raises(PriceLimitPublicationError):
            replace(record, **changes)

    pointer = _pointer(record)
    invalid_pointers = (
        {"dataset_key": "equity.price.bar"},
        {"publication_key": " "},
        {"pointer_id": "bad"},
        {"publication_id": "bad"},
        {"publication_hash": "sha256:" + "a" * 64},
        {"activation_id": "bad activation"},
        {"updated_at": datetime(2026, 10, 29, 2, 0)},
        {"pointer_id": None},
    )
    for changes in invalid_pointers:
        with pytest.raises(PriceLimitPublicationError):
            replace(pointer, **changes)

    absent = PriceLimitPublicationPointerExpectation(
        dataset_key="equity.price.limit",
        publication_key=record.seal.publication_key,
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    assert absent.is_absent
