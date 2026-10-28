"""Validate same-screen result-to-action continuation declarations."""

from __future__ import annotations

import re
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
    readback_sources: dict[str, str] = {}
    for source in actions:
        if "result_continuation" not in source:
            continue
        source_key = str(source.get("key") or "")
        descriptor = source.get("result_continuation")
        base_descriptor_keys = {"target_action_key", "field_map"}
        optional_descriptor_keys = {
            "reuse_source_idempotency_key",
            "readback_action_key",
            "readback_scope_map",
        }
        if (
            not isinstance(descriptor, dict)
            or not base_descriptor_keys.issubset(descriptor)
            or not set(descriptor).issubset(base_descriptor_keys.union(optional_descriptor_keys))
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation must contain target_action_key and field_map: "
                f"{source_key}"
            )
        reuse_source_key = descriptor.get("reuse_source_idempotency_key")
        readback_key = descriptor.get("readback_action_key")
        scope_map = descriptor.get("readback_scope_map", {})
        if "readback_scope_map" in descriptor and (
            source_key != "simulated-trading.fee-correction-preview"
            or scope_map != {"source_locator": "preview.source_locator"}
            or readback_key is None
        ):
            raise TuiMetadataValidationError("Fee readback scope must name only its public locator")
        if (
            ("reuse_source_idempotency_key" in descriptor and reuse_source_key is not True)
            or (
                "readback_action_key" in descriptor
                and (not isinstance(readback_key, str) or not readback_key.strip())
            )
            or (readback_key is not None and reuse_source_key is not True)
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation readback requires strict source-key reuse: "
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
        source_method = str(source.get("method") or "GET").upper()
        target_method = str(target.get("method") or "GET").upper()
        source_risk = str(source.get("risk") or "read")
        target_risk = str(target.get("risk") or "read")
        confirmed_mutation_risks = {"write", "admin", "unsafe"}
        source_is_read_preview = (
            source_method == "POST"
            and source_risk == "read"
            and str(source.get("effect") or "read") == "read"
            and not source.get("confirmation_required")
        )
        source_is_confirmed_mutation = (
            source_method == "POST"
            and source_risk in confirmed_mutation_risks
            and bool(source.get("confirmation_required"))
        )
        target_is_confirmed_mutation = (
            target_method == "POST"
            and target_risk in confirmed_mutation_risks
            and bool(target.get("confirmation_required"))
        )
        if (
            not source.get("session_auth_required")
            or not target.get("session_auth_required")
            or not (source_is_read_preview or source_is_confirmed_mutation)
            or not target_is_confirmed_mutation
        ):
            raise TuiMetadataValidationError(
                f"Action result_continuation requires an authenticated POST preview "
                f"or confirmed mutation and a confirmed POST target: {source_key}.{target_key}"
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
        optional_broker_preview_context = (
            source_key == "audit.manual-trade-import-preview"
            and target_key == "audit.manual-trade-import"
            and field_map
            == {
                "expected_fact_set_fingerprint": "expected_fact_set_fingerprint",
                "expected_balance_fingerprint": "expected_balance_fingerprint",
            }
        )
        for input_key, field_key in field_map.items():
            field = target_fields.get(field_key)
            required_for_continuation = not optional_broker_preview_context
            if (
                field is None
                or field.get("input_type") != "hidden"
                or field.get("value_type") != "string"
                or field.get("required") is not required_for_continuation
                or str(field.get("binding") or "body") != "body"
                or field.get("presentation_semantic") != "api_token"
                or field.get("default") not in (None, "")
            ):
                raise TuiMetadataValidationError(
                    f"Action result_continuation must map to hidden string token fields with "
                    f"the declared requirement: "
                    f"{source_key}.{input_key}.{field_key}"
                )

        if readback_key is not None:
            if source_method != "POST" or not source.get("session_auth_required"):
                raise TuiMetadataValidationError(
                    f"Action readback requires an authenticated POST source: {source_key}"
                )
            readback = action_by_key.get(readback_key)
            if readback is None or readback_key in readback_sources:
                raise TuiMetadataValidationError(
                    f"Action result_continuation readback must be a unique known action: "
                    f"{source_key}.{readback_key}"
                )
            readback_method = str(readback.get("method") or "GET").upper()
            if (
                readback_key in {source_key, target_key}
                or str(readback.get("screen_key") or "") != str(source.get("screen_key") or "")
                or readback_method != "GET"
                or str(readback.get("risk") or "read") != "read"
                or str(readback.get("effect") or "read") != "read"
                or not readback.get("session_auth_required")
                or bool(readback.get("confirmation_required"))
                or str(readback.get("audience") or "authenticated")
                != str(source.get("audience") or "authenticated")
            ):
                raise TuiMetadataValidationError(
                    f"Action readback must be an authenticated same-screen read-only GET: "
                    f"{source_key}.{readback_key}"
                )
            placeholder_pattern = re.compile(
                r"<(?:[A-Za-z_][A-Za-z0-9_]*:)?([A-Za-z_][A-Za-z0-9_]*)>"
            )
            target_path_field_list = placeholder_pattern.findall(str(target.get("endpoint") or ""))
            readback_path_field_list = placeholder_pattern.findall(
                str(readback.get("endpoint") or "")
            )
            target_path_fields = set(target_path_field_list)
            readback_path_fields = set(readback_path_field_list)
            readback_field_list = [
                field for field in readback.get("fields", []) if isinstance(field, dict)
            ]
            readback_fields = {str(field.get("key") or ""): field for field in readback_field_list}
            if (
                not target_path_fields
                or len(target_path_field_list) != len(target_path_fields)
                or len(readback_path_field_list) != len(readback_path_fields)
                or target_path_fields.union(scope_map) != readback_path_fields
                or target_path_fields.intersection(scope_map)
                or not target_path_fields.issubset(set(field_map.values()))
                or len(readback_field_list) != len(readback.get("fields", []))
                or len(readback_fields) != len(readback_field_list)
                or set(readback_fields) != readback_path_fields
            ):
                raise TuiMetadataValidationError(
                    f"Action readback must use the exact mapped target path scope: "
                    f"{source_key}.{readback_key}"
                )
            for field_key in readback_path_fields:
                field = readback_fields[field_key]
                if (
                    field.get("input_type") != "hidden"
                    or field.get("value_type") != "string"
                    or field.get("required") is not True
                    or str(field.get("binding") or "body") != "body"
                    or field.get("presentation_semantic") != "api_token"
                    or field.get("default") not in (None, "")
                ):
                    raise TuiMetadataValidationError(
                        f"Action readback path fields must be required hidden strings: "
                        f"{source_key}.{readback_key}.{field_key}"
                    )
            readback_sources[readback_key] = source_key

        source_keys.add(source_key)
        target_sources[target_key] = source_key

    chained_targets = source_keys.intersection(target_sources)
    if chained_targets:
        target_key = sorted(chained_targets)[0]
        raise TuiMetadataValidationError(
            f"Action result_continuation cannot chain through another source: {target_key}"
        )

    conflicting_readbacks = set(readback_sources).intersection(source_keys.union(target_sources))
    if conflicting_readbacks:
        readback_key = sorted(conflicting_readbacks)[0]
        raise TuiMetadataValidationError(
            f"Action continuation readback cannot also be a source or target: {readback_key}"
        )

    continuation_keys = source_keys.union(target_sources).union(readback_sources)
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
