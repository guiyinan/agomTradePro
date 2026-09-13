"""Actual SQLite coverage for the candidate-bound policy activation command."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import models

from apps.data_center.application.current_publication_evidence import (
    current_publication_evidence_blocked_reason,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import CanonicalPublicationModel

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_SOURCE = ROOT / "governance" / "publication_policies.json"
CATALOG_MODELS = (
    ("data_center_dataset_contract", DatasetContractModel),
    ("data_center_dataset_provider_binding", DatasetProviderBindingModel),
    ("data_center_data_owner_registration", DataOwnerRegistrationModel),
)


def _rowset_fingerprint(model: type[models.Model]) -> tuple[int, str]:
    """Match the preflight's all-fields, primary-key ordered row-set hash."""

    rows = list(model._default_manager.order_by("pk").values())
    encoded = json.dumps(
        rows,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return len(rows), hashlib.sha256(encoded).hexdigest()


def _catalog_baseline() -> dict[str, dict[str, object]]:
    """Return the independent SQLite fixture's exact catalog baseline."""

    return {
        table_name: {
            "row_count": row_count,
            "all_persisted_fields_sha256": digest,
            "encoding": "catalog-rowset-v1-including-identities-and-timestamps",
        }
        for table_name, model in CATALOG_MODELS
        for row_count, digest in [_rowset_fingerprint(model)]
    }


def _legacy_policy(row: dict[str, object], contract: DatasetKey) -> PublicationPolicy:
    """Build one legacy expected policy from the immutable preflight row."""

    return PublicationPolicy(
        dataset=contract,
        minimum_coverage_ratio=float(row["minimum_coverage_ratio"]),
        allow_partial=bool(row["allow_partial"]),
        conflict_action=str(row["conflict_action"]),
        required_evidence=tuple(str(item) for item in row["required_evidence"]),
        retention_days=int(row["retention_days"]),
        policy_version="legacy",
    )


@pytest.fixture
def activation_inputs(tmp_path: Path) -> dict[str, object]:
    """Seed ten legacy policies and build a disposable expected-state artifact."""

    candidate_bytes = CANDIDATE_SOURCE.read_bytes()
    candidate_payload = json.loads(candidate_bytes.decode("utf-8"))
    contract_rows = [
        {
            "dataset_key": row["dataset_key"],
            "contract_version": "1.0",
            "schema_version": "1.0",
        }
        for row in candidate_payload["policies"]
    ]
    legacy_evidence = {
        "equity.price.bar": ["source", "observed_at", "payload_hash"],
        "equity.quote.snapshot": ["source", "observed_at", "fetched_at", "payload_hash"],
        "equity.financial.fact": [
            "source",
            "observed_at",
            "available_at",
            "payload_hash",
        ],
        "equity.valuation.fact": ["source", "observed_at", "payload_hash"],
    }
    policy_rows = []
    for source_row in candidate_payload["policies"]:
        row = dict(source_row)
        row.pop("policy_version", None)
        if str(source_row["dataset_key"]) in legacy_evidence:
            row["required_evidence"] = legacy_evidence[str(source_row["dataset_key"])]
        row["active"] = True
        policy_rows.append(row)
    contracts: dict[str, DatasetKey] = {}
    for row in contract_rows:
        key = DatasetKey(
            value=str(row["dataset_key"]),
            contract_version=str(row["contract_version"]),
            schema_version=str(row["schema_version"]),
        )
        contracts[key.value] = key
        DatasetContractModel.objects.create(
            dataset_key=key.value,
            contract_version=key.contract_version,
            schema_version=key.schema_version,
            owner="data-platform",
            frequency="daily",
            decision_critical=True,
            fields=[
                {
                    "name": "observed_at",
                    "type": "datetime",
                    "unit": None,
                    "nullable": False,
                    "zero_allowed": False,
                }
            ],
            freshness_seconds=86_400,
            comparable_group="activation-test",
            active=True,
        )
    for row in policy_rows:
        dataset_key = str(row["dataset_key"])
        policy = _legacy_policy(row, contracts[dataset_key])
        DatasetPublicationPolicyModel.objects.create(
            dataset_key=policy.dataset.value,
            contract_version=policy.dataset.contract_version,
            schema_version=policy.dataset.schema_version,
            policy_version=policy.policy_version,
            minimum_coverage_ratio=policy.minimum_coverage_ratio,
            allow_partial=policy.allow_partial,
            conflict_action=policy.conflict_action,
            required_evidence=list(policy.required_evidence),
            retention_days=policy.retention_days,
            active=True,
        )

    publication = CanonicalPublicationModel.objects.create(
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="1.0:1.0",
        state="published",
        selected_source="activation-test",
        publication_hash="0" * 64,
        member_count=1,
        conflict_count=0,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        coverage_missing_count=0,
        coverage_conflict_count=0,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        published_at=datetime(2026, 1, 2, tzinfo=UTC),
        must_not_use_for_decision=False,
        blocked_reason="",
        created_by="activation-test",
    )

    candidate_path = tmp_path / "publication_policies.json"
    candidate_path.write_bytes(candidate_bytes)
    targets = tuple(
        sorted(
            str(row["dataset_key"])
            for row in candidate_payload["policies"]
            if row.get("policy_version", "legacy") != "legacy"
        )
    )
    state: dict[str, object] = {
        "read_only": True,
        "existing_policy_own_version_column": True,
        "active_contract_keys": contract_rows,
        "active_policies": policy_rows,
        "unrelated_catalog_baseline": _catalog_baseline(),
        "candidate_policy_projection_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "candidate_target_dataset_keys": list(targets),
    }
    state["published_current_metadata"] = [
        {
            "dataset_key": publication.dataset_key,
            "publication_id": str(publication.publication_id),
            "policy_version": publication.policy_version,
            "publication_hash": publication.publication_hash,
            "member_count": publication.member_count,
            "as_of": str(publication.as_of),
            "published_at": str(publication.published_at),
            "must_not_use_for_decision": publication.must_not_use_for_decision,
            "blocked_reason": publication.blocked_reason,
        }
    ]
    expected_path = tmp_path / "expected_state.json"
    expected_path.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "expected": expected_path,
        "candidate": candidate_path,
        "targets": targets,
        "publication_id": str(publication.publication_id),
    }


