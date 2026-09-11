"""Session-only JSON entry point for server-bound policy publication."""

import os
from typing import cast

from django.db import DEFAULT_DB_ALIAS
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
)
from core.exceptions import DuplicateResourceError, ExternalServiceError
from core.integration.bound_single_owner_policy_publication import (
    PublishBoundSingleOwnerPolicyCommand,
    publish_bound_single_owner_policy,
)

_FIELDS = frozenset({"binding_id", "binding_version", "binding_content_hash"})


class SingleOwnerPolicyPublishRequestSerializer(serializers.Serializer[dict[str, str]]):
    """Reject all client identity, authority and scope fields before Core calls."""

    binding_id = serializers.RegexField(r"\A[^\s]+\Z", max_length=192, trim_whitespace=False)
    binding_version = serializers.RegexField(r"\A[^\s]+\Z", max_length=192, trim_whitespace=False)
    binding_content_hash = serializers.RegexField(r"\A[0-9a-f]{64}\Z", trim_whitespace=False)

    def to_internal_value(self, data: object) -> dict[str, str]:
        """Require an exact JSON object containing only string selector values."""
        if type(data) is not dict or set(data) != _FIELDS:
            raise serializers.ValidationError(
                {"non_field_errors": ["Provide exactly the three account binding fields."]}
            )
        if any(type(value) is not str for value in data.values()):
            raise serializers.ValidationError(
                {"non_field_errors": ["Account binding selectors must be strings."]}
            )
        return cast(dict[str, str], super().to_internal_value(data))


class SingleOwnerPolicyPublishView(APIView):
    """Validate transport input and delegate the authenticated publication use case."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    http_method_names = ["post", "options"]

    def post(self, request: Request) -> Response:
        """Publish or replay one policy without accepting client authority facts."""
        serializer = SingleOwnerPolicyPublishRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            command = PublishBoundSingleOwnerPolicyCommand(
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                **serializer.validated_data,
            )
        except (TypeError, ValueError) as error:
            raise serializers.ValidationError(
                {
                    "Idempotency-Key": "Provide a non-empty canonical request key of at most 192 characters."
                }
            ) from error
        environment = (
            "production"
            if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".production")
            else "development"
        )
        try:
            policy = publish_bound_single_owner_policy(
                request=request, command=command, environment=environment, using=DEFAULT_DB_ALIAS
            )
        except (AccountOwnerAssignmentConflict, CanonicalAccountCreationBindingV2Conflict) as error:
            raise DuplicateResourceError(
                "Policy publication conflicts with existing evidence"
            ) from error
        except (
            AccountOwnerAssignmentUnavailable,
            CanonicalAccountCreationBindingV2Unavailable,
            AccountOwnerAssignmentCorruption,
            CanonicalAccountCreationBindingV2Corruption,
        ) as error:
            raise ExternalServiceError(
                "Policy publication evidence is unavailable or invalid"
            ) from error
        return Response({"policy": policy.to_payload(), "authority_granted": False})
