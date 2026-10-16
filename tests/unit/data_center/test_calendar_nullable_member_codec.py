"""Calendar-only nullable-member hashing must preserve legacy publication bytes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.data_center.application import publication_utils
from apps.data_center.domain import control_plane as data_center_control_plane
from apps.data_center.domain import publication_evidence
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    PublicationFactReference,
    PublicationMember,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _versioned_policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("data_center.exchange_calendar_snapshot", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=3650,
        policy_version="2",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _legacy_reference() -> PublicationFactReference:
    return PublicationFactReference(
        natural_key="asset:2026-09-13:provider",
        source="provider",
        source_record_id="record-1",
        fact_table="data_center_valuation_fact",
        fact_pk="17",
        observed_at=datetime(2026, 9, 13, 9, 0, tzinfo=UTC),
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=2,
        available_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        source_published_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
        raw_payload_scope="batch_response_body",
        fact_content_hash="b" * 64,
    )


def _calendar_member(**changes: object) -> PublicationMember:
    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-1",
        dataset_key="data_center.exchange_calendar_snapshot",
        natural_key="SSE:2026-01-01:2026-12-31",
        source="tushare",
        source_record_id="raw-payload-1",
        fact_table="data_center_exchange_calendar_snapshot",
        fact_pk="snapshot-1",
        observed_at=None,
        raw_payload_hash="sha256:" + "d" * 64,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=NOW,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    return replace(member, **changes)


def _calendar_reference(
    *,
    member: PublicationMember | None = None,
    snapshot_content_hash: str = "sha256:" + "b" * 64,
    snapshot_record_digest: str = "sha256:" + "c" * 64,
    codec_version: object = "calendar-nullable-member-v1",
) -> object:
    reference_type = getattr(data_center_control_plane, "CalendarPublicationMemberReference", None)
    assert isinstance(reference_type, type), "calendar nullable-member reference API is missing"
    return reference_type(
        member=member or _calendar_member(),
        snapshot_content_hash=snapshot_content_hash,
        snapshot_record_digest=snapshot_record_digest,
        codec_version=codec_version,
    )


def _codec_version() -> object:
    version_type = getattr(data_center_control_plane, "CalendarNullableMemberCodecVersion", None)
    assert isinstance(version_type, type), "calendar nullable-member codec version is missing"
    return version_type.V1


def _unregistered_codec_version() -> object:
    """Model a future enum value reaching the current v1-only contract."""

    version_type = type(_codec_version())
    version = str.__new__(version_type, "calendar-nullable-member-v2")
    object.__setattr__(version, "_name_", "V2")
    object.__setattr__(version, "_value_", "calendar-nullable-member-v2")
    return version


def test_existing_nonnullable_policy_and_hashes_match_prechange_goldens() -> None:
    policy = PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "raw_payload_hash",
            "raw_payload_scope",
        ),
        retention_days=3650,
        policy_version="2",
    )
    reference = _legacy_reference()

    assert policy.content_hash == "d53ab2699d49f0986b0024c866945d02cc25d1ed64109dabfcb94a08788b5345"
    assert (
        policy.identity == "p2:2:d53ab2699d49f0986b0024c866945d02cc25d1ed64109dabfcb94a08788b5345"
    )
    assert publication_utils.publication_hash([reference]) == (
        "62abcbf9443144e2516ebad291fcefa5727026e6aa78559503be26f32cafcf95"
    )
    assert publication_utils.publication_hash([reference], policy_identity=policy.identity) == (
        "47ca9d664d2325ae50613cf5ed2d78d0ddcf2d6cf823ce1d809ca0775677d571"
    )


def test_generic_member_hash_path_still_rejects_missing_observed_time() -> None:
    with pytest.raises(ValueError, match="observed_at"):
        publication_utils.member_reference(_calendar_member())


def test_generic_hash_and_evidence_paths_reject_calendar_nullable_dto() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    with pytest.raises(TypeError, match="PublicationFactReference"):
        publication_utils.publication_hash([cast(PublicationFactReference, reference)])
    with pytest.raises(TypeError, match="PublicationMember"):
        publication_utils.member_reference(cast(PublicationMember, reference))
    with pytest.raises(TypeError, match="references or members"):
        publication_evidence.validate_publication_evidence(
            replace(_versioned_policy(), member_codec_version=None),
            [cast(PublicationFactReference, reference)],
            published_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "value", "exception"),
    [
        ("source", "", ValueError),
        ("revision_number", 0, ValueError),
        ("raw_payload_hash", 1, TypeError),
        ("fetched_at", "not-a-datetime", TypeError),
        ("fact_content_hash", 1, TypeError),
    ],
)
def test_calendar_reference_revalidates_mutated_nested_member(
    field: str,
    value: object,
    exception: type[Exception],
) -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    object.__setattr__(reference.member, field, value)

    with pytest.raises(exception):
        reference.to_payload()


def test_calendar_reference_rejects_non_member_value() -> None:
    with pytest.raises(TypeError, match="PublicationMember"):
        _calendar_reference(
            member=cast(PublicationMember, object()),
            codec_version=_codec_version(),
        )


@pytest.mark.parametrize(
    "digest",
    [None, "x" + "a" * 64, "sha256:" + "A" * 64],
)
def test_calendar_reference_rejects_malformed_prefixed_snapshot_digests(
    digest: object,
) -> None:
    with pytest.raises(ValueError, match="snapshot_content_hash"):
        _calendar_reference(
            snapshot_content_hash=cast(str, digest),
            codec_version=_codec_version(),
        )


def test_calendar_codec_roundtrips_null_times_and_binds_distinct_hashes() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    codec = getattr(publication_utils, "calendar_publication_hash", None)
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(codec), "calendar nullable-member hash API is missing"
    assert callable(validator), "calendar nullable-member evidence validator is missing"

    payload = reference.to_payload()
    member_payload = cast(dict[str, object], payload["member"])
    assert member_payload["observed_at"] is None
    assert member_payload["available_at"] is None
    assert member_payload["source_published_at"] is None
    assert member_payload["fetched_at"] == NOW.isoformat()
    assert member_payload["fact_content_hash"] == "a" * 64
    assert payload["snapshot_content_hash"] == "sha256:" + "b" * 64
    assert payload["snapshot_record_digest"] == "sha256:" + "c" * 64

    policy = _versioned_policy()
    validator(policy, [reference], codec_version=_codec_version(), published_at=NOW)
    digest = codec([reference], policy=policy, codec_version=_codec_version())
    # The payload codec is unchanged; explicit policy binding changes its policy identity.
    assert digest == "26114f8f9433d0faf66f8c764261c4b5151821cb339c3dd61ca0318b96c45d39"


def test_calendar_codec_rejects_member_from_another_dataset() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    codec = getattr(publication_utils, "calendar_publication_hash", None)
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(codec), "calendar nullable-member hash API is missing"
    assert callable(validator), "calendar nullable-member evidence validator is missing"
    policy = replace(
        _versioned_policy(),
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
    )

    with pytest.raises(ValueError, match="dataset_key"):
        codec([reference], policy=policy, codec_version=_codec_version())
    with pytest.raises(ValueError, match="dataset_key"):
        validator(policy, [reference], codec_version=_codec_version(), published_at=NOW)


def test_calendar_codec_policy_binding_is_independent_of_dataset_spelling() -> None:
    policy = replace(
        _versioned_policy(),
        dataset=DatasetKey("equity.quote.fact", "1.0", "1.0"),
    )
    member = _calendar_member(dataset_key=policy.dataset.value)
    reference = _calendar_reference(member=member, codec_version=_codec_version())
    codec = getattr(publication_utils, "calendar_publication_hash", None)
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(codec), "calendar nullable-member hash API is missing"
    assert callable(validator), "calendar nullable-member evidence validator is missing"

    validator(policy, [reference], codec_version=_codec_version(), published_at=NOW)
    assert codec([reference], policy=policy, codec_version=_codec_version())


def test_calendar_codec_rejects_legacy_policy_and_unknown_codec_version() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    codec = getattr(publication_utils, "calendar_publication_hash", None)
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(codec), "calendar nullable-member hash API is missing"
    assert callable(validator), "calendar nullable-member evidence validator is missing"

    legacy_policy = replace(_versioned_policy(), policy_version="legacy", member_codec_version=None)
    with pytest.raises(ValueError, match="versioned"):
        codec([reference], policy=legacy_policy, codec_version=_codec_version())
    with pytest.raises((TypeError, ValueError), match="codec_version|codec version"):
        codec([reference], policy=_versioned_policy(), codec_version="calendar-nullable-member-v2")
    with pytest.raises(ValueError, match="versioned"):
        validator(legacy_policy, [reference], codec_version=_codec_version(), published_at=NOW)


def test_calendar_validator_rejects_wrong_and_unregistered_codec_versions() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(validator), "calendar nullable-member evidence validator is missing"

    with pytest.raises(TypeError, match="codec_version"):
        validator(
            _versioned_policy(),
            [reference],
            codec_version="calendar-nullable-member-v1",
            published_at=NOW,
        )
    with pytest.raises(ValueError, match="not supported"):
        validator(
            _versioned_policy(),
            [reference],
            codec_version=cast(type(_codec_version()), _unregistered_codec_version()),
            published_at=NOW,
        )
    with pytest.raises(ValueError, match="not supported"):
        _calendar_reference(codec_version=_unregistered_codec_version())

    object.__setattr__(reference, "codec_version", _unregistered_codec_version())
    with pytest.raises(ValueError, match="differs from the requested version"):
        validator(
            _versioned_policy(),
            [reference],
            codec_version=_codec_version(),
            published_at=NOW,
        )


@pytest.mark.parametrize(
    ("member_hash", "snapshot_content_hash", "snapshot_record_digest"),
    [
        ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64),
        ("a" * 64, "b" * 64, "sha256:" + "c" * 64),
        ("a" * 64, "sha256:" + "b" * 64, "c" * 64),
    ],
)
def test_calendar_codec_rejects_hash_domain_substitution(
    member_hash: str,
    snapshot_content_hash: str,
    snapshot_record_digest: str,
) -> None:
    with pytest.raises(ValueError, match="hash|digest"):
        _calendar_reference(
            member=_calendar_member(fact_content_hash=member_hash),
            snapshot_content_hash=snapshot_content_hash,
            snapshot_record_digest=snapshot_record_digest,
            codec_version=_codec_version(),
        )


def test_calendar_codec_requires_explicit_version_and_preserves_upstream_unknowns() -> None:
    with pytest.raises((TypeError, ValueError), match="codec_version|codec version"):
        _calendar_reference(codec_version="calendar-nullable-member-v2")

    reference = _calendar_reference(codec_version=_codec_version())
    payload = reference.to_payload()
    member_payload = cast(dict[str, object], payload["member"])
    assert member_payload["observed_at"] is None
    assert member_payload["available_at"] is None
    assert member_payload["source_published_at"] is None


def test_calendar_codec_preserves_missing_local_fetch_time_as_none() -> None:
    reference = _calendar_reference(
        member=_calendar_member(fetched_at=None),
        codec_version=_codec_version(),
    )

    payload = reference.to_payload()
    member_payload = cast(dict[str, object], payload["member"])
    assert member_payload["fetched_at"] is None


@pytest.mark.parametrize("field", ["observed_at", "available_at", "source_published_at"])
def test_calendar_codec_rejects_local_time_substitution_for_unknown_source_times(
    field: str,
) -> None:
    with pytest.raises(ValueError, match="source timestamps"):
        _calendar_reference(
            member=_calendar_member(**{field: NOW}),
            codec_version=_codec_version(),
        )


def test_calendar_codec_rejects_policy_that_requires_unknown_source_time() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(validator), "calendar nullable-member evidence validator is missing"
    policy = replace(
        _versioned_policy(),
        required_evidence=("source", "observed_at"),
    )
    with pytest.raises(ValueError, match="unavailable source timestamps"):
        validator(policy, [reference], codec_version=_codec_version(), published_at=NOW)


def test_calendar_evidence_validator_rejects_invalid_boundary_arguments() -> None:
    reference = _calendar_reference(codec_version=_codec_version())
    validator = getattr(publication_evidence, "validate_calendar_publication_evidence", None)
    assert callable(validator), "calendar nullable-member evidence validator is missing"

    with pytest.raises(TypeError, match="PublicationPolicy"):
        validator(None, [reference], codec_version=_codec_version(), published_at=NOW)
    with pytest.raises(ValueError, match="published_at"):
        validator(
            _versioned_policy(),
            [reference],
            codec_version=_codec_version(),
            published_at=datetime(2026, 9, 13, 12, 0),
        )
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        validator(
            _versioned_policy(),
            [reference],
            codec_version=_codec_version(),
            published_at=NOW,
            knowledge_cutoff=datetime(2026, 9, 13, 12, 0),
        )
    with pytest.raises(TypeError, match="sequence"):
        validator(
            _versioned_policy(),
            "not-a-sequence",
            codec_version=_codec_version(),
            published_at=NOW,
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        validator(_versioned_policy(), [], codec_version=_codec_version(), published_at=NOW)
    with pytest.raises(TypeError, match="member references"):
        validator(
            _versioned_policy(),
            [cast(object, _legacy_reference())],
            codec_version=_codec_version(),
            published_at=NOW,
        )
