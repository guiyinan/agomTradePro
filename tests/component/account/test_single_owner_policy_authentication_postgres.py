"""Real Session/CSRF eligibility and rollback for the policy authentication boundary."""

import base64
import hashlib
import json

from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import path
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.owner_policy_authorization_source import (
    decode_owner_policy_authorization_source,
)
from apps.account.application.single_owner_policy_publication_settings import (
    decode_single_owner_policy_publication_settings,
)
from apps.account.infrastructure.single_owner_policy_authentication import (
    authenticated_single_owner_policy_transaction,
)
from core.exceptions import AuthenticationError
from tests.component.account.test_account_actor_authority_raw_source_publisher_http import (
    _csrf_bootstrap,
    _csrf_token,
    _use_evid06_http_database,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)


class _EligibilityView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    alias = ""
    source = None
    publication_settings = None

    def post(self, request):
        def reauthenticate():
            result = request.successful_authenticator.authenticate(request)
            if result is None:
                raise AuthenticationError("Session unavailable")
            return result

        try:
            with authenticated_single_owner_policy_transaction(
                using=self.alias,
                authenticated_user=request.user,
                session=request._request.session,
                reauthenticate=reauthenticate,
                settings=self.publication_settings,
                source=self.source,
            ) as requester:
                if request.data.get("revoke"):
                    User.objects.using(self.alias).filter(pk=requester.user_id).update(
                        is_staff=False
                    )
            return Response({"eligible": True})
        except AuthenticationError:
            return Response({"eligible": False}, status=403)


urlpatterns = [path("csrf/", _csrf_bootstrap), path("eligibility/", _EligibilityView.as_view())]


def test_real_session_csrf_and_final_owner_recheck(evid06_alias, monkeypatch):
    user, _ = _new_user(evid06_alias)
    raw = json.dumps(
        {
            "schema": "sprint-owner-account-authorization.v1",
            "recorded_at": "2020-01-01T00:00:00+00:00",
            "source": {
                "kind": "interactive_user_declaration",
                "account_binding_answer": "Use fixture owner",
            },
            "owner_account": {
                "username": user.username,
                "user_id": user.pk,
                "role": "project_owner_and_human_approver",
                "binding_basis": "explicit_user_designation",
            },
        }
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    source = decode_owner_policy_authorization_source(
        {
            "schema_version": "account.single_owner_policy.authorization_source.v1",
            "source_id": "test-source",
            "source_version": "v1",
            "content_hash": digest,
            "document_base64": base64.b64encode(raw).decode(),
        }
    )
    settings = decode_single_owner_policy_publication_settings(
        {
            "schema_version": "account.single_owner_policy.publication_settings.v1",
            "owner_username": user.username,
            "tenant_id": "tenant",
            "owner_id": "owner",
            "authorization_source_id": "test-source",
            "authorization_source_version": "v1",
            "authorization_content_hash": digest,
            "ttl_seconds": 300,
        }
    )
    monkeypatch.setattr(_EligibilityView, "alias", evid06_alias)
    monkeypatch.setattr(_EligibilityView, "source", source)
    monkeypatch.setattr(_EligibilityView, "publication_settings", settings)
    with _use_evid06_http_database(evid06_alias), override_settings(ROOT_URLCONF=__name__):
        client = Client(enforce_csrf_checks=True)
        assert client.login(username=user.username, password="evid06-test-password")
        assert (
            client.post("/eligibility/", data="{}", content_type="application/json").status_code
            == 403
        )
        csrf = _csrf_token(client)
        result = client.post(
            "/eligibility/", data="{}", content_type="application/json", HTTP_X_CSRFTOKEN=csrf
        )
        assert result.status_code == 200, result.content
        assert result["Content-Type"].startswith("application/json")
        revoked = client.post(
            "/eligibility/",
            data='{"revoke": true}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert revoked.status_code == 403, revoked.content
        user.refresh_from_db(using=evid06_alias)
        assert user.is_staff is True, "final eligibility failure must roll back the mutation"
        client.logout()
        assert (
            client.post(
                "/eligibility/", data="{}", content_type="application/json", HTTP_X_CSRFTOKEN=csrf
            ).status_code
            == 403
        )
