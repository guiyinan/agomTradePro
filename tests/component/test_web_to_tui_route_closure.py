"""Route-level closure evidence for the Web-to-TUI compatibility surface."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import Group
from django.template.loader import get_template
from django.test import Client

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
TEMPLATE_REFERENCE_PATTERN = re.compile(r"{%\s*(?:extends|include)\s+[\"']([^\"']+)[\"']")
PATH_PARAMETER_PATTERN = re.compile(r"<(?:(int|str|slug|uuid|path):)?([^>]+)>")
PATH_PARAMETER_VALUES = {
    "int": "1",
    "str": "closure-test",
    "slug": "closure-test",
    "uuid": "00000000-0000-0000-0000-000000000001",
    "path": "closure-test",
}
TERMINAL_CONFIG_TEMPLATE = "core/templates/terminal/config.html"
MIXED_ROLE_ROUTE_PATHS = {
    "apps/audit/templates/audit/threshold_validation.html",
    "core/templates/ops/capability_gateway.html",
    "core/templates/ops/center.html",
    "core/templates/signal/manage.html",
}
SHARED_RESEARCH_ROUTE_PATHS = {
    "core/templates/dashboard/alpha_history.html",
    "core/templates/dashboard/alpha_ranking.html",
    "core/templates/equity/detail.html",
    "core/templates/equity/pool.html",
    "core/templates/equity/screen.html",
    "core/templates/equity/valuation_repair.html",
    "core/templates/filter/dashboard.html",
    "core/templates/fund/dashboard.html",
    "core/templates/macro/data.html",
    "core/templates/regime/dashboard.html",
    "core/templates/sentiment/dashboard.html",
}


def _migrated_route_rows() -> list[dict[str, str]]:
    """Return every active A/B route page from the reviewed matrix."""

    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("template_role") == "route_page"
            and row.get("destination_class") in {"A", "B"}
            and row.get("status") == "migrated"
        ]


def _concrete_paths(patterns: str) -> Iterator[str]:
    """Expand reviewed Django-style path placeholders into harmless values."""

    def replace(match: re.Match[str]) -> str:
        converter = match.group(1) or "str"
        return PATH_PARAMETER_VALUES[converter]

    for raw_pattern in patterns.split(";"):
        pattern = raw_pattern.strip()
        if pattern:
            yield PATH_PARAMETER_PATTERN.sub(replace, pattern)


def _template_source(template_path: str) -> str:
    """Collect one template and its statically referenced inheritance graph."""

    pending = [ROOT / template_path]
    visited: set[Path] = set()
    chunks: list[str] = []
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        source = path.read_text(encoding="utf-8")
        chunks.append(source)
        for template_name in TEMPLATE_REFERENCE_PATTERN.findall(source):
            template = get_template(template_name)
            origin_path = Path(template.origin.name).resolve()
            if origin_path.is_relative_to(ROOT) and origin_path not in visited:
                pending.append(origin_path)
    return "\n".join(chunks)


def _planned_role(audience: str) -> str:
    """Return the least-privileged role required by one matrix route."""

    normalized = audience.lower()
    if "operator" in normalized:
        return "operator"
    if "admin" in normalized and "authenticated" not in normalized:
        return "admin"
    return "regular"


def _matrix_values(row: dict[str, str], key: str) -> set[str]:
    """Return one semicolon-delimited matrix field as a normalized set."""

    return {value.strip() for value in row.get(key, "").split(";") if value.strip()}


def _screen_actions(client: Client, screen_key: str) -> dict[str, dict[str, Any]]:
    """Return actions visible to the client's current actor on one screen."""

    payload = _screen_payload(client, screen_key)
    if not payload:
        return {}
    action_values = payload.get("actions")
    actions = action_values if isinstance(action_values, list) else []
    return {
        str(action["key"]): action
        for action in actions
        if isinstance(action, dict) and str(action.get("key") or "").strip()
    }


def _screen_payload(client: Client, screen_key: str) -> dict[str, Any]:
    """Return one role-filtered screen contract, or an empty mapping when hidden."""

    response = client.get(f"/api/tui/screens/{screen_key}/")
    if response.status_code in {403, 404}:
        return {}
    assert response.status_code == 200, f"{screen_key}: {response.status_code}"
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


