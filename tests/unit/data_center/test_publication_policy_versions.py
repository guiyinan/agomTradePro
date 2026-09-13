"""Stored policy content is immutable within one independent policy version."""

from dataclasses import replace

import pytest

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.catalog_runtime_repositories import PublicationPolicyRepository

pytestmark = pytest.mark.django_db


def _policy(version: str = "2") -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("test.policy.immutable", "1.0", "1.0"),
        minimum_coverage_ratio=0.99,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=("source", "payload_hash"),
        retention_days=3650,
        policy_version=version,
    )


def test_same_policy_version_replay_preserves_content_and_created_row() -> None:
    repository = PublicationPolicyRepository()
    policy = _policy()
    first = repository.save(policy)
    row = DatasetPublicationPolicyModel.objects.get(dataset_key=policy.dataset.value)
    first_created = row.created_at
    assert repository.save(policy) == first == policy
    row.refresh_from_db()
    assert row.created_at == first_created
    assert DatasetPublicationPolicyModel.objects.count() == 1


def test_same_policy_version_cannot_rewrite_threshold_or_required_evidence() -> None:
    repository = PublicationPolicyRepository()
    policy = _policy()
    repository.save(policy)
    for changed in [
        replace(policy, minimum_coverage_ratio=1.0),
        replace(policy, required_evidence=("source", "observed_at", "payload_hash")),
    ]:
        with pytest.raises(ValueError, match="immutable"):
            repository.save(changed)
        assert repository.get_active(policy.dataset.value) == policy
    assert DatasetPublicationPolicyModel.objects.count() == 1


def test_new_policy_version_supersedes_without_overwriting_previous_content() -> None:
    repository = PublicationPolicyRepository()
    previous = _policy()
    repository.save(previous)
    successor = replace(previous, policy_version="3", minimum_coverage_ratio=1.0)
    assert repository.save(successor) == successor
    assert repository.get_active(previous.dataset.value) == successor
    rows = list(DatasetPublicationPolicyModel.objects.order_by("policy_version"))
    assert len(rows) == 2
    assert rows[0].to_domain() == previous and not rows[0].active
    assert rows[1].to_domain() == successor and rows[1].active


def test_failed_rewrite_does_not_deactivate_other_current_version() -> None:
    repository = PublicationPolicyRepository()
    previous = _policy()
    current = _policy("3")
    repository.save(previous)
    repository.save(current)
    with pytest.raises(ValueError, match="immutable"):
        repository.save(replace(previous, retention_days=1825))
    assert repository.get_active(current.dataset.value) == current
