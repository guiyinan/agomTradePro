"""Tests for the authenticated Account actor-authority raw publisher boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    AccountActorAuthorityRawSourcePublicationReceiptV3,
    AccountActorAuthorityRawSourceSelectorV3,
    AccountActorAuthorityRawSourceV3Unavailable,
    PublishAccountActorAuthorityRawSourceV3,
    PublishAccountActorAuthorityRawSourceV3Command,
)
from apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 import (
    DjangoAccountActorAuthorityRawSourcePublisherGatewayV3,
)
from apps.account.interface.account_actor_authority_raw_source_api_views import (
    AccountActorAuthorityRawSourcePublishRequestSerializer,
    AccountActorAuthorityRawSourcePublishView,
)


def _receipt() -> AccountActorAuthorityRawSourcePublicationReceiptV3:
    """Build a secret-free receipt for application-boundary tests."""

    digest = "a" * 64
    selector = AccountActorAuthorityRawSourceSelectorV3("source", "v1", digest)
    return AccountActorAuthorityRawSourcePublicationReceiptV3(
        authentication_context=selector,
        user=selector,
        rbac=selector,
        actor=selector,
        user_id=7,
        principal_id="principal-7",
        observed_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 9, 10, 8, 5, tzinfo=UTC),
    )


def test_publisher_delegates_only_the_empty_typed_command() -> None:
    """The public use case accepts no client authority or runtime facts."""

    gateway = Mock()
    gateway.publish.return_value = _receipt()
    publisher = PublishAccountActorAuthorityRawSourceV3(gateway)

    result = publisher.execute(PublishAccountActorAuthorityRawSourceV3Command())

    assert result == _receipt()
    gateway.publish.assert_called_once_with()


def test_publisher_rejects_a_command_with_client_supplied_facts() -> None:
    """The use case must reject substituted command objects before persistence."""

    gateway = Mock()
    publisher = PublishAccountActorAuthorityRawSourceV3(gateway)

    with pytest.raises(TypeError):
        publisher.execute(Mock())

    gateway.publish.assert_not_called()


def test_publish_request_serializer_rejects_all_client_fields() -> None:
    """The HTTP body is an explicit empty object and cannot carry authority facts."""

    serializer = AccountActorAuthorityRawSourcePublishRequestSerializer(
        data={"user_id": 1, "rbac_role": "admin", "ttl_seconds": 300}
    )

    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


def test_publish_request_serializer_accepts_only_empty_object() -> None:
    """The HTTP boundary accepts the explicit no-input request."""

    serializer = AccountActorAuthorityRawSourcePublishRequestSerializer(data={})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {}


def test_publish_view_is_session_only_and_post_only() -> None:
    """The write endpoint must be CSRF-enforced by DRF SessionAuthentication."""

    assert AccountActorAuthorityRawSourcePublishView.authentication_classes == [
        SessionAuthentication
    ]
    assert AccountActorAuthorityRawSourcePublishView.permission_classes == [IsAuthenticated]
    assert AccountActorAuthorityRawSourcePublishView.http_method_names == ["post", "options"]


def test_receipt_contains_no_scope_or_approval_claims() -> None:
    """The raw-source receipt is limited to exact attestation selectors."""

    payload = _receipt().to_payload()

    assert payload["outcome"] == "success"
    assert payload["status"] == "attestation_only"
    assert "scope" not in payload
    assert "approval" not in payload
    assert "password" not in payload
    assert "session_key" not in payload


def test_missing_database_alias_fails_before_session_access() -> None:
    """A missing server alias has the same unavailable boundary as an invalid backend."""

    session = Mock()
    gateway = DjangoAccountActorAuthorityRawSourcePublisherGatewayV3(
        authenticated_user=Mock(), session=session, using="evid06_missing_publisher_alias"
    )

    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable, match="database alias"):
        gateway.publish()

    session.get.assert_not_called()
