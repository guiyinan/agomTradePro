"""Exact policy bindings for nullable publication member codecs."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest
from django.core.management.base import CommandError

from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
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
from apps.data_center.domain.publication_member_codec import (
    PriceLimitNullableMemberCodecVersion,
    decode_publication_member_codec,
)
from apps.data_center.management.commands.activate_publication_policies import _policy
from apps.data_center.management.commands.initialize_data_center_catalog import _load_policies

NOW = datetime(2026, 10, 29, 8, tzinfo=UTC)


def _price_limit_policy(**changes: object) -> PublicationPolicy:
    """Create a complete policy that does not require unavailable source clocks."""

    policy = PublicationPolicy(
        dataset=DatasetKey("equity.price.limit", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "raw_payload_hash",
            "fetched_at",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="1",
        member_codec_version=PriceLimitNullableMemberCodecVersion.V1,
    )
    return replace(policy, **changes) if changes else policy


def _calendar_reference() -> CalendarPublicationMemberReference:
    """Build a valid nullable Calendar reference for cross-validator tests."""

    return CalendarPublicationMemberReference(
        member=PublicationMember(
            member_id="member-1",
            publication_id="publication-1",
            dataset_key="data_center.exchange_calendar_snapshot",
            natural_key="SSE:2026-01-01:2026-12-31",
            source="tushare",
            source_record_id="raw-1",
            fact_table="data_center_exchange_calendar_snapshot",
            fact_pk="snapshot-1",
            observed_at=None,
            quality_status="accepted",
            fact_content_hash="a" * 64,
        ),
        snapshot_content_hash="sha256:" + "b" * 64,
        snapshot_record_digest="sha256:" + "c" * 64,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _contract(dataset_key: str) -> DatasetContract:
    """Build a minimal catalog contract for command-parser tests."""

    return DatasetContract(
        key=DatasetKey(dataset_key, "1.0", "1.0"),
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="source_record_id",
                value_type="string",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
        ),
    )


def _policy_row(dataset_key: str = "equity.price.limit") -> dict[str, object]:
    """Return a command row whose evidence does not require unknown source clocks."""

    return {
        "dataset_key": dataset_key,
        "minimum_coverage_ratio": 1.0,
        "allow_partial": False,
        "conflict_action": "block",
        "required_evidence": [
            "source",
            "raw_payload_hash",
            "fetched_at",
            "raw_payload_scope",
            "fact_content_hash",
        ],
        "retention_days": 3650,
        "policy_version": "1",
        "member_codec_version": "price-limit-nullable-member-v1",
    }


def test_publication_codec_decoder_preserves_exact_enum_identities() -> None:
    assert decode_publication_member_codec(None) is None
    assert (
        decode_publication_member_codec("calendar-nullable-member-v1")
        is CalendarNullableMemberCodecVersion.V1
    )
    assert (
        decode_publication_member_codec("price-limit-nullable-member-v1")
        is PriceLimitNullableMemberCodecVersion.V1
    )


@pytest.mark.parametrize("invalid", [False, 1, [], {}, CalendarNullableMemberCodecVersion.V1])
def test_publication_codec_decoder_rejects_non_exact_text_types(invalid: object) -> None:
    with pytest.raises(TypeError, match="text"):
        decode_publication_member_codec(cast(str | None, invalid))


@pytest.mark.parametrize("invalid", ["", "calendar-nullable-member-v2", "unknown-codec"])
def test_publication_codec_decoder_rejects_empty_or_unknown_values(invalid: str) -> None:
    with pytest.raises(ValueError, match="supported"):
        decode_publication_member_codec(invalid)


def test_price_limit_policy_binds_exact_dataset_and_versioned_identity() -> None:
    policy = _price_limit_policy()

    assert policy.member_codec_version is PriceLimitNullableMemberCodecVersion.V1
    assert policy.identity == f"p2:1:{policy.content_hash}"
    assert policy.content_hash == replace(policy).content_hash
    assert policy.content_hash != replace(policy, member_codec_version=None).content_hash


def test_price_limit_policy_rejects_other_datasets() -> None:
    with pytest.raises(ValueError, match="equity.price.limit"):
        replace(
            _price_limit_policy(),
            dataset=DatasetKey("equity.price.bar", "1.0", "1.0"),
        )


def test_price_limit_policy_rejects_untyped_and_unregistered_codec_values() -> None:
    with pytest.raises(ValueError, match="member_codec_version"):
        replace(
            _price_limit_policy(),
            member_codec_version=cast(
                PriceLimitNullableMemberCodecVersion,
                "price-limit-nullable-member-v1",
            ),
        )

    future = str.__new__(PriceLimitNullableMemberCodecVersion, "price-limit-nullable-member-v2")
    object.__setattr__(future, "_name_", "V2")
    object.__setattr__(future, "_value_", "price-limit-nullable-member-v2")
    with pytest.raises(ValueError, match="member_codec_version"):
        replace(_price_limit_policy(), member_codec_version=future)


def test_price_limit_policy_cannot_be_legacy() -> None:
    with pytest.raises(ValueError, match="versioned"):
        replace(_price_limit_policy(), policy_version="legacy")


@pytest.mark.parametrize("evidence_key", ["observed_at", "available_at", "published_at"])
def test_price_limit_policy_cannot_require_unknown_source_clocks(evidence_key: str) -> None:
    policy = _price_limit_policy()
    with pytest.raises(ValueError, match="source timestamps"):
        replace(policy, required_evidence=(*policy.required_evidence, evidence_key))


def test_price_limit_policy_is_rejected_by_generic_and_calendar_evidence_validators() -> None:
    policy = _price_limit_policy()
    reference = PublicationFactReference(
        natural_key="600000.SH:2026-10-28",
        source="tushare",
        source_record_id="raw-1",
        fact_table="data_center_price_limit_snapshot_fact",
        fact_pk="snapshot-1",
        observed_at=NOW,
        fact_content_hash="d" * 64,
    )

    with pytest.raises(ValueError, match="codec"):
        validate_publication_evidence(policy, [reference], published_at=NOW)
    with pytest.raises(ValueError, match="policy.*codec"):
        validate_calendar_publication_evidence(
            policy,
            [_calendar_reference()],
            codec_version=CalendarNullableMemberCodecVersion.V1,
            published_at=NOW,
        )


def test_catalog_initializer_decodes_price_limit_member_codec(tmp_path) -> None:
    manifest = tmp_path / "publication-policies.json"
    manifest.write_text(
        '{"schema_version":"1.0","policies":['
        + json.dumps(_policy_row(), separators=(",", ":"))
        + "]}",
        encoding="utf-8",
    )

    policies = _load_policies(manifest, {"equity.price.limit": _contract("equity.price.limit")})

    assert policies[0].member_codec_version is PriceLimitNullableMemberCodecVersion.V1


def test_catalog_initializer_rejects_price_codec_for_wrong_dataset(tmp_path) -> None:
    manifest = tmp_path / "publication-policies.json"
    manifest.write_text(
        '{"schema_version":"1.0","policies":['
        + json.dumps(_policy_row("equity.price.bar"), separators=(",", ":"))
        + "]}",
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="equity.price.limit"):
        _load_policies(manifest, {"equity.price.bar": _contract("equity.price.bar")})


def test_activation_command_decodes_price_limit_member_codec() -> None:
    contract = DatasetKey("equity.price.limit", "1.0", "1.0")

    policy = _policy(
        _policy_row(),
        context="candidate policy",
        contracts={contract.value: contract},
        require_active=False,
    )

    assert policy.member_codec_version is PriceLimitNullableMemberCodecVersion.V1


def test_activation_command_rejects_price_codec_for_wrong_dataset() -> None:
    contract = DatasetKey("equity.price.bar", "1.0", "1.0")

    with pytest.raises(CommandError, match="equity.price.limit"):
        _policy(
            _policy_row("equity.price.bar"),
            context="candidate policy",
            contracts={contract.value: contract},
            require_active=False,
        )


@pytest.mark.parametrize(
    ("command", "evidence_key"),
    [
        ("initialize", "observed_at"),
        ("initialize", "available_at"),
        ("initialize", "published_at"),
        ("activate", "observed_at"),
        ("activate", "available_at"),
        ("activate", "published_at"),
    ],
)
def test_both_policy_commands_reject_price_codec_source_clock_requirements(
    tmp_path,
    command: str,
    evidence_key: str,
) -> None:
    row = _policy_row()
    evidence = cast(list[str], row["required_evidence"])
    evidence.append(evidence_key)
    with pytest.raises(CommandError, match="unavailable source timestamps"):
        if command == "initialize":
            manifest = tmp_path / "publication-policies.json"
            manifest.write_text(
                '{"schema_version":"1.0","policies":['
                + json.dumps(row, separators=(",", ":"))
                + "]}",
                encoding="utf-8",
            )
            _load_policies(
                manifest,
                {"equity.price.limit": _contract("equity.price.limit")},
            )
        else:
            contract = DatasetKey("equity.price.limit", "1.0", "1.0")
            _policy(
                row,
                context="candidate policy",
                contracts={contract.value: contract},
                require_active=False,
            )
