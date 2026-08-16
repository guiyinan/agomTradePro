from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.audit.application.system_audit_authority_provider import (
    ExactScopedSystemAuditAuthorityProvider,
    SystemAuditActorAuthorityFacts,
    SystemAuditAuthorityBundleSelector,
    SystemAuditScopeAuthorityFacts,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ACTOR_HASH = "a" * 64
SCOPE_HASH = "b" * 64


class ActorReader:
    def __init__(self, value: SystemAuditActorAuthorityFacts | None) -> None:
        self.value = value

    def get_current(self, **kwargs: object) -> SystemAuditActorAuthorityFacts | None:
        del kwargs
        return self.value


class ScopeReader:
    def __init__(self, value: SystemAuditScopeAuthorityFacts | None) -> None:
        self.value = value

    def get_current(self, **kwargs: object) -> SystemAuditScopeAuthorityFacts | None:
        del kwargs
        return self.value


def _selector(**changes: object) -> SystemAuditAuthorityBundleSelector:
    values: dict[str, object] = {
        "actor_source_id": "actor-source",
        "actor_source_version": "v1",
        "actor_content_hash": ACTOR_HASH,
        "scope_source_id": "scope-source",
        "scope_source_version": "v1",
        "scope_content_hash": SCOPE_HASH,
    }
    values.update(changes)
    return SystemAuditAuthorityBundleSelector(**values)  # type: ignore[arg-type]


def _actor(**changes: object) -> SystemAuditActorAuthorityFacts:
    values: dict[str, object] = {
        "source_id": "actor-source",
        "source_version": "v1",
        "content_hash": ACTOR_HASH,
        "actor_id": "django-user:7",
        "user_id": 7,
        "is_authenticated": True,
        "is_staff": True,
        "role": "audit_reader",
        "authority_state": "active",
        "recorded_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return SystemAuditActorAuthorityFacts(**values)  # type: ignore[arg-type]


def _scope(**changes: object) -> SystemAuditScopeAuthorityFacts:
    values: dict[str, object] = {
        "source_id": "scope-source",
        "source_version": "v1",
        "content_hash": SCOPE_HASH,
        "actor_id": "django-user:7",
        "user_id": 7,
        "tenant_id": "tenant:7",
        "owner_id": "owner:7",
        "authority_state": "active",
        "recorded_at": NOW - timedelta(minutes=4),
        "valid_until": NOW + timedelta(minutes=4),
    }
    values.update(changes)
    return SystemAuditScopeAuthorityFacts(**values)  # type: ignore[arg-type]


def _provider(
    actor: SystemAuditActorAuthorityFacts | None = None,
    scope: SystemAuditScopeAuthorityFacts | None = None,
    selector: SystemAuditAuthorityBundleSelector | None = None,
) -> ExactScopedSystemAuditAuthorityProvider:
    return ExactScopedSystemAuditAuthorityProvider(
        actor_reader=ActorReader(actor),
        scope_reader=ScopeReader(scope),
        selector=selector,
    )


def test_missing_selector_is_fail_closed() -> None:
    assert _provider(_actor(), _scope()).get_current(as_of=NOW) is None


def test_exact_actor_scope_bundle_projects_provider_issued_snapshot() -> None:
    snapshot = _provider(_actor(), _scope(), _selector()).get_current(as_of=NOW)

    assert snapshot is not None
    assert snapshot.can_read
    assert snapshot.actor_id == "django-user:7"
    assert snapshot.user_id == 7
    assert snapshot.tenant_id == "tenant:7"
    assert snapshot.owner_id == "owner:7"
    assert snapshot.source_id.startswith("audit-authority-bundle:")


def test_reader_result_substitution_is_fail_closed() -> None:
    substituted = _actor(source_id="other-source")
    assert _provider(substituted, _scope(), _selector()).get_current(as_of=NOW) is None


def test_actor_scope_identity_or_staff_mismatch_is_fail_closed() -> None:
    assert _provider(
        _actor(is_staff=False), _scope(), _selector()
    ).get_current(as_of=NOW) is None
    assert _provider(
        _actor(), _scope(actor_id="django-user:8"), _selector()
    ).get_current(as_of=NOW) is None


def test_expired_or_future_authority_is_fail_closed() -> None:
    assert _provider(
        _actor(valid_until=NOW), _scope(), _selector()
    ).get_current(as_of=NOW) is None
    assert _provider(
        _actor(recorded_at=NOW + timedelta(seconds=1)), _scope(), _selector()
    ).get_current(as_of=NOW) is None


def test_reader_exception_is_fail_closed_without_leaking_details() -> None:
    class BrokenReader:
        def get_current(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("database password must not escape")

    provider = ExactScopedSystemAuditAuthorityProvider(
        actor_reader=BrokenReader(),
        scope_reader=ScopeReader(_scope()),
        selector=_selector(),
    )
    assert provider.get_current(as_of=NOW) is None
