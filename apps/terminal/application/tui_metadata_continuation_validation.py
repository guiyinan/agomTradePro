"""Validate same-screen result-to-action continuation declarations."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_metadata_filter_validation import (
    TuiMetadataValidationError as TuiMetadataValidationError,
)


def _validate_result_continuations(
    *,
    actions: list[dict[str, Any]],
    screens: list[dict[str, Any]],
    action_by_key: dict[str, dict[str, Any]],
) -> None:
    """Validate exact same-screen result-to-action handoff declarations."""

    source_keys: set[str] = set()
    target_sources: dict[str, str] = {}
    for source in actions:
        if "result_continuation" not in source:
            continue
        source_key = str(source.get("key") or "")
        descriptor = source.get("result_continuation")
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "target_action_key",
            "field_map",
        }:
            raise TuiMetadataValidationError(
                f"Action result_continuation must contain target_action_key and field_map: "
                f"{source_key}"
            )
        target_key = descriptor.get("target_action_key")
        field_map = descriptor.get("field_map")
        if not isinstance(target_key, str) or not target_key.strip():
            raise TuiMetadataValidationError(
                f"Action result_continuation target_action_key must be non-empty: {source_key}"
            )
        if not isinstance(field_map, dict) or not field_map:
            raise TuiMetadataValidationError(
                f"Action result_continuation field_map must be a non-empty object: {source_key}"
            )
        if any(
            not isinstance(input_key, str)
            or not input_key.strip()
            or not isinstance(field_key, str)
            or not field_key.strip()
            for input_key, field_key in field_map.items()
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation field_map entries must be non-empty strings: "
                f"{source_key}"
            )
        if len(set(field_map.values())) != len(field_map):
            raise TuiMetadataValidationError(
                f"Action result_continuation target fields must be unique: {source_key}"
            )
        target = action_by_key.get(target_key)
        if target is None:
            raise TuiMetadataValidationError(
                f"Action result_continuation references unknown target: {source_key}.{target_key}"
            )
        if target_key == source_key:
            raise TuiMetadataValidationError(
                f"Action result_continuation cannot target itself: {source_key}"
            )
        if str(target.get("screen_key") or "") != str(source.get("screen_key") or ""):
            raise TuiMetadataValidationError(
                f"Action result_continuation target must stay on the same screen: "
                f"{source_key}.{target_key}"
            )
        if target_key in target_sources:
            raise TuiMetadataValidationError(
                f"Action result_continuation target must have one source: {target_key}"
            )
        if (
            not source.get("session_auth_required")
            or not target.get("session_auth_required")
            or str(source.get("method") or "GET").upper() == "GET"
            or str(target.get("method") or "GET").upper() == "GET"
            or str(source.get("risk") or "read") not in {"write", "admin", "unsafe"}
            or str(target.get("risk") or "read") not in {"write", "admin", "unsafe"}
            or not source.get("confirmation_required")
            or not target.get("confirmation_required")
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation requires authenticated, confirmed mutations: "
                f"{source_key}.{target_key}"
            )
        if str(source.get("audience") or "authenticated") != str(
            target.get("audience") or "authenticated"
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation source and target audiences must match: "
                f"{source_key}.{target_key}"
            )

        target_fields = {
            str(field.get("key") or ""): field
            for field in target.get("fields", [])
            if isinstance(field, dict)
        }
        for input_key, field_key in field_map.items():
            field = target_fields.get(field_key)
            if (
                field is None
                or field.get("input_type") != "hidden"
                or field.get("value_type") != "string"
                or field.get("required") is not True
                or str(field.get("binding") or "body") != "body"
                or field.get("presentation_semantic") != "api_token"
                or field.get("default") not in (None, "")
            ):
                raise TuiMetadataValidationError(
                    f"Action result_continuation must map to required hidden string token fields: "
                    f"{source_key}.{input_key}.{field_key}"
                )

        source_keys.add(source_key)
        target_sources[target_key] = source_key

    chained_targets = source_keys.intersection(target_sources)
    if chained_targets:
        target_key = sorted(chained_targets)[0]
        raise TuiMetadataValidationError(
            f"Action result_continuation cannot chain through another source: {target_key}"
        )

    continuation_keys = source_keys.union(target_sources)
    for screen in screens:
        for panel in screen.get("dashboard_panels", []):
            if not isinstance(panel, dict):
                continue
            for row_action in panel.get("row_actions", []):
                if not isinstance(row_action, dict):
                    continue
                action_key = str(row_action.get("action_key") or "")
                if action_key in continuation_keys:
                    raise TuiMetadataValidationError(
                        f"Dashboard row actions cannot carry result continuations: {action_key}"
                    )
