"""Validate and project task navigation without introducing business routing rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError


class ExperienceEntry(TypedDict):
    """A passive navigation destination or a local safe-resume command."""

    key: str
    kind: Literal["screen", "resume"]
    label: str
    description: str
    screen_key: NotRequired[str]


class ExperienceMode(TypedDict):
    """One presentation mode, independent of business and security state."""

    key: Literal["task", "professional"]
    label: str
    entries: list[ExperienceEntry]


class Experience(TypedDict):
    """Server-owned task map whose destinations use canonical IA screen keys."""

    home_screen_key: str
    default_mode: Literal["task"]
    modes: list[ExperienceMode]
    utilities: list[ExperienceEntry]


def _text(source: Mapping[object, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"experience.{key} must be a nonempty string")
    return value


def _entries(
    raw: object, screen_keys: frozenset[str], *, allow_resume: bool
) -> list[ExperienceEntry]:
    if not isinstance(raw, list):
        raise ValueError("experience entries must be an array")
    entries: list[ExperienceEntry] = []
    keys: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("experience entry must be an object")
        kind = item.get("kind")
        if kind not in ("screen", "resume") or (kind == "resume" and not allow_resume):
            raise ValueError("experience entry has an invalid kind")
        expected = {"key", "kind", "label", "description"}
        if kind == "screen":
            expected.add("screen_key")
        if set(item) != expected:
            raise ValueError("experience entry has invalid fields")
        key = _text(item, "key")
        if key in keys:
            raise ValueError("experience entry keys must be unique")
        keys.add(key)
        entry: ExperienceEntry = {
            "key": key,
            "kind": "screen" if kind == "screen" else "resume",
            "label": _text(item, "label"),
            "description": _text(item, "description"),
        }
        if kind == "screen":
            screen_key = _text(item, "screen_key")
            if screen_key not in screen_keys:
                raise ValueError(f"experience references unknown screen {screen_key}")
            entry["screen_key"] = screen_key
        entries.append(entry)
    return entries


def validate_experience(raw: object, screen_keys: frozenset[str]) -> Experience:
    """Narrow untrusted JSON and reject duplicate, active or dangling destinations."""

    if not isinstance(raw, Mapping) or set(raw) != {
        "home_screen_key",
        "default_mode",
        "modes",
        "utilities",
    }:
        raise ValueError("experience has invalid fields")
    home = _text(raw, "home_screen_key")
    if home not in screen_keys or raw.get("default_mode") != "task":
        raise ValueError("experience home or default mode is invalid")
    raw_modes = raw.get("modes")
    if not isinstance(raw_modes, list) or len(raw_modes) != 2:
        raise ValueError("experience must define task and professional modes")
    modes: list[ExperienceMode] = []
    for expected_key, mode in zip(("task", "professional"), raw_modes, strict=True):
        if not isinstance(mode, Mapping) or set(mode) != {"key", "label", "entries"}:
            raise ValueError("experience mode has invalid fields")
        if mode.get("key") != expected_key:
            raise ValueError("experience mode order must be task, professional")
        entries = _entries(mode.get("entries"), screen_keys, allow_resume=False)
        if expected_key == "professional" and entries:
            raise ValueError("professional mode uses the complete authorized catalog")
        modes.append(
            {
                "key": "task" if expected_key == "task" else "professional",
                "label": _text(mode, "label"),
                "entries": entries,
            }
        )
    return {
        "home_screen_key": home,
        "default_mode": "task",
        "modes": modes,
        "utilities": _entries(raw.get("utilities"), screen_keys, allow_resume=True),
    }


def project_experience(
    raw: object, *, all_screen_keys: frozenset[str], visible_screen_keys: frozenset[str]
) -> Experience | None:
    """Return a fresh permission-filtered map without modifying cached metadata."""

    if raw is None:
        return None
    result = validate_experience(raw, all_screen_keys)
    if result["home_screen_key"] not in visible_screen_keys:
        return None
    for mode in result["modes"]:
        mode["entries"] = [
            entry for entry in mode["entries"] if entry.get("screen_key") in visible_screen_keys
        ]
    result["utilities"] = [
        entry
        for entry in result["utilities"]
        if entry["kind"] == "resume" or entry.get("screen_key") in visible_screen_keys
    ]
    return result


def validate_metadata_experience(payload: Mapping[str, object]) -> None:
    """Validate optional root navigation against the already normalized screen graph."""

    if "experience" not in payload:
        return
    screens = payload.get("screens")
    if not isinstance(screens, list):
        raise TuiMetadataValidationError("experience requires a screen graph")
    screen_keys = frozenset(
        str(screen["key"]) for screen in screens if isinstance(screen, Mapping) and "key" in screen
    )
    try:
        experience = validate_experience(payload["experience"], screen_keys)
        if experience["home_screen_key"] != payload.get("default_screen"):
            raise ValueError("experience home_screen_key must match default_screen")
    except ValueError as exc:
        raise TuiMetadataValidationError(str(exc)) from exc
