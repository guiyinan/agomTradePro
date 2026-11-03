"""Database contracts for inactive Config Center draft persistence."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from apps.config_center.application.runtime_config_drafts import (
    RuntimeConfigDraftConflictError,
    RuntimeConfigDraftRequest,
    RuntimeConfigDraftService,
    RuntimeConfigDraftValueInput,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigReloadMode,
    RuntimeValueType,
)
from apps.config_center.infrastructure.models import (
    RuntimeConfigProfileModel,
    RuntimeConfigRevisionModel,
    RuntimeConfigSnapshotModel,
    RuntimeConfigValueModel,
)
from apps.config_center.infrastructure.runtime_config_repositories import (
    RuntimeConfigDefinitionRepository,
    RuntimeConfigDraftUnitOfWork,
    RuntimeConfigProfileRepository,
    RuntimeConfigSnapshotRepository,
)


def _service() -> RuntimeConfigDraftService:
    """Build the production definition reader and draft transaction for one test."""

    definitions = RuntimeConfigDefinitionRepository()
    definitions.save(
        RuntimeConfigDefinition(
            key="test.runtime_config.draft_value",
            namespace="test",
            owner_app="test",
            value_type=RuntimeValueType.TYPED_JSON,
            criticality=RuntimeConfigCriticality.NORMAL,
            reload_mode=RuntimeConfigReloadMode.IMMEDIATE,
        )
    )
    return RuntimeConfigDraftService(definitions, RuntimeConfigDraftUnitOfWork())


def _request(value: str = "first") -> RuntimeConfigDraftRequest:
    """Return a deterministic one-value draft request."""

    return RuntimeConfigDraftRequest(
        profile_key="test.runtime_config.draft_profile",
        environment="development",
        version=1,
        actor="operator@example.test",
        reason="create-only draft contract",
        values=(
            RuntimeConfigDraftValueInput(
                definition_key="test.runtime_config.draft_value",
                value_json={"value": value},
                source="test_fixture",
            ),
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_draft_rows_are_atomic_inactive_unsnapshotted_and_idempotent() -> None:
    service = _service()
    profiles = RuntimeConfigProfileRepository()
    snapshots = RuntimeConfigSnapshotRepository()
    active_before = profiles.get_active("development")
    planned = service.preview(_request())

    first = service.create(_request())
    retry = service.create(_request())

    stored_profile = RuntimeConfigProfileModel._default_manager.get(
        profile_id=UUID(first.profile.profile_id)
    )
    assert first.created is True
    assert retry.created is False
    assert first.profile.profile_id == retry.profile.profile_id == planned.profile.profile_id
    assert stored_profile.status == "draft"
    assert stored_profile.activated_at is None
    assert (
        RuntimeConfigValueModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 1
    )
    assert (
        RuntimeConfigRevisionModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 1
    )
    assert (
        RuntimeConfigSnapshotModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 0
    )
    assert snapshots.get_latest(first.profile.profile_key) is None
    assert profiles.get_active("development") == active_before


@pytest.mark.django_db(transaction=True)
def test_different_content_at_same_key_version_is_rejected_without_mutation() -> None:
    service = _service()
    first = service.create(_request())

    with pytest.raises(RuntimeConfigDraftConflictError):
        service.create(_request("different"))

    assert (
        RuntimeConfigProfileModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id),
            content_hash=first.profile.content_hash,
        ).count()
        == 1
    )
    assert (
        RuntimeConfigValueModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 1
    )
    assert (
        RuntimeConfigRevisionModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 1
    )
    assert (
        RuntimeConfigSnapshotModel._default_manager.filter(
            profile_id=UUID(first.profile.profile_id)
        ).count()
        == 0
    )


@pytest.mark.django_db(transaction=True)
def test_revision_collision_rolls_back_profile_and_value_insertion() -> None:
    service = _service()
    request = _request()
    plan = service.preview(request)
    RuntimeConfigRevisionModel._default_manager.create(
        revision_id=UUID(plan.revision.revision_id),
        profile_id=uuid4(),
        before_hash="",
        after_hash="collision",
        changed_keys=[],
        before_projection={},
        after_projection={},
        actor="collision@example.test",
        reason="force a late transaction conflict",
        validation_evidence={},
    )

    with pytest.raises(RuntimeConfigDraftConflictError):
        service.create(request)

    assert not RuntimeConfigProfileModel._default_manager.filter(
        profile_key=request.profile_key,
        version=request.version,
    ).exists()
    assert not RuntimeConfigValueModel._default_manager.filter(
        profile_id=UUID(plan.profile.profile_id)
    ).exists()
    assert not RuntimeConfigSnapshotModel._default_manager.filter(
        profile_key=request.profile_key
    ).exists()