@pytest.mark.django_db
def test_all_classic_routes_preserve_the_anonymous_auth_boundary(client: Client) -> None:
    """Every reviewed Classic URL must reject anonymous execution before view work."""

    rows = _migrated_route_rows()
    assert len(rows) == 108
    failures: list[str] = []
    checked_paths = 0
    for row in rows:
        for path in _concrete_paths(row["url_path_pattern"]):
            checked_paths += 1
            response = client.get(path, follow=False)
            location = str(response.headers.get("Location") or "")
            login_path = urlparse(location).path
            if response.status_code not in {401, 403} and not (
                response.status_code == 302
                and login_path in {"/account/login/", "/admin/login/", "/login/"}
            ):
                failures.append(
                    f"{row['template_path']}: {path} -> " f"{response.status_code} {location}"
                )

    assert checked_paths >= 108
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_classic_compatibility_surfaces_publish_reviewed_tui_destinations(
    client: Client,
    django_user_model: type[Any],
) -> None:
    """Each retained page or explicit redirect exposes its reviewed TUI destination."""

    rows = _migrated_route_rows()
    failures: list[str] = []
    for row in rows:
        redirect_target = str(row.get("redirect_target") or "").strip()
        query = parse_qs(urlparse(redirect_target).query)
        screen_keys = {
            value.strip()
            for value in str(row.get("target_screen_key") or "").split(";")
            if value.strip()
        }
        action_key = next(iter(query.get("action") or []), "")
        if row["template_path"] == TERMINAL_CONFIG_TEMPLATE:
            continue

        source = _template_source(row["template_path"])
        missing_screens = sorted(screen for screen in screen_keys if screen not in source)
        if not screen_keys or missing_screens:
            failures.append(f"{row['template_path']}: missing screens {missing_screens!r}")
        if action_key and "{" not in action_key and action_key not in source:
            failures.append(f"{row['template_path']}: missing action {action_key!r}")
        compatibility_marker = any(marker in source for marker in ("Classic", "经典页面", "兼容期"))
        if "TUI" not in source or not compatibility_marker:
            failures.append(f"{row['template_path']}: missing compatibility notice")

    staff = django_user_model.objects.create_user(
        username="route_closure_staff",
        password="RouteClosure!2026",
        is_staff=True,
    )
    client.force_login(staff)
    terminal_row = next(row for row in rows if row["template_path"] == TERMINAL_CONFIG_TEMPLATE)
    response = client.get("/terminal/config/", follow=False)
    if (
        response.status_code != 302
        or response.headers.get("Location") != terminal_row["redirect_target"]
    ):
        failures.append(
            f"{TERMINAL_CONFIG_TEMPLATE}: expected direct redirect to "
            f"{terminal_row['redirect_target']!r}"
        )

    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_route_actions_preserve_admin_and_operator_role_boundaries(
    django_user_model: type[Any],
) -> None:
    """Restricted route actions stay visible and executable only to reviewed roles."""

    regular = django_user_model.objects.create_user(username="closure_regular")
    operator = django_user_model.objects.create_user(username="closure_operator")
    operator_group = Group.objects.create(name="operator")
    operator.groups.add(operator_group)
    admin = django_user_model.objects.create_user(
        username="closure_admin",
        is_staff=True,
        is_superuser=True,
    )
    actors = {"regular": regular, "operator": operator, "admin": admin}
    clients: dict[str, Client] = {}
    for role, actor in actors.items():
        role_client = Client()
        role_client.force_login(actor)
        clients[role] = role_client

    action_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def visible_actions(role: str, screen_key: str) -> dict[str, dict[str, Any]]:
        cache_key = (role, screen_key)
        if cache_key not in action_cache:
            action_cache[cache_key] = _screen_actions(clients[role], screen_key)
        return action_cache[cache_key]

    failures: list[str] = []
    restricted_route_count = 0
    protected_route_paths: set[str] = set()
    shared_route_paths: set[str] = set()
    restricted_action_keys: set[str] = set()
    for row in _migrated_route_rows():
        planned_role = _planned_role(row["audience"])
        screen_keys = _matrix_values(row, "target_screen_key")
        target_actions = _matrix_values(row, "target_action_keys")
        allowed_actions = {
            key: action
            for screen_key in screen_keys
            for key, action in visible_actions(planned_role, screen_key).items()
        }
        if not target_actions.intersection(allowed_actions):
            failures.append(f"{row['template_path']}: {planned_role} cannot see a target action")
            continue
        if planned_role not in {"admin", "operator"}:
            continue

        restricted_route_count += 1
        row_restricted_actions = target_actions.intersection(allowed_actions)
        if not row_restricted_actions:
            failures.append(f"{row['template_path']}: no restricted target action")
            continue
        regular_actions = {
            key for screen_key in screen_keys for key in visible_actions("regular", screen_key)
        }
        hidden_actions = row_restricted_actions - regular_actions
        if hidden_actions:
            protected_route_paths.add(row["template_path"])
            restricted_action_keys.update(hidden_actions)
        else:
            shared_route_paths.add(row["template_path"])

    for action_key in sorted(restricted_action_keys):
        response = clients["regular"].post(
            f"/api/tui/actions/{action_key}/run/",
            data="{}",
            content_type="application/json",
        )
        if response.status_code not in {403, 404}:
            failures.append(f"{action_key}: regular execution returned {response.status_code}")

    assert restricted_route_count == 36
    assert shared_route_paths == {
        "apps/audit/templates/audit/decision_traces_admin.html",
        "apps/risk_center/templates/risk_center/console.html",
        "core/templates/terminal/config.html",
    }
    assert len(protected_route_paths) == 33
    assert not failures, "\n".join(failures)
    assert restricted_action_keys


