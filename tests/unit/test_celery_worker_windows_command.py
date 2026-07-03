from __future__ import annotations

import sys

from core.management.commands.celery_worker_windows import Command


def test_celery_worker_windows_starts_solo_worker_with_queue_and_hostname(
    monkeypatch,
) -> None:
    captured: dict[str, list[str]] = {}
    command = Command()
    parser = command.create_parser("manage.py", "celery_worker_windows")
    parsed = parser.parse_args(
        [
            "-Q",
            "celery,qlib_infer,qlib_train",
            "-n",
            "readiness@%h",
        ]
    )

    def fake_worker_main(argv: list[str]) -> None:
        captured["argv"] = argv

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("core.celery.app.worker_main", fake_worker_main)

    assert parsed.queues == "celery,qlib_infer,qlib_train"
    assert parsed.hostname == "readiness@%h"

    command.handle(
        loglevel="warning",
        concurrency=1,
        queues="celery,qlib_infer,qlib_train",
        hostname="readiness@%h",
    )

    assert captured["argv"] == [
        "worker",
        "--loglevel=warning",
        "--pool=solo",
        "--concurrency=1",
        "--queues=celery,qlib_infer,qlib_train",
        "--hostname=readiness@%h",
    ]


def test_celery_worker_windows_starts_prefork_worker_on_non_windows(
    monkeypatch,
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_worker_main(argv: list[str]) -> None:
        captured["argv"] = argv

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("core.celery.app.worker_main", fake_worker_main)

    Command().handle(
        loglevel="info",
        concurrency=2,
        queues=None,
        hostname=None,
    )

    assert captured["argv"] == [
        "worker",
        "--loglevel=info",
        "--pool=prefork",
        "--concurrency=2",
    ]
