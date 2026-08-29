"""Pure helpers for published TUI metadata repository projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _append_unique_payloads(
    *,
    payloads: list[dict[str, Any]],
    additions: tuple[dict[str, Any], ...],
    replace_existing: bool = False,
) -> int:
    """Upsert payloads by unique key and return the number of changed items."""

    existing_index = {
        str(payload.get("key") or ""): index for index, payload in enumerate(payloads)
    }
    inserted = 0
    for addition in additions:
        addition_key = str(addition.get("key") or "")
        current_index = existing_index.get(addition_key)
        if current_index is not None:
            if replace_existing and payloads[current_index] != addition:
                payloads[current_index] = dict(addition)
                inserted += 1
            continue
        payloads.append(dict(addition))
        existing_index[addition_key] = len(payloads) - 1
        inserted += 1
    return inserted


def _apply_runtime_patch(
    action: dict[str, Any],
    patch: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Apply one runtime patch and report whether it changed the action."""

    updated = dict(action)
    changed = False
    for key, value in patch.items():
        if key == "view_model":
            current_view_model = dict(action.get("view_model") or {})
            merged_view_model = {
                **current_view_model,
                **dict(value or {}),
            }
            if merged_view_model != current_view_model:
                changed = True
            updated["view_model"] = merged_view_model
            continue
        if updated.get(key) != value:
            changed = True
        updated[key] = value
    return updated, changed


def payload_hash(payload: dict[str, Any]) -> str:
    """Return a deterministic hash for audit/diff checks."""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def changed_fields(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return top-level and action-level metadata changes for audit review."""

    if not previous:
        return ["initial_publish"]
    changes: list[str] = []
    for key in sorted(set(previous) | set(current)):
        if key == "actions":
            continue
        if previous.get(key) != current.get(key):
            changes.append(key)

    previous_actions = {
        str(action.get("key")): action
        for action in previous.get("actions", [])
        if isinstance(action, dict)
    }
    current_actions = {
        str(action.get("key")): action
        for action in current.get("actions", [])
        if isinstance(action, dict)
    }
    for key in sorted(set(previous_actions) - set(current_actions)):
        changes.append(f"actions.removed.{key}")
    for key in sorted(set(current_actions) - set(previous_actions)):
        changes.append(f"actions.added.{key}")
    for key in sorted(set(previous_actions) & set(current_actions)):
        if previous_actions[key] != current_actions[key]:
            changes.append(f"actions.changed.{key}")
    return changes


__all__ = [
    "_append_unique_payloads",
    "_apply_runtime_patch",
    "changed_fields",
    "payload_hash",
]
