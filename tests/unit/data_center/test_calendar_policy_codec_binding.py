"""A calendar codec is an explicit immutable policy decision, never a fallback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.data_center.application.publication_utils import calendar_publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationFactReference,
    PublicationMember,
)
from apps.data_center.domain.publication_evidence import (
    validate_calendar_publication_evidence,
    validate_publication_evidence,
)

NOW = datetime(2026, 10, 16, 10, tzinfo=UTC)


def _policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=0.99,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=("source", "observed_at", "available_at", "payload_hash"),
        retention_days=3650,
        policy_version="2",
    )


def _calendar_policy() -> PublicationPolicy:
    return replace(
        _policy(),
        required_evidence=("source", "fact_content_hash"),
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _calendar_reference() -> CalendarPublicationMemberReference:
    return CalendarPublicationMemberReference(
        member=PublicationMember(
            member_id="member-1",
            publication_id="publication-1",
            dataset_key=_policy().dataset.value,
            natural_key="explicit-exchange:window",
            source="source",
            source_record_id="raw-1",
            fact_table="calendar-snapshot",
            fact_pk="snapshot-1",
            observed_at=None,
            quality_status="accepted",
            fact_content_hash="a" * 64,
        ),
        snapshot_content_hash="sha256:" + "b" * 64,
        snapshot_record_digest="sha256:" + "c" * 64,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def test_unbound_policy_preserves_original_hash_and_identity() -> None:
    policy = _policy()
    assert policy.member_codec_version is None
    assert policy.content_hash == "50d295d89f7ad2a96e10889aef3a36ca57961399e383b225778fef328d2fb3f0"
    assert policy.identity == "p2:2:" + policy.content_hash
    assert replace(policy, policy_version="legacy").identity == "1.0:1.0"


def test_codec_binding_uses_distinct_explicit_policy_encoding() -> None:
    policy = _calendar_policy()
    payload = {
        "encoding": "publication-policy-v2",
        "dataset_key": policy.dataset.value,
        "contract_version": "1.0",
        "schema_version": "1.0",
        "policy_version": "2",
        "minimum_coverage_ratio": 0.99,
        "allow_partial": True,
        "conflict_action": "quarantine",
        "required_evidence": ["source", "fact_content_hash"],
        "retention_days": 3650,
        "member_codec_version": "calendar-nullable-member-v1",
    }
    expected = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    assert policy.content_hash == expected
    assert policy.content_hash != replace(policy, member_codec_version=None).content_hash
    assert policy.identity == f"p2:2:{expected}"


@pytest.mark.parametrize("invalid", ["", "calendar-nullable-member-v1", "unknown", False, 1, []])
def test_domain_rejects_untyped_or_unknown_codec(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError), match="member_codec_version"):
        replace(_policy(), member_codec_version=cast(CalendarNullableMemberCodecVersion, invalid))


def test_legacy_identity_cannot_hide_codec_binding() -> None:
    with pytest.raises(ValueError, match="versioned"):
        replace(_calendar_policy(), policy_version="legacy")


def test_domain_rejects_unregistered_enum_member() -> None:
    future = str.__new__(CalendarNullableMemberCodecVersion, "calendar-nullable-member-v2")
    object.__setattr__(future, "_name_", "V2")
    object.__setattr__(future, "_value_", "calendar-nullable-member-v2")
    with pytest.raises(ValueError, match="member_codec_version"):
        replace(_policy(), member_codec_version=future)


@pytest.mark.parametrize(
    "change",
    [
        {"minimum_coverage_ratio": -0.01},
        {"minimum_coverage_ratio": 1.01},
        {"minimum_coverage_ratio": float("nan")},
        {"conflict_action": "silently-ignore"},
        {"required_evidence": ()},
        {"required_evidence": ("",)},
        {"retention_days": 0},
        {"retention_days": -1},
    ],
)
def test_bound_policy_still_enforces_coverage_evidence_and_retention(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_calendar_policy(), **change)


def test_calendar_entry_points_require_policy_codec_binding() -> None:
    policy = replace(_calendar_policy(), member_codec_version=None)
    reference = _calendar_reference()
    with pytest.raises(ValueError, match="policy.*codec"):
        calendar_publication_hash(
            [reference], policy=policy, codec_version=CalendarNullableMemberCodecVersion.V1
        )
    with pytest.raises(ValueError, match="policy.*codec"):
        validate_calendar_publication_evidence(
            policy,
            [reference],
            codec_version=CalendarNullableMemberCodecVersion.V1,
            published_at=NOW,
        )


def test_bound_calendar_policy_is_rejected_by_ordinary_evidence_validator() -> None:
    reference = PublicationFactReference(
        natural_key="reference",
        source="source",
        source_record_id="raw-1",
        fact_table="fact",
        fact_pk="1",
        observed_at=NOW,
        fact_content_hash="a" * 64,
    )
    with pytest.raises(ValueError, match="codec"):
        validate_publication_evidence(_calendar_policy(), [reference], published_at=NOW)


def test_explicit_bound_policy_can_hash_and_validate_matching_calendar_member() -> None:
    reference = _calendar_reference()
    validate_calendar_publication_evidence(
        _calendar_policy(),
        [reference],
        codec_version=CalendarNullableMemberCodecVersion.V1,
        published_at=NOW,
    )
    assert (
        len(
            calendar_publication_hash(
                [reference],
                policy=_calendar_policy(),
                codec_version=CalendarNullableMemberCodecVersion.V1,
            )
        )
        == 64
    )
