import json
import tempfile
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.terminal.infrastructure.tui_contract_export import (
    export_tui_django_contract_manifest,
    write_tui_django_contract_manifest,
)


def test_export_tui_django_contract_manifest_returns_code_owned_contracts():
    payload = export_tui_django_contract_manifest()

    assert payload["host_kind"] == "django"
    assert payload["app_labels"] == ["terminal"]
    assert len(payload["models"]) >= 4
    assert len(payload["aggregates"]) == 2

    terminal_command_model = next(
        item for item in payload["models"] if item["model"] == "TerminalCommandORM"
    )
    command_type_field = next(
        field for field in terminal_command_model["fields"] if field["name"] == "command_type"
    )
    assert command_type_field["type"] == "CharField"
    assert command_type_field["choices"][0]["value"] == "prompt"

    terminal_command_aggregate = next(
        item for item in payload["aggregates"] if item["entity"] == "TerminalCommand"
    )
    parameters_field = next(
        field for field in terminal_command_aggregate["fields"] if field["name"] == "parameters"
    )
    assert parameters_field["value_type"] == "list"
    assert parameters_field["required"] is False


def test_export_tui_django_contracts_command_writes_manifest():
    output_dir = Path(tempfile.mkdtemp(prefix="agomtui-contract-export-"))
    output_path = output_dir / "tui_django_contracts.json"
    stdout = StringIO()

    call_command(
        "export_tui_django_contracts",
        "--output",
        str(output_path),
        stdout=stdout,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["host_kind"] == "django"
    assert any(item["model"] == "TuiMetadataRegistryORM" for item in payload["models"])
    assert any(item["entity"] == "TerminalAuditEntry" for item in payload["aggregates"])
    assert "models=" in stdout.getvalue()


def test_export_tui_contract_manifest_honors_explicit_empty_scope() -> None:
    payload = export_tui_django_contract_manifest(
        app_labels=[],
        model_paths=[],
        domain_class_paths=[],
    )

    assert payload["app_labels"] == []
    assert payload["models"] == []
    assert payload["aggregates"] == []


def test_export_tui_contract_manifest_rejects_non_model_and_non_dataclass_paths() -> None:
    constant_path = (
        "apps.terminal.infrastructure.tui_contract_export." "DEFAULT_TUI_CONTRACT_APP_LABELS"
    )
    with pytest.raises(TypeError, match="not a Django model"):
        export_tui_django_contract_manifest(
            app_labels=[],
            model_paths=[constant_path],
            domain_class_paths=[],
        )
    with pytest.raises(TypeError, match="not a dataclass"):
        export_tui_django_contract_manifest(
            app_labels=[],
            model_paths=[],
            domain_class_paths=[constant_path],
        )


@pytest.mark.parametrize("indent", [True, False, -1, 9])
def test_write_tui_contract_manifest_rejects_invalid_indent_before_write(
    tmp_path: Path,
    indent: int,
) -> None:
    output_path = tmp_path / "contract.json"

    with pytest.raises(ValueError, match="between 0 and 8"):
        write_tui_django_contract_manifest(output_path, indent=indent)

    assert not output_path.exists()


def test_explicit_model_and_domain_paths_are_deduplicated() -> None:
    baseline = export_tui_django_contract_manifest()
    model_path = baseline["models"][0]["module"]
    domain_path = "apps.terminal.domain.entities.TerminalCommand"

    payload = export_tui_django_contract_manifest(
        app_labels=[],
        model_paths=[model_path, model_path],
        domain_class_paths=[domain_path, domain_path],
    )

    assert len(payload["models"]) == 1
    assert len(payload["aggregates"]) == 1
