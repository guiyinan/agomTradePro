from django.contrib import admin

from apps.alpha_trigger.interface.admin import AlphaCandidateAdmin, AlphaTriggerAdmin
from apps.alpha_trigger.models import AlphaCandidateModel, AlphaTriggerModel
from apps.beta_gate.interface.admin import VisibilityUniverseSnapshotAdmin
from apps.beta_gate.models import VisibilityUniverseSnapshotModel
from apps.events.event_store import EventSnapshotModel, StoredEventModel
from apps.events.interface.admin import EventSnapshotAdmin, StoredEventActionsAdmin


def test_events_admin_uses_supported_metadata_and_registration() -> None:
    assert StoredEventActionsAdmin.payload_preview.short_description == "Payload"
    assert StoredEventActionsAdmin.cleanup_old_events.short_description == "删除选中的事件"
    assert isinstance(admin.site._registry[StoredEventModel], StoredEventActionsAdmin)
    assert isinstance(admin.site._registry[EventSnapshotModel], EventSnapshotAdmin)


def test_alpha_trigger_admin_uses_supported_metadata_and_registration() -> None:
    assert AlphaTriggerAdmin.strength_display.short_description == "强度"
    assert AlphaCandidateAdmin.entry_zone_display.short_description == "入场区域"
    assert isinstance(admin.site._registry[AlphaTriggerModel], AlphaTriggerAdmin)
    assert isinstance(admin.site._registry[AlphaCandidateModel], AlphaCandidateAdmin)


def test_beta_gate_admin_uses_supported_metadata_and_registration() -> None:
    assert VisibilityUniverseSnapshotAdmin.visible_categories_count.short_description == (
        "可见类别数"
    )
    assert VisibilityUniverseSnapshotAdmin.hard_exclusions_display.short_description == (
        "硬排除列表"
    )
    assert isinstance(
        admin.site._registry[VisibilityUniverseSnapshotModel],
        VisibilityUniverseSnapshotAdmin,
    )
