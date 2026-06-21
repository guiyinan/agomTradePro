"""Smoke-test published TUI actions through the same service used by /tui/."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _params_from_fields(fields: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    params: dict[str, Any] = {}
    missing: list[str] = []
    for field in fields:
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        default = field.get("default", "")
        if default not in (None, ""):
            params[key] = default
        elif field.get("required"):
            missing.append(key)
    return params, missing


def _user(username: str | None) -> Any:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    if username:
        user = user_model._default_manager.filter(username=username).first()
        if user is not None:
            return user
    user = user_model._default_manager.filter(is_active=True, is_staff=True).order_by("id").first()
    if user is not None:
        return user
    user = user_model._default_manager.filter(is_active=True).order_by("id").first()
    if user is not None:
        return user
    return user_model(username="tui-smoke")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test published TUI actions.")
    parser.add_argument("--registry-key", default="default")
    parser.add_argument(
        "--metadata-path",
        default="",
        help="Validate a metadata JSON file instead of the DB-published row",
    )
    parser.add_argument("--username", default="")
    parser.add_argument("--screen-prefix", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json-output", default="")
    parser.add_argument("--prune-output", default="")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")

    import django

    django.setup()

    from apps.terminal.application.tui_metadata import (
        compact_tui_metadata_payload,
        validate_tui_metadata,
    )
    from apps.terminal.application.tui_workbench import TuiWorkbenchService
    from apps.terminal.infrastructure.tui_adapters import get_tui_action_executor
    from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository

    class FileMetadataRepository:
        def __init__(self, path: Path) -> None:
            self.payload = validate_tui_metadata(json.loads(path.read_text(encoding="utf-8")))

        def load_published(self, registry_key: str = "default") -> dict[str, Any]:
            return self.payload

    if args.metadata_path:
        metadata_path = (root / args.metadata_path).resolve()
        repository = FileMetadataRepository(metadata_path)
    else:
        repository = PublishedTuiMetadataRepository()
    metadata = repository.load_published(args.registry_key)
    service = TuiWorkbenchService(
        metadata_repository=repository,
        action_executor=get_tui_action_executor(),
        registry_key=args.registry_key,
    )
    actions = [
        action for action in metadata["actions"] if str(action.get("risk")) in {"read", "ai"}
    ]
    if args.screen_prefix:
        actions = [
            action
            for action in actions
            if str(action.get("screen_key", "")).startswith(args.screen_prefix)
        ]
    if args.source:
        actions = [action for action in actions if str(action.get("source", "")) == args.source]
    if args.limit > 0:
        actions = actions[: args.limit]

    user = _user(args.username or None)
    results: list[dict[str, Any]] = []
    summary = {
        "total": len(actions),
        "ok": 0,
        "needs_input": 0,
        "error": 0,
        "by_screen": {},
    }

    for action in actions:
        params, missing = _params_from_fields(list(action.get("fields") or []))
        if missing:
            outcome = {
                "key": action["key"],
                "label": action["label"],
                "screen_key": action["screen_key"],
                "endpoint": action["endpoint"],
                "status": "needs_input",
                "missing_fields": missing,
            }
            summary["needs_input"] += 1
            results.append(outcome)
            continue
        try:
            payload = service.run_action(action_key=action["key"], params=params, user=user)
            view_model = payload.get("view_model") or {}
            response = payload.get("response") or {}
            status_code = int(response.get("status_code") or 0)
            status_label = str(view_model.get("status") or "")
            ok = 200 <= status_code < 300
            endpoint = str(action.get("endpoint") or "")
            business_status = status_code in {503} and (
                action["screen_key"].startswith("api-library.")
                or endpoint in {"/api/ready/", "/api/health/"}
                or endpoint.startswith("/api/system/")
            )
            outcome = {
                "key": action["key"],
                "label": action["label"],
                "screen_key": action["screen_key"],
                "endpoint": action["endpoint"],
                "status": "ok" if ok or business_status else "error",
                "status_code": status_code,
                "view_kind": view_model.get("kind", ""),
                "view_status": status_label,
            }
            summary["ok" if ok or business_status else "error"] += 1
        except Exception as exc:  # noqa: BLE001 - smoke result should capture all runtime failures.
            outcome = {
                "key": action["key"],
                "label": action["label"],
                "screen_key": action["screen_key"],
                "endpoint": action["endpoint"],
                "status": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            summary["error"] += 1
        screen_stats = summary["by_screen"].setdefault(
            action["screen_key"],
            {"total": 0, "ok": 0, "needs_input": 0, "error": 0},
        )
        screen_stats["total"] += 1
        screen_stats[outcome["status"]] += 1
        results.append(outcome)

    payload = {"summary": summary, "results": results}
    if args.json_output:
        output_path = (root / args.json_output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.prune_output:
        failed_keys = {result["key"] for result in results if result.get("status") == "error"}
        pruned = dict(metadata)
        pruned_actions = [
            action
            for action in metadata["actions"]
            if not (
                action["key"] in failed_keys
                and str(action.get("source")) == "api-collector:candidate"
            )
        ]
        pruned["actions"] = pruned_actions
        coverage = dict(pruned.get("coverage_summary") or {})
        newly_pruned = len(metadata["actions"]) - len(pruned_actions)
        try:
            prior_pruned = int(coverage.get("smoke_pruned_auto_actions", 0))
        except (TypeError, ValueError):
            prior_pruned = 0
        coverage["smoke_total"] = summary["total"] - newly_pruned
        coverage["smoke_ok"] = summary["ok"]
        coverage["smoke_needs_input"] = summary["needs_input"]
        coverage["smoke_error"] = max(0, summary["error"] - newly_pruned)
        coverage["smoke_pruned_auto_actions"] = prior_pruned + newly_pruned
        coverage["published_actions"] = len(pruned_actions)
        pruned["coverage_summary"] = coverage
        pruned_output_path = (root / args.prune_output).resolve()
        pruned_output_path.parent.mkdir(parents=True, exist_ok=True)
        pruned_output_path.write_text(
            json.dumps(compact_tui_metadata_payload(pruned), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.fail_on_error and summary["error"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
