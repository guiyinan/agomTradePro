"""Check the declarative, published, and runtime TUI metadata boundaries.

The check deliberately treats the Information Architecture registry as the
owner of published-screen copy.  Runtime injection may add runtime-only
screens and actions, but it must not replace the shared published-screen
semantic fields.  This is a read-only guard: it never publishes, repairs, or
mutates a metadata record.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISHED_PATH = (
    ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
)
DEFAULT_IA_PATH = ROOT / "config" / "tui" / "ia" / "tui_information_architecture.v1.json"

SCREEN_SEMANTIC_FIELDS = (
    "label",
    "summary",
    "user_experience",
    "business_context",
    "audience",
    "view_type",
    "group",
    "module_key",
)
RUNTIME_SCREEN_REQUIRED_FIELDS = ("summary", "user_experience", "default_action_key")
FORBIDDEN_USER_COPY_TERMS: tuple[tuple[str, str], ...] = (
    ("regime", "Regime"),
    ("prompt", "Prompt"),
    ("data_date", "数据日期"),
    ("observation_date", "观测日期"),
)


@dataclass(frozen=True)
class TuiMetadataConsistencyViolation:
    """One deterministic source-boundary violation."""

    rule_id: str
    message: str


@dataclass(frozen=True)
class TuiMetadataPatchBoundary:
    """Classify screen patches without recommending unsafe deletion."""

    configured_keys: tuple[str, ...]
    ignored_on_full_ia_payload: tuple[str, ...]
    not_in_ia_registry: tuple[str, ...]


@dataclass(frozen=True)
class TuiMetadataConsistencyReport:
    """Stable summary emitted by the source-boundary guard."""

    outcome: str
    published_screen_count: int
    runtime_screen_count: int
    published_action_count: int
    runtime_action_count: int
    violations: tuple[TuiMetadataConsistencyViolation, ...]
    patch_boundary: TuiMetadataPatchBoundary

    @property
    def passed(self) -> bool:
        """Return whether all source-boundary checks passed."""

        return not self.violations

    def as_json(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "outcome": self.outcome,
            "passed": self.passed,
            "published_screen_count": self.published_screen_count,
            "runtime_screen_count": self.runtime_screen_count,
            "published_action_count": self.published_action_count,
            "runtime_action_count": self.runtime_action_count,
            "violations": [asdict(item) for item in self.violations],
            "patch_boundary": asdict(self.patch_boundary),
        }


def _screen_map(payload: Mapping[str, Any], key: str) -> dict[str, dict[str, Any]]:
    """Return a screen mapping while ignoring malformed entries for reporting."""

    raw_screens = payload.get(key, [])
    if not isinstance(raw_screens, list):
        return {}
    return {
        str(screen.get("key")): dict(screen)
        for screen in raw_screens
        if isinstance(screen, Mapping) and str(screen.get("key") or "").strip()
    }


def _action_map(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return action entries keyed by their stable action key."""

    raw_actions = payload.get("actions", [])
    if not isinstance(raw_actions, list):
        return {}
    return {
        str(action.get("key")): dict(action)
        for action in raw_actions
        if isinstance(action, Mapping) and str(action.get("key") or "").strip()
    }


def _semantic_values(screen: Mapping[str, Any]) -> dict[str, Any]:
    """Project only user-facing screen fields owned by the IA registry."""

    return {field: screen.get(field) for field in SCREEN_SEMANTIC_FIELDS}


def _append_violation(
    violations: list[TuiMetadataConsistencyViolation],
    rule_id: str,
    message: str,
) -> None:
    """Append one violation with deterministic text."""

    violations.append(TuiMetadataConsistencyViolation(rule_id, message))


def _append_terminology_violations(
    violations: list[TuiMetadataConsistencyViolation],
    *,
    item_kind: str,
    entries: Mapping[str, Mapping[str, Any]],
) -> None:
    """Reject retired user-facing terminology in normalized runtime metadata."""

    for item_key, item in sorted(entries.items()):
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
        for term_key, forbidden_term in FORBIDDEN_USER_COPY_TERMS:
            if forbidden_term not in serialized:
                continue
            _append_violation(
                violations,
                f"terminology:{item_kind}:{item_key}:{term_key}",
                f"runtime {item_kind} copy contains retired term: {forbidden_term}",
            )


def _patch_boundary(
    patch_keys: Sequence[str],
    *,
    ia_published_keys: set[str],
    ia_runtime_keys: set[str],
) -> TuiMetadataPatchBoundary:
    """Report production filtering and preserve unknown patch provenance."""

    configured = tuple(sorted({str(key).strip() for key in patch_keys if str(key).strip()}))
    known_ia_keys = ia_published_keys | ia_runtime_keys
    return TuiMetadataPatchBoundary(
        configured_keys=configured,
        ignored_on_full_ia_payload=tuple(sorted(set(configured) & ia_published_keys)),
        not_in_ia_registry=tuple(sorted(set(configured) - known_ia_keys)),
    )


