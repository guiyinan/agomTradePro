"""Real production API transport over Session, creation bindings and policy storage."""

from django.db import connections
from django.test import override_settings
from django.urls import path

from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.interface import single_owner_policy_api_views as api
from core.integration import config_center_runtime
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
from tests.component.account.test_bound_policy_publication_postgres import _values

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)

URL = "/api/account/authority/policy/publish/"
urlpatterns = [*creation_urls, path(URL.lstrip("/"), api.SingleOwnerPolicyPublishView.as_view())]


def test_real_api_json_replay_and_input_contracts(creation_http_alias, monkeypatch):
    alias = creation_http_alias
    original = api.publish_bound_single_owner_policy

    def publish_on_test_alias(*, request, command, environment, using):
        assert using == "default"
        assert environment in {"development", "production"}
        return original(request=request, command=command, using=alias, environment="test")

    monkeypatch.setattr(api, "publish_bound_single_owner_policy", publish_on_test_alias)
    with connections[alias].schema_editor() as editor:
        editor.create_model(SingleOwnerAuthorityPolicyV1Model)
    try:
        with override_settings(ROOT_URLCONF=__name__):
            client, user, csrf = _logged_in_client(alias)
            created = _post(client, csrf)
            assert created.status_code == 201, created.content
            binding = CanonicalAccountCreationBindingV2Model.objects.using(alias).get()
            values = _values(user)

            def read(*, environment, definition_key):
                assert environment == "test"
                return values.get(definition_key)

            monkeypatch.setattr(config_center_runtime, "get_active_runtime_value", read)
            payload = {
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "binding_content_hash": binding.content_hash,
            }

            def post(body, **headers):
                return client.post(
                    URL, body, content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **headers
                )

            assert post(payload).status_code == 400
            assert (
                post({**payload, "owner_id": "injected"}, HTTP_IDEMPOTENCY_KEY="one").status_code
                == 400
            )
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 0
            first = post(payload, HTTP_IDEMPOTENCY_KEY="one")
            assert first.status_code == 200, first.content
            assert first["Content-Type"].startswith("application/json")
            assert set(first.json()) == {"policy", "authority_granted"}
            assert first.json()["authority_granted"] is False
            replay = post(payload, HTTP_IDEMPOTENCY_KEY="one")
            assert replay.status_code == 200, replay.content
            assert replay.json() == first.json()
            conflict = post(payload, HTTP_IDEMPOTENCY_KEY="two")
            assert conflict.status_code == 409, conflict.content
            assert conflict["Content-Type"].startswith("application/json")
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 1
            values.pop("account.single_owner_policy.authorization_source")
            unavailable = post(payload, HTTP_IDEMPOTENCY_KEY="one")
            assert unavailable.status_code == 503, unavailable.content
            assert unavailable["Content-Type"].startswith("application/json")
            assert SingleOwnerAuthorityPolicyV1Model.objects.using(alias).count() == 1
    finally:
        with connections[alias].schema_editor() as editor:
            editor.delete_model(SingleOwnerAuthorityPolicyV1Model)
