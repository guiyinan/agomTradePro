"""Private TUX10 acceptance audit for effective TUI surface placement.

This future pytest is intentionally read-only at the product boundary: it uses
the composed published metadata repository and authenticated GETs to the real
catalog and screen-detail APIs. It never posts or executes a TUI action. The
JSON artifact contains a safe projection, not raw API bodies or input defaults.
Action task reuse requires an explicit screen action reference associated with
a projected task entry and that role's action-detail visibility; screen
membership alone only categorizes the screen.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pytest

_CATALOG_PATH = "/api/tui/catalog/"
_SCREEN_PATH = "/api/tui/screens/{screen_key}/"
_SURFACES = frozenset(
    {
        "task_reuse",
        "professional_retained",
        "admin_governance",
        "review_dedupe",
    }
)


def _objects(source: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    """Return a required list of JSON objects without silently dropping rows."""

    value = source.get(field)
    assert isinstance(value, list), f"metadata field {field!r} must be a list"
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        assert isinstance(item, Mapping), f"{field}[{index}] must be an object"
        result.append(item)
    return result


def _key(source: Mapping[str, Any], field: str = "key") -> str:
    """Return a nonempty string key from a metadata object."""

    value = source.get(field)
    assert isinstance(value, str) and value.strip(), f"missing {field!r} key"
    return value


def _label(source: Mapping[str, Any]) -> str:
    """Return only the curated display label, never descriptions or values."""

    value = source.get("label")
    return value.strip() if isinstance(value, str) else ""


def _index_by_key(
    items: Sequence[Mapping[str, Any]], *, inventory_name: str
) -> dict[str, Mapping[str, Any]]:
    """Index a metadata inventory and reject duplicate or missing keys."""

    result: dict[str, Mapping[str, Any]] = {}
    for item in items:
        key = _key(item)
        assert key not in result, f"duplicate {inventory_name} key: {key}"
        result[key] = item
    return result


def _catalog_screens(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Flatten only the real catalog's grouped screen projection."""

    result: dict[str, Mapping[str, Any]] = {}
    for group in _objects(catalog, "groups"):
        for module in _objects(group, "modules"):
            for screen in _objects(module, "screens"):
                key = _key(screen)
                assert key not in result, f"duplicate catalog screen key: {key}"
                result[key] = screen
    return result


