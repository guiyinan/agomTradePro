"""PostgreSQL connection-capacity projection contracts."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import OperationalError
from django.http import HttpRequest

from core import database_metrics, metrics


@dataclass
class _GaugeObservation:
    labels: dict[str, str]
    value: float


class _GaugeChild:
    def __init__(
        self,
        observations: list[_GaugeObservation],
        labels: dict[str, str],
    ) -> None:
        self._observations = observations
        self._labels = labels

    def set(self, value: float) -> None:
        self._observations.append(_GaugeObservation(labels=self._labels, value=float(value)))


class _Gauge:
    def __init__(self) -> None:
        self.observations: list[_GaugeObservation] = []

    def labels(self, **labels: str) -> _GaugeChild:
        return _GaugeChild(self.observations, labels)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row
        self.executed_sql = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def execute(self, sql: str) -> None:
        self.executed_sql = sql

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    vendor = "postgresql"

    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor


def test_postgresql_connection_snapshot_projects_usage_capacity_and_success(
    monkeypatch,
) -> None:
    """One scrape must publish real usage against non-reserved capacity."""

    cursor = _Cursor((2, 7, 1, 100, 3))
    connection_gauge = _Gauge()
    capacity_gauge = _Gauge()
    observation_gauge = _Gauge()
    monkeypatch.setattr(database_metrics, "connections", {"default": _Connection(cursor)})
    monkeypatch.setattr(metrics, "db_connections_total", connection_gauge)
    monkeypatch.setattr(metrics, "db_connection_capacity", capacity_gauge)
    monkeypatch.setattr(metrics, "db_connection_observation_up", observation_gauge)

    assert database_metrics.project_database_connection_metrics() is True

    assert "pg_stat_activity" in cursor.executed_sql
    assert "backend_type = 'client backend'" in cursor.executed_sql
    assert "current_setting('reserved_connections', true)" in cursor.executed_sql
    assert connection_gauge.observations == [
        _GaugeObservation({"database": "default", "status": "active"}, 2.0),
        _GaugeObservation({"database": "default", "status": "idle"}, 7.0),
        _GaugeObservation({"database": "default", "status": "other"}, 1.0),
    ]
    assert capacity_gauge.observations == [
        _GaugeObservation({"database": "default", "kind": "max"}, 100.0),
        _GaugeObservation({"database": "default", "kind": "reserved"}, 3.0),
        _GaugeObservation({"database": "default", "kind": "usable"}, 97.0),
    ]
    assert observation_gauge.observations == [_GaugeObservation({"database": "default"}, 1.0)]


def test_postgresql_connection_snapshot_failure_is_visible_and_redacted(
    monkeypatch,
    caplog,
) -> None:
    """A failed observation must export down without leaking DB credentials."""

    class BrokenConnection:
        vendor = "postgresql"

        def cursor(self) -> _Cursor:
            raise OperationalError("postgres://user:secret@db.internal/agom")

    observation_gauge = _Gauge()
    monkeypatch.setattr(database_metrics, "connections", {"default": BrokenConnection()})
    monkeypatch.setattr(metrics, "db_connection_observation_up", observation_gauge)

    with caplog.at_level(logging.WARNING, logger="core.database_metrics"):
        assert database_metrics.project_database_connection_metrics() is False

    assert observation_gauge.observations == [_GaugeObservation({"database": "default"}, 0.0)]
    assert "OperationalError" in caplog.text
    assert "secret" not in caplog.text
    assert "db.internal" not in caplog.text


def test_non_postgresql_database_skips_capacity_projection(monkeypatch) -> None:
    """Local SQLite must keep the generic metrics endpoint usable."""

    class SqliteConnection:
        vendor = "sqlite"

        def cursor(self) -> _Cursor:
            raise AssertionError("SQLite must not receive PostgreSQL catalog SQL")

    monkeypatch.setattr(database_metrics, "connections", {"default": SqliteConnection()})

    assert database_metrics.project_database_connection_metrics() is True


def test_shared_metrics_view_projects_database_capacity_before_export(monkeypatch) -> None:
    """The deployed scrape route must invoke the connection-capacity projector."""

    from apps.audit.application import repository_provider
    from core import urls

    calls: list[None] = []
    monkeypatch.setattr(
        database_metrics,
        "project_database_connection_metrics",
        lambda: calls.append(None) or True,
    )
    monkeypatch.setattr(
        repository_provider,
        "project_audit_outbox_backlog_metrics",
        lambda: True,
    )
    monkeypatch.setattr(urls, "generate_latest", lambda: b"# HELP db_metric\n")

    response = urls.metrics_view(HttpRequest())

    assert response.status_code == 200
    assert response.content == b"# HELP db_metric\n"
    assert calls == [None]
