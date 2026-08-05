"""Authenticated read-only API views for governed allocation policies."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.strategy.application.allocation_policy import (
    get_active_allocation_policy,
    get_allocation_policy_version,
    list_allocation_policy_versions,
)
from apps.strategy.domain.allocation_matrix import AllocationPolicyUnavailableError
from apps.strategy.interface.allocation_policy_serializers import (
    AllocationPolicyQuerySerializer,
    allocation_policy_detail,
    allocation_policy_summary,
    validated_policy_key,
)


class AllocationPolicyActiveView(APIView):
    """Return the complete active allocation policy to authenticated callers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Read the active policy without mutating governance state."""

        policy_key = _validated_query_policy_key(request)
        try:
            policy = get_active_allocation_policy(policy_key)
        except AllocationPolicyUnavailableError as exc:
            return _unavailable_response(exc, not_found=True)
        except ValueError as exc:
            return _unavailable_response(exc, not_found=False)
        return Response(allocation_policy_detail(policy))


class AllocationPolicyVersionListView(APIView):
    """List allocation-policy version metadata for authenticated callers."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return newest-first immutable version summaries."""

        policy_key = _validated_query_policy_key(request)
        try:
            versions = list_allocation_policy_versions(policy_key)
        except ValueError as exc:
            return _unavailable_response(exc, not_found=False)
        return Response(
            {
                "policy_key": policy_key,
                "count": len(versions),
                "results": [allocation_policy_summary(policy) for policy in versions],
            }
        )


class AllocationPolicyVersionDetailView(APIView):
    """Return one immutable allocation-policy version by number."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, version: int) -> Response:
        """Read a specific version without treating it as active implicitly."""

        policy_key = _validated_query_policy_key(request)
        if version <= 0:
            return Response(
                {"version": ["Ensure this value is greater than or equal to 1."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            policy = get_allocation_policy_version(version, policy_key)
        except AllocationPolicyUnavailableError as exc:
            return _unavailable_response(exc, not_found=True)
        except ValueError as exc:
            return _unavailable_response(exc, not_found=False)
        return Response(allocation_policy_detail(policy))


def _validated_query_policy_key(request: Request) -> str:
    """Validate the complete query mapping before calling Application."""

    serializer = AllocationPolicyQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return validated_policy_key(serializer)


def _unavailable_response(exc: ValueError, *, not_found: bool) -> Response:
    """Return a stable fail-closed envelope for missing or corrupt policy data."""

    code = "allocation_policy_not_found" if not_found else "allocation_policy_unavailable"
    response_status = (
        status.HTTP_404_NOT_FOUND if not_found else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return Response(
        {
            "error": {"code": code, "message": str(exc)},
            "must_not_use_for_decision": True,
        },
        status=response_status,
    )
