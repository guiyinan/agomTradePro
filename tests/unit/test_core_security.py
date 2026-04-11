from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from rest_framework.test import APIRequestFactory

from core.throttling import ResilientUserRateThrottle

from core.security import LockoutModelBackend


@pytest.mark.django_db
def test_lockout_backend_authenticates_when_cache_get_fails(monkeypatch):
    user = get_user_model().objects.create_user(
        username="cache-fallback-user",
        password="CachePass123!",
    )

    monkeypatch.setattr("core.security.cache.get", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis down")))
    monkeypatch.setattr(
        ModelBackend,
        "authenticate",
        lambda self, request, username=None, password=None, **kwargs: user,
    )

    backend = LockoutModelBackend()
    request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

    assert backend.authenticate(request, username="cache-fallback-user", password="CachePass123!") == user


@pytest.mark.django_db
def test_lockout_backend_records_failure_without_crashing_when_cache_is_down(monkeypatch):
    monkeypatch.setattr("core.security.cache.get", lambda *args, **kwargs: 0)
    monkeypatch.setattr("core.security.cache.incr", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis down")))
    monkeypatch.setattr("core.security.cache.set", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis down")))
    monkeypatch.setattr(
        ModelBackend,
        "authenticate",
        lambda self, request, username=None, password=None, **kwargs: None,
    )

    backend = LockoutModelBackend()
    request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

    assert backend.authenticate(request, username="cache-fallback-user", password="wrong-pass") is None


def test_resilient_user_throttle_allows_request_when_cache_is_down(monkeypatch):
    throttle = ResilientUserRateThrottle()
    request = APIRequestFactory().get("/api/demo/")
    request.user = SimpleNamespace(is_authenticated=True, pk=1)
    view = SimpleNamespace(__class__=SimpleNamespace(__name__="DemoView"))

    monkeypatch.setattr(
        "rest_framework.throttling.UserRateThrottle.allow_request",
        lambda self, request, view: (_ for _ in ()).throw(ConnectionError("redis down")),
    )

    assert throttle.allow_request(request, view) is True
