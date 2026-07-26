from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.test import RequestFactory, override_settings
from rest_framework.test import APIRequestFactory

from core.security import (
    LockoutModelBackend,
    _cache_get_int,
    _cache_record_failure,
    _get_limits,
    _request_ip,
)
from core.throttling import ResilientUserRateThrottle


@pytest.mark.django_db
def test_lockout_backend_authenticates_when_cache_get_fails(monkeypatch):
    user = get_user_model().objects.create_user(
        username="cache-fallback-user",
        password="CachePass123!",
    )

    monkeypatch.setattr(
        "core.security.cache.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    monkeypatch.setattr(
        ModelBackend,
        "authenticate",
        lambda self, request, username=None, password=None, **kwargs: user,
    )

    backend = LockoutModelBackend()
    request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

    assert (
        backend.authenticate(request, username="cache-fallback-user", password="CachePass123!")
        == user
    )


@pytest.mark.django_db
def test_lockout_backend_records_failure_without_crashing_when_cache_is_down(monkeypatch):
    monkeypatch.setattr("core.security.cache.get", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        "core.security.cache.add",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    monkeypatch.setattr(
        ModelBackend,
        "authenticate",
        lambda self, request, username=None, password=None, **kwargs: None,
    )

    backend = LockoutModelBackend()
    request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

    assert (
        backend.authenticate(request, username="cache-fallback-user", password="wrong-pass") is None
    )


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


def test_lockout_ignores_forwarded_for_without_explicit_proxy_trust():
    request = RequestFactory().post(
        "/account/login/",
        REMOTE_ADDR="10.0.0.5",
        HTTP_X_FORWARDED_FOR="198.51.100.7",
    )

    assert _request_ip(request) == "10.0.0.5"


@override_settings(LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR=True)
def test_lockout_uses_first_forwarded_ip_when_proxy_trust_is_explicit():
    request = RequestFactory().post(
        "/account/login/",
        REMOTE_ADDR="10.0.0.5",
        HTTP_X_FORWARDED_FOR="198.51.100.7, 10.0.0.4",
    )

    assert _request_ip(request) == "198.51.100.7"


@override_settings(LOGIN_LOCKOUT_MAX_ATTEMPTS=0, LOGIN_LOCKOUT_WINDOW_SECONDS=-1)
def test_invalid_lockout_limits_fall_back_to_safe_defaults():
    assert _get_limits() == (5, 900)


def test_failure_counter_uses_atomic_add_before_increment(monkeypatch):
    add_calls = []
    increment_calls = []
    monkeypatch.setattr(
        "core.security.cache.add",
        lambda key, value, timeout: add_calls.append((key, value, timeout)) or False,
    )
    monkeypatch.setattr(
        "core.security.cache.incr",
        lambda key: increment_calls.append(key),
    )

    _cache_record_failure("lockout-key", 60)

    assert add_calls == [("lockout-key", 1, 60)]
    assert increment_calls == ["lockout-key"]


def test_cache_failure_log_does_not_disclose_exception_text(monkeypatch, caplog):
    monkeypatch.setattr(
        "core.security.cache.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("redis://user:secret@cache")),
    )

    assert _cache_get_int("lockout-key") == 0
    assert "ConnectionError" in caplog.text
    assert "user:secret" not in caplog.text
