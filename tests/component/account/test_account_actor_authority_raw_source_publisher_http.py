"""HTTP component coverage for the authenticated EVID-06 publisher."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.db import models
from django.db import router as db_router
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.test import Client, override_settings
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.account.account_actor_authority_raw_source_publisher_composition import (
    build_account_actor_authority_raw_source_publisher,
)
from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    PublishAccountActorAuthorityRawSourceV3,
)
from apps.account.interface.account_actor_authority_raw_source_api_views import (
    AccountActorAuthorityRawSourcePublishView,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
    _raw_counts,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)

PUBLISH_PATH = "/api/account/authority/raw/publish/"
_TEST_MIDDLEWARE = (
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
)
_OWNED_MODEL_LABELS = frozenset(
    {
        "auth.user",
        "sessions.session",
        "account.accountprofilemodel",
    }
)
_MISSING = object()


@ensure_csrf_cookie
def _csrf_bootstrap(request: HttpRequest) -> JsonResponse:
    """Expose a test-only CSRF token bootstrap endpoint."""

    return JsonResponse({"csrf_token": get_token(request)})


urlpatterns = [
    path("csrf/", _csrf_bootstrap),
    path(
        "api/account/authority/raw/publish/",
        AccountActorAuthorityRawSourcePublishView.as_view(),
    ),
]


class _Evid06DatabaseRouter:
    """Route only the real login/session/profile models to the disposable alias."""

    def __init__(self, alias: str) -> None:
        self.alias = alias

    @staticmethod
    def _owns(model: type[models.Model]) -> bool:
        return model._meta.label_lower in _OWNED_MODEL_LABELS

    def db_for_read(self, model: type[models.Model], **hints: object) -> str | None:
        """Route authentication, session, and profile reads to the test alias."""

        del hints
        return self.alias if self._owns(model) else None

    def db_for_write(self, model: type[models.Model], **hints: object) -> str | None:
        """Route authentication, session, and profile writes to the test alias."""

        del hints
        return self.alias if self._owns(model) else None

    def allow_relation(
        self,
        obj1: models.Model,
        obj2: models.Model,
        **hints: object,
    ) -> bool | None:
        """Allow fresh alias-bound User/Profile relations without cross-database joins."""

        del hints
        model1 = type(obj1)
        model2 = type(obj2)
        if not (self._owns(model1) or self._owns(model2)):
            return None
        databases = {
            database
            for database in (
                getattr(getattr(obj1, "_state", None), "db", None),
                getattr(getattr(obj2, "_state", None), "db", None),
            )
            if database is not None
        }
        return not databases or databases == {self.alias}


@contextmanager
def _use_evid06_http_database(alias: str) -> Iterator[None]:
    """Install and restore the disposable authentication database router."""

    previous_routers = db_router._routers
    previous_cached = db_router.__dict__.get("routers", _MISSING)
    db_router._routers = [_Evid06DatabaseRouter(alias)]
    db_router.__dict__.pop("routers", None)
    try:
        with override_settings(
            DATABASE_ROUTERS=[_Evid06DatabaseRouter(alias)],
            MIDDLEWARE=_TEST_MIDDLEWARE,
            ROOT_URLCONF=__name__,
        ):
            yield
    finally:
        db_router._routers = previous_routers
        if previous_cached is _MISSING:
            db_router.__dict__.pop("routers", None)
        else:
            db_router.__dict__["routers"] = previous_cached


@pytest.fixture
def _evid06_http_context(
    evid06_alias: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Bind real HTTP authentication and publisher composition to the test alias."""

    import apps.account.interface.account_actor_authority_raw_source_api_views as view_module

    def build_for_test_alias(
        *, authenticated_user: object, session: object
    ) -> PublishAccountActorAuthorityRawSourceV3:
        """Use production composition with only its explicit alias seam changed."""

        return build_account_actor_authority_raw_source_publisher(
            authenticated_user=authenticated_user,
            session=session,
            using=evid06_alias,
        )

    monkeypatch.setattr(
        view_module,
        "build_account_actor_authority_raw_source_publisher",
        build_for_test_alias,
    )
    with _use_evid06_http_database(evid06_alias):
        yield evid06_alias


