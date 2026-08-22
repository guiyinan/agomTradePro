from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    root_claim_hash_for_account_user_authority_source_v3,
)
from apps.account.infrastructure import (
    account_owner_assignment_actor_authority_bundle_provider as module,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    AccountActorAuthorityRawSourceRepositoriesV3,
    DjangoAccountActorAuthorityInputBundleProviderV3,
)
from tests.unit.account.test_account_authentication_context_source_v3 import (
    _source as authentication_source,
)
from tests.unit.account.test_account_rbac_authority_source_v3 import _source as rbac_source
from tests.unit.account.test_account_user_authority_source_v3 import _source as user_source

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)
AS_OF = NOW + timedelta(minutes=30)


class _Cursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


class _Connection:
    def __init__(self, *, vendor: str = "postgresql", alias: str = "default") -> None:
        self.vendor = vendor
        self.alias = alias
        self.in_atomic_block = False
        self.cursor_value = _Cursor()

    def get_autocommit(self) -> bool:
        return True

    def cursor(self) -> _Cursor:
        return self.cursor_value


class _Atomic:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> None:
        self.entered += 1

    def __exit__(self, *args: object) -> None:
        self.exited += 1


class _Reader:
    def __init__(self, value: object | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.selectors: list[object] = []

    def execute(self, selector: object) -> object | None:
        self.selectors.append(selector)
        if self.error is not None:
            raise self.error
        return self.value


class _Factory:
    def __init__(self, *, using: str = "default") -> None:
        self.using = using
        self.calls: list[str] = []

    def build(self, *, using: str) -> AccountActorAuthorityRawSourceRepositoriesV3:
        self.calls.append(using)
        return AccountActorAuthorityRawSourceRepositoriesV3(
            using=self.using,
            authentication=object(),  # type: ignore[arg-type]
            user=object(),  # type: ignore[arg-type]
            rbac=object(),  # type: ignore[arg-type]
        )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connection: _Connection,
    atomic: _Atomic,
    context: object | None,
    user: object | None,
    rbac: object | None,
    reader_error: Exception | None = None,
) -> None:
    monkeypatch.setattr(module, "_connection_for_alias", lambda using: connection)
    monkeypatch.setattr(module, "_atomic_for_alias", lambda using: atomic)
    monkeypatch.setattr(
        module,
        "GetCurrentAccountAuthenticationContextSourceV3",
        lambda repository: _Reader(context, reader_error),
    )
    monkeypatch.setattr(
        module,
        "GetCurrentAccountUserAuthoritySourceV3",
        lambda repository: _Reader(user, reader_error),
    )
    monkeypatch.setattr(
        module,
        "GetCurrentAccountRbacAuthoritySourceV3",
        lambda repository: _Reader(rbac, reader_error),
    )


def _provider(factory: _Factory | None = None) -> DjangoAccountActorAuthorityInputBundleProviderV3:
    return DjangoAccountActorAuthorityInputBundleProviderV3(
        using="default", repositories_factory=factory or _Factory()
    )


def _sources() -> tuple[object, object, object]:
    return authentication_source(), user_source(), rbac_source()


def _kwargs(context: object, user: object, rbac: object) -> dict[str, object]:
    return {
        "authentication_context_id": context.identity.source_id,  # type: ignore[attr-defined]
        "authentication_context_version": context.identity.source_version,  # type: ignore[attr-defined]
        "expected_authentication_context_content_hash": context.content_hash,  # type: ignore[attr-defined]
        "user_source_id": user.identity.source_id,  # type: ignore[attr-defined]
        "user_source_version": user.identity.source_version,  # type: ignore[attr-defined]
        "expected_user_source_content_hash": user.content_hash,  # type: ignore[attr-defined]
        "rbac_source_id": rbac.identity.source_id,  # type: ignore[attr-defined]
        "rbac_source_version": rbac.identity.source_version,  # type: ignore[attr-defined]
        "expected_rbac_source_content_hash": rbac.content_hash,  # type: ignore[attr-defined]
        "as_of": AS_OF,
    }


def test_projects_exact_current_sources_in_one_read_only_repeatable_read_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, user, rbac = _sources()
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=user,
        rbac=rbac,
    )

    result = _provider().get_exact_current(**_kwargs(context, user, rbac))

    assert result is not None
    assert result.context.user_id == 41
    assert result.user.actor_id == "django-user:41"
    assert result.rbac.rbac_role == "owner"
    assert connection.cursor_value.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    ]
    assert atomic.entered == atomic.exited == 1


def test_empty_or_non_current_ledger_never_becomes_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, user, rbac = _sources()
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=None,
        rbac=rbac,
    )

    assert _provider().get_exact_current(**_kwargs(context, user, rbac)) is None


def test_sqlite_is_rejected_before_factory_or_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    context, user, rbac = _sources()
    connection = _Connection(vendor="sqlite")
    atomic = _Atomic()
    factory = _Factory()
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=user,
        rbac=rbac,
    )

    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable, match="PostgreSQL"):
        _provider(factory).get_exact_current(**_kwargs(context, user, rbac))
    assert factory.calls == []
    assert atomic.entered == 0


def test_alias_drift_is_corruption_and_does_not_read_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, user, rbac = _sources()
    connection = _Connection()
    atomic = _Atomic()
    factory = _Factory(using="other")
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=user,
        rbac=rbac,
    )

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="alias"):
        _provider(factory).get_exact_current(**_kwargs(context, user, rbac))
    assert atomic.entered == 0


def test_identity_or_hash_drift_is_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    context, user, rbac = _sources()
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=user,
        rbac=rbac,
    )
    kwargs = _kwargs(context, user, rbac)
    kwargs["expected_user_source_content_hash"] = "f" * 64

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="identity|hash"):
        _provider().get_exact_current(**kwargs)


def test_cross_ledger_user_identity_drift_is_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    context, user, rbac = _sources()
    drifted_user = replace(
        user,
        user_id=42,
        actor_id="django-user:42",
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id=user.identity.source_id,
                user_id=42,
                actor_id="django-user:42",
            )
        ),
        identity_hash="",
        user_seal="",
        facts_seal="",
        clock_seal="",
        chain_seal="",
        fixed_authority_seal="",
        record_seal="",
        content_hash="",
    )
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=drifted_user,
        rbac=rbac,
    )
    kwargs = _kwargs(context, drifted_user, rbac)

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="drift"):
        _provider().get_exact_current(**kwargs)


def test_reader_unavailable_remains_stable_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    context, user, rbac = _sources()
    connection = _Connection()
    atomic = _Atomic()
    error = AccountActorAuthorityRawSourceV3Unavailable("ledger unavailable")
    _patch_runtime(
        monkeypatch,
        connection=connection,
        atomic=atomic,
        context=context,
        user=user,
        rbac=rbac,
        reader_error=error,
    )

    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable, match="ledger unavailable"):
        _provider().get_exact_current(**_kwargs(context, user, rbac))