def _run_command(inputs: dict[str, object], *, execute: bool = False) -> dict[str, object]:
    """Invoke the command and decode its one-line JSON result."""

    output = StringIO()
    options: dict[str, object] = {
        "expected_state": str(inputs["expected"]),
        "policies": str(inputs["candidate"]),
        "stdout": output,
    }
    if execute:
        options["execute"] = True
    call_command("activate_publication_policies", **options)
    return json.loads(output.getvalue())


def test_preview_is_read_only_and_derives_targets_from_candidate(
    activation_inputs: dict[str, object],
) -> None:
    """The default command mode reports all dynamic targets without writes."""

    before_count = DatasetPublicationPolicyModel.objects.count()
    result = _run_command(activation_inputs)

    assert result["mode"] == "preview"
    assert result["activated"] is False
    assert tuple(result["target_dataset_keys"]) == activation_inputs["targets"]
    assert result["published_current_metadata"][0]["blocked_reason"] == ""
    assert DatasetPublicationPolicyModel.objects.count() == before_count
    assert not DatasetPublicationPolicyModel.objects.filter(policy_version="2").exists()


def test_extra_active_policy_dataset_is_rejected_before_activation(
    activation_inputs: dict[str, object],
) -> None:
    """An active policy outside the complete preflight rowset is a phantom drift."""

    DatasetPublicationPolicyModel.objects.create(
        dataset_key="unexpected.dataset",
        contract_version="1.0",
        schema_version="1.0",
        policy_version="legacy",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "payload_hash"],
        retention_days=365,
        active=True,
    )

    with pytest.raises(CommandError, match="dataset set"):
        _run_command(activation_inputs, execute=True)
    assert not DatasetPublicationPolicyModel.objects.filter(policy_version="2").exists()


