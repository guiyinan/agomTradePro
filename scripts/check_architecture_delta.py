#!/usr/bin/env python
"""Fail fast on architecture violations introduced by added diff lines only."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from verify_architecture import (
    DEFAULT_SCAN_ROOTS,
    REPO_ROOT,
    build_report,
    build_top_counts,
    collect_import_records,
    collect_line_records,
    find_import_violations,
    find_line_violations,
    iter_source_files,
    load_rules,
    print_text_report,
)


def build_git_pathspecs(source_roots: Sequence[str]) -> list[str]:
    """Build git pathspecs for the configured scan roots."""

    return [f":(glob){root}/**/*.py" for root in source_roots]


def run_git_command(args: Sequence[str], *, repo_root: Path) -> str:
    """Run a git command and return stdout."""

    return subprocess.check_output(
        list(args),
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stderr=subprocess.STDOUT,
    )


def resolve_head_ref(repo_root: Path) -> str | None:
    """Return HEAD if the repository has at least one commit."""

    try:
        return run_git_command(["git", "rev-parse", "HEAD"], repo_root=repo_root).strip()
    except subprocess.CalledProcessError:
        return None


def render_full_scan_diff(*, repo_root: Path, source_roots: Sequence[str]) -> str:
    """Render a synthetic diff that marks every tracked source line as added."""

    pathspecs = build_git_pathspecs(source_roots)
    paths = run_git_command(["git", "ls-files", *pathspecs], repo_root=repo_root).splitlines()
    chunks: list[str] = []
    for path in paths:
        file_path = repo_root / path
        if not file_path.exists():
            continue
        chunks.append(f"diff --git a/{path} b/{path}\n+++ b/{path}\n@@ -0,0 +1,999999 @@\n")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            chunks.append(f"+{line}\n")
    return "".join(chunks)


def collect_incremental_diff(
    *,
    repo_root: Path,
    source_roots: Sequence[str],
    base_ref: str | None,
    head_ref: str | None,
) -> str:
    """Return a unified diff for added python lines within configured roots."""

    resolved_head = head_ref or resolve_head_ref(repo_root)
    pathspecs = build_git_pathspecs(source_roots)

    if base_ref and resolved_head and base_ref != resolved_head:
        diff_commands = [
            ["git", "diff", "-U0", f"{base_ref}...{resolved_head}", "--", *pathspecs],
            ["git", "diff", "-U0", base_ref, resolved_head, "--", *pathspecs],
        ]
        for command in diff_commands:
            try:
                return run_git_command(command, repo_root=repo_root)
            except subprocess.CalledProcessError as exc:
                if exc.returncode != 128:
                    raise

        try:
            fallback_base = run_git_command(
                ["git", "rev-parse", f"{resolved_head}^"],
                repo_root=repo_root,
            ).strip()
        except subprocess.CalledProcessError:
            return render_full_scan_diff(repo_root=repo_root, source_roots=source_roots)

        if fallback_base and fallback_base != resolved_head:
            return run_git_command(
                ["git", "diff", "-U0", fallback_base, resolved_head, "--", *pathspecs],
                repo_root=repo_root,
            )

    if resolved_head:
        return run_git_command(
            ["git", "diff", "-U0", resolved_head, "--", *pathspecs],
            repo_root=repo_root,
        )

    return render_full_scan_diff(repo_root=repo_root, source_roots=source_roots)


def normalize_source_path(path_text: str) -> str:
    """Normalize git diff file paths to report-style source paths."""

    return Path(path_text.strip()).as_posix().lstrip("./")


def parse_added_lines(diff_text: str) -> dict[str, set[int]]:
    """Collect added line numbers keyed by source path."""

    added_lines: dict[str, set[int]] = defaultdict(set)
    current_file: str | None = None
    current_line = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_file = normalize_source_path(raw_line[6:])
            current_line = 0
            continue
        if raw_line.startswith("+++ /dev/null"):
            current_file = None
            current_line = 0
            continue
        if current_file is None:
            continue

        match = hunk_re.match(raw_line)
        if match:
            current_line = int(match.group(1))
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added_lines[current_file].add(current_line)
            current_line += 1
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue

        if raw_line and not raw_line.startswith("\\"):
            current_line += 1

    return {path: lines for path, lines in added_lines.items() if lines}


def filter_violations_to_added_lines(
    violations: Sequence[dict],
    added_lines: dict[str, set[int]],
) -> list[dict]:
    """Keep only violations that fall on added lines."""

    if not added_lines:
        return []

    return [
        violation
        for violation in violations
        if violation["source_path"] in added_lines
        and violation["lineno"] in added_lines[violation["source_path"]]
    ]


def build_delta_report(
    *,
    ruleset: dict,
    source_roots: Sequence[str],
    base_ref: str | None,
    head_ref: str | None,
    added_lines: dict[str, set[int]],
    boundary_violations: list[dict],
    audit_violations: list[dict] | None,
) -> dict:
    """Build a delta-focused report using the shared report schema."""

    source_files = list(iter_source_files(source_roots))
    import_records = collect_import_records(source_files)
    report = build_report(
        ruleset,
        source_files,
        import_records,
        boundary_violations,
        audit_violations,
    )
    report["mode"] = "delta"
    report["base_ref"] = base_ref
    report["head_ref"] = head_ref
    report["changed_files"] = sorted(added_lines)
    report["changed_file_count"] = len(added_lines)
    report["changed_line_count"] = sum(len(lines) for lines in added_lines.values())
    if audit_violations is not None:
        report["audit"]["top_rules"] = build_top_counts(audit_violations, "rule_id", "rule_id")
        report["audit"]["top_files"] = build_top_counts(audit_violations, "source_path", "source_path")
    return report


def print_delta_text_report(report: dict) -> None:
    """Print delta-specific context followed by the shared text report."""

    print("Architecture delta guard")
    print(f"Base ref: {report.get('base_ref') or '<working-tree>'}")
    print(f"Head ref: {report.get('head_ref') or '<working-tree>'}")
    print(f"Changed files: {report['changed_file_count']}")
    print(f"Added lines: {report['changed_line_count']}")
    print_text_report(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check architecture violations on added diff lines.")
    parser.add_argument(
        "--rules-file",
        default="governance/architecture_rules.json",
        help="Path to the versioned architecture rules file.",
    )
    parser.add_argument(
        "--base-ref",
        help="Base git ref for diff comparison.",
    )
    parser.add_argument(
        "--head-ref",
        help="Head git ref for diff comparison. Defaults to HEAD or working tree.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--include-audit",
        action="store_true",
        help="Include structural audit rules in the delta result.",
    )
    parser.add_argument(
        "--fail-on-audit-violations",
        action="store_true",
        help="Treat audit violations on added lines as hard failures.",
    )
    args = parser.parse_args()

    rules_path = (REPO_ROOT / args.rules_file).resolve()
    ruleset = load_rules(rules_path)
    source_roots = tuple(ruleset.get("source_roots", DEFAULT_SCAN_ROOTS))

    diff_text = collect_incremental_diff(
        repo_root=REPO_ROOT,
        source_roots=source_roots,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    )
    added_lines = parse_added_lines(diff_text)

    source_files = list(iter_source_files(source_roots))
    import_records = collect_import_records(source_files)
    line_records = collect_line_records(source_files) if args.include_audit else []

    all_boundary_violations = find_import_violations(import_records, ruleset["boundary_rules"])
    boundary_violations = filter_violations_to_added_lines(all_boundary_violations, added_lines)

    audit_violations: list[dict] | None = None
    if args.include_audit:
        all_audit_violations = sorted(
            [
                *find_import_violations(import_records, ruleset.get("audit_rules", [])),
                *find_line_violations(line_records, ruleset.get("audit_rules", [])),
            ],
            key=lambda item: (item["source_path"], item["lineno"], item["rule_id"], item["kind"]),
        )
        audit_violations = filter_violations_to_added_lines(all_audit_violations, added_lines)

    report = build_delta_report(
        ruleset=ruleset,
        source_roots=source_roots,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        added_lines=added_lines,
        boundary_violations=boundary_violations,
        audit_violations=audit_violations,
    )

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_delta_text_report(report)

    has_boundary_violations = bool(boundary_violations)
    has_audit_violations = bool(audit_violations)
    if has_boundary_violations or (args.fail_on_audit_violations and has_audit_violations):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