@pytest.mark.django_db
def test_login_only_routes_require_authentication_for_their_visible_actions(
    django_user_model: type[Any],
) -> None:
    """Pure login-required routes expose their reviewed actions only after login."""

    rows = [
        row
        for row in _migrated_route_rows()
        if row["audience"] == "authenticated" and row["permission_rule"] == "login_required"
    ]
    assert len(rows) == 23

    regular = django_user_model.objects.create_user(username="closure_authenticated")
    authenticated_client = Client()
    authenticated_client.force_login(regular)
    anonymous_client = Client()
    action_cache: dict[str, dict[str, dict[str, Any]]] = {}
    visible_action_keys: set[str] = set()
    failures: list[str] = []

    for row in rows:
        target_actions = _matrix_values(row, "target_action_keys")
        row_visible_actions: set[str] = set()
        for screen_key in _matrix_values(row, "target_screen_key"):
            if screen_key not in action_cache:
                action_cache[screen_key] = _screen_actions(authenticated_client, screen_key)
            row_visible_actions.update(target_actions.intersection(action_cache[screen_key]))
        if not row_visible_actions:
            failures.append(f"{row['template_path']}: authenticated target action is not visible")
        visible_action_keys.update(row_visible_actions)

    for action_key in sorted(visible_action_keys):
        response = anonymous_client.post(
            f"/api/tui/actions/{action_key}/run/",
            data="{}",
            content_type="application/json",
        )
        if response.status_code not in {401, 403}:
            failures.append(f"{action_key}: anonymous execution returned {response.status_code}")

    assert visible_action_keys
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_mixed_role_routes_keep_reads_available_and_admin_actions_restricted(
    django_user_model: type[Any],
) -> None:
    """Mixed-role routes expose reads to users without leaking admin actions."""

    regular = django_user_model.objects.create_user(username="closure_mixed_regular")
    admin = django_user_model.objects.create_user(
        username="closure_mixed_admin",
        is_staff=True,
        is_superuser=True,
    )
    clients: dict[str, Client] = {}
    for role, actor in (("regular", regular), ("admin", admin)):
        role_client = Client()
        role_client.force_login(actor)
        clients[role] = role_client

    rows = [row for row in _migrated_route_rows() if row["template_path"] in MIXED_ROLE_ROUTE_PATHS]
    assert {row["template_path"] for row in rows} == MIXED_ROLE_ROUTE_PATHS

    action_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def visible_actions(role: str, screen_key: str) -> set[str]:
        cache_key = (role, screen_key)
        if cache_key not in action_cache:
            action_cache[cache_key] = _screen_actions(clients[role], screen_key)
        return set(action_cache[cache_key])

    failures: list[str] = []
    restricted_action_keys: set[str] = set()
    for row in rows:
        targets = _matrix_values(row, "target_action_keys")
        regular_actions = {
            key
            for screen_key in _matrix_values(row, "target_screen_key")
            for key in visible_actions("regular", screen_key)
        }
        admin_actions = {
            key
            for screen_key in _matrix_values(row, "target_screen_key")
            for key in visible_actions("admin", screen_key)
        }
        regular_targets = targets.intersection(regular_actions)
        restricted_targets = targets.intersection(admin_actions) - regular_actions
        if not regular_targets:
            failures.append(f"{row['template_path']}: no authenticated target action")
        if not restricted_targets:
            failures.append(f"{row['template_path']}: no admin-only target action")
        restricted_action_keys.update(restricted_targets)

    for action_key in sorted(restricted_action_keys):
        response = clients["regular"].post(
            f"/api/tui/actions/{action_key}/run/",
            data="{}",
            content_type="application/json",
        )
        if response.status_code not in {403, 404}:
            failures.append(f"{action_key}: regular execution returned {response.status_code}")

    assert restricted_action_keys
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_shared_research_routes_enforce_the_authenticated_backend_boundary(
    django_user_model: type[Any],
) -> None:
    """Shared research routes require login without inventing an owner boundary."""

    rows = [
        row for row in _migrated_route_rows() if row["template_path"] in SHARED_RESEARCH_ROUTE_PATHS
    ]
    assert {row["template_path"] for row in rows} == SHARED_RESEARCH_ROUTE_PATHS

    regular = django_user_model.objects.create_user(username="closure_research_user")
    authenticated_client = Client()
    authenticated_client.force_login(regular)
    anonymous_client = Client()
    action_cache: dict[str, dict[str, dict[str, Any]]] = {}
    visible_action_keys: set[str] = set()
    failures: list[str] = []

    for row in rows:
        targets = _matrix_values(row, "target_action_keys")
        row_visible_actions: set[str] = set()
        for screen_key in _matrix_values(row, "target_screen_key"):
            if screen_key not in action_cache:
                action_cache[screen_key] = _screen_actions(authenticated_client, screen_key)
            row_visible_actions.update(targets.intersection(action_cache[screen_key]))
        if not row_visible_actions:
            failures.append(f"{row['template_path']}: authenticated target action is not visible")
        visible_action_keys.update(row_visible_actions)

    for action_key in sorted(visible_action_keys):
        response = anonymous_client.post(
            f"/api/tui/actions/{action_key}/run/",
            data="{}",
            content_type="application/json",
        )
        if response.status_code not in {401, 403}:
            failures.append(f"{action_key}: anonymous execution returned {response.status_code}")

    assert visible_action_keys
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_every_migrated_route_has_task_level_empty_state_guidance(
    django_user_model: type[Any],
) -> None:
    """Every route publishes an actionable empty state for its planned actor and task."""

    regular = django_user_model.objects.create_user(username="closure_empty_regular")
    operator = django_user_model.objects.create_user(username="closure_empty_operator")
    operator_group = Group.objects.create(name="operator")
    operator.groups.add(operator_group)
    admin = django_user_model.objects.create_user(
        username="closure_empty_admin",
        is_staff=True,
        is_superuser=True,
    )
    clients: dict[str, Client] = {}
    for role, actor in (("regular", regular), ("operator", operator), ("admin", admin)):
        role_client = Client()
        role_client.force_login(actor)
        clients[role] = role_client

    screen_cache: dict[tuple[str, str], dict[str, Any]] = {}
    reviewed_routes: set[str] = set()
    failures: list[str] = []
    implementation_markers = ("/api/", "auto.api", "param.api", "http method", "{")

    for row in _migrated_route_rows():
        role = _planned_role(row["audience"])
        targets = _matrix_values(row, "target_action_keys")
        reviewed_target = False
        for screen_key in _matrix_values(row, "target_screen_key"):
            cache_key = (role, screen_key)
            if cache_key not in screen_cache:
                screen_cache[cache_key] = _screen_payload(clients[role], screen_key)
            payload = screen_cache[cache_key]
            if not payload:
                continue
            actions = {
                str(action.get("key") or ""): action
                for action in payload.get("actions") or []
                if isinstance(action, dict)
            }
            visible_targets = targets.intersection(actions)
            if not visible_targets:
                continue
            screen = payload.get("screen")
            screen_payload = screen if isinstance(screen, dict) else {}
            experience = screen_payload.get("user_experience")
            experience_payload = experience if isinstance(experience, dict) else {}
            empty_hint = str(experience_payload.get("empty_state_hint") or "").strip()
            next_hint = str(experience_payload.get("next_step_hint") or "").strip()
            combined_hint = f"{empty_hint} {next_hint}".lower()
            if not empty_hint or not next_hint:
                failures.append(
                    f"{row['template_path']}: {screen_key} lacks empty/next-step guidance"
                )
                continue
            leaked = [marker for marker in implementation_markers if marker in combined_hint]
            if leaked:
                failures.append(
                    f"{row['template_path']}: {screen_key} leaks implementation markers {leaked!r}"
                )
                continue
            unlabeled = sorted(
                action_key
                for action_key in visible_targets
                if not str(actions[action_key].get("label") or "").strip()
            )
            if unlabeled:
                failures.append(
                    f"{row['template_path']}: unlabeled empty-state tasks {unlabeled!r}"
                )
                continue
            reviewed_target = True
            break
        if reviewed_target:
            reviewed_routes.add(row["template_path"])
        else:
            failures.append(f"{row['template_path']}: no task-level empty-state target")

    assert len(reviewed_routes) == 108
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
def test_every_migrated_route_has_bounded_task_level_error_recovery(
    django_user_model: type[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every route maps an unexpected task failure to its reviewed screen recovery."""

    regular = django_user_model.objects.create_user(username="closure_error_regular")
    operator = django_user_model.objects.create_user(username="closure_error_operator")
    operator_group = Group.objects.create(name="operator")
    operator.groups.add(operator_group)
    admin = django_user_model.objects.create_user(
        username="closure_error_admin",
        is_staff=True,
        is_superuser=True,
    )
    clients: dict[str, Client] = {}
    for role, actor in (("regular", regular), ("operator", operator), ("admin", admin)):
        role_client = Client()
        role_client.force_login(actor)
        clients[role] = role_client

    def raise_reviewed_failure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("private route closure exception")

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench.TuiWorkbenchService.run_action",
        raise_reviewed_failure,
    )
    screen_cache: dict[tuple[str, str], dict[str, Any]] = {}
    reviewed_routes: set[str] = set()
    failures: list[str] = []

    for row in _migrated_route_rows():
        role = _planned_role(row["audience"])
        targets = _matrix_values(row, "target_action_keys")
        selected: tuple[str, str, str] | None = None
        for screen_key in _matrix_values(row, "target_screen_key"):
            cache_key = (role, screen_key)
            if cache_key not in screen_cache:
                screen_cache[cache_key] = _screen_payload(clients[role], screen_key)
            payload = screen_cache[cache_key]
            actions = {
                str(action.get("key") or ""): action
                for action in payload.get("actions") or []
                if isinstance(action, dict)
            }
            visible_targets = sorted(targets.intersection(actions))
            if visible_targets:
                action_key = visible_targets[0]
                selected = (
                    screen_key,
                    action_key,
                    str(actions[action_key].get("label") or "").strip(),
                )
                break
        if selected is None:
            failures.append(f"{row['template_path']}: no visible error-state target")
            continue

        screen_key, action_key, action_label = selected
        response = clients[role].post(
            f"/api/tui/actions/{action_key}/run/",
            data={"params": {}},
            content_type="application/json",
            HTTP_X_REQUEST_ID=f"closure-error-{len(reviewed_routes) + 1}",
        )
        payload = response.json()
        expected_recovery = [{"label": f"返回{action_label}", "screen_key": screen_key}]
        if response.status_code != 502:
            failures.append(f"{row['template_path']}: {action_key} returned {response.status_code}")
        elif set(payload) != {
            "error_code",
            "title",
            "detail",
            "recovery_actions",
            "trace_id",
        }:
            failures.append(f"{row['template_path']}: unbounded error envelope")
        elif payload.get("error_code") != "tui_action_unavailable":
            failures.append(f"{row['template_path']}: wrong error code")
        elif action_label not in str(payload.get("detail") or ""):
            failures.append(f"{row['template_path']}: missing task label")
        elif payload.get("recovery_actions") != expected_recovery:
            failures.append(f"{row['template_path']}: wrong recovery target")
        elif "private route closure" in str(payload):
            failures.append(f"{row['template_path']}: leaked exception text")
        elif not str(payload.get("trace_id") or "").strip():
            failures.append(f"{row['template_path']}: missing trace id")
        else:
            reviewed_routes.add(row["template_path"])

    assert len(reviewed_routes) == 108
    assert not failures, "\n".join(failures)