def _csrf_token(client: Client) -> str:
    """Obtain a real CSRF token through the test URLconf and middleware."""

    response = client.get("/csrf/")
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _logged_in_client(alias: str) -> tuple[Client, User, str]:
    """Log in through Django's authentication/session backend on the test alias."""

    user, _ = _new_user(alias)
    client = Client(enforce_csrf_checks=True)
    assert client.login(username=user.username, password="evid06-test-password") is True
    session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert Session._default_manager.using(alias).filter(session_key=session_key).exists()
    return client, user, _csrf_token(client)


def _post_json(
    client: Client,
    payload: Mapping[str, object],
    *,
    csrf_token: str | None = None,
) -> HttpResponse:
    """POST JSON to the publisher, optionally carrying the CSRF header."""

    headers = {"HTTP_X_CSRFTOKEN": csrf_token} if csrf_token is not None else {}
    return client.post(
        PUBLISH_PATH,
        data=json.dumps(dict(payload)),
        content_type="application/json",
        **headers,
    )


def test_authenticated_http_login_publishes_four_pg_ledgers(
    _evid06_http_context: str,
) -> None:
    """A real logged-in session reaches the view and commits all raw/actor rows."""

    client, user, csrf_token = _logged_in_client(_evid06_http_context)
    response = _post_json(client, {}, csrf_token=csrf_token)

    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()["data"]
    assert payload["outcome"] == "success"
    assert payload["status"] == "attestation_only"
    assert payload["user_id"] == user.pk
    assert set(payload) == {
        "outcome",
        "status",
        "user_id",
        "principal_id",
        "observed_at",
        "valid_until",
        "authentication_context",
        "user",
        "rbac",
        "actor",
    }
    for selector_name in ("authentication_context", "user", "rbac", "actor"):
        assert set(payload[selector_name]) == {
            "source_id",
            "source_version",
            "content_hash",
        }
    assert _raw_counts(_evid06_http_context) == (1,) * 8
    assert "session_key" not in json.dumps(payload)
    assert "password" not in json.dumps(payload)


def test_http_contract_rejects_missing_csrf_anonymous_extra_fields_and_get(
    _evid06_http_context: str,
) -> None:
    """Authentication, CSRF, input, and method boundaries fail before any write."""

    client, _, csrf_token = _logged_in_client(_evid06_http_context)

    missing_csrf = _post_json(client, {})
    assert missing_csrf.status_code == 403
    assert _raw_counts(_evid06_http_context) == (0,) * 8

    extra_field = _post_json(client, {"scope": "write"}, csrf_token=csrf_token)
    assert extra_field.status_code == 400
    assert extra_field["Content-Type"].startswith("application/json")
    assert "no client authority fields" in str(extra_field.json()).lower()
    assert _raw_counts(_evid06_http_context) == (0,) * 8

    anonymous = Client(enforce_csrf_checks=True)
    anonymous_csrf = _csrf_token(anonymous)
    anonymous_response = _post_json(anonymous, {}, csrf_token=anonymous_csrf)
    assert anonymous_response.status_code == 403
    assert anonymous_response["Content-Type"].startswith("application/json")
    assert _raw_counts(_evid06_http_context) == (0,) * 8

    method_response = client.get(PUBLISH_PATH)
    assert method_response.status_code == 405
    assert method_response["Content-Type"].startswith("application/json")
    assert _raw_counts(_evid06_http_context) == (0,) * 8


__all__ = [
    "urlpatterns",
    "test_authenticated_http_login_publishes_four_pg_ledgers",
    "test_http_contract_rejects_missing_csrf_anonymous_extra_fields_and_get",
]
