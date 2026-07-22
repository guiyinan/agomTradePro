"""Type-sensitive public field contracts for Audit serializers."""

from apps.audit.interface.serializers import (
    DecisionTraceSummarySerializer,
    ExportOperationLogsSerializer,
    OperationLogIngestSerializer,
    OperationLogQuerySerializer,
    OperationLogSerializer,
)


def test_reserved_audit_fields_remain_registered_under_public_names() -> None:
    """Dynamic registration must preserve the established source/data keys."""

    assert "source" in OperationLogSerializer().fields
    assert "source" in OperationLogQuerySerializer().fields
    assert "source" in OperationLogIngestSerializer().fields
    assert "source" in DecisionTraceSummarySerializer().fields
    assert "data" in ExportOperationLogsSerializer().fields


def test_operation_log_source_validation_and_default_are_preserved() -> None:
    """Query and ingest serializers retain source validation semantics."""

    query = OperationLogQuerySerializer(data={"source": "SDK"})
    ingest = OperationLogIngestSerializer(data={"request_id": "request-1"})

    assert query.is_valid(), query.errors
    assert ingest.is_valid(), ingest.errors
    assert query.validated_data["source"] == "SDK"
    assert ingest.validated_data["source"] == "MCP"


def test_export_payload_keeps_data_field() -> None:
    """The export response still emits its public data field."""

    payload = {"success": True, "data": "csv-content", "row_count": 1}

    assert ExportOperationLogsSerializer(payload).data["data"] == "csv-content"
