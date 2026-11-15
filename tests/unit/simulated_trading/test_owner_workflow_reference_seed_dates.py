"""Keep the cash-reference record date beyond seeded tax settlement changes."""

import json
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Literal, cast
from zoneinfo import ZoneInfo

import pytest

from tests.support import ash03_auto_calendar_fixture as calendar_fixture
from tests.support.ash05_owner_workflow_native_world import _local_anchor


@pytest.mark.parametrize("weekday", range(7))
def test_reference_seed_settlement_precedes_the_recent_record_date(weekday: int) -> None:
    """An older retained seed leaves a zero-change record session all week."""
    local_day = date(2026, 11, 9) + timedelta(days=weekday)
    actual = datetime.combine(local_day, time(16), tzinfo=ZoneInfo("Asia/Shanghai"))
    anchor, anchor_at = _local_anchor(actual, history_weeks=2)
    sessions = tuple(
        anchor + timedelta(days=offset)
        for offset in range(1, (local_day - anchor).days + 1)
        if (anchor + timedelta(days=offset)).weekday() < 5
    )
    seeded_sale_settlement = sessions[3]
    reference_record_date = sessions[-2]

    assert seeded_sale_settlement < reference_record_date
    assert reference_record_date < sessions[-1] <= local_day
    assert anchor_at.astimezone(UTC) < actual.astimezone(UTC)
    assert _local_anchor(actual) == _local_anchor(actual, history_weeks=1)


class _BeforeRuntimeWrite(RuntimeError):
    """Stop after actual source bytes are built and before any database write."""


@pytest.mark.parametrize("weekday", range(7))
@pytest.mark.parametrize("history_weeks", (1, 2))
def test_live_calendar_source_preserves_the_selected_history_origin(
    monkeypatch: pytest.MonkeyPatch, weekday: int, history_weeks: Literal[1, 2]
) -> None:
    """Exercise the real live producer through its exact serialized source body."""
    local_day = date(2026, 11, 9) + timedelta(days=weekday)
    actual = datetime.combine(local_day, time(16), tzinfo=ZoneInfo("Asia/Shanghai"))
    anchor, _ = _local_anchor(actual, history_weeks=history_weeks)
    bodies: list[bytes] = []
    serialize = calendar_fixture._raw_calendar_body

    def observe(rows: tuple[tuple[str, str, int, str], ...]) -> bytes:
        body = serialize(rows)
        bodies.append(body)
        return body

    def stop() -> None:
        raise _BeforeRuntimeWrite

    monkeypatch.setattr(calendar_fixture, "connection", SimpleNamespace(vendor="postgresql"))
    monkeypatch.setattr(calendar_fixture.django_timezone, "now", lambda: actual)
    monkeypatch.setattr(calendar_fixture, "_raw_calendar_body", observe)
    monkeypatch.setattr(calendar_fixture, "configure_critical_runtime", stop)
    with pytest.raises(_BeforeRuntimeWrite):
        calendar_fixture.persist_auto_uow_formal_calendar(
            as_of=actual.astimezone(UTC),
            exchange="SZSE",
            timezone_name="Asia/Shanghai",
            live_clock=True,
            live_coverage_start=anchor if history_weeks == 2 else None,
        )

    assert len(bodies) == 1
    rows = json.loads(bodies[0])["data"]["items"]
    assert rows[0][1] == anchor.strftime("%Y%m%d")
    assert rows[-1][1] == (local_day + timedelta(days=14)).strftime("%Y%m%d")
    assert len(rows) == (local_day + timedelta(days=14) - anchor).days + 1


@pytest.mark.parametrize(
    ("live_clock", "start"),
    (
        (False, date(2026, 10, 30)),
        (True, datetime(2026, 10, 30, tzinfo=UTC)),
        (True, date(2026, 11, 16)),
    ),
)
def test_live_calendar_rejects_invalid_history_coverage(
    monkeypatch: pytest.MonkeyPatch, live_clock: bool, start: object
) -> None:
    """Coverage selection cannot change fixed-clock fixtures or enter the future."""
    actual = datetime(2026, 11, 15, 8, tzinfo=UTC)
    monkeypatch.setattr(calendar_fixture, "connection", SimpleNamespace(vendor="postgresql"))
    monkeypatch.setattr(calendar_fixture.django_timezone, "now", lambda: actual)
    with pytest.raises(ValueError, match="coverage"):
        calendar_fixture.persist_auto_uow_formal_calendar(
            as_of=actual,
            exchange="SZSE",
            timezone_name="Asia/Shanghai",
            live_clock=live_clock,
            live_coverage_start=cast(date, start),
        )


@pytest.mark.django_db
def test_historical_owner_session_expires_and_same_owner_reauthenticates_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical setup cannot carry an expired session into the live workflow."""
    from uuid import uuid4

    from django.conf import settings
    from django.contrib.auth.models import User
    from django.contrib.sessions.models import Session
    from django.test import override_settings
    from django.utils import timezone
    from rest_framework.test import APIClient

    from apps.account.domain.canonical_account_creation_binding_v2 import (
        CanonicalAccountCreationBindingV2,
    )
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
    from tests.support import ash05_owner_workflow_native_world as world_fixture
    from tests.support.ash07_owner_account_authority import OwnerAccountSeed

    actual = datetime(2026, 11, 15, 8, tzinfo=UTC)
    _anchor, anchor_at = _local_anchor(actual, history_weeks=2)
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    monkeypatch.setattr(timezone, "now", lambda: anchor_at)
    owner = User.objects.create_user(username=f"ash05-session-unit-{uuid4().hex}")
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(owner)
    old_key = client.session.session_key
    assert old_key is not None
    assert Session.objects.get(session_key=old_key).expire_date <= actual
    seed = OwnerAccountSeed(
        owner=owner,
        client=client,
        csrf_token="expired-fixture-token",
        account=cast(SimulatedAccountModel, object()),
        binding=cast(CanonicalAccountCreationBindingV2, object()),
        environment="development",
    )
    age_before = settings.SESSION_COOKIE_AGE
    monkeypatch.setattr(timezone, "now", lambda: actual)
    with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
        expired = client.get("/csrf/bootstrap/", secure=True)
        assert expired.wsgi_request.user.is_authenticated is False
        refreshed = world_fixture._reauthenticate_current_owner(seed)
        current = refreshed.client.get("/csrf/bootstrap/", secure=True)
        assert current.wsgi_request.user.pk == owner.pk
        assert current.wsgi_request.user.is_authenticated is True
    assert refreshed.owner is owner
    assert refreshed.account is seed.account and refreshed.binding is seed.binding
    assert refreshed.client is client and refreshed.csrf_token != seed.csrf_token
    assert client.session.session_key != old_key
    assert client.session.get_expiry_date() > actual
    assert settings.SESSION_COOKIE_AGE == age_before
    owner.refresh_from_db()
    assert owner.is_staff is False and owner.is_superuser is False
