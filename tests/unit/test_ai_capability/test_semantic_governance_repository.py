"""Repository tests for transactional semantic-key governance."""

from __future__ import annotations

import pytest

from apps.ai_capability.domain.entities import CapabilityDefinition, SourceType
from apps.ai_capability.domain.semantic_governance import (
    SemanticCorrection,
    SemanticCorrectionBatch,
    SemanticIdempotencyConflict,
    SemanticValueSnapshot,
)
from apps.ai_capability.infrastructure.models import (
    CapabilityCatalogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
)
from apps.ai_capability.infrastructure.repositories import DjangoCapabilityRepository
from apps.ai_capability.infrastructure.semantic_governance_repository import (
    DjangoSemanticGovernanceRepository,
)


@pytest.mark.django_db
def test_repository_lists_only_active_overrides(django_user_model) -> None:
    """Inactive historical decisions are excluded from effective overrides."""

    user = django_user_model.objects.create_user(username="override-list")
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="capability.active",
        semantic_key="semantic.active",
        reason="Active decision",
        updated_by=user,
    )
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="capability.inactive",
        semantic_key="semantic.inactive",
        reason="Removed decision",
        is_active=False,
        updated_by=user,
    )

    overrides = DjangoSemanticGovernanceRepository().list_active_overrides()

    assert overrides == {"capability.active": "semantic.active"}


@pytest.mark.django_db
def test_repository_applies_set_and_remove_in_one_audited_batch(
    django_user_model,
) -> None:
    """One transaction updates current truth and appends ordered evidence."""

    user = django_user_model.objects.create_user(username="override-apply")
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="capability.remove",
        semantic_key="semantic.old_override",
        reason="Earlier decision",
        updated_by=user,
    )
    batch = SemanticCorrectionBatch(
        idempotency_key="semantic-repo-001",
        reason="Resolve two catalog groups",
        corrections=(
            SemanticCorrection("capability.set", "set", "semantic.new"),
            SemanticCorrection("capability.remove", "remove"),
        ),
    )
    snapshots = {
        "capability.set": SemanticValueSnapshot(
            capability_key="capability.set",
            collected_semantic_key="semantic.collected",
            effective_semantic_key="semantic.collected",
        ),
        "capability.remove": SemanticValueSnapshot(
            capability_key="capability.remove",
            collected_semantic_key="semantic.original",
            effective_semantic_key="semantic.old_override",
        ),
    }

    result = DjangoSemanticGovernanceRepository().apply_batch(
        batch,
        operator_id=user.pk,
        snapshots=snapshots,
    )

    assert result.replayed is False
    assert [entry.capability_key for entry in result.entries] == [
        "capability.set",
        "capability.remove",
    ]
    assert [entry.new_effective_value for entry in result.entries] == [
        "semantic.new",
        "semantic.original",
    ]
    assert DjangoSemanticGovernanceRepository().list_active_overrides() == {
        "capability.set": "semantic.new"
    }
    assert CapabilitySemanticAuditModel.objects.filter(
        batch_id=result.batch_id
    ).count() == 2


@pytest.mark.django_db
def test_repository_replays_same_idempotent_batch_without_new_writes(
    django_user_model,
) -> None:
    """A matching idempotent retry returns stored evidence exactly once."""

    user = django_user_model.objects.create_user(username="override-replay")
    batch = SemanticCorrectionBatch(
        "semantic-repo-replay",
        "Stable retry",
        (SemanticCorrection("capability.one", "set", "semantic.one"),),
    )
    snapshots = {
        "capability.one": SemanticValueSnapshot(
            "capability.one",
            "semantic.collected",
            "semantic.collected",
        )
    }
    repository = DjangoSemanticGovernanceRepository()
    first = repository.apply_batch(batch, operator_id=user.pk, snapshots=snapshots)
    second = repository.apply_batch(batch, operator_id=user.pk, snapshots=snapshots)

    assert second.replayed is True
    assert second.batch_id == first.batch_id
    assert second.entries == first.entries
    assert CapabilitySemanticAuditModel.objects.count() == 1


@pytest.mark.django_db
def test_repository_rejects_reused_idempotency_key_with_different_payload(
    django_user_model,
) -> None:
    """An idempotency key cannot authorize a different correction payload."""

    user = django_user_model.objects.create_user(username="override-conflict")
    repository = DjangoSemanticGovernanceRepository()
    snapshots = {
        "capability.one": SemanticValueSnapshot(
            "capability.one",
            "semantic.collected",
            "semantic.collected",
        )
    }
    repository.apply_batch(
        SemanticCorrectionBatch(
            "semantic-repo-conflict",
            "First reason",
            (SemanticCorrection("capability.one", "set", "semantic.one"),),
        ),
        operator_id=user.pk,
        snapshots=snapshots,
    )

    with pytest.raises(SemanticIdempotencyConflict):
        repository.apply_batch(
            SemanticCorrectionBatch(
                "semantic-repo-conflict",
                "Different reason",
                (SemanticCorrection("capability.one", "set", "semantic.one"),),
            ),
            operator_id=user.pk,
            snapshots=snapshots,
        )

    assert CapabilitySemanticAuditModel.objects.count() == 1


@pytest.mark.django_db
def test_repository_rolls_back_entire_batch_when_snapshot_is_missing(
    django_user_model,
) -> None:
    """Missing source evidence cannot leave a partial override or audit."""

    user = django_user_model.objects.create_user(username="override-rollback")
    batch = SemanticCorrectionBatch(
        "semantic-repo-rollback",
        "Incomplete evidence",
        (
            SemanticCorrection("capability.one", "set", "semantic.one"),
            SemanticCorrection("capability.two", "set", "semantic.two"),
        ),
    )
    snapshots = {
        "capability.one": SemanticValueSnapshot(
            "capability.one",
            "semantic.collected",
            "semantic.collected",
        )
    }

    with pytest.raises(ValueError, match="missing snapshot"):
        DjangoSemanticGovernanceRepository().apply_batch(
            batch,
            operator_id=user.pk,
            snapshots=snapshots,
        )

    assert CapabilitySemanticOverrideModel.objects.count() == 0
    assert CapabilitySemanticAuditModel.objects.count() == 0


@pytest.mark.django_db
def test_catalog_upsert_preserves_collected_and_effective_semantic_keys() -> None:
    """Catalog persistence retains source evidence beside the routed key."""

    capability = CapabilityDefinition(
        capability_key="mcp_tool.replay_events",
        source_type=SourceType.MCP_TOOL,
        source_ref="replay_events",
        name="replay_events",
        summary="Replay events",
        semantic_key="events.replay.events",
    )

    DjangoCapabilityRepository().bulk_upsert(
        [capability],
        collected_semantic_keys={
            "mcp_tool.replay_events": "legacy.mcp.replay_events"
        },
    )

    model = CapabilityCatalogModel.objects.get(
        capability_key="mcp_tool.replay_events"
    )
    assert model.collected_semantic_key == "legacy.mcp.replay_events"
    assert model.semantic_key == "events.replay.events"
