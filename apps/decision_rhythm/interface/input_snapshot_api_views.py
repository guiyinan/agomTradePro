"""HTTP endpoints for canonical decision input snapshots."""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.decision_rhythm.application.input_snapshot_use_cases import (
    BuildDecisionInputSnapshotRequest,
)
from apps.decision_rhythm.composition import (
    make_build_decision_input_snapshot_use_case,
    make_get_decision_input_snapshot_use_case,
)
from apps.decision_rhythm.domain.input_snapshot import DecisionInputSnapshot


class DecisionInputSnapshotSerializer(serializers.Serializer[dict[str, object]]):
    """Validate snapshot creation payloads."""

    as_of_time = serializers.DateTimeField()
    pit_manifest_id = serializers.CharField(max_length=64)
    components = serializers.DictField(child=serializers.DictField(), allow_empty=False)
    portfolio_snapshot_id = serializers.CharField(max_length=64)
    config_version = serializers.CharField(max_length=64)
    strategy_version = serializers.CharField(max_length=64)
    prompt_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    freshness = serializers.DictField(required=False, default=dict)
    quality = serializers.DictField(required=False, default=dict)
    must_not_use = serializers.BooleanField(required=False, default=False)
    missing_components = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    creation_reason = serializers.CharField(required=False, allow_blank=True)
    correlation_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    caller = serializers.CharField(max_length=128, required=False, allow_blank=True)
    schema_version = serializers.CharField(max_length=16, required=False, default="v1")


def _serialize(snapshot: DecisionInputSnapshot) -> dict[str, object]:
    return {
        **snapshot.canonical_payload(),
        "snapshot_id": snapshot.snapshot_id,
        "state_hash": snapshot.state_hash,
        "creation_reason": snapshot.creation_reason,
        "correlation_id": snapshot.correlation_id,
        "caller": snapshot.caller,
    }


class DecisionInputSnapshotListCreateView(APIView):
    """Freeze a canonical decision input package."""

    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = DecisionInputSnapshotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["missing_components"] = tuple(data.get("missing_components", []))
        snapshot = make_build_decision_input_snapshot_use_case().execute(
            BuildDecisionInputSnapshotRequest(**data)
        )
        return Response(_serialize(snapshot), status=status.HTTP_201_CREATED)


class DecisionInputSnapshotDetailView(APIView):
    """Return one frozen decision package."""

    permission_classes = [IsAuthenticated]

    def get(self, request, snapshot_id: str):  # type: ignore[no-untyped-def]
        snapshot = make_get_decision_input_snapshot_use_case().execute(snapshot_id)
        if snapshot is None:
            return Response({"detail": "Snapshot not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(snapshot))

