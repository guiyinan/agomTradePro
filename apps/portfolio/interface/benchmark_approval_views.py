"""Session-authenticated and CSRF-protected benchmark governance commands."""

import json
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from django.db import DatabaseError
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.portfolio.benchmark_execution_composition import (
    approve_benchmark,
    read_benchmark_submission_for_review,
    revoke_benchmark,
    submit_benchmark_approval,
)
from apps.portfolio.domain.benchmark_approval_history import (
    BenchmarkApprovalConflict,
    BenchmarkApprovalDenied,
    BenchmarkApprovalUnavailable,
)
from core.exceptions import AuthenticationError, ExternalServiceError


class _ClosedInput(serializers.Serializer[dict[str, object]]):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject additional identity, permission, valuation or date fields."""
        if not isinstance(data, Mapping) or set(data) != set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Unexpected or missing selector fields."]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class _SubmitInput(_ClosedInput):
    request_id = serializers.UUIDField()
    valuation_id = serializers.UUIDField()
    valuation_version = serializers.IntegerField(min_value=1)


class _ReviewInput(_ClosedInput):
    expected_content_hash = serializers.RegexField(regex=r"^[0-9a-f]{64}$", trim_whitespace=False)


class BenchmarkApprovalCommandView(APIView):
    """Accept only immutable selectors from a signed-in human operator."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    action = "submit"

    def post(self, request: Request, request_id: UUID | None = None) -> Response:
        """Submit, independently approve or withdraw an exact benchmark receipt."""
        serializer = (
            _SubmitInput(data=request.data)
            if self.action == "submit"
            else _ReviewInput(data=request.data)
        )
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            if self.action == "submit":
                event = submit_benchmark_approval(
                    request=request,
                    request_id=values["request_id"],
                    valuation_id=values["valuation_id"],
                    valuation_version=values["valuation_version"],
                )
            elif request_id is None:
                raise BenchmarkApprovalConflict("benchmark_request_id_required")
            elif self.action == "approve":
                event = approve_benchmark(
                    request=request,
                    request_id=request_id,
                    expected_submission_hash=values["expected_content_hash"],
                )
            elif self.action == "revoke":
                event = revoke_benchmark(
                    request=request,
                    request_id=request_id,
                    expected_approval_hash=values["expected_content_hash"],
                )
            else:
                raise BenchmarkApprovalConflict("unknown_benchmark_action")
        except AuthenticationError:
            return Response(
                {"detail": "Current authenticated session required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except (BenchmarkApprovalDenied, BenchmarkApprovalUnavailable):
            return Response(
                {"detail": "Scoped benchmark input unavailable."}, status=status.HTTP_404_NOT_FOUND
            )
        except BenchmarkApprovalConflict as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        except (DatabaseError, ExternalServiceError, ValueError):
            return Response(
                {"detail": "Benchmark sources unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {
                "request_id": str(event.request_id),
                "version": event.sequence,
                "content_hash": event.content_hash,
                "action": event.action,
                "valid_until": event.valid_until.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class BenchmarkApprovalReviewView(APIView):
    """Show immutable source selectors to an authenticated, scoped benchmark reviewer."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, request_id: UUID) -> Response:
        """Display the exact source commitment needed for an informed second-person approval."""
        try:
            event, stage = read_benchmark_submission_for_review(
                request=request, request_id=request_id
            )
        except AuthenticationError:
            return Response(
                {"detail": "Current authenticated session required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except (BenchmarkApprovalDenied, BenchmarkApprovalUnavailable):
            return Response(
                {"detail": "Scoped benchmark input unavailable."}, status=status.HTTP_404_NOT_FOUND
            )
        except (DatabaseError, ExternalServiceError, ValueError):
            return Response(
                {"detail": "Benchmark sources unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {
                "request_id": str(event.request_id),
                "submission_hash": event.content_hash,
                "state": stage,
                "source": json.loads(event.source_manifest),
                "valid_until": event.valid_until.isoformat(),
            }
        )
