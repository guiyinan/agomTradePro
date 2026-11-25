"""Native SZSE renewal with real auth, publication and audit, and simulated HTTP."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from celery import Celery
from celery.beat import Scheduler
from celery.contrib.testing.worker import start_worker
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import DatabaseError, close_old_connections, connection, connections
from django.test import override_settings
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from django_celery_beat.schedulers import ModelEntry

from apps.data_center.application.calendar_renewal_task import renew_szse_calendar
from apps.data_center.calendar_renewal_composition import QUEUE, TASK_NAME
from apps.data_center.infrastructure.calendar_renewal_models import (
    CalendarRenewalGrant,
    CalendarRenewalReceipt,
)
from tests.component.data_center import test_calendar_operations_http as http
from tests.support.isolated_schema import isolated_schema

GRANTS = "/api/data-center/exchange-calendars/renewals/"
native_postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="native calendar publication requires PostgreSQL"
)


def _deliver(grant_id, delivery_id=None):
    renew_szse_calendar.push_request(id=str(delivery_id or uuid4()))
    try:
        return renew_szse_calendar.run(grant_id)
    finally:
        renew_szse_calendar.pop_request()


def test_invalid_input():
    result = _deliver("wrong")
    assert (result["outcome"], result["reason_code"], result["stored"]) == (
        "failed",
        "invalid_input",
        0,
    )


@pytest.fixture
def world(transactional_db, monkeypatch):
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with (
        override_settings(
            ROOT_URLCONF=http.__name__,
            AGOMTRADEPRO_ENCRYPTION_KEY="calendar-http-component-fixture-key",
        ),
        isolated_schema((*http._HTTP_SCHEMA_MODELS, CalendarRenewalGrant, CalendarRenewalReceipt)),
    ):
        http._clear_auth_join_rows()
        try:
            yield
        finally:
            http._clear_auth_join_rows()


def _seed(monkeypatch, *bodies, ttl=5):
    body = http._calendar_body().replace(b"SSE", b"SZSE")
    sessions = http._install_source(monkeypatch, [body, *bodies])
    http.DatasetContractModel.objects.filter(dataset_key=http.DATASET_KEY).update(
        calendar_response_max_age_seconds=ttl
    )
    client, owner, csrf = http._client_for_user("calendar-renewal-owner")
    capture = http._success_data(
        http._post(
            client,
            http._CAPTURE_PATH,
            {
                "exchange": "SZSE",
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf,
        ),
        201,
    )
    preview = http._success_data(
        http._post(client, http._PREVIEW_PATH, capture["preview_intent"], csrf), 200
    )
    http._success_data(
        http._post(client, http._CONFIRM_PATH, preview["confirmation_intent"], csrf), 201
    )
    payload = {
        "dataset_key": http.DATASET_KEY,
        "expires_at": (timezone.now() + timedelta(days=365)).isoformat(),
    }
    http._json(http._post(client, GRANTS, payload, csrf), 403)
    ct = ContentType.objects.get_for_model(CalendarRenewalGrant)
    perm, _ = Permission.objects.get_or_create(
        content_type=ct,
        codename="delegate_szse_calendar_renewal",
        defaults={"name": "Delegate SZSE renewal"},
    )
    owner.user_permissions.add(perm)
    issued = http._json(http._post(client, GRANTS, payload, csrf), 201)
    grant = CalendarRenewalGrant.objects.get(pk=issued["grant_id"])
    schedule = PeriodicTask.objects.get(name=f"szse-calendar-renewal-{grant.pk}")
    assert (schedule.enabled, schedule.task, schedule.queue, json.loads(schedule.args)) == (
        False,
        TASK_NAME,
        QUEUE,
        [str(grant.pk)],
    )
    return client, owner, csrf, grant, sessions, perm


def _await_due(grant, ttl):
    # Wait past the formal half-open source window on the real server clock.
    delay = (grant.verified_at + timedelta(seconds=ttl) - timezone.now()).total_seconds()
    time.sleep(max(0, delay))


@native_postgres_only
def test_renewal_is_noop_while_valid(world, monkeypatch):
    _, _, _, grant, sessions, _ = _seed(monkeypatch, ttl=900)
    assert _deliver(str(grant.pk))["reason_code"] == "still_valid"
    assert len(sessions) == 1
    assert not CalendarRenewalReceipt.objects.exists()


@native_postgres_only
def test_revocation_blocks_replayed_task(world, monkeypatch):
    client, _, csrf, grant, sessions, _ = _seed(monkeypatch, ttl=900)
    http._json(http._post(client, f"{GRANTS}{grant.pk}/revoke/", {}, csrf), 200)
    result = _deliver(str(grant.pk))
    assert (result["outcome"], result["stored"]) == ("blocked", 0)
    assert len(sessions) == 1


@native_postgres_only
def test_removed_and_recreated_owner_grant_blocks(world, monkeypatch):
    _, owner, _, grant, sessions, perm = _seed(monkeypatch, ttl=900)
    owner.user_permissions.remove(perm)
    owner.user_permissions.add(perm)
    assert _deliver(str(grant.pk))["outcome"] == "blocked"
    assert len(sessions) == 1


@native_postgres_only
def test_expired_source_failure_preserves_original_pointer(world, monkeypatch):
    _, _, _, grant, sessions, _ = _seed(monkeypatch, b"{}")
    before = http._formal_counts()
    _await_due(grant, 5)
    assert _deliver(str(grant.pk))["reason_code"] == "CALENDAR_RENEWAL_SCHEDULE_DISABLED"
    assert len(sessions) == 1
    PeriodicTask.objects.filter(name=f"szse-calendar-renewal-{grant.pk}").update(enabled=True)
    result = _deliver(str(grant.pk))
    assert (result["outcome"], result["stored"]) == ("failed", 0), result
    assert len(sessions) == 2
    assert http._formal_counts() == before
    pointer = http.CanonicalPublicationPointerModel.objects.get()
    assert str(pointer.activation_id) == grant.activation_id
    assert not CalendarRenewalReceipt.objects.exists()


@native_postgres_only
def test_receipt_write_failure_rolls_back_confirm_and_capture(world, monkeypatch):
    _, _, _, grant, sessions, _ = _seed(monkeypatch, http._calendar_body().replace(b"SSE", b"SZSE"))
    originals = http._source_counts(), http._formal_counts()
    PeriodicTask.objects.filter(name=f"szse-calendar-renewal-{grant.pk}").update(enabled=True)

    def fail_insert(self, *args, **kwargs):
        assert self.grant_id == grant.pk
        assert http.SystemAuditEventModel.objects.filter(event_id=self.event_id).exists()
        raise DatabaseError("injected failure after formal confirmation")

    monkeypatch.setattr(CalendarRenewalReceipt, "save", fail_insert)
    _await_due(grant, 5)
    result = _deliver(str(grant.pk))
    assert (result["outcome"], result["reason_code"], result["stored"]) == (
        "failed",
        "CALENDAR_RENEWAL_STORAGE_FAILURE",
        0,
    )
    assert len(sessions) == 2
    assert (http._source_counts(), http._formal_counts()) == originals
    assert (
        str(http.CanonicalPublicationPointerModel.objects.get().activation_id)
        == grant.activation_id
    )
    assert not CalendarRenewalReceipt.objects.exists()


@native_postgres_only
def test_concurrent_due_deliveries_publish_one_audited_successor(world, monkeypatch):
    _, owner, _, grant, sessions, _ = _seed(
        monkeypatch, http._calendar_body().replace(b"SSE", b"SZSE")
    )
    Session.objects.all().delete()
    before = http._formal_counts()
    _await_due(grant, 5)
    PeriodicTask.objects.filter(name=f"szse-calendar-renewal-{grant.pk}").update(enabled=True)
    barrier = Barrier(2)

    def deliver():
        close_old_connections()
        try:
            barrier.wait(10)
            return _deliver(str(grant.pk))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: deliver(), range(2)))
    assert sorted(r["outcome"] for r in results) == ["noop", "success"], results
    assert len(sessions) == 2
    receipt = CalendarRenewalReceipt.objects.get(grant=grant)
    assert receipt.previous_activation_id == grant.activation_id
    grant.refresh_from_db()
    assert receipt.activation_id == grant.activation_id
    audit = http.SystemAuditEventModel.objects.get(event_id=receipt.event_id)
    assert audit.actor_id == f"django-user:{owner.pk}"
    assert audit.content_hash == receipt.event_content_hash
    assert http.SystemAuditOutboxModel.objects.filter(pk=receipt.outbox_id).exists()
    assert http._formal_counts()[0] == before[0] + 1
    _await_due(grant, 5)
    assert _deliver(str(grant.pk), receipt.delivery_id)["reason_code"] == "already_renewed"
    assert len(sessions) == 2


@pytest.mark.skipif(
    not os.getenv("AGOM_SZSE_TEST_REDIS"), reason="dedicated loopback Redis required"
)
@native_postgres_only
def test_beat_delivers_due_renewal_to_isolated_worker(world, monkeypatch):
    from urllib.parse import urlsplit

    url = os.environ["AGOM_SZSE_TEST_REDIS"]
    assert urlsplit(url).hostname in {"127.0.0.1", "::1"}
    assert connection.settings_dict["NAME"] == connection.settings_dict["TEST"]["NAME"]
    _, _, _, grant, sessions, _ = _seed(
        monkeypatch, http._calendar_body().replace(b"SSE", b"SZSE"), ttl=8
    )
    app = Celery("szse-renewal-test", broker=url, backend=url, set_as_current=False)
    app.conf.update(task_default_queue=QUEUE, broker_connection_retry_on_startup=False)
    schedule = PeriodicTask.objects.get(name=f"szse-calendar-renewal-{grant.pk}")
    schedule.enabled = True
    schedule.last_run_at = timezone.now() - timedelta(minutes=2)
    schedule.save()
    try:
        with start_worker(app, pool="solo", queues=[QUEUE], perform_ping_check=False):
            _await_due(grant, 8)
            entry = ModelEntry(schedule, app=app)
            assert entry.is_due().is_due
            result = Scheduler(app=app, lazy=True).apply_async(entry)
            assert result.get(timeout=20)["outcome"] == "success"
        assert len(sessions) == 2
        assert CalendarRenewalReceipt.objects.filter(grant=grant).count() == 1
    finally:
        app.close()
