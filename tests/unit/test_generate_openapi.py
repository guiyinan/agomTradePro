"""Contracts for the single OpenAPI generation and export entry point."""

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts import generate_openapi


@pytest.fixture
def generated_schema(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stand in for Django generation without loading routes or a database."""
    commands: list[list[str]] = []

    def run(command: list[str], *, cwd: Path, check: bool) -> CompletedProcess[str]:
        assert cwd == generate_openapi.REPO_ROOT
        assert check is False
        commands.append(command)
        output = Path(command[command.index("--file") + 1])
        payload = (
            '{"openapi": "3.0.3", "paths": {}}\n'
            if command[command.index("--format") + 1] == "openapi-json"
            else "openapi: 3.0.3\npaths: {}\n"
        )
        output.write_text(payload, encoding="utf-8")
        return CompletedProcess(command, 0)

    monkeypatch.setattr(generate_openapi.subprocess, "run", run)
    return commands


def test_default_generation_updates_only_canonical_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generated_schema: list[list[str]]
) -> None:
    output = tmp_path / "docs/testing/api/openapi.yaml"
    monkeypatch.setattr(generate_openapi, "DEFAULT_OUTPUT", output)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")

    assert generate_openapi.main([]) == 0

    assert output.read_text(encoding="utf-8") == "openapi: 3.0.3\npaths: {}\n"
    assert not (tmp_path / "schema.yml").exists()
    assert not output.with_suffix(".json").exists()
    assert len(generated_schema) == 1
    assert "--fail-on-warn" in generated_schema[0]
    assert generated_schema[0][-2:] == ["--settings", "core.settings.openapi"]


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [("openapi: 3.0.3\npaths: {}\n", 0), ("outdated\n", 1), (None, 1)],
)
def test_check_reports_drift_without_writing(
    tmp_path: Path,
    generated_schema: list[list[str]],
    content: str | None,
    expected_code: int,
) -> None:
    output = tmp_path / "openapi.yaml"
    if content is not None:
        output.write_text(content, encoding="utf-8", newline="\r\n")
    before = output.read_bytes() if output.exists() else None

    assert generate_openapi.main(["--check", "--output", str(output)]) == expected_code

    assert (output.read_bytes() if output.exists() else None) == before


@pytest.mark.parametrize("check_mode", [False, True])
def test_generation_failure_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check_mode: bool
) -> None:
    output = tmp_path / "openapi.yaml"
    output.write_text("existing schema\n", encoding="utf-8")

    def fail(command: list[str], *, cwd: Path, check: bool) -> CompletedProcess[str]:
        Path(command[command.index("--file") + 1]).write_text("partial", encoding="utf-8")
        return CompletedProcess(command, 2)

    monkeypatch.setattr(generate_openapi.subprocess, "run", fail)

    arguments = ["--output", str(output)]
    if check_mode:
        arguments.append("--check")
    assert generate_openapi.main(arguments) == 2
    assert output.read_text(encoding="utf-8") == "existing schema\n"


def test_json_export_uses_explicit_output_and_settings(
    tmp_path: Path, generated_schema: list[list[str]]
) -> None:
    output = tmp_path / "exports/tui_openapi.json"

    assert (
        generate_openapi.main(
            [
                "--format",
                "json",
                "--output",
                str(output),
                "--settings",
                "core.settings.development_sqlite",
            ]
        )
        == 0
    )

    assert output.read_text(encoding="utf-8") == '{"openapi": "3.0.3", "paths": {}}\n'
    assert generated_schema[0][-2:] == ["--settings", "core.settings.development_sqlite"]


def test_json_format_requires_explicit_output() -> None:
    with pytest.raises(SystemExit) as error:
        generate_openapi.main(["--format", "json"])
    assert error.value.code == 2


def test_json_export_cannot_overwrite_canonical_yaml() -> None:
    with pytest.raises(SystemExit) as error:
        generate_openapi.main(
            ["--format", "json", "--output", str(generate_openapi.DEFAULT_OUTPUT)]
        )
    assert error.value.code == 2