def _mode(experience: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Find one named task/professional mode in validated experience metadata."""

    modes = _objects(experience, "modes")
    matches = [item for item in modes if item.get("key") == key]
    assert len(matches) == 1, f"experience must contain exactly one {key!r} mode"
    return matches[0]


def _entry_keys(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return ordered entry keys for comparing metadata with API projections."""

    return [_key(entry) for entry in entries]


def _assert_experience_projection(
    raw_experience: Mapping[str, Any],
    catalog: Mapping[str, Any],
    visible_screen_keys: frozenset[str],
) -> None:
    """Check the real catalog filters task/professional/utilities by screen access."""

    expected_home_visible = raw_experience.get("home_screen_key") in visible_screen_keys
    projected = catalog.get("experience")
    if not expected_home_visible:
        assert projected is None
        return

    assert isinstance(projected, Mapping), "visible task home must publish experience"
    assert projected.get("home_screen_key") == raw_experience.get("home_screen_key")
    assert projected.get("default_mode") == raw_experience.get("default_mode") == "task"

    for mode_key in ("task", "professional"):
        raw_mode = _mode(raw_experience, mode_key)
        actual_mode = _mode(projected, mode_key)
        raw_entries = _objects(raw_mode, "entries")
        actual_entries = _objects(actual_mode, "entries")
        expected_keys = [
            _key(entry) for entry in raw_entries if entry.get("screen_key") in visible_screen_keys
        ]
        assert _entry_keys(actual_entries) == expected_keys
        if mode_key == "professional":
            assert not raw_entries, "professional mode must use the full authorized catalog"
            assert not actual_entries

    raw_utilities = _objects(raw_experience, "utilities")
    actual_utilities = _objects(projected, "utilities")
    expected_utility_keys = [
        _key(entry)
        for entry in raw_utilities
        if entry.get("kind") == "resume" or entry.get("screen_key") in visible_screen_keys
    ]
    assert _entry_keys(actual_utilities) == expected_utility_keys


def _digest(value: object) -> str:
    """Hash canonical JSON for one already-sanitized evidence object."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _with_record_hash(record: dict[str, Any]) -> dict[str, Any]:
    """Add a digest of a safe record projection, excluding raw metadata values."""

    record["record_sha256"] = _digest(record)
    return record


def _screen_panel_refs(
    screen: Mapping[str, Any],
    action_keys: frozenset[str],
    screen_keys: frozenset[str],
) -> tuple[list[str], list[str], list[str]]:
    """Collect and validate safe panel, action, and destination references."""

    panels_raw = screen.get("dashboard_panels")
    if panels_raw is None:
        return [], [], []
    assert isinstance(panels_raw, list), "dashboard_panels must be a list"
    panel_keys: list[str] = []
    panel_key_set: set[str] = set()
    for panel in panels_raw:
        assert isinstance(panel, Mapping), "dashboard panel must be an object"
        panel_key = panel.get("key")
        if isinstance(panel_key, str) and panel_key:
            assert panel_key not in panel_key_set, "duplicate dashboard panel key"
            panel_key_set.add(panel_key)
            panel_keys.append(panel_key)

    panel_action_keys: list[str] = []
    target_screen_keys: list[str] = []
    for panel in panels_raw:
        action_key = panel.get("action_key")
        if isinstance(action_key, str) and action_key:
            assert action_key in action_keys, f"dangling dashboard action reference: {action_key}"
            panel_action_keys.append(action_key)
        target_screen = panel.get("target_screen")
        if isinstance(target_screen, str) and target_screen:
            assert (
                target_screen in screen_keys
            ), f"dangling dashboard screen reference: {target_screen}"
            target_screen_keys.append(target_screen)
        row_actions = panel.get("row_actions") or []
        assert isinstance(row_actions, list), "dashboard row_actions must be a list"
        for row_action in row_actions:
            assert isinstance(row_action, Mapping), "dashboard row action must be an object"
            row_action_key = row_action.get("action_key")
            if isinstance(row_action_key, str) and row_action_key:
                assert (
                    row_action_key in action_keys
                ), f"dangling dashboard row action reference: {row_action_key}"
                panel_action_keys.append(row_action_key)
            for panel_ref_name in ("result_panel_key", "refresh_panel_key"):
                panel_ref = row_action.get(panel_ref_name)
                if isinstance(panel_ref, str) and panel_ref:
                    assert (
                        panel_ref in panel_key_set
                    ), f"dangling dashboard panel reference: {panel_ref}"
    return (
        sorted(panel_keys),
        sorted(set(panel_action_keys)),
        sorted(set(target_screen_keys)),
    )


def _action_references(screen: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Collect explicit action references after dangling-reference checks."""

    references: list[dict[str, Any]] = []
    configured_default = screen.get("default_action_key")
    if isinstance(configured_default, str) and configured_default:
        references.append(
            {
                "reference_kind": "screen_default_action_key",
                "panel_key": None,
                "action_key": configured_default,
                "reference_key_stable": True,
            }
        )

    panels = screen.get("dashboard_panels") or []
    assert isinstance(panels, list), "dashboard_panels must be a list"
    for panel in panels:
        assert isinstance(panel, Mapping), "dashboard panel must be an object"
        panel_key_value = panel.get("key")
        panel_key = (
            panel_key_value if isinstance(panel_key_value, str) and panel_key_value else None
        )
        action_value = panel.get("action_key")
        if isinstance(action_value, str) and action_value:
            references.append(
                {
                    "reference_kind": "dashboard_panel_action_key",
                    "panel_key": panel_key,
                    "action_key": action_value,
                    "reference_key_stable": panel_key is not None,
                }
            )

        row_actions = panel.get("row_actions") or []
        assert isinstance(row_actions, list), "dashboard row_actions must be a list"
        for row_action_index, row_action in enumerate(row_actions):
            assert isinstance(row_action, Mapping), "dashboard row action must be an object"
            action_value = row_action.get("action_key")
            if not isinstance(action_value, str) or not action_value:
                continue
            references.append(
                {
                    "reference_kind": "dashboard_row_action_key",
                    "panel_key": panel_key,
                    "action_key": action_value,
                    "reference_key_stable": panel_key is not None,
                    "row_action_index": row_action_index,
                }
            )
    return references


def _workflow_neighbor(
    screen: Mapping[str, Any],
    relation: str,
    screen_keys: frozenset[str],
    aliases: Mapping[str, str],
) -> dict[str, Any] | None:
    """Resolve a workflow reference without discarding its declared key."""

    workflow = screen.get("workflow")
    if not isinstance(workflow, Mapping):
        return None
    neighbor = workflow.get(relation)
    if not isinstance(neighbor, Mapping):
        return None
    key = neighbor.get("key")
    if not isinstance(key, str) or not key:
        return None
    canonical_key = aliases.get(key, key)
    if canonical_key in screen_keys:
        resolution_status = "legacy_alias" if canonical_key != key else "canonical"
        resolution_basis = (
            "effective_metadata_legacy_screen_aliases"
            if resolution_status == "legacy_alias"
            else "effective_metadata_canonical_screen_key"
        )
        resolved_key: str | None = canonical_key
    else:
        resolution_status = "dangling_pending_review"
        resolution_basis = "no_canonical_screen_or_declared_legacy_alias_target"
        resolved_key = None
    return {
        "declared_key": key,
        "canonical_screen_key": resolved_key,
        "resolution_status": resolution_status,
        "resolution_basis": resolution_basis,
    }


def _review_state(surface: str, direct_link_only: bool) -> str | None:
    """Name direct-link-only or otherwise unmounted items for human review."""

    if direct_link_only:
        return "direct_link_only_pending_review"
    if surface == "review_dedupe":
        return "not_mounted_or_not_visible_pending_review"
    return None


def _artifact_path(settings: Any) -> tuple[Path, str]:
    """Allocate a unique, non-overwriting TUX10 artifact destination."""

    configured_root = getattr(settings, "TUX10_ARTIFACT_ROOT", None)
    if configured_root:
        root = Path(str(configured_root))
    else:
        root = Path(settings.BASE_DIR) / ".tmp" / "tux10-integrated-next-prep" / "artifacts"
    requested_label = os.environ.get("TUX10_RUN_LABEL", "surface-inventory")
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", requested_label).strip("._-")
    label = (label or "surface-inventory")[:48]
    artifact_id = f"{label}-{uuid4().hex}"
    return root / f"tux10-surface-inventory-{artifact_id}.json", artifact_id


@pytest.mark.django_db
def test_tux10_surface_inventory(django_user_model: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Export a safe, role-filtered inventory of every effective screen and action."""

    from django.conf import settings
    from django.test import Client

    from apps.terminal.application.repository_provider import get_tui_metadata_repository

    network_attempts: list[str] = []

    def reject_network(*_args: object, **_kwargs: object) -> None:
        network_attempts.append("blocked_network_operation")
        raise AssertionError("Metadata inventory attempted network I/O")

    # API Client is in-process and SQLite is local. This guard starts after
    # Django initialization and is not a process-wide initialization claim.
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)

    repository = get_tui_metadata_repository()
    metadata = repository.load_published("default")
    assert isinstance(metadata, Mapping)

    groups = _index_by_key(_objects(metadata, "groups"), inventory_name="group")
    modules = _index_by_key(_objects(metadata, "modules"), inventory_name="module")
    screens = _index_by_key(_objects(metadata, "screens"), inventory_name="screen")
    actions = _index_by_key(_objects(metadata, "actions"), inventory_name="action")
    screen_keys = frozenset(screens)
    action_keys = frozenset(actions)
    assert groups and modules and screens and actions

    aliases = metadata.get("legacy_screen_aliases") or {}
    assert isinstance(aliases, Mapping), "legacy_screen_aliases must be an object"
    for alias, canonical in aliases.items():
        assert isinstance(alias, str) and isinstance(canonical, str)
        assert canonical in screens, f"legacy screen alias has a dangling target: {alias}"

    assert metadata.get("default_screen") in screen_keys
    for module_key, module in modules.items():
        group_key = module.get("group")
        assert group_key in groups, f"module {module_key} has a dangling group reference"
    screen_module_keys: dict[str, str] = {}
    screen_group_keys: dict[str, str] = {}
    screen_action_refs: dict[str, list[dict[str, Any]]] = {}
    for screen_key, screen in screens.items():
        module_key = screen.get("module_key")
        assert module_key in modules, f"screen {screen_key} has a dangling module reference"
        screen_module_keys[screen_key] = str(module_key)
        screen_group_keys[screen_key] = str(modules[str(module_key)].get("group"))
        default_action_key = screen.get("default_action_key")
        if isinstance(default_action_key, str) and default_action_key:
            assert (
                default_action_key in actions
            ), f"screen {screen_key} has a dangling default action reference"
        _screen_panel_refs(screen, action_keys, screen_keys)
        screen_action_refs[screen_key] = _action_references(screen)
    for action_key, action in actions.items():
        screen_key = action.get("screen_key")
        assert screen_key in screens, f"action {action_key} has a dangling screen reference"
        module_key = action.get("module_key")
        if isinstance(module_key, str) and module_key:
            assert module_key in modules, f"action {action_key} has a dangling module reference"

    raw_experience = metadata.get("experience")
    assert isinstance(raw_experience, Mapping), "effective metadata must define task experience"
    task_mode = _mode(raw_experience, "task")
    professional_mode = _mode(raw_experience, "professional")
    task_entries = _objects(task_mode, "entries")
    assert not _objects(professional_mode, "entries")
    task_entry_targets: dict[str, list[str]] = {}
    task_entry_records: list[dict[str, Any]] = []
    entry_keys: set[str] = set()
    for entry in task_entries:
        entry_key = _key(entry)
        assert entry_key not in entry_keys, f"duplicate task entry key: {entry_key}"
        entry_keys.add(entry_key)
        target = entry.get("screen_key")
        assert (
            isinstance(target, str) and target in screens
        ), f"task entry {entry_key} has a dangling canonical screen reference"
        assert (
            aliases.get(target, target) == target
        ), f"task entry {entry_key} must point to a canonical professional screen"
        task_entry_targets.setdefault(target, []).append(entry_key)
        task_entry_records.append(
            {
                "key": entry_key,
                "label": _label(entry),
                "kind": entry.get("kind"),
                "professional_screen_key": target,
            }
        )

    task_entry_action_refs_by_action: dict[str, list[dict[str, Any]]] = {}
    for screen_key, target_entry_keys in task_entry_targets.items():
        for reference in screen_action_refs[screen_key]:
            action_key = str(reference["action_key"])
            for entry_key in target_entry_keys:
                task_entry_action_refs_by_action.setdefault(action_key, []).append(
                    {
                        "entry_key": entry_key,
                        "screen_key": screen_key,
                        "action_key": action_key,
                        "reference_kind": reference["reference_kind"],
                        "panel_key": reference["panel_key"],
                        "row_action_index": reference.get("row_action_index"),
                        "reference_key_stable": reference["reference_key_stable"],
                        "link_basis": (
                            "task_entry_target_screen_plus_explicit_screen_action_reference"
                        ),
                        "reference_evidence_scope": "effective_metadata_declaration",
                        "browser_execution_asserted": False,
                    }
                )

    # These are fresh, identified Django users; the catalog and detail reads go
    # through the real API composition used by the application.
    user_token = uuid4().hex
    user = django_user_model.objects.create_user(
        username=f"tux10-inventory-user-{user_token}", password=uuid4().hex
    )
    admin = django_user_model.objects.create_superuser(
        username=f"tux10-inventory-admin-{user_token}",
        email=f"tux10-inventory-admin-{user_token}@example.invalid",
        password=uuid4().hex,
    )
    assert user.is_staff is False and user.is_superuser is False
    assert admin.is_staff is True and admin.is_superuser is True
    principals = {"user": user, "admin": admin}
    catalog_screen_keys: dict[str, frozenset[str]] = {}
    detail_status: dict[str, dict[str, int]] = {role: {} for role in principals}
    detail_action_keys: dict[str, dict[str, frozenset[str]]] = {role: {} for role in principals}
    role_snapshots: dict[str, dict[str, Any]] = {}
    api_reads: list[tuple[str, str]] = []

    for role, principal in principals.items():
        client = Client()
        client.force_login(principal)
        response = client.get(_CATALOG_PATH)
        api_reads.append((role, "catalog"))
        assert response.headers.get("Content-Type", "").split(";", 1)[0] == "application/json"
        assert response.status_code == 200, f"{role} catalog did not return 200"
        catalog = response.json()
        assert isinstance(catalog, Mapping)
        catalog_index = _catalog_screens(catalog)
        visible_catalog_keys = frozenset(catalog_index)
        catalog_screen_keys[role] = visible_catalog_keys
        diagnostics = catalog.get("diagnostics")
        assert isinstance(diagnostics, Mapping)
        raw_response_allowed = diagnostics.get("raw_response_allowed")
        assert isinstance(raw_response_allowed, bool)
        assert raw_response_allowed is (role == "admin"), (
            "raw diagnostic response policy must be withheld from the normal user "
            "and granted to the identified superuser"
        )

        for screen_key in sorted(screens):
            path = _SCREEN_PATH.format(screen_key=quote(screen_key, safe=""))
            detail_response = client.get(path)
            api_reads.append((role, "screen_detail"))
            assert (
                detail_response.headers.get("Content-Type", "").split(";", 1)[0]
                == "application/json"
            )
            assert detail_response.status_code in (200, 403), (
                f"effective screen {screen_key} returned unexpected detail status "
                f"{detail_response.status_code} for {role}"
            )
            detail_status[role][screen_key] = detail_response.status_code
            if detail_response.status_code == 200:
                detail = detail_response.json()
                assert isinstance(detail, Mapping)
                detail_screen = detail.get("screen")
                assert isinstance(detail_screen, Mapping)
                assert detail_screen.get("key") == screen_key
                visible_actions = _objects(detail, "actions")
                visible_keys: set[str] = set()
                for visible_action in visible_actions:
                    visible_key = _key(visible_action)
                    assert (
                        visible_key in actions
                    ), f"{role} detail exposed an action outside effective metadata"
                    assert (
                        visible_key not in visible_keys
                    ), f"{role} detail duplicated action {visible_key}"
                    assert actions[visible_key].get("screen_key") == screen_key
                    visible_keys.add(visible_key)
                detail_action_keys[role][screen_key] = frozenset(visible_keys)
            else:
                detail_action_keys[role][screen_key] = frozenset()
                assert (
                    screen_key not in visible_catalog_keys
                ), f"forbidden screen {screen_key} remains in {role} catalog"

        assert visible_catalog_keys.issubset(
            {key for key, status_code in detail_status[role].items() if status_code == 200}
        ), f"{role} catalog contains a screen forbidden by its detail API"

        _assert_experience_projection(raw_experience, catalog, visible_catalog_keys)
        actual_experience = catalog.get("experience")
        actual_task_entry_keys: list[str] = []
        actual_professional_entry_keys: list[str] = []
        if isinstance(actual_experience, Mapping):
            actual_task_mode = _mode(actual_experience, "task")
            actual_task_entry_keys = _entry_keys(_objects(actual_task_mode, "entries"))
            actual_professional_mode = _mode(actual_experience, "professional")
            actual_professional_entry_keys = _entry_keys(
                _objects(actual_professional_mode, "entries")
            )
        assert not actual_professional_entry_keys
        expected_task_entry_keys = [
            _key(entry) for entry in task_entries if entry.get("screen_key") in visible_catalog_keys
        ]
        assert actual_task_entry_keys == expected_task_entry_keys
        detail_authorized_keys = sorted(
            key for key, status_code in detail_status[role].items() if status_code == 200
        )
        role_snapshots[role] = {
            "is_staff": bool(principal.is_staff),
            "is_superuser": bool(principal.is_superuser),
            "catalog_screen_keys": sorted(visible_catalog_keys),
            "professional_catalog_screen_keys": sorted(visible_catalog_keys),
            "professional_mode_entry_keys": actual_professional_entry_keys,
            "detail_authorized_screen_keys": detail_authorized_keys,
            "direct_link_only_screen_keys": sorted(
                key for key in detail_authorized_keys if key not in visible_catalog_keys
            ),
            "task_entry_keys": actual_task_entry_keys,
            "diagnostics_raw_response_allowed": raw_response_allowed,
        }

    assert all(kind in {"catalog", "screen_detail"} for _, kind in api_reads)
    assert len(api_reads) == 2 * (1 + len(screens))
    admin_raw_response_allowed = bool(role_snapshots["admin"]["diagnostics_raw_response_allowed"])
    visible_task_entry_keys = {
        entry_key
        for snapshot in role_snapshots.values()
        for entry_key in snapshot["task_entry_keys"]
    }
    visible_task_entry_targets = {
        str(entry["screen_key"])
        for entry in task_entries
        if entry.get("key") in visible_task_entry_keys and isinstance(entry.get("screen_key"), str)
    }

    screen_records: list[dict[str, Any]] = []
    workflow_review_findings: list[dict[str, Any]] = []
    for screen_key, screen in screens.items():
        module_key = screen_module_keys[screen_key]
        group_key = screen_group_keys[screen_key]
        panel_keys, panel_action_keys, panel_target_screen_keys = _screen_panel_refs(
            screen, action_keys, screen_keys
        )
        user_detail = detail_status["user"][screen_key] == 200
        admin_detail = detail_status["admin"][screen_key] == 200
        catalog_visible_any = any(screen_key in catalog_screen_keys[role] for role in principals)
        direct_link_only_roles = [
            role
            for role in principals
            if detail_status[role][screen_key] == 200
            and screen_key not in catalog_screen_keys[role]
        ]
        workflow_references = {
            "previous": _workflow_neighbor(screen, "previous", screen_keys, aliases),
            "next": _workflow_neighbor(screen, "next", screen_keys, aliases),
        }
        for relation, reference in workflow_references.items():
            if (
                reference is not None
                and reference["resolution_status"] == "dangling_pending_review"
            ):
                workflow_review_findings.append(
                    {
                        "surface": "review_dedupe",
                        "finding_kind": "dangling_workflow_screen_reference",
                        "screen_key": screen_key,
                        "relation": relation,
                        **reference,
                        "review_state": "dangling_reference_pending_review",
                    }
                )
        if screen.get("audience") == "admin" or (admin_detail and not user_detail):
            surface = "admin_governance"
            surface_basis = "admin_audience_or_actual_role_filter"
        elif screen_key in visible_task_entry_targets:
            surface = "task_reuse"
            surface_basis = "catalog_projected_task_mode_entry"
        elif catalog_visible_any:
            surface = "professional_retained"
            surface_basis = "actual_professional_catalog_membership"
        else:
            surface = "review_dedupe"
            surface_basis = (
                "direct_link_only_pending_review"
                if user_detail or admin_detail
                else "not_visible_pending_review"
            )
        assert surface in _SURFACES
        screen_records.append(
            _with_record_hash(
                {
                    "key": screen_key,
                    "label": _label(screen),
                    "surface": surface,
                    "surface_basis": surface_basis,
                    "audience_policy": screen.get("audience"),
                    "status_policy": screen.get("status"),
                    "view_type": screen.get("view_type"),
                    "owner_refs": {
                        "group_key": group_key,
                        "module_key": module_key,
                        "default_action_key": screen.get("default_action_key"),
                        "dashboard_panel_keys": panel_keys,
                        "dashboard_action_keys": panel_action_keys,
                        "dashboard_target_screen_keys": panel_target_screen_keys,
                        "declared_action_refs": [
                            {
                                **reference,
                                "reference_evidence_scope": ("effective_metadata_declaration"),
                            }
                            for reference in screen_action_refs[screen_key]
                        ],
                        "task_entry_keys": sorted(task_entry_targets.get(screen_key, [])),
                        "workflow_previous_screen_key": (
                            workflow_references["previous"]["canonical_screen_key"]
                            if workflow_references["previous"] is not None
                            else None
                        ),
                        "workflow_previous_reference": workflow_references["previous"],
                        "workflow_next_screen_key": (
                            workflow_references["next"]["canonical_screen_key"]
                            if workflow_references["next"] is not None
                            else None
                        ),
                        "workflow_next_reference": workflow_references["next"],
                        "professional_screen_key": screen_key,
                    },
                    "roles": {
                        role: {
                            "catalog_visible": screen_key in catalog_screen_keys[role],
                            "detail_status": detail_status[role][screen_key],
                            "direct_link_only": role in direct_link_only_roles,
                        }
                        for role in principals
                    },
                    "review_state": _review_state(
                        surface, direct_link_only=bool(direct_link_only_roles)
                    ),
                }
            )
        )

    action_records: list[dict[str, Any]] = []
    for action_key, action in actions.items():
        screen_key = str(action["screen_key"])

        group_key = screen_group_keys[screen_key]
        user_visible = action_key in detail_action_keys["user"][screen_key]
        admin_visible = action_key in detail_action_keys["admin"][screen_key]
        catalog_visible_any = any(screen_key in catalog_screen_keys[role] for role in principals)
        direct_link_only_roles = [
            role
            for role in principals
            if action_key in detail_action_keys[role][screen_key]
            and screen_key not in catalog_screen_keys[role]
        ]
        task_action_refs = task_entry_action_refs_by_action.get(action_key, [])
        # A task entry names a screen, not an action. Keep every other screen
        # action professional/review unless effective metadata explicitly links it.
        role_task_ref_checks: dict[str, list[dict[str, Any]]] = {}
        role_task_reuse_evidence: dict[str, bool] = {}
        for role in principals:
            role_task_refs: list[dict[str, Any]] = []
            for task_ref in task_action_refs:
                action_detail_visible = (
                    task_ref["action_key"] in detail_action_keys[role][task_ref["screen_key"]]
                )
                task_entry_projected = (
                    task_ref["entry_key"] in role_snapshots[role]["task_entry_keys"]
                )
                role_task_refs.append(
                    {
                        **task_ref,
                        "role_projection": {
                            "task_entry_projected": task_entry_projected,
                            "action_detail_visible": action_detail_visible,
                            "task_reuse_evidence": (task_entry_projected and action_detail_visible),
                            "evidence_scope": (
                                "metadata_task_entry_and_action_declaration_plus_"
                                "authenticated_detail_visibility"
                            ),
                            "browser_execution_asserted": False,
                        },
                    }
                )
            role_task_ref_checks[role] = role_task_refs
            role_task_reuse_evidence[role] = any(
                task_ref["role_projection"]["task_reuse_evidence"] is True
                for task_ref in role_task_refs
            )
        has_task_reuse_evidence = any(role_task_reuse_evidence.values())
        if (
            action.get("audience") == "admin"
            or action.get("risk") == "admin"
            or (admin_visible and not user_visible)
        ):
            surface = "admin_governance"
            surface_basis = "admin_audience_risk_or_actual_role_filter"
        elif has_task_reuse_evidence:
            surface = "task_reuse"
            surface_basis = (
                "effective_metadata_task_entry_target_with_explicit_action_reference_"
                "and_role_visible_action"
            )
        elif catalog_visible_any and (user_visible or admin_visible):
            surface = "professional_retained"
            surface_basis = (
                "actual_catalog_screen_with_role_visible_action_without_"
                "role_visible_task_action_evidence"
                if screen_key in visible_task_entry_targets
                else "actual_catalog_screen_with_role_visible_action"
            )
        else:
            surface = "review_dedupe"
            surface_basis = (
                "direct_link_only_pending_review"
                if user_visible or admin_visible
                else "not_visible_pending_review"
            )
        assert surface in _SURFACES
        action_module_key = action.get("module_key")
        if not isinstance(action_module_key, str) or not action_module_key:
            action_module_key = screen_module_keys[screen_key]
        assert action_module_key in modules, f"action {action_key} has a dangling module reference"
        fields = action.get("fields") or []
        assert isinstance(fields, list)
        safe_fields: list[dict[str, Any]] = []
        for field in fields:
            assert isinstance(field, Mapping)
            safe_fields.append(
                {
                    "key": _key(field),
                    "label": _label(field),
                    "required_policy": field.get("required") is True,
                }
            )
        raw_debug_effective = action.get("raw_debug", True) is True
        task_entry_action_reference_records: list[dict[str, Any]] = []
        for reference_index, task_ref in enumerate(task_action_refs):
            reference_record = {
                key: value for key, value in task_ref.items() if key != "role_projection"
            }
            reference_record["role_projection"] = {
                role: role_task_ref_checks[role][reference_index]["role_projection"]
                for role in principals
            }
            task_entry_action_reference_records.append(reference_record)
        action_records.append(
            _with_record_hash(
                {
                    "key": action_key,
                    "label": _label(action),
                    "surface": surface,
                    "surface_basis": surface_basis,
                    "safe_policy": {
                        "audience": action.get("audience"),
                        "risk": action.get("risk"),
                        "effect": action.get("effect"),
                        "method": action.get("method"),
                        "session_auth_required": action.get("session_auth_required") is True,
                        "confirmation_required_declared": (
                            action.get("confirmation_required") is True
                        ),
                        "field_contracts": safe_fields,
                    },
                    "diagnostic_policy_only": {
                        "raw_debug_explicit": "raw_debug" in action,
                        "raw_debug_effective": raw_debug_effective,
                        "admin_catalog_raw_response_allowed": admin_raw_response_allowed,
                        "necessary_flags_satisfied_not_authorization": (
                            raw_debug_effective and admin_raw_response_allowed
                        ),
                        "execution_attempted": False,
                    },
                    "owner_refs": {
                        "group_key": group_key,
                        "module_key": action_module_key,
                        "screen_key": screen_key,
                        "task_entry_keys": sorted(task_entry_targets.get(screen_key, [])),
                        "professional_screen_key": screen_key,
                    },
                    "task_entry_action_references": (task_entry_action_reference_records),
                    "roles": {
                        role: {
                            "parent_catalog_visible": screen_key in catalog_screen_keys[role],
                            "parent_detail_status": detail_status[role][screen_key],
                            "action_detail_visible": action_key
                            in detail_action_keys[role][screen_key],
                            "task_entry_projected": any(
                                reference["role_projection"]["task_entry_projected"]
                                for reference in role_task_ref_checks[role]
                            ),
                            "task_entry_action_visible": any(
                                reference["role_projection"]["action_detail_visible"]
                                for reference in role_task_ref_checks[role]
                            ),
                            "task_reuse_evidence": role_task_reuse_evidence[role],
                            "task_reuse_evidence_scope": (
                                "metadata_task_entry_and_action_declaration_plus_"
                                "authenticated_detail_visibility"
                                if role_task_reuse_evidence[role]
                                else "not_established"
                            ),
                            "direct_link_only": role in direct_link_only_roles,
                        }
                        for role in principals
                    },
                    "review_state": _review_state(
                        surface, direct_link_only=bool(direct_link_only_roles)
                    ),
                }
            )
        )

    assert len(screen_records) == len(screens)
    assert {record["key"] for record in screen_records} == screen_keys
    assert len({record["key"] for record in screen_records}) == len(screen_records)
    assert len(action_records) == len(actions)
    assert {record["key"] for record in action_records} == action_keys
    assert len({record["key"] for record in action_records}) == len(action_records)
    for finding in workflow_review_findings:
        assert finding["surface"] == "review_dedupe"
        assert finding["finding_kind"] == "dangling_workflow_screen_reference"
        assert finding["screen_key"] in screen_keys
        assert finding["relation"] in {"previous", "next"}
        assert finding["canonical_screen_key"] is None
        assert finding["resolution_status"] == "dangling_pending_review"
        assert finding["review_state"] == "dangling_reference_pending_review"
    for record in action_records:
        action_key = record["key"]
        for reference in record["task_entry_action_references"]:
            assert reference["action_key"] == action_key
            assert reference["entry_key"] in task_entry_targets[reference["screen_key"]]
            assert any(
                declared_ref["reference_kind"] == reference["reference_kind"]
                and declared_ref["panel_key"] == reference["panel_key"]
                and declared_ref["action_key"] == action_key
                and declared_ref.get("row_action_index") == reference["row_action_index"]
                for declared_ref in screen_action_refs[reference["screen_key"]]
            ), f"task entry action reference is not declared by metadata: {action_key}"
            assert reference["reference_evidence_scope"] == ("effective_metadata_declaration")
            assert reference["browser_execution_asserted"] is False
            role_projection = reference["role_projection"]
            assert set(role_projection) == set(principals)
            for role, role_evidence in role_projection.items():
                if role_evidence["task_entry_projected"]:
                    assert reference["entry_key"] in role_snapshots[role]["task_entry_keys"]
                if role_evidence["action_detail_visible"]:
                    assert action_key in detail_action_keys[role][reference["screen_key"]]
                assert role_evidence["task_reuse_evidence"] is (
                    role_evidence["task_entry_projected"] and role_evidence["action_detail_visible"]
                )
        for role, role_record in record["roles"].items():
            assert role_record["task_reuse_evidence"] is any(
                reference["role_projection"][role]["task_reuse_evidence"]
                for reference in record["task_entry_action_references"]
            )
        if record["surface"] == "task_reuse":
            assert any(
                role_record["task_reuse_evidence"] is True
                and role_record["task_entry_action_visible"] is True
                and role_record["task_entry_projected"] is True
                for role_record in record["roles"].values()
            ), f"task_reuse action {action_key} lacks declared and role-visible evidence"
    for record in screen_records + action_records:
        assert record["surface"] in _SURFACES
        assert record["record_sha256"] == _digest(
            {key: value for key, value in record.items() if key != "record_sha256"}
        )

    utility_records: list[dict[str, Any]] = []
    for entry in _objects(raw_experience, "utilities"):
        screen_key = entry.get("screen_key")
        if isinstance(screen_key, str):
            assert screen_key in screens, "experience utility has a dangling screen reference"
            assert aliases.get(screen_key, screen_key) == screen_key
        utility_records.append(
            {
                "key": _key(entry),
                "label": _label(entry),
                "kind": entry.get("kind"),
                "professional_screen_key": screen_key,
            }
        )

    assert not network_attempts, "Metadata reads attempted network I/O, even if swallowed"
    evidence: dict[str, Any] = {
        "schema": "tux10-surface-inventory.v3",
        "artifact_id": "pending",
        "metadata_scope": (
            "effective repository metadata from the published repository composition; "
            "published records and runtime injections are audited together"
        ),
        "metadata_source_ref": (
            "apps.terminal.application.repository_provider.get_tui_metadata_repository()"
            ".load_published('default')"
        ),
        "metadata_version": metadata.get("version"),
        "default_screen_key": metadata.get("default_screen"),
        "groups": [
            {
                "key": key,
                "label": _label(group),
                "module_keys": sorted(
                    module_key
                    for module_key, module in modules.items()
                    if module.get("group") == key
                ),
            }
            for key, group in sorted(groups.items())
        ],
        "modules": [
            {
                "key": key,
                "label": _label(module),
                "group_key": module.get("group"),
                "screen_keys": sorted(
                    screen_key
                    for screen_key, module_key in screen_module_keys.items()
                    if module_key == key
                ),
            }
            for key, module in sorted(modules.items())
        ],
        "legacy_screen_aliases": [
            {"alias": alias, "canonical_screen_key": canonical}
            for alias, canonical in sorted(aliases.items())
        ],
        "coverage": {
            "groups": len(groups),
            "modules": len(modules),
            "screens": len(screens),
            "actions": len(actions),
            "aliases": len(aliases),
            "screen_keys_complete": {record["key"] for record in screen_records} == screen_keys,
            "action_keys_complete": {record["key"] for record in action_records} == action_keys,
        },
        "experience": {
            "home_screen_key": raw_experience.get("home_screen_key"),
            "default_mode": raw_experience.get("default_mode"),
            "modes": [
                {
                    "key": _key(mode),
                    "label": _label(mode),
                    "entry_keys": _entry_keys(_objects(mode, "entries")),
                    "professional_screen_keys": [
                        entry.get("screen_key")
                        for entry in _objects(mode, "entries")
                        if isinstance(entry.get("screen_key"), str)
                    ],
                }
                for mode in _objects(raw_experience, "modes")
            ],
            "task_entries": task_entry_records,
            "utilities": utility_records,
        },
        "role_snapshots": role_snapshots,
        "network_boundary": {
            "scope": "Only inside this metadata audit after Django initialization",
            "blocked_attempt_count": len(network_attempts),
            "business_action_submissions": 0,
        },
        "screens": sorted(screen_records, key=lambda record: record["key"]),
        "actions": sorted(action_records, key=lambda record: record["key"]),
        "workflow_review_findings": sorted(
            workflow_review_findings,
            key=lambda finding: (finding["screen_key"], finding["relation"]),
        ),
    }
    output_path, artifact_id = _artifact_path(settings)
    evidence["artifact_id"] = artifact_id
    evidence["evidence_sha256"] = _digest(evidence)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(evidence, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
