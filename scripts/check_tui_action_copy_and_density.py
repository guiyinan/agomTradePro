"""Check TUX-03 user-facing action copy, action split, and density budgets.

The guard treats the 12 Information Architecture ``published_screens`` as the
TUX-03 exit scope.  The normalized runtime graph is used to verify inherited
action tiers and same-screen label uniqueness, but runtime-only screens do not
silently expand the repository unit's density budget.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_tui_metadata_source_consistency import (
    DEFAULT_IA_PATH,
    DEFAULT_PUBLISHED_PATH,
    load_json_payload,
    load_runtime_payload,
)

ROUTE_ACTION_PREFIXES = ("auto.api.", "param.api.")
ROUTE_COPY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api-path", re.compile(r"/api/", re.IGNORECASE)),
    ("auto-action-key", re.compile(r"\bauto\.api\b", re.IGNORECASE)),
    ("parameterized-action-key", re.compile(r"\bparam\.api\b", re.IGNORECASE)),
    ("http-method", re.compile(r"(?:^|\s)(?:GET|POST)(?:$|\s)", re.IGNORECASE)),
    ("route-placeholder", re.compile(r"(?:\{[^{}]+\}|<[^<>]+>)")),
)
MACHINE_COPY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("celery-health", re.compile(r"^Celery\s+健康$")),
    ("unified-by", re.compile(r"\bUnified\s+By\b")),
    ("db-token", re.compile(r"(?:^|\s)Db$")),
    ("mcp-self", re.compile(r"\bMcp\s+Self\b")),
    ("mcp-tool", re.compile(r"\bMcp\s+Tool\b")),
    ("mcp-access-truncation", re.compile(r"\bMcp\s+Acce(?:\s|$)")),
    ("prompt-plural-suffix", re.compile(r"提示词s(?:\s|/|$)")),
    ("category-truncation", re.compile(r"\bCategorie(?:\s|$)")),
    ("allocation-truncation", re.compile(r"全部ocation")),
    ("english-plural-or-version", re.compile(r"\b(?:Policie|Version)\b")),
)
BOILERPLATE_SUFFIXES = ("（查看）", "（需确认）", "（交互）")
BUDGETED_TASK_TIERS = {"primary", "operation"}


@dataclass(frozen=True)
class TuiActionCopyDensityViolation:
    """One deterministic TUX-03 copy or density violation."""

    rule_id: str
    message: str
    screen_key: str = ""
    action_key: str = ""


@dataclass(frozen=True)
class TuiTaskGroupDensity:
    """One task group's budgeted action count."""

    task_group: str
    primary_operation_count: int
    limit: int

    @property
    def over_limit_by(self) -> int:
        """Return the number of actions above the group budget."""

        return max(0, self.primary_operation_count - self.limit)


@dataclass(frozen=True)
class TuiScreenActionDensity:
    """One published screen's normalized runtime density measurement."""

    screen_key: str
    primary_operation_count: int
    primary_operation_limit: int
    task_groups: tuple[TuiTaskGroupDensity, ...]

    @property
    def over_limit_by(self) -> int:
        """Return the number of actions above the screen budget."""

        return max(0, self.primary_operation_count - self.primary_operation_limit)


