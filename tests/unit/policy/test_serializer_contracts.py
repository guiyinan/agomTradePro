"""Type-sensitive public field contracts for Policy serializers."""

from apps.policy.domain.entities import GateLevel, PolicyLevel, WorkbenchSummary
from apps.policy.interface.serializers import (
    PolicyCreateResponseSerializer,
    PolicyLevelField,
    RSSFetchLogSerializer,
    RSSFetchOutputSerializer,
    WorkbenchFetchOutputSerializer,
    WorkbenchSummarySerializer,
)


def test_policy_level_field_round_trips_domain_enum() -> None:
    """The custom level field keeps the enum/string API boundary explicit."""

    field = PolicyLevelField()

    assert field.run_validation("P2") is PolicyLevel.P2
    assert field.to_representation(PolicyLevel.P3) == "P3"


def test_reserved_policy_fields_remain_registered_under_public_names() -> None:
    """Dynamic fields retain the established errors/source response keys."""

    assert "errors" in PolicyCreateResponseSerializer().fields
    assert "source" in RSSFetchLogSerializer().fields
    assert "errors" in RSSFetchOutputSerializer().fields
    assert "errors" in WorkbenchFetchOutputSerializer().fields


def test_policy_error_fields_remain_in_serialized_payloads() -> None:
    """Error lists keep their required/optional response behavior."""

    create_payload = {
        "success": False,
        "event": None,
        "errors": ["invalid"],
        "alert_triggered": False,
    }
    fetch_payload = {
        "success": False,
        "sources_processed": 1,
        "total_items": 0,
        "new_policy_events": 0,
        "errors": ["timeout"],
        "details": [],
    }

    assert PolicyCreateResponseSerializer(create_payload).data["errors"] == ["invalid"]
    assert RSSFetchOutputSerializer(fetch_payload).data["errors"] == ["timeout"]


def test_workbench_summary_serializes_typed_enum_fields() -> None:
    """SerializerMethodFields read the concrete WorkbenchSummary contract."""

    summary = WorkbenchSummary(
        policy_level=PolicyLevel.P2,
        policy_level_event="政策事件",
        global_heat_score=80.0,
        global_sentiment_score=-0.7,
        global_gate_level=GateLevel.L2,
        pending_review_count=2,
        sla_exceeded_count=1,
        effective_today_count=3,
    )

    payload = WorkbenchSummarySerializer(summary).data
    assert payload["policy_level"] == "P2"
    assert payload["global_gate_level"] == "L2"
