"""Persist explicit calendar codecs without reinterpreting old policy versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.market_rehearsal_runner import (
    canonical_publication_policy_evidence,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.management.commands.activate_publication_policies import (
    _policy as parse_activation_policy,
)
from apps.data_center.management.commands.initialize_data_center_catalog import _load_policies


def _contract() -> DatasetContract:
    return DatasetContract(
        key=DatasetKey("explicit.calendar.reference", "codec-test-1", "1.0"),
        owner="source-owner",
        frequency="explicit",
        decision_critical=True,
        fields=(DatasetFieldContract("sessions", "json", None, False, False),),
    )


def _policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=_contract().key,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=30,
        policy_version="explicit-codec-1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _manifest_row(codec: object) -> dict[str, object]:
    return {
        "dataset_key": _contract().key.value,
        "policy_version": "explicit-codec-1",
        "minimum_coverage_ratio": 1.0,
        "allow_partial": False,
        "conflict_action": "block",
        "required_evidence": ["source", "fact_content_hash"],
        "retention_days": 30,
        "member_codec_version": codec,
    }


@pytest.mark.django_db
def test_explicit_codec_roundtrips_through_actual_policy_repository() -> None:
    repo = PublicationPolicyRepository()
    policy = _policy()
    assert repo.save(policy) == policy
    row = DatasetPublicationPolicyModel.objects.get(dataset_key=policy.dataset.value)
    original = (row.pk, row.created_at)
    assert row.member_codec_version == CalendarNullableMemberCodecVersion.V1.value
    assert repo.get_active(policy.dataset.value) == policy
    assert repo.save(policy) == policy
    row.refresh_from_db()
    assert (row.pk, row.created_at) == original
    assert (
        DatasetPublicationPolicyModel.objects.filter(dataset_key=policy.dataset.value).count() == 1
    )


@pytest.mark.django_db
@pytest.mark.parametrize("bound_first", [True, False])
def test_same_policy_version_cannot_change_its_codec(bound_first: bool) -> None:
    repo = PublicationPolicyRepository()
    bound = _policy()
    unbound = replace(bound, member_codec_version=None)
    original, changed = (bound, unbound) if bound_first else (unbound, bound)
    repo.save(original)
    with pytest.raises(ValueError, match="immutable"):
        repo.save(changed)
    assert repo.get_active(original.dataset.value) == original


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("codec", "version"), [("unknown", "v2"), ("", "v2"), ("calendar-nullable-member-v1", "legacy")]
)
def test_database_rejects_invalid_or_legacy_codec(codec: str, version: str) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        DatasetPublicationPolicyModel.objects.create(
            dataset_key=_contract().key.value,
            contract_version="1.0",
            schema_version="1.0",
            policy_version=version,
            member_codec_version=codec,
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=["source"],
            retention_days=1,
        )


def test_old_policy_model_with_null_codec_preserves_unbound_semantics() -> None:
    row = DatasetPublicationPolicyModel(
        dataset_key=_contract().key.value,
        contract_version="1.0",
        schema_version="1.0",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source"],
        retention_days=1,
        member_codec_version=None,
    )
    assert row.to_domain().member_codec_version is None
    assert row.to_domain().identity == "1.0:1.0"


@pytest.mark.parametrize("codec", ["unknown", False, 7, [], ""])
def test_model_adapter_does_not_coerce_unknown_codecs(codec: object) -> None:
    row = DatasetPublicationPolicyModel(
        dataset_key=_contract().key.value,
        contract_version="1.0",
        schema_version="1.0",
        policy_version="explicit",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source"],
        retention_days=1,
    )
    row.__dict__["member_codec_version"] = codec
    with pytest.raises((TypeError, ValueError)):
        row.to_domain()


@pytest.mark.parametrize("codec", [None, "calendar-nullable-member-v1"])
def test_both_policy_command_parsers_preserve_explicit_binding(
    tmp_path: Path, codec: str | None
) -> None:
    row = _manifest_row(codec)
    path = tmp_path / "policies.json"
    path.write_text(json.dumps({"schema_version": "1.0", "policies": [row]}), encoding="utf-8")
    imported = _load_policies(path, {_contract().key.value: _contract()})
    activation = parse_activation_policy(
        row,
        context="candidate",
        contracts={_contract().key.value: _contract().key},
        require_active=False,
    )
    expected = CalendarNullableMemberCodecVersion.V1 if codec is not None else None
    assert imported[0].member_codec_version is expected
    assert activation == imported[0]


@pytest.mark.parametrize("codec", [True, 1, [], "", "unknown"])
def test_both_policy_commands_reject_unknown_codec(tmp_path: Path, codec: object) -> None:
    row = _manifest_row(codec)
    path = tmp_path / "policies.json"
    path.write_text(json.dumps({"schema_version": "1.0", "policies": [row]}), encoding="utf-8")
    with pytest.raises(CommandError, match="member_codec_version"):
        _load_policies(path, {_contract().key.value: _contract()})
    with pytest.raises(CommandError, match="member_codec_version"):
        parse_activation_policy(
            row,
            context="candidate",
            contracts={_contract().key.value: _contract().key},
            require_active=False,
        )


def test_both_policy_commands_reject_codec_hidden_under_legacy_identity(tmp_path: Path) -> None:
    row = _manifest_row("calendar-nullable-member-v1")
    row["policy_version"] = "legacy"
    path = tmp_path / "policies.json"
    path.write_text(json.dumps({"schema_version": "1.0", "policies": [row]}), encoding="utf-8")
    with pytest.raises(CommandError, match="versioned"):
        _load_policies(path, {_contract().key.value: _contract()})
    with pytest.raises(CommandError, match="versioned"):
        parse_activation_policy(
            row,
            context="candidate",
            contracts={_contract().key.value: _contract().key},
            require_active=False,
        )


def test_rehearsal_policy_evidence_has_the_exact_bound_content_hash() -> None:
    policy = _policy()
    evidence = canonical_publication_policy_evidence(policy)
    encoded = json.dumps(
        evidence["content"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == evidence["content_sha256"] == policy.content_hash
