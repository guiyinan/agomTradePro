#!/usr/bin/env python
"""Verify the generated data-dictionary projections and optional exact delta."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_data_dictionary import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    GENERATED_BY,
    SCHEMA_VERSION,
    build_data_dictionary,
    render_markdown,
)
from check_data_dictionary_model_delta import (  # noqa: E402
    ModelDelta,
    Ref01ExplanationRow,
    compare_model_projections,
    parse_ref01_explanation_rows,
    run_model_delta_check,
    validate_deleted_model_consumers,
    validate_delta_explanations,
    validate_unprojected_new_model_declarations,
)

__all__ = [
    "ModelDelta",
    "Ref01ExplanationRow",
    "compare_model_projections",
    "parse_ref01_explanation_rows",
    "run_model_delta_check",
    "validate_deleted_model_consumers",
    "validate_delta_explanations",
    "validate_unprojected_new_model_declarations",
]
REMEDIATION = "run: python scripts/build_data_dictionary.py"


def _validate_envelope(payload: dict[str, object]) -> list[str]:
    """Validate schema identity fields of a data dictionary payload."""

    problems: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version: expected {SCHEMA_VERSION!r}, got {payload.get('schema_version')!r}"
        )
    if payload.get("generated_by") != GENERATED_BY:
        problems.append(
            f"generated_by: expected {GENERATED_BY!r}, got {payload.get('generated_by')!r}"
        )
    return problems


def _diff_apps(committed: dict[str, object], regenerated: dict[str, object]) -> list[str]:
    """Return a concise app/model-level diff summary between two payloads."""

    committed_apps = committed.get("apps", {})
    regenerated_apps = regenerated.get("apps", {})
    if not isinstance(committed_apps, dict) or not isinstance(regenerated_apps, dict):
        return ["apps: not a JSON object in one of the payloads"]

    lines: list[str] = []
    committed_names = set(committed_apps)
    regenerated_names = set(regenerated_apps)
    for name in sorted(committed_names - regenerated_names):
        lines.append(f"app removed from code, still in file: {name}")
    for name in sorted(regenerated_names - committed_names):
        lines.append(f"app added in code, missing in file: {name}")
    for name in sorted(committed_names & regenerated_names):
        committed_record = committed_apps[name]
        regenerated_record = regenerated_apps[name]
        if committed_record == regenerated_record:
            continue
        committed_models = _model_index(committed_record)
        regenerated_models = _model_index(regenerated_record)
        for model_key in sorted(committed_models.keys() - regenerated_models.keys()):
            lines.append(f"{name}: model removed from code, still in file: {model_key}")
        for model_key in sorted(regenerated_models.keys() - committed_models.keys()):
            lines.append(f"{name}: model added in code, missing in file: {model_key}")
        for model_key in sorted(committed_models.keys() & regenerated_models.keys()):
            if committed_models[model_key] != regenerated_models[model_key]:
                lines.append(f"{name}: model differs: {model_key}")
    return lines


def _model_index(app_record: object) -> dict[str, object]:
    """Index an app record's models by ``source_file:class_name``."""

    index: dict[str, object] = {}
    if not isinstance(app_record, dict):
        return index
    models = app_record.get("models", [])
    if not isinstance(models, list):
        return index
    for model in models:
        if isinstance(model, dict):
            key = f"{model.get('source_file', '?')}:{model.get('class_name', '?')}"
            index[key] = model
    return index


def _diff_text(committed: str, regenerated: str, label: str) -> list[str]:
    """Return a short unified-diff summary between two rendered texts."""

    diff = list(
        difflib.unified_diff(
            committed.splitlines(),
            regenerated.splitlines(),
            fromfile=f"committed:{label}",
            tofile=f"regenerated:{label}",
            lineterm="",
            n=1,
        )
    )
    if len(diff) > 40:
        diff = diff[:40] + [f"... ({len(diff) - 40} more diff lines)"]
    return diff


def main() -> int:
    """Regenerate current projections and optionally verify an exact model delta."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-file",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="committed data dictionary JSON path to verify",
    )
    parser.add_argument(
        "--md-file",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="committed data dictionary Markdown path to verify",
    )
    parser.add_argument(
        "--base-ref",
        help="full Git object id of the exact baseline commit (requires --head-ref)",
    )
    parser.add_argument(
        "--head-ref",
        help="full Git object id of the checked-out candidate commit (requires --base-ref)",
    )
    parser.add_argument(
        "--plan-file",
        type=Path,
        default=None,
        help="optional repository-relative changed docs/plans Markdown file to scan",
    )
    args = parser.parse_args()
    if (args.base_ref is None) != (args.head_ref is None):
        parser.error("--base-ref and --head-ref must be supplied together")

    payload = build_data_dictionary()
    failed = False

    if not args.json_file.exists():
        print(f"data dictionary JSON missing: {args.json_file}")
        failed = True
    else:
        try:
            committed = json.loads(args.json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"data dictionary JSON is not valid JSON: {args.json_file}: {exc}")
            failed = True
        else:
            if not isinstance(committed, dict):
                print(f"data dictionary JSON root must be a JSON object: {args.json_file}")
                failed = True
            else:
                envelope_problems = _validate_envelope(committed)
                if envelope_problems:
                    for problem in envelope_problems:
                        print(f"INVALID {problem}")
                    failed = True
                elif committed != payload:
                    print(f"data dictionary JSON drift detected: {args.json_file}")
                    for line in _diff_apps(committed, payload):
                        print(f"- {line}")
                    failed = True

    expected_markdown = render_markdown(payload)
    if not args.md_file.exists():
        print(f"data dictionary Markdown missing: {args.md_file}")
        failed = True
    else:
        committed_markdown = args.md_file.read_text(encoding="utf-8")
        if committed_markdown != expected_markdown:
            print(f"data dictionary Markdown drift detected: {args.md_file}")
            for line in _diff_text(committed_markdown, expected_markdown, args.md_file.name):
                print(line)
            failed = True

    if failed:
        print(REMEDIATION)
        return 1

    apps = payload["apps"]
    app_count = len(apps) if isinstance(apps, dict) else 0
    model_count = 0
    if isinstance(apps, dict):
        for app_record in apps.values():
            if isinstance(app_record, dict) and isinstance(app_record.get("models"), list):
                model_count += len(app_record["models"])
    print(
        f"data dictionary OK: {args.json_file} and {args.md_file} match the source tree "
        f"(apps={app_count} models={model_count})"
    )
    if args.base_ref is None or args.head_ref is None:
        return 0
    return run_model_delta_check(
        repository_root=Path(__file__).resolve().parents[1],
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        json_path=args.json_file,
        markdown_path=args.md_file,
        plan_file=args.plan_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
