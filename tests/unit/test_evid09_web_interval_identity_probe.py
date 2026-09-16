"""Read-only Docker Web identity selection and denial tests."""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts import evid09_web_interval_identity_probe as probe


def _result(body: str, *, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=body, stderr="secret")


def test_collect_identity_emits_only_selected_web_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect = [
        {
            "Image": "sha256:" + "a" * 64,
            "Config": {"Env": ["SECRET_KEY=do-not-emit"]},
            "State": {
                "StartedAt": "2026-09-15T18:00:00Z",
                "Status": "running",
                "Health": {"Status": "healthy"},
            },
        }
    ]
    seen: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return _result(
            json.dumps(inspect) if argv[1] == "inspect" else "b" * 64 + "  " + probe.MANIFEST + "\n"
        )

    monkeypatch.setattr(probe.subprocess, "run", run)
    report = probe.collect_identity()

    assert report["decision"] == "PASS_READ_ONLY"
    assert report["release_manifest_sha256"] == "b" * 64
    assert "do-not-emit" not in json.dumps(report)
    assert seen == [
        ["docker", "inspect", probe.WEB_CONTAINER],
        ["docker", "exec", probe.WEB_CONTAINER, "sha256sum", probe.MANIFEST],
    ]


@pytest.mark.parametrize(
    "inspect_body,manifest_body",
    [
        ("[]", "b" * 64 + "  " + probe.MANIFEST),
        (
            json.dumps([{"State": {}, "Image": "sha256:" + "a" * 64}]),
            "b" * 64 + "  " + probe.MANIFEST,
        ),
        (json.dumps([{"State": {"Health": {}}, "Image": "sha256:" + "a" * 64}]), "bad digest"),
    ],
)
def test_malformed_inspect_or_manifest_denied(
    monkeypatch: pytest.MonkeyPatch, inspect_body: str, manifest_body: str
) -> None:
    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _result(inspect_body if argv[1] == "inspect" else manifest_body)

    monkeypatch.setattr(probe.subprocess, "run", run)
    with pytest.raises(probe.WebIntervalIdentityError):
        probe.collect_identity()


def test_docker_command_failure_denied_without_leaking_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(probe.subprocess, "run", lambda argv, **kwargs: _result("", code=1))

    assert probe.main() == 1
    assert "secret" not in capsys.readouterr().err
