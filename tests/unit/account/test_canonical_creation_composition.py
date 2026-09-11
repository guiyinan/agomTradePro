from __future__ import annotations

import pytest

from apps.account.application.canonical_account_creation import (
    AllocateCanonicalAccountCreationCommand,
)
from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.canonical_creation_composition import (
    CanonicalAccountCreationStages,
    build_canonical_account_creation_stages,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationRequester,
)


def _settings(**changes: object) -> CanonicalAccountCreationEvidenceSettings:
    values: dict[str, object] = {
        "schema_version": ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        "ttl_seconds": 300,
        "allocation_recorder_service_id": "allocation-recorder-v1",
        "physical_v2_recorder_service_id": "physical-v2-recorder-v1",
        "allocated_v3_recorder_service_id": "allocated-v3-recorder-v1",
        "binding_recorder_service_id": "binding-recorder-v1",
    }
    values.update(changes)
    return CanonicalAccountCreationEvidenceSettings(**values)  # type: ignore[arg-type]


def _requester() -> CanonicalAccountCreationRequester:
    return CanonicalAccountCreationRequester(actor_id="actor-7", user_id=7)


def _command() -> AllocateCanonicalAccountCreationCommand:
    return AllocateCanonicalAccountCreationCommand(
        allocation_id="allocation-7",
        allocation_version="v1",
        request_fingerprint_hash="a" * 64,
        requested_raw_account_type="SIMULATED",
    )


def test_factory_builds_frozen_same_alias_operations_with_explicit_recorders() -> None:
    stages = build_canonical_account_creation_stages(
        using="creation_test",
        settings=_settings(),
        requester=_requester(),
    )

    assert type(stages) is CanonicalAccountCreationStages
    assert stages.database_alias == "creation_test"
    assert stages.allocate._using == "creation_test"  # noqa: SLF001
    assert stages.physical_capture._using == "creation_test"  # noqa: SLF001
    assert stages.allocated_capture._using == "creation_test"  # noqa: SLF001
    assert stages.bind._using == "creation_test"  # noqa: SLF001
    assert stages.get_exact_binding._using == "creation_test"  # noqa: SLF001

    allocation = stages.allocate._operation  # noqa: SLF001
    physical = stages.physical_capture._operation  # noqa: SLF001
    allocated = stages.allocated_capture._operation  # noqa: SLF001
    binding = stages.bind._operation  # noqa: SLF001
    assert allocation._allocator.service_id == "allocation-recorder-v1"  # noqa: SLF001
    assert physical._recorder.recorder_id == "physical-v2-recorder-v1"  # noqa: SLF001
    assert physical._recorder.service_name == "physical-v2-recorder-v1"  # noqa: SLF001
    assert allocated._recorder.service_id == "allocated-v3-recorder-v1"  # noqa: SLF001
    assert binding._binder.service_id == "binding-recorder-v1"  # noqa: SLF001


@pytest.mark.parametrize("using", ["", " bad", "bad alias", True])
def test_factory_rejects_invalid_alias_before_constructing_stages(using: object) -> None:
    with pytest.raises(ValueError, match="database alias"):
        build_canonical_account_creation_stages(
            using=using,  # type: ignore[arg-type]
            settings=_settings(),
            requester=_requester(),
        )


def test_factory_rejects_wrong_snapshot_or_requester_types() -> None:
    with pytest.raises(TypeError, match="settings"):
        build_canonical_account_creation_stages(
            using="creation_test",
            settings=object(),  # type: ignore[arg-type]
            requester=_requester(),
        )
    with pytest.raises(TypeError, match="requester"):
        build_canonical_account_creation_stages(
            using="creation_test",
            settings=_settings(),
            requester=object(),  # type: ignore[arg-type]
        )


def test_write_operation_requires_caller_owned_outer_transaction() -> None:
    stages = build_canonical_account_creation_stages(
        using="default",
        settings=_settings(),
        requester=_requester(),
    )

    with pytest.raises(RuntimeError, match="outer transaction"):
        stages.allocate.execute(_command())


def test_factory_rejects_ttl_that_cannot_form_a_current_deadline() -> None:
    with pytest.raises(ValueError, match="datetime deadline"):
        build_canonical_account_creation_stages(
            using="creation_test",
            settings=_settings(ttl_seconds=10**12),
            requester=_requester(),
        )
