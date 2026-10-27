"""Field-level contracts for safe opt-in TUI text-file capture."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from apps.terminal.application import tui_metadata
from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError

ROOT = Path(__file__).resolve().parents[3]
MAX_FILE_BYTES = 1_048_576
MAX_TEXT_FILE_BYTES = 2_097_152


def _valid_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "csv_text",
            "label": "费用文件",
            "input_type": "file",
            "value_type": "string",
            "binding": "body",
            "required": True,
            "file_name_field": "original_filename",
            "max_bytes": MAX_FILE_BYTES,
        },
        {
            "key": "original_filename",
            "label": "文件名",
            "input_type": "hidden",
            "value_type": "string",
            "binding": "body",
            "required": True,
            "default": "",
        },
    ]


def _validate(action: dict[str, Any], fields: list[dict[str, Any]]) -> None:
    validator = getattr(tui_metadata, "_validate_file_input_contract", None)
    assert callable(validator), "file-input contract validator must be available"
    validator(action, fields)


def test_file_input_contract_accepts_explicit_body_name_pair_and_legacy_file() -> None:
    action = {"key": "simulated-trading.fee-correction-preview"}
    fields = _valid_fields()

    _validate(action, fields)
    _validate(action, [{"key": "legacy_file", "input_type": "file", "value_type": "string"}])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fields: fields[0].pop("max_bytes"),
        lambda fields: fields[0].pop("file_name_field"),
        lambda fields: fields[0].update(input_type="text"),
        lambda fields: fields[0].update(value_type="bytes"),
        lambda fields: fields[0].update(binding="query"),
        lambda fields: fields[0].update(max_bytes=True),
        lambda fields: fields[0].update(max_bytes=0),
        lambda fields: fields[0].update(max_bytes=MAX_TEXT_FILE_BYTES + 1),
        lambda fields: fields[0].update(file_name_field="csv_text"),
        lambda fields: fields[0].update(file_name_field="missing"),
        lambda fields: fields[1].update(input_type="text"),
        lambda fields: fields[1].update(value_type="integer"),
        lambda fields: fields[1].update(binding="query"),
        lambda fields: fields[1].update(required=False),
        lambda fields: fields[1].update(default="forged.csv"),
        lambda fields: fields.append(
            {
                "key": "second_file",
                "input_type": "file",
                "value_type": "string",
                "binding": "body",
                "file_name_field": "original_filename",
                "max_bytes": MAX_FILE_BYTES,
            }
        ),
        lambda fields: fields.append({**fields[1]}),
    ],
)
def test_file_input_contract_rejects_bad_pair_targets_and_overrides(
    mutate: Callable[[list[dict[str, Any]]], object],
) -> None:
    fields = deepcopy(_valid_fields())
    mutate(fields)

    with pytest.raises(TuiMetadataValidationError):
        _validate({"key": "simulated-trading.fee-correction-preview"}, fields)


def test_schema_requires_pair_and_limits_file_field_contract() -> None:
    schema_path = ROOT / "config" / "tui" / "schema" / "tui_metadata.schema.v3.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema["$defs"]["field"])
    file_field = {
        "key": "csv_text",
        "label": "费用文件",
        "input_type": "file",
        "value_type": "string",
        "binding": "body",
        "file_name_field": "original_filename",
        "max_bytes": MAX_FILE_BYTES,
    }
    validator.validate(file_field)
    for invalid in (
        {key: value for key, value in file_field.items() if key != "max_bytes"},
        {key: value for key, value in file_field.items() if key != "file_name_field"},
        {**file_field, "input_type": "text"},
        {**file_field, "value_type": "object"},
        {**file_field, "binding": "query"},
        {**file_field, "max_bytes": MAX_TEXT_FILE_BYTES + 1},
    ):
        with pytest.raises(ValidationError):
            validator.validate(invalid)
