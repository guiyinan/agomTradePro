"""Authenticated staff-only exact reads for canonical Research evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.research.domain.evidence_contracts import (
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)
from apps.research.evidence_composition import make_evidence_read_facade
from apps.research.interface.evidence_serializers import (
    EnvelopeExactReadSerializer,
    OperatorSpecExactReadSerializer,
    TrackRecordExactReadSerializer,
)


class _StaffExactEvidenceReadView(APIView):
    """Shared deny-by-default policy for canonical evidence detail reads."""

    permission_classes: list[type[BasePermission]] = [IsAuthenticated, IsAdminUser]
    http_method_names: list[str] = ["get", "head", "options"]


class EvidenceOperatorSpecDetailView(_StaffExactEvidenceReadView):
    """Read an exact content-addressed Operator Spec at a PIT cutoff."""

    def get(self, request: Request, operator_id: str, operator_version: str) -> Response:
        """Return the requested Operator Spec or a non-enumerating 404."""

        serializer = OperatorSpecExactReadSerializer(
            data=_selector_payload(
                request,
                operator_id=operator_id,
                operator_version=operator_version,
            )
        )
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        spec = make_evidence_read_facade().get_operator_spec(
            operator_id=cast(str, values["operator_id"]),
            operator_version=cast(str, values["operator_version"]),
            expected_content_hash=cast(str, values["expected_content_hash"]),
            as_of=cast(datetime, values["as_of"]),
        )
        if spec is None:
            raise NotFound("Exact evidence was not found at the requested cutoff.")
        return Response(_operator_payload(spec))


class EvidenceTrackRecordDetailView(_StaffExactEvidenceReadView):
    """Read an exact content-addressed Track Record at a PIT cutoff."""

    def get(self, request: Request, snapshot_id: str, snapshot_version: str) -> Response:
        """Return the requested Track Record or a non-enumerating 404."""

        serializer = TrackRecordExactReadSerializer(
            data=_selector_payload(
                request,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
        )
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        snapshot = make_evidence_read_facade().get_track_record(
            snapshot_id=cast(str, values["snapshot_id"]),
            snapshot_version=cast(str, values["snapshot_version"]),
            expected_content_hash=cast(str, values["expected_content_hash"]),
            as_of=cast(datetime, values["as_of"]),
        )
        if snapshot is None:
            raise NotFound("Exact evidence was not found at the requested cutoff.")
        return Response(_track_record_payload(snapshot))


class EvidenceEnvelopeDetailView(_StaffExactEvidenceReadView):
    """Read an owner-qualified exact Envelope at a PIT cutoff."""

    def get(
        self,
        request: Request,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
    ) -> Response:
        """Return the requested Envelope or a non-enumerating 404."""

        serializer = EnvelopeExactReadSerializer(
            data=_selector_payload(
                request,
                output_owner=output_owner,
                output_artifact_type=output_artifact_type,
                output_artifact_id=output_artifact_id,
                output_artifact_version=output_artifact_version,
            )
        )
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        envelope = make_evidence_read_facade().get_envelope(
            output_owner=cast(str, values["output_owner"]),
            output_artifact_type=cast(str, values["output_artifact_type"]),
            output_artifact_id=cast(str, values["output_artifact_id"]),
            output_artifact_version=cast(str, values["output_artifact_version"]),
            expected_content_hash=cast(str, values["expected_content_hash"]),
            as_of=cast(datetime, values["as_of"]),
        )
        if envelope is None:
            raise NotFound("Exact evidence was not found at the requested cutoff.")
        return Response(_envelope_payload(envelope))


def _selector_payload(request: Request, **identity: str) -> dict[str, object]:
    """Merge path identity and query selectors while rejecting duplicates."""

    payload: dict[str, object] = dict(identity)
    for key, values in request.query_params.lists():
        if key in payload or len(values) != 1:
            payload[key] = values
        else:
            payload[key] = values[0]
    return payload


def _operator_payload(spec: EvidenceOperatorSpec) -> dict[str, object]:
    """Serialize an Operator Spec without changing canonical value semantics."""

    return {
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
        "research_family": spec.research_family,
        "output_artifact_type": spec.output_artifact_type,
        "claim_kind": spec.claim_kind.value,
        "method_kind": spec.method_kind.value,
        "required_input_roles": list(spec.required_input_roles),
        "dependency_flags": sorted(item.value for item in spec.dependency_flags),
        "maximum_permission": spec.maximum_permission.value,
        "requires_track_record": spec.requires_track_record,
        "activated_at": _utc_text(spec.activated_at),
        "valid_until": _utc_text(spec.valid_until),
        "content_hash": spec.content_hash,
    }


def _track_record_payload(snapshot: TrackRecordSnapshot) -> dict[str, object]:
    """Serialize exact Track Record evidence without decimal precision loss."""

    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "artifact": snapshot.artifact.to_payload(),
        "target": snapshot.target,
        "horizon": snapshot.horizon,
        "sample_policy_id": snapshot.sample_policy_id,
        "sample_policy_version": snapshot.sample_policy_version,
        "evaluated_at": _utc_text(snapshot.evaluated_at),
        "valid_until": _utc_text(snapshot.valid_until),
        "eligible": snapshot.eligible,
        "resolved": snapshot.resolved,
        "unresolved": snapshot.unresolved,
        "censored": snapshot.censored,
        "invalidated": snapshot.invalidated,
        "n_eff": str(snapshot.n_eff),
        "coverage": str(snapshot.coverage),
        "market_regimes": list(snapshot.market_regimes),
        "primary_metric_code": snapshot.primary_metric_code,
        "primary_metric_unit": snapshot.primary_metric_unit,
        "metric_direction": (
            snapshot.metric_direction.value if snapshot.metric_direction is not None else None
        ),
        "primary_metric_value": _optional_decimal(snapshot.primary_metric_value),
        "benchmark_metric_value": _optional_decimal(snapshot.benchmark_metric_value),
        "skill_delta": _optional_decimal(snapshot.skill_delta),
        "confidence_interval_low": _optional_decimal(snapshot.confidence_interval_low),
        "confidence_interval_high": _optional_decimal(snapshot.confidence_interval_high),
        "drift_detected": snapshot.drift_detected,
        "promotion_ref": snapshot.promotion_ref.to_payload(),
        "outcome_refs": [item.to_payload() for item in snapshot.outcome_refs],
        "content_hash": snapshot.content_hash,
    }


def _envelope_payload(envelope: EvidenceEnvelope) -> dict[str, object]:
    """Serialize an exact Envelope and its fail-closed compatibility flags."""

    return {
        "output_artifact": envelope.output_artifact.to_payload(),
        "operator_spec_ref": envelope.operator_spec_ref.to_payload(),
        "claim_kind": envelope.claim_kind.value,
        "method_kind": envelope.method_kind.value,
        "research_family": envelope.research_family,
        "governance_state": envelope.governance_state.value,
        "permission": envelope.permission.value,
        "lineage": [item.to_payload() for item in envelope.lineage],
        "dependency_flags": sorted(item.value for item in envelope.dependency_flags),
        "track_record_ref": (
            envelope.track_record_ref.to_payload()
            if envelope.track_record_ref is not None
            else None
        ),
        "blockers": [item.value for item in envelope.blockers],
        "evaluated_at": _utc_text(envelope.evaluated_at),
        "valid_until": _utc_text(envelope.valid_until),
        "content_hash": envelope.content_hash,
        "must_not_use_for_decision": envelope.must_not_use_for_decision,
        "must_not_execute": envelope.must_not_execute,
    }


def _optional_decimal(value: Decimal | None) -> str | None:
    """Preserve an optional canonical Decimal as text at the HTTP boundary."""

    return None if value is None else str(value)


def _utc_text(value: datetime) -> str:
    """Return one stable UTC timestamp without replacing source time."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "EvidenceEnvelopeDetailView",
    "EvidenceOperatorSpecDetailView",
    "EvidenceTrackRecordDetailView",
]
