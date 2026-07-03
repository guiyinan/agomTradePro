from __future__ import annotations

from core.management.commands.celery_beat_windows import Command


def test_celery_beat_windows_starts_beat_with_database_scheduler(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_start(argv: list[str]) -> None:
        captured["argv"] = argv

    monkeypatch.setattr("core.celery.app.start", fake_start)

    Command().handle(loglevel="warning", scheduler="custom.Scheduler")

    assert captured["argv"] == [
        "beat",
        "--loglevel=warning",
        "--scheduler=custom.Scheduler",
    ]