def test_candidate_hash_drift_is_rejected_before_any_policy_write(
    activation_inputs: dict[str, object],
) -> None:
    """Changing candidate bytes after preflight fails before the transaction writes."""

    candidate_path = Path(str(activation_inputs["candidate"]))
    candidate_path.write_bytes(candidate_path.read_bytes() + b"\n")

    with pytest.raises(CommandError, match="SHA-256"):
        _run_command(activation_inputs, execute=True)
    assert not DatasetPublicationPolicyModel.objects.filter(policy_version="2").exists()


def test_legacy_same_identity_content_drift_is_rejected(
    activation_inputs: dict[str, object],
) -> None:
    """A legacy identity cannot launder a changed threshold through activation."""

    DatasetPublicationPolicyModel.objects.filter(dataset_key="asset.master").update(
        minimum_coverage_ratio=0.95
    )

    with pytest.raises(CommandError, match="decision content"):
        _run_command(activation_inputs, execute=True)
    assert not DatasetPublicationPolicyModel.objects.filter(policy_version="2").exists()


def test_execute_preserves_catalog_and_existing_current_publication(
    activation_inputs: dict[str, object],
) -> None:
    """Successful activation changes only the candidate target policy heads."""

    before_publication = dict(
        CanonicalPublicationModel.objects.values().get(
            publication_id=activation_inputs["publication_id"]
        )
    )
    result = _run_command(activation_inputs, execute=True)

    assert result["mode"] == "execute"
    active = {
        row["dataset_key"]: row["policy_version"]
        for row in DatasetPublicationPolicyModel.objects.filter(active=True).values(
            "dataset_key", "policy_version"
        )
    }
    assert {key for key, version in active.items() if version == "2"} == set(
        activation_inputs["targets"]
    )
    assert len(active) == 10
    assert DatasetPublicationPolicyModel.objects.count() == 14
    assert _catalog_baseline() == {
        table_name: {
            "row_count": item["row_count"],
            "all_persisted_fields_sha256": item["all_persisted_fields_sha256"],
            "encoding": item["encoding"],
        }
        for table_name, item in json.loads(Path(str(activation_inputs["expected"])).read_text())[
            "unrelated_catalog_baseline"
        ].items()
    }
    after_publication = dict(
        CanonicalPublicationModel.objects.values().get(
            publication_id=activation_inputs["publication_id"]
        )
    )
    assert after_publication == before_publication


def test_failure_on_last_target_rolls_back_every_policy_write(
    activation_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late candidate failure leaves all ten active heads and rows unchanged."""

    original_save = PublicationPolicyRepository.save
    last_target = tuple(activation_inputs["targets"])[-1]

    def fail_last(
        self: PublicationPolicyRepository, policy: PublicationPolicy
    ) -> PublicationPolicy:
        if policy.dataset.value == last_target:
            raise ValueError("simulated final target failure")
        return original_save(self, policy)

    monkeypatch.setattr(PublicationPolicyRepository, "save", fail_last)
    with pytest.raises(CommandError, match="simulated final target failure"):
        _run_command(activation_inputs, execute=True)

    assert DatasetPublicationPolicyModel.objects.count() == 10
    assert not DatasetPublicationPolicyModel.objects.filter(policy_version="2").exists()
    assert DatasetPublicationPolicyModel.objects.filter(active=True).count() == 10


def test_policy_activation_leaves_old_current_head_blocked_by_policy_changed(
    activation_inputs: dict[str, object],
) -> None:
    """Activating P2 does not rewrite a legacy current publication into P2."""

    _run_command(activation_inputs, execute=True)
    publication = CanonicalPublicationModel.objects.get(
        publication_id=activation_inputs["publication_id"]
    )
    policy_row = DatasetPublicationPolicyModel.objects.get(
        dataset_key="equity.price.bar", active=True
    )
    reason = current_publication_evidence_blocked_reason(
        publication.to_domain(),
        policy=policy_row.to_domain(),
        members=(),
        fact_content_hashes={},
        knowledge_cutoff=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert reason == "publication_policy_changed"
