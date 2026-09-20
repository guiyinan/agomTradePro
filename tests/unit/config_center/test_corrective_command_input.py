"""Input-boundary regressions for the corrective Config Center command."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError

from apps.config_center.management.commands import activate_runtime_profile_corrective


def _options(patch_file: Path) -> dict[str, object]:
    """Return the common dry-run options used by command input tests."""

    return {
        "environment": "production",
        "patch_file": str(patch_file),
        "actor": "config-review",
        "reason": "input boundary test",
        "release_ref": "",
        "execute": False,
        "expected_profile_id": "",
        "expected_profile_version": None,
        "expected_profile_hash": "",
        "expected_snapshot_hash": "",
    }


def _write_json(path: Path, payload: object) -> None:
    """Write one UTF-8 JSON fixture without exposing values through output."""

    path.write_text(json.dumps(payload), encoding="utf-8")


def test_secret_ref_only_envelope_defaults_patch_to_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A secret-only structured envelope must not become a normal definition patch."""

    patch_file = tmp_path / "secret-only.json"
    secret_ref = "secret://provider/v17"
    _write_json(patch_file, {"secret_ref_patch": {"provider.key": secret_ref}})
    captured: dict[str, object] = {}

    def _preview(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"valid": True, "changed_keys": ("provider.key",)}

    monkeypatch.setattr(
        activate_runtime_profile_corrective,
        "preview_runtime_profile_patch",
        _preview,
    )
    command = activate_runtime_profile_corrective.Command()
    command.stdout = StringIO()

    command.handle(**_options(patch_file))

    assert captured["patch"] == {}
    assert captured["secret_ref_patch"] == {"provider.key": secret_ref}
    assert secret_ref not in command.stdout.getvalue()


@pytest.mark.parametrize(
    "patch_file_name, contents",
    (
        ("invalid.json", "{not-json"),
        ("missing.json", None),
    ),
)
def test_invalid_or_missing_patch_file_is_reported_as_command_error(
    patch_file_name: str,
    contents: str | None,
    tmp_path: Path,
) -> None:
    """File and JSON decoding failures must use Django's command error boundary."""

    patch_file = tmp_path / patch_file_name
    if contents is not None:
        patch_file.write_text(contents, encoding="utf-8")

    command = activate_runtime_profile_corrective.Command()
    command.stdout = StringIO()

    with pytest.raises(CommandError):
        command.handle(**_options(patch_file))


def test_structured_envelope_rejects_unknown_fields_without_echoing_secret_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Envelope typos must fail closed and keep secret-reference values out of errors."""

    patch_file = tmp_path / "unknown-field.json"
    secret_ref = "secret://provider/v17"
    _write_json(
        patch_file,
        {
            "patch": {"audit.mode": "on"},
            "secret_ref_patch": {"provider.key": secret_ref},
            "secret_ref_pach": {"provider.key": secret_ref},
        },
    )
    monkeypatch.setattr(
        activate_runtime_profile_corrective,
        "preview_runtime_profile_patch",
        lambda **_: {"valid": True},
    )
    command = activate_runtime_profile_corrective.Command()
    command.stdout = StringIO()

    with pytest.raises(CommandError) as error:
        command.handle(**_options(patch_file))

    message = str(error.value)
    assert "secret_ref_pach" in message
    assert secret_ref not in message
