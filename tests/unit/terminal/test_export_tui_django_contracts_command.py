import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command

from apps.terminal.infrastructure.tui_contract_export import (
    export_tui_django_contract_manifest,
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
        field
        for field in terminal_command_model["fields"]
        if field["name"] == "command_type"
    )
    assert command_type_field["type"] == "CharField"
    assert command_type_field["choices"][0]["value"] == "prompt"

    terminal_command_aggregate = next(
        item
        for item in payload["aggregates"]
        if item["entity"] == "TerminalCommand"
    )
    parameters_field = next(
        field
        for field in terminal_command_aggregate["fields"]
        if field["name"] == "parameters"
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
