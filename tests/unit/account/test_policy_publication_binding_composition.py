"""Scope resolution uses exact permanent binding and the authenticated requester."""

from types import SimpleNamespace

import pytest

from apps.account import policy_publication_binding_composition as subject
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from core.exceptions import AuthenticationError, ExternalServiceError
from tests.unit.account.test_canonical_account_creation_binding_v2 import _at, _binding


def _setup(monkeypatch, *, vendor="postgresql", atomic=True, missing=False):
    binding = _binding()
    calls = []

    class Repository:
        def __init__(self, *, using):
            assert using == "bound-alias"

        def get_exact_by_hash(self, **kwargs):
            calls.append(kwargs)
            return None if missing else binding

    monkeypatch.setattr(
        subject,
        "connections",
        {"bound-alias": SimpleNamespace(vendor=vendor, in_atomic_block=atomic)},
    )
    monkeypatch.setattr(subject, "DjangoCanonicalAccountCreationConsumptionRepository", Repository)
    options = {
        "using": "bound-alias",
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "expected_content_hash": binding.content_hash,
        "requester": binding.allocation.requested_by,
        "as_of": _at(20),
    }
    return binding, options, calls


def test_resolves_exact_permanent_binding_after_old_root_expiry(monkeypatch):
    binding, options, calls = _setup(monkeypatch)
    assert binding.creation_root.valid_until < options["as_of"]
    assert subject.resolve_policy_publication_binding(**options) == binding
    assert calls == [
        {key: value for key, value in options.items() if key not in {"using", "requester"}}
    ]
    assert binding.must_not_execute is True


@pytest.mark.parametrize("vendor,atomic", [("sqlite", True), ("postgresql", False)])
def test_requires_same_alias_outer_postgresql_transaction(monkeypatch, vendor, atomic):
    _, options, calls = _setup(monkeypatch, vendor=vendor, atomic=atomic)
    with pytest.raises(ExternalServiceError):
        subject.resolve_policy_publication_binding(**options)
    assert calls == []


def test_another_authenticated_user_cannot_resolve_owner_scope(monkeypatch):
    _, options, _ = _setup(monkeypatch)
    options["requester"] = CanonicalAccountCreationRequester(
        actor_id="django-user:999", user_id=999
    )
    with pytest.raises(AuthenticationError):
        subject.resolve_policy_publication_binding(**options)


def test_missing_binding_has_no_scope_fallback(monkeypatch):
    _, options, _ = _setup(monkeypatch, missing=True)
    with pytest.raises(ExternalServiceError):
        subject.resolve_policy_publication_binding(**options)