def check_tui_metadata_source_consistency(
    *,
    published_payload: Mapping[str, Any],
    ia_payload: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
    runtime_screen_patch_keys: Sequence[str] = (),
) -> TuiMetadataConsistencyReport:
    """Compare published JSON, IA registry, and normalized runtime payload."""

    violations: list[TuiMetadataConsistencyViolation] = []
    ia_published = _screen_map(ia_payload, "published_screens")
    ia_runtime = _screen_map(ia_payload, "runtime_screens")
    published = _screen_map(published_payload, "screens")
    runtime = _screen_map(runtime_payload, "screens")
    published_actions = _action_map(published_payload)
    runtime_actions = _action_map(runtime_payload)
    patch_boundary = _patch_boundary(
        runtime_screen_patch_keys,
        ia_published_keys=set(ia_published),
        ia_runtime_keys=set(ia_runtime),
    )

    expected_published_keys = set(ia_published)
    expected_runtime_keys = expected_published_keys | set(ia_runtime)

    if str(published_payload.get("ia_version") or "") != str(ia_payload.get("version") or ""):
        _append_violation(
            violations,
            "ia_version",
            "published ia_version does not match the IA registry version",
        )
    if set(published) != expected_published_keys:
        _append_violation(
            violations,
            "published_screen_set",
            "published JSON screen keys differ from IA published_screens",
        )
    if set(runtime) != expected_runtime_keys:
        _append_violation(
            violations,
            "runtime_screen_set",
            "runtime screen keys differ from IA published_screens + runtime_screens",
        )

    for screen_key in sorted(expected_published_keys):
        ia_screen = ia_published[screen_key]
        published_screen = published.get(screen_key)
        runtime_screen = runtime.get(screen_key)
        if published_screen is None or runtime_screen is None:
            continue
        expected = _semantic_values(ia_screen)
        if _semantic_values(published_screen) != expected:
            _append_violation(
                violations,
                f"published_screen_copy:{screen_key}",
                "published screen semantic fields differ from IA ownership",
            )
        if _semantic_values(runtime_screen) != expected:
            _append_violation(
                violations,
                f"runtime_screen_copy:{screen_key}",
                "runtime loader replaced IA-owned published screen copy",
            )

    for screen_key in sorted(ia_runtime):
        runtime_screen = runtime.get(screen_key)
        if runtime_screen is None:
            continue
        for field in RUNTIME_SCREEN_REQUIRED_FIELDS:
            value = runtime_screen.get(field)
            if field == "default_action_key":
                if not str(value or "").strip():
                    _append_violation(
                        violations,
                        f"runtime_screen_contract:{screen_key}",
                        "runtime screen is missing a default_action_key",
                    )
            elif not isinstance(value, (dict, str)) or not value:
                _append_violation(
                    violations,
                    f"runtime_screen_contract:{screen_key}",
                    f"runtime screen is missing {field}",
                )

    _append_terminology_violations(
        violations,
        item_kind="screen",
        entries=runtime,
    )
    _append_terminology_violations(
        violations,
        item_kind="action",
        entries=runtime_actions,
    )

    action_keys = set(runtime_actions)
    for action_key, action in sorted(runtime_actions.items()):
        screen_key = str(action.get("screen_key") or "")
        if screen_key not in runtime:
            _append_violation(
                violations,
                f"action_screen_reference:{action_key}",
                "runtime action references an unknown runtime screen",
            )
    for screen_key, screen in sorted(runtime.items()):
        panels = screen.get("dashboard_panels", [])
        if not isinstance(panels, list):
            continue
        for panel in panels:
            if not isinstance(panel, Mapping):
                continue
            action_key = str(panel.get("action_key") or "").strip()
            if action_key and action_key not in action_keys:
                _append_violation(
                    violations,
                    f"panel_action_reference:{screen_key}:{action_key}",
                    "runtime dashboard panel references an unknown action",
                )
            target_screen = str(panel.get("target_screen") or "").strip()
            if target_screen and target_screen not in runtime:
                _append_violation(
                    violations,
                    f"panel_screen_reference:{screen_key}:{target_screen}",
                    "runtime dashboard panel references an unknown target screen",
                )

    if len(published_actions) != len(published_payload.get("actions", [])):
        _append_violation(
            violations,
            "published_action_keys",
            "published JSON contains duplicate or malformed action keys",
        )
    if len(runtime_actions) != len(runtime_payload.get("actions", [])):
        _append_violation(
            violations,
            "runtime_action_keys",
            "runtime payload contains duplicate or malformed action keys",
        )

    return TuiMetadataConsistencyReport(
        outcome="ok" if not violations else "blocked",
        published_screen_count=len(published),
        runtime_screen_count=len(runtime),
        published_action_count=len(published_actions),
        runtime_action_count=len(runtime_actions),
        violations=tuple(violations),
        patch_boundary=patch_boundary,
    )


def load_json_payload(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"metadata payload must be an object: {path}")
    return payload


def load_runtime_payload(published_path: Path) -> dict[str, Any]:
    """Load the normalized runtime graph through the real repository path."""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    import django

    django.setup()
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    return PublishedTuiMetadataRepository(published_path=published_path)._load_published_file()


def build_report(
    *,
    published_path: Path = DEFAULT_PUBLISHED_PATH,
    ia_path: Path = DEFAULT_IA_PATH,
) -> TuiMetadataConsistencyReport:
    """Load all three sources and return the read-only consistency report."""

    published_payload = load_json_payload(published_path)
    ia_payload = load_json_payload(ia_path)
    runtime_payload = load_runtime_payload(published_path)
    from apps.terminal.infrastructure.tui_metadata_runtime_constants import (
        RUNTIME_SCREEN_PATCHES,
    )

    return check_tui_metadata_source_consistency(
        published_payload=published_payload,
        ia_payload=ia_payload,
        runtime_payload=runtime_payload,
        runtime_screen_patch_keys=tuple(RUNTIME_SCREEN_PATCHES),
    )


def main() -> int:
    """Run the source-boundary check and emit stable JSON."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, default=DEFAULT_PUBLISHED_PATH)
    parser.add_argument("--ia", type=Path, default=DEFAULT_IA_PATH)
    args = parser.parse_args()
    report = build_report(published_path=args.published, ia_path=args.ia)
    print(json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
