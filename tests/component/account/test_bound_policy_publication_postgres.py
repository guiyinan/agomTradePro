"""Actual creation, Session authentication and policy ledger through Core composition."""

import base64
import hashlib
import json

from django.contrib.auth.models import User
from django.db import connections
from django.test import override_settings
from django.urls import path
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from core.exceptions import AgomTradeProException
from core.integration import config_center_runtime
from core.integration.bound_single_owner_policy_publication import (
    PublishBoundSingleOwnerPolicyCommand,
    publish_bound_single_owner_policy,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_http import (
    _logged_in_client,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    _post,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    creation_http_alias as creation_http_alias,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    urlpatterns as creation_urls,
)

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)


class _PublishView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    alias = ""

    def post(self, request):
        try:
            result = publish_bound_single_owner_policy(
                request=request,
                command=PublishBoundSingleOwnerPolicyCommand(
                    idempotency_key=request.headers["Idempotency-Key"],
                    **request.data,
                ),
                environment="test",
                using=self.alias,
            )
            return Response(result.to_payload())
        except (
            AgomTradeProException,
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentUnavailable,
        ):
            return Response({"blocked": True}, status=409)


urlpatterns = [*creation_urls, path("test/policy/", _PublishView.as_view())]


def _values(user):
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
    return {
        "account.single_owner_policy.authorization_source": {
            "schema_version": "account.single_owner_policy.authorization_source.v1",
            "source_id": "fixture",
            "source_version": "v1",
            "content_hash": digest,
            "document_base64": base64.b64encode(raw).decode(),
        },
        "account.single_owner_policy.publication_settings": {
            "schema_version": "account.single_owner_policy.publication_settings.v1",
            "owner_username": user.username,
            "tenant_id": "fixture-tenant",
            "owner_id": "fixture-owner",
            "authorization_source_id": "fixture",
            "authorization_source_version": "v1",
            "authorization_content_hash": digest,
            "ttl_seconds": 300,
        },
    }


def _publish(client, csrf, binding, key="first-policy"):
    return client.post(
        "/test/policy/",
        {
            "binding_id": binding.binding_id,
            "binding_version": binding.binding_version,
            "binding_content_hash": binding.content_hash,
        },
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_real_bound_policy_replay_conflict_and_final_rechecks(creation_http_alias, monkeypatch):
    alias = creation_http_alias
    with connections[alias].schema_editor() as editor:
        editor.create_model(SingleOwnerAuthorityPolicyV1Model)
    try:
        monkeypatch.setattr(_PublishView, "alias", alias)
        with override_settings(ROOT_URLCONF=__name__):
            client, user, csrf = _logged_in_client(alias)
            assert _post(client, csrf).status_code == 201
            first_binding = CanonicalAccountCreationBindingV2Model.objects.using(alias).get()
            values = _values(user)

            def read(*, environment, definition_key):
                assert environment == "test"
                return values.get(definition_key)

            monkeypatch.setattr(config_center_runtime, "get_active_runtime_value", read)
            first = _publish(client, csrf, first_binding)
            assert first.status_code == 200, first.content
            assert first["Content-Type"].startswith("application/json")
            replay = _publish(client, csrf, first_binding)
            assert replay.status_code == 200, replay.content
            assert replay.json() == first.json()
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 1
            assert _publish(client, csrf, first_binding, "different-key").status_code == 409
            assert (
                _post(client, csrf, key="second-create", account_name="Second").status_code == 201
            )
            second_binding = (
                CanonicalAccountCreationBindingV2Model.objects.using(alias)
                .exclude(pk=first_binding.pk)
                .get()
            )
            assert _publish(client, csrf, second_binding).status_code == 409
            original_append = DjangoSingleOwnerAuthorityPolicyV1Repository.append

            def revoke_after_append(repository, **kwargs):
                result = original_append(repository, **kwargs)
                User.objects.using(alias).filter(pk=user.pk).update(is_staff=False)
                return result

            monkeypatch.setattr(
                DjangoSingleOwnerAuthorityPolicyV1Repository, "append", revoke_after_append
            )
            assert _publish(client, csrf, second_binding, "revoked-request").status_code == 409
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 1
            user.refresh_from_db(using=alias)
            assert user.is_staff is True

            def change_source_after_append(repository, **kwargs):
                result = original_append(repository, **kwargs)
                values.pop("account.single_owner_policy.authorization_source")
                return result

            monkeypatch.setattr(
                DjangoSingleOwnerAuthorityPolicyV1Repository, "append", change_source_after_append
            )
            assert _publish(client, csrf, second_binding, "changed-source").status_code == 409
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 1
    finally:
        with connections[alias].schema_editor() as editor:
            editor.delete_model(SingleOwnerAuthorityPolicyV1Model)
