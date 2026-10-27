"""Validation helpers for action input fields in published TUI metadata."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_metadata_constants import (
    ALLOWED_TUI_FIELD_BINDINGS,
    ALLOWED_TUI_FIELD_INPUT_TYPES,
    ALLOWED_TUI_FIELD_PRESENTATION_SEMANTICS,
    ALLOWED_TUI_FIELD_VALUE_TYPES,
)
from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError

MAX_TUI_TEXT_FILE_BYTES = 2_097_152


def _validate_field(action: dict[str, Any], field: dict[str, Any]) -> None:
    """Validate and normalize one action field without changing its public shape."""
    field_key = str(field["key"])
    input_type = str(field["input_type"])
    if input_type not in ALLOWED_TUI_FIELD_INPUT_TYPES:
        raise TuiMetadataValidationError(
            f"Action field has unsupported input_type: {action['key']}.{field_key}.{input_type}"
        )

    if input_type == "number" and not field.get("value_type"):
        field["value_type"] = (
            "integer" if field_key.endswith("_id") or field_key == "pk" else "float"
        )
    if input_type == "checkbox" and not field.get("value_type"):
        field["value_type"] = "boolean"
    if input_type in {
        "text",
        "textarea",
        "hidden",
        "password",
        "select",
        "file",
    } and not field.get("value_type"):
        field["value_type"] = "string"

    value_type = field.get("value_type")
    if value_type and str(value_type) not in ALLOWED_TUI_FIELD_VALUE_TYPES:
        raise TuiMetadataValidationError(
            f"Action field has unsupported value_type: {action['key']}.{field_key}.{value_type}"
        )
    binding = field.get("binding")
    if binding and str(binding) not in ALLOWED_TUI_FIELD_BINDINGS:
        raise TuiMetadataValidationError(
            f"Action field has unsupported binding: {action['key']}.{field_key}.{binding}"
        )
    if input_type == "select" and not isinstance(field.get("options"), list):
        raise TuiMetadataValidationError(
            f"Select field must define options: {action['key']}.{field_key}"
        )
    if field.get("aliases") is not None and not _is_string_list(field.get("aliases")):
        raise TuiMetadataValidationError(
            f"Action field aliases must be a string list: {action['key']}.{field_key}"
        )
    if field.get("semantic") is not None and not isinstance(field.get("semantic"), str):
        raise TuiMetadataValidationError(
            f"Action field semantic must be a string: {action['key']}.{field_key}"
        )
    if field.get("accept") is not None and not isinstance(field.get("accept"), str):
        raise TuiMetadataValidationError(
            f"Action file field accept must be a string: {action['key']}.{field_key}"
        )
    field.setdefault("presentation_semantic", _default_field_presentation_semantic(field_key))
    presentation_semantic = str(field.get("presentation_semantic") or "")
    if presentation_semantic not in ALLOWED_TUI_FIELD_PRESENTATION_SEMANTICS:
        raise TuiMetadataValidationError(
            f"Action field has unsupported presentation_semantic: "
            f"{action['key']}.{field_key}.{presentation_semantic}"
        )
    if presentation_semantic == "prompt_text" and input_type != "textarea":
        raise TuiMetadataValidationError(
            f"Prompt field must use textarea: {action['key']}.{field_key}"
        )
    if presentation_semantic == "endpoint_url" and input_type != "text":
        raise TuiMetadataValidationError(
            f"Endpoint field must use text input: {action['key']}.{field_key}"
        )
    if (
        presentation_semantic in {"api_token", "endpoint_url", "prompt_text"}
        and str(field.get("value_type") or "") != "string"
    ):
        raise TuiMetadataValidationError(
            f"Sensitive/copyable field must use string value_type: {action['key']}.{field_key}"
        )


def _validate_file_input_contract(action: dict[str, Any], fields: list[dict[str, Any]]) -> None:
    """Validate paired opt-in file text and filename fields for one action."""
    action_key = str(action.get("key", ""))
    claimed_filename_fields: set[str] = set()
    for field in fields:
        has_filename_field = "file_name_field" in field
        has_max_bytes = "max_bytes" in field
        if not has_filename_field and not has_max_bytes:
            continue
        field_key = str(field.get("key", ""))
        if has_filename_field != has_max_bytes:
            raise TuiMetadataValidationError(
                f"File text capture requires file_name_field and max_bytes together: "
                f"{action_key}.{field_key}"
            )
        if field.get("input_type") != "file":
            raise TuiMetadataValidationError(
                f"File text capture requires a file input: {action_key}.{field_key}"
            )
        if field.get("value_type") != "string" or field.get("binding") != "body":
            raise TuiMetadataValidationError(
                f"File text capture must bind a string body field: {action_key}.{field_key}"
            )

        max_bytes = field.get("max_bytes")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= MAX_TUI_TEXT_FILE_BYTES
        ):
            raise TuiMetadataValidationError(
                f"File text capture max_bytes must be between 1 and 2097152: "
                f"{action_key}.{field_key}"
            )

        filename_key = field.get("file_name_field")
        if not isinstance(filename_key, str) or not filename_key.strip():
            raise TuiMetadataValidationError(
                f"File text capture filename target must be a non-empty field key: "
                f"{action_key}.{field_key}"
            )
        if filename_key == field_key:
            raise TuiMetadataValidationError(
                f"File text capture cannot target its own field: {action_key}.{field_key}"
            )
        if filename_key in claimed_filename_fields:
            raise TuiMetadataValidationError(
                f"File text capture filename target must be unique: " f"{action_key}.{filename_key}"
            )
        claimed_filename_fields.add(filename_key)

        target_fields = [candidate for candidate in fields if candidate.get("key") == filename_key]
        if len(target_fields) != 1:
            raise TuiMetadataValidationError(
                f"File text capture filename target must identify one action field: "
                f"{action_key}.{field_key}.{filename_key}"
            )
        target = target_fields[0]
        if (
            target.get("input_type") != "hidden"
            or target.get("value_type") != "string"
            or target.get("binding") != "body"
            or target.get("required") is not True
        ):
            raise TuiMetadataValidationError(
                f"File text capture filename target must be a required hidden string body field: "
                f"{action_key}.{filename_key}"
            )
        if target.get("default", "") != "":
            raise TuiMetadataValidationError(
                f"File text capture filename target cannot have a supplied default: "
                f"{action_key}.{filename_key}"
            )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _default_field_presentation_semantic(field_key: str) -> str:
    normalized = field_key.lower()
    if normalized in {"api_token", "access_token", "token_value", "display_token"} or any(
        token in normalized for token in ("secret", "api_key")
    ):
        return "api_token"
    if "endpoint" in normalized or normalized.endswith("_url") or normalized == "url":
        return "endpoint_url"
    if normalized.endswith("_id") or normalized in {"pk", "token_id"}:
        return "primary_selector"
    if normalized in {
        "prompt",
        "prompt_text",
        "prompt_body",
        "system_prompt",
        "user_prompt",
        "user_prompt_template",
    } or normalized.endswith("_prompt"):
        return "prompt_text"
    return "identifier"
