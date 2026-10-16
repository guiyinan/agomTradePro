"""Serialize actual grant revocation against the calendar authority transaction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from typing import Literal, cast

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.db import close_old_connections, connection, connections, models, transaction

from apps.data_center.application.calendar_audit_read_authority import (
    CalendarAuditReaderSessionRequestProof,
)
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from core.exceptions import AuthorizationError
from tests.component.data_center.test_calendar_authority_clock_boundaries import (
    NOW,
    _auth_schema,
    _Clock,
    _proof,
)

__all__ = ["_auth_schema"]  # Export the imported fixture for pytest's module discovery.

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)
GrantKind = Literal["direct", "group_permission", "group_membership"]
AuthorityPurpose = Literal["publisher", "audit_reader"]


@pytest.fixture(autouse=True)
def _requires_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("revocation serialization requires two actual PostgreSQL connections")


def _witness(
    user: User,
    kind: GrantKind,
    permission_codename: str,
) -> tuple[type[models.Model], int]:
    permission = Permission.objects.get(
        codename=permission_codename,
        content_type__app_label="data_center",
        content_type__model="exchangecalendarsnapshotfactmodel",
    )
    direct_model = cast(type[models.Model], type(user).user_permissions.through)
    if kind == "direct":
        row = direct_model._default_manager.get(user_id=user.pk, permission_id=permission.pk)
        return direct_model, cast(int, row.pk)
    user.user_permissions.clear()
    group = Group.objects.create(name="root-test-calendar-grant")
    user.groups.add(group)
    group.permissions.add(permission)
    if kind == "group_permission":
        model = cast(type[models.Model], Group.permissions.through)
        row = model._default_manager.get(group_id=group.pk, permission_id=permission.pk)
    else:
        model = cast(type[models.Model], type(user).groups.through)
        row = model._default_manager.get(user_id=user.pk, group_id=group.pk)
    return model, cast(int, row.pk)


def _prepare_authority(
    purpose: AuthorityPurpose,
) -> tuple[
    User, CalendarPublisherSessionRequestProof | CalendarAuditReaderSessionRequestProof, str
]:
    user, proof = _proof()
    if purpose == "publisher":
        return user, proof, "publish_exchange_calendar"
    permission, _ = Permission.objects.get_or_create(
        content_type=Permission.objects.get(codename="publish_exchange_calendar").content_type,
        codename="view_exchange_calendar_publication_audit",
        defaults={"name": "Test-only calendar read permission"},
    )
    user.user_permissions.clear()
    user.user_permissions.add(permission)
    return (
        user,
        CalendarAuditReaderSessionRequestProof(
            user_id=proof.user_id,
            session_key=proof.session_key,
            request_authenticated_at=proof.request_authenticated_at,
            request_user_database_alias=proof.request_user_database_alias,
            database_alias=proof.database_alias,
        ),
        permission.codename,
    )


def _worker_pid() -> int:
    with connections["default"].cursor() as cursor:
        cursor.execute("SET statement_timeout = '10s'")
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _assert_blocked_by(waiter: int, holder: int) -> None:
    deadline = monotonic() + 1.5
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = %s",
                [waiter],
            )
            row = cursor.fetchone()
        if row is not None and row[0] == "Lock" and holder in row[1]:
            return
        Event().wait(0.01)
    raise AssertionError(
        "Expected actual PostgreSQL lock wait with the other test backend as blocker"
    )


@pytest.mark.parametrize("kind", ["direct", "group_permission", "group_membership"])
@pytest.mark.parametrize("purpose", ["publisher", "audit_reader"])
def test_authorization_first_holds_witness_until_its_write_commits(
    kind: GrantKind,
    purpose: AuthorityPurpose,
) -> None:
    user, proof, codename = _prepare_authority(purpose)
    model, pk = _witness(user, kind, codename)
    authorized, revoke_started, may_commit = Event(), Event(), Event()
    pids: dict[str, int] = {}

    def publish() -> str:
        close_old_connections()
        try:
            pids["publisher"] = _worker_pid()
            repository = DjangoCalendarPublisherAuthorityRepository(
                using="default", clock=_Clock(NOW)
            )
            lease = (
                repository.locked_calendar_publisher(proof)
                if isinstance(proof, CalendarPublisherSessionRequestProof)
                else repository.locked_calendar_audit_reader(proof)
            )
            with lease as principal:
                principal.assert_live()
                authorized.set()
                assert may_commit.wait(10)
                type(user).objects.filter(pk=user.pk).update(last_name="authorized-write")
            return "committed"
        finally:
            connections["default"].close()

    def revoke() -> int:
        close_old_connections()
        try:
            assert authorized.wait(10)
            pids["revoker"] = _worker_pid()
            revoke_started.set()
            deleted, _ = model._default_manager.filter(pk=pk).delete()
            return deleted
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        publisher, revoker = pool.submit(publish), pool.submit(revoke)
        try:
            assert authorized.wait(10)
            assert revoke_started.wait(10)
            assert pids["publisher"] != pids["revoker"]
            _assert_blocked_by(pids["revoker"], pids["publisher"])
        finally:
            may_commit.set()
        assert publisher.result(timeout=15) == "committed"
        assert revoker.result(timeout=15) == 1
    user.refresh_from_db()
    assert user.last_name == "authorized-write"
    assert not model._default_manager.filter(pk=pk).exists()


@pytest.mark.parametrize("kind", ["direct", "group_permission", "group_membership"])
@pytest.mark.parametrize("purpose", ["publisher", "audit_reader"])
def test_revocation_first_prevents_callback_write_after_locked_recheck(
    kind: GrantKind,
    purpose: AuthorityPurpose,
) -> None:
    user, proof, codename = _prepare_authority(purpose)
    model, pk = _witness(user, kind, codename)
    deleted, publisher_started, may_revoke_commit = Event(), Event(), Event()
    pids: dict[str, int] = {}

    def revoke() -> None:
        close_old_connections()
        try:
            pids["revoker"] = _worker_pid()
            with transaction.atomic():
                count, _ = model._default_manager.filter(pk=pk).delete()
                assert count == 1
                deleted.set()
                assert may_revoke_commit.wait(10)
        finally:
            connections["default"].close()

    def publish() -> str:
        close_old_connections()
        try:
            assert deleted.wait(10)
            pids["publisher"] = _worker_pid()
            publisher_started.set()
            try:
                repository = DjangoCalendarPublisherAuthorityRepository(
                    using="default", clock=_Clock(NOW)
                )
                lease = (
                    repository.locked_calendar_publisher(proof)
                    if isinstance(proof, CalendarPublisherSessionRequestProof)
                    else repository.locked_calendar_audit_reader(proof)
                )
                with lease:
                    type(user).objects.filter(pk=user.pk).update(last_name="forbidden-write")
            except AuthorizationError as exc:
                prefix = "CALENDAR_PUBLISHER" if purpose == "publisher" else "CALENDAR_AUDIT_READER"
                assert exc.code == f"{prefix}_PERMISSION_REQUIRED"
                return "blocked"
            raise AssertionError("A revoked witness authorized a callback write")
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        revoker, publisher = pool.submit(revoke), pool.submit(publish)
        try:
            assert deleted.wait(10)
            assert publisher_started.wait(10)
            assert pids["publisher"] != pids["revoker"]
            _assert_blocked_by(pids["publisher"], pids["revoker"])
        finally:
            may_revoke_commit.set()
        revoker.result(timeout=15)
        assert publisher.result(timeout=15) == "blocked"
    user.refresh_from_db()
    assert user.last_name == ""
    assert not model._default_manager.filter(pk=pk).exists()
