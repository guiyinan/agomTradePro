"""Application contracts for candidate-bound publication policy activation."""

from dataclasses import replace

import pytest

from apps.data_center.application.publication_policy_activation import (
    ActivatePublicationPoliciesUseCase,
    CatalogFingerprint,
    PublicationPolicyActivationError,
    PublicationPolicyActivationExpectedState,
    PublicationPolicyActivationRequest,
    PublicationPolicyActivationResult,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy


def _policy(dataset_key: str, *, version: str = "legacy") -> PublicationPolicy:
    """Build a small valid policy for application-port tests."""

    return PublicationPolicy(
        dataset=DatasetKey(dataset_key, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "payload_hash"),
        retention_days=365,
        policy_version=version,
    )


def _expected_state(
    *policies: PublicationPolicy,
    target_dataset_keys: tuple[str, ...] = (),
) -> PublicationPolicyActivationExpectedState:
    """Build a complete typed expected-state value."""

    return PublicationPolicyActivationExpectedState(
        active_policies=tuple(policies),
        active_contract_keys=tuple(policy.dataset for policy in policies),
        unrelated_catalog_baseline=tuple(
            CatalogFingerprint(table_name=table, row_count=0, sha256="0" * 64)
            for table in (
                "data_center_dataset_contract",
                "data_center_dataset_provider_binding",
                "data_center_data_owner_registration",
            )
        ),
        published_current_metadata=(),
        candidate_policy_projection_sha256="1" * 64,
        candidate_target_dataset_keys=target_dataset_keys,
    )


class _Repository:
    """Typed fake proving the Application layer delegates persistence."""

    def __init__(self) -> None:
        self.preview_requests: list[PublicationPolicyActivationRequest] = []
        self.execute_requests: list[PublicationPolicyActivationRequest] = []

    def preview(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        self.preview_requests.append(request)
        return PublicationPolicyActivationResult(
            preview=True,
            activated=False,
            target_dataset_keys=request.target_dataset_keys,
            active_policy_identities=(),
            catalog_fingerprints=request.expected_state.unrelated_catalog_baseline,
            published_current_metadata=(),
        )

    def execute(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        self.execute_requests.append(request)
        return PublicationPolicyActivationResult(
            preview=False,
            activated=True,
            target_dataset_keys=request.target_dataset_keys,
            active_policy_identities=(),
            catalog_fingerprints=request.expected_state.unrelated_catalog_baseline,
            published_current_metadata=(),
        )


def test_application_use_case_exposes_typed_preview_and_execute_ports() -> None:
    """Preview and execute keep the candidate request behind one repository port."""

    legacy = _policy("test.legacy")
    candidate = replace(legacy, policy_version="2")
    expected = _expected_state(legacy, target_dataset_keys=("test.legacy",))
    request = PublicationPolicyActivationRequest(
        expected_state=expected,
        candidate_policies=(candidate,),
        candidate_manifest_sha256="1" * 64,
    )
    repository = _Repository()
    use_case = ActivatePublicationPoliciesUseCase(repository)

    preview = use_case.preview(request)
    executed = use_case.execute(request)

    assert preview.preview and not preview.activated
    assert executed.activated and not executed.preview
    assert repository.preview_requests == [request]
    assert repository.execute_requests == [request]


def test_request_derives_nonlegacy_targets_and_rejects_projection_hash_drift() -> None:
    """The typed request binds dynamic targets and exact manifest bytes."""

    legacy = _policy("test.legacy")
    expected = _expected_state(legacy, target_dataset_keys=("test.legacy",))
    candidate = replace(legacy, policy_version="2")

    request = PublicationPolicyActivationRequest(
        expected_state=expected,
        candidate_policies=(candidate,),
        candidate_manifest_sha256="1" * 64,
    )
    assert request.target_dataset_keys == ("test.legacy",)

    with pytest.raises(PublicationPolicyActivationError, match="SHA-256"):
        PublicationPolicyActivationRequest(
            expected_state=expected,
            candidate_policies=(candidate,),
            candidate_manifest_sha256="2" * 64,
        )


def test_legacy_identity_does_not_hide_decision_content_drift() -> None:
    """Legacy rows retain their identity while their complete content still differs."""

    original = _policy("test.legacy")
    changed = replace(original, minimum_coverage_ratio=0.95)

    assert original.identity == changed.identity == "1.0:1.0"
    assert original.content_hash != changed.content_hash
    assert original != changed


def test_expected_state_requires_all_unrelated_catalog_fingerprints() -> None:
    """A preflight without the three catalog baselines cannot be activated."""

    policy = _policy("test.policy")
    with pytest.raises(PublicationPolicyActivationError, match="all unrelated"):
        PublicationPolicyActivationExpectedState(
            active_policies=(policy,),
            active_contract_keys=(policy.dataset,),
            unrelated_catalog_baseline=(),
            published_current_metadata=(),
            candidate_policy_projection_sha256="1" * 64,
            candidate_target_dataset_keys=(),
        )