@dataclass(frozen=True)
class TuiActionCopyDensityReport:
    """Stable machine-readable TUX-03 report."""

    outcome: str
    published_screen_count: int
    published_action_count: int
    runtime_action_count: int
    route_action_count: int
    exposed_route_action_count: int
    boilerplate_description_count: int
    read_boilerplate_description_count: int
    machine_copy_count: int
    machine_copy_pattern_count: int
    published_duplicate_label_group_count: int
    runtime_duplicate_label_group_count: int
    route_default_reference_count: int
    route_panel_reference_count: int
    over_budget_screen_count: int
    over_budget_task_group_count: int
    screen_densities: tuple[TuiScreenActionDensity, ...]
    violations: tuple[TuiActionCopyDensityViolation, ...]

    @property
    def passed(self) -> bool:
        """Return whether every TUX-03 machine rule passed."""

        return not self.violations

    def as_json(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""

        return {
            "outcome": self.outcome,
            "passed": self.passed,
            "published_screen_count": self.published_screen_count,
            "published_action_count": self.published_action_count,
            "runtime_action_count": self.runtime_action_count,
            "route_action_count": self.route_action_count,
            "exposed_route_action_count": self.exposed_route_action_count,
            "boilerplate_description_count": self.boilerplate_description_count,
            "read_boilerplate_description_count": self.read_boilerplate_description_count,
            "machine_copy_count": self.machine_copy_count,
            "machine_copy_pattern_count": self.machine_copy_pattern_count,
            "published_duplicate_label_group_count": (self.published_duplicate_label_group_count),
            "runtime_duplicate_label_group_count": self.runtime_duplicate_label_group_count,
            "route_default_reference_count": self.route_default_reference_count,
            "route_panel_reference_count": self.route_panel_reference_count,
            "over_budget_screen_count": self.over_budget_screen_count,
            "over_budget_task_group_count": self.over_budget_task_group_count,
            "screen_densities": [
                {
                    "screen_key": density.screen_key,
                    "primary_operation_count": density.primary_operation_count,
                    "primary_operation_limit": density.primary_operation_limit,
                    "over_limit_by": density.over_limit_by,
                    "task_groups": [
                        {
                            **asdict(group),
                            "over_limit_by": group.over_limit_by,
                        }
                        for group in density.task_groups
                    ],
                }
                for density in self.screen_densities
            ],
            "violations": [asdict(item) for item in self.violations],
        }


def _items(payload: Mapping[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    """Return well-formed mapping items from one payload collection."""

    raw_items = payload.get(key, [])
    if not isinstance(raw_items, list):
        return ()
    return tuple(dict(item) for item in raw_items if isinstance(item, Mapping))


def _screen_map(payload: Mapping[str, Any], key: str) -> dict[str, dict[str, Any]]:
    """Return screen records keyed by non-empty screen key."""

    return {
        str(screen.get("key")): screen
        for screen in _items(payload, key)
        if str(screen.get("key") or "").strip()
    }


def _is_route_action_key(value: str) -> bool:
    """Return whether an action identifier was derived from an API route."""

    return value.startswith(ROUTE_ACTION_PREFIXES)


def _append_violation(
    violations: list[TuiActionCopyDensityViolation],
    *,
    rule_id: str,
    message: str,
    screen_key: str = "",
    action_key: str = "",
) -> None:
    """Append one deterministic violation."""

    violations.append(
        TuiActionCopyDensityViolation(
            rule_id=rule_id,
            message=message,
            screen_key=screen_key,
            action_key=action_key,
        )
    )


def _normalized_label(value: Any) -> str:
    """Normalize a user-visible label for same-screen duplicate checks."""

    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _duplicate_label_groups(
    actions: Sequence[Mapping[str, Any]],
    *,
    published_screen_keys: set[str],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return exact same-screen label collisions in the published-screen scope."""

    grouped: defaultdict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for action in actions:
        screen_key = str(action.get("screen_key") or "").strip()
        label = str(action.get("label") or "").strip()
        normalized = _normalized_label(label)
        action_key = str(action.get("key") or "").strip()
        if screen_key not in published_screen_keys or not normalized or not action_key:
            continue
        grouped[(screen_key, normalized)].append((action_key, label))

    duplicates: list[tuple[str, str, tuple[str, ...]]] = []
    for (screen_key, _), entries in sorted(grouped.items()):
        action_keys = tuple(sorted({action_key for action_key, _ in entries}))
        if len(action_keys) < 2:
            continue
        label = sorted({label for _, label in entries})[0]
        duplicates.append((screen_key, label, action_keys))
    return tuple(duplicates)


def _density_limits(ia_payload: Mapping[str, Any]) -> tuple[int, dict[str, int], int]:
    """Return the reviewed IA screen and task-group density limits."""

    raw_density = ia_payload.get("action_density", {})
    density = dict(raw_density) if isinstance(raw_density, Mapping) else {}
    default_limit = int(density.get("default_primary_operation_limit") or 0)
    raw_screen_limits = density.get("screen_limits", {})
    screen_limits = (
        {str(key): int(value) for key, value in raw_screen_limits.items() if str(key).strip()}
        if isinstance(raw_screen_limits, Mapping)
        else {}
    )
    task_group_limit = int(density.get("task_group_limit") or 0)
    return default_limit, screen_limits, task_group_limit


def _screen_densities(
    *,
    published_screen_keys: set[str],
    runtime_actions: Sequence[Mapping[str, Any]],
    default_limit: int,
    screen_limits: Mapping[str, int],
    task_group_limit: int,
) -> tuple[TuiScreenActionDensity, ...]:
    """Measure normalized runtime actions for each IA-published screen."""

    actions_by_screen: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for action in runtime_actions:
        screen_key = str(action.get("screen_key") or "").strip()
        if screen_key in published_screen_keys:
            actions_by_screen[screen_key].append(action)

    densities: list[TuiScreenActionDensity] = []
    for screen_key in sorted(published_screen_keys):
        budgeted = [
            action
            for action in actions_by_screen.get(screen_key, [])
            if str(action.get("task_tier") or "primary").strip().lower() in BUDGETED_TASK_TIERS
        ]
        group_counts = Counter(
            str(action.get("task_group") or "未分组").strip() or "未分组" for action in budgeted
        )
        groups = tuple(
            TuiTaskGroupDensity(
                task_group=group,
                primary_operation_count=count,
                limit=task_group_limit,
            )
            for group, count in sorted(group_counts.items())
        )
        densities.append(
            TuiScreenActionDensity(
                screen_key=screen_key,
                primary_operation_count=len(budgeted),
                primary_operation_limit=int(screen_limits.get(screen_key, default_limit)),
                task_groups=groups,
            )
        )
    return tuple(densities)


def check_tui_action_copy_and_density(
    *,
    published_payload: Mapping[str, Any],
    ia_payload: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
) -> TuiActionCopyDensityReport:
    """Evaluate the complete TUX-03 repository exit contract."""

    violations: list[TuiActionCopyDensityViolation] = []
    published_screens = _screen_map(ia_payload, "published_screens")
    published_screen_keys = set(published_screens)
    published_actions = _items(published_payload, "actions")
    runtime_actions = _items(runtime_payload, "actions")
    published_screen_summaries = {
        screen_key: str(screen.get("summary") or "").strip()
        for screen_key, screen in published_screens.items()
    }

    route_action_keys: set[str] = set()
    exposed_route_action_keys: set[str] = set()
    boilerplate_action_keys: set[str] = set()
    read_boilerplate_action_keys: set[str] = set()
    machine_copy_action_keys: set[str] = set()
    machine_copy_pattern_ids: set[str] = set()

    for action in sorted(published_actions, key=lambda item: str(item.get("key") or "")):
        action_key = str(action.get("key") or "").strip()
        screen_key = str(action.get("screen_key") or "").strip()
        label = str(action.get("label") or "").strip()
        description = str(action.get("description") or "").strip()
        task_tier = str(action.get("task_tier") or "primary").strip().lower()

        if _is_route_action_key(action_key):
            route_action_keys.add(action_key)
            if task_tier in BUDGETED_TASK_TIERS:
                exposed_route_action_keys.add(action_key)
                _append_violation(
                    violations,
                    rule_id="action_split:promoted_route_exposed",
                    message=(
                        "route-derived action must be support/advanced or replaced by a "
                        "curated semantic action"
                    ),
                    screen_key=screen_key,
                    action_key=action_key,
                )

        for field_name, copy_value in (("label", label), ("description", description)):
            for fragment_id, pattern in ROUTE_COPY_PATTERNS:
                if not pattern.search(copy_value):
                    continue
                _append_violation(
                    violations,
                    rule_id="action_copy:route_fragment",
                    message=f"{field_name} exposes route fragment {fragment_id}",
                    screen_key=screen_key,
                    action_key=action_key,
                )

        summary = published_screen_summaries.get(screen_key, "")
        if summary and any(description == f"{summary}{suffix}" for suffix in BOILERPLATE_SUFFIXES):
            boilerplate_action_keys.add(action_key)
            if description.endswith("（查看）"):
                read_boilerplate_action_keys.add(action_key)
            _append_violation(
                violations,
                rule_id="action_copy:boilerplate_description",
                message="description repeats the screen summary instead of this action's task",
                screen_key=screen_key,
                action_key=action_key,
            )

        for pattern_id, pattern in MACHINE_COPY_PATTERNS:
            if not pattern.search(label):
                continue
            machine_copy_action_keys.add(action_key)
            machine_copy_pattern_ids.add(pattern_id)
            _append_violation(
                violations,
                rule_id=f"action_copy:machine_fragment:{pattern_id}",
                message=f"label contains machine-generated fragment {pattern_id}",
                screen_key=screen_key,
                action_key=action_key,
            )

    published_duplicates = _duplicate_label_groups(
        published_actions,
        published_screen_keys=published_screen_keys,
    )
    runtime_duplicates = _duplicate_label_groups(
        runtime_actions,
        published_screen_keys=published_screen_keys,
    )
    for source_name, duplicates in (
        ("published", published_duplicates),
        ("runtime", runtime_duplicates),
    ):
        for screen_key, label, action_keys in duplicates:
            _append_violation(
                violations,
                rule_id=f"duplicate_label:{source_name}",
                message=f"same-screen label {label!r} is shared by: {', '.join(action_keys)}",
                screen_key=screen_key,
            )

    route_default_reference_count = 0
    route_panel_reference_count = 0
    for screen_key, screen in sorted(published_screens.items()):
        default_action_key = str(screen.get("default_action_key") or "").strip()
        if _is_route_action_key(default_action_key):
            route_default_reference_count += 1
            _append_violation(
                violations,
                rule_id="screen_reference:route_default",
                message="published screen default_action_key uses a route-derived action key",
                screen_key=screen_key,
                action_key=default_action_key,
            )
        panels = screen.get("dashboard_panels", [])
        if not isinstance(panels, list):
            continue
        for panel in panels:
            if not isinstance(panel, Mapping):
                continue
            action_key = str(panel.get("action_key") or "").strip()
            if not _is_route_action_key(action_key):
                continue
            route_panel_reference_count += 1
            _append_violation(
                violations,
                rule_id="screen_reference:route_panel",
                message="published dashboard panel uses a route-derived action key",
                screen_key=screen_key,
                action_key=action_key,
            )

    default_limit, screen_limits, task_group_limit = _density_limits(ia_payload)
    if default_limit <= 0 or task_group_limit <= 0:
        _append_violation(
            violations,
            rule_id="density:configuration",
            message="IA action_density limits must be positive integers",
        )
    densities = _screen_densities(
        published_screen_keys=published_screen_keys,
        runtime_actions=runtime_actions,
        default_limit=default_limit,
        screen_limits=screen_limits,
        task_group_limit=task_group_limit,
    )
    over_budget_screen_count = 0
    over_budget_task_group_count = 0
    for density in densities:
        if density.over_limit_by > 0:
            over_budget_screen_count += 1
            _append_violation(
                violations,
                rule_id="density:screen_limit",
                message=(
                    f"primary+operation count {density.primary_operation_count} exceeds "
                    f"limit {density.primary_operation_limit}"
                ),
                screen_key=density.screen_key,
            )
        for group in density.task_groups:
            if group.over_limit_by <= 0:
                continue
            over_budget_task_group_count += 1
            _append_violation(
                violations,
                rule_id="density:task_group_limit",
                message=(
                    f"task group {group.task_group!r} has {group.primary_operation_count} "
                    f"primary+operation actions; limit is {group.limit}"
                ),
                screen_key=density.screen_key,
            )

    ordered_violations = tuple(
        sorted(
            violations,
            key=lambda item: (
                item.rule_id,
                item.screen_key,
                item.action_key,
                item.message,
            ),
        )
    )
    return TuiActionCopyDensityReport(
        outcome="ok" if not ordered_violations else "blocked",
        published_screen_count=len(published_screen_keys),
        published_action_count=len(published_actions),
        runtime_action_count=len(runtime_actions),
        route_action_count=len(route_action_keys),
        exposed_route_action_count=len(exposed_route_action_keys),
        boilerplate_description_count=len(boilerplate_action_keys),
        read_boilerplate_description_count=len(read_boilerplate_action_keys),
        machine_copy_count=len(machine_copy_action_keys),
        machine_copy_pattern_count=len(machine_copy_pattern_ids),
        published_duplicate_label_group_count=len(published_duplicates),
        runtime_duplicate_label_group_count=len(runtime_duplicates),
        route_default_reference_count=route_default_reference_count,
        route_panel_reference_count=route_panel_reference_count,
        over_budget_screen_count=over_budget_screen_count,
        over_budget_task_group_count=over_budget_task_group_count,
        screen_densities=densities,
        violations=ordered_violations,
    )


def build_report(
    *,
    published_path: Path = DEFAULT_PUBLISHED_PATH,
    ia_path: Path = DEFAULT_IA_PATH,
) -> TuiActionCopyDensityReport:
    """Load real TUI sources and return the read-only TUX-03 report."""

    published_payload = load_json_payload(published_path)
    ia_payload = load_json_payload(ia_path)
    runtime_payload = load_runtime_payload(published_path)
    return check_tui_action_copy_and_density(
        published_payload=published_payload,
        ia_payload=ia_payload,
        runtime_payload=runtime_payload,
    )


def main() -> int:
    """Run the TUX-03 guard and emit stable JSON."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, default=DEFAULT_PUBLISHED_PATH)
    parser.add_argument("--ia", type=Path, default=DEFAULT_IA_PATH)
    args = parser.parse_args()
    report = build_report(published_path=args.published, ia_path=args.ia)
    print(json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
