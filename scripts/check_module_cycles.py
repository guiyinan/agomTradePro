#!/usr/bin/env python
"""Detect app-level import cycles and compare them with an allowlist baseline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timezone
from pathlib import Path

from verify_architecture import (
    REPO_ROOT,
    collect_import_records,
    iter_module_dirs,
    iter_source_files,
)


def normalize_pair(pair: Sequence[str]) -> tuple[str, str]:
    if len(pair) != 2:
        raise ValueError(f"Cycle pair must contain exactly 2 module names: {pair!r}")
    left, right = sorted(str(item).strip() for item in pair)
    if not left or not right or left == right:
        raise ValueError(f"Invalid cycle pair: {pair!r}")
    return left, right


def build_app_graph(source_roots: Sequence[str]) -> tuple[dict[str, set[str]], list, list[str]]:
    source_files = list(iter_source_files(source_roots))
    import_records = collect_import_records(source_files)
    modules = [path.name for path in iter_module_dirs(REPO_ROOT / "apps")]
    module_set = set(modules)
    graph: dict[str, set[str]] = {module: set() for module in modules}

    for record in import_records:
        if record.source_root != "apps":
            continue
        if "/tests/" in record.source_path:
            continue
        if record.source_module not in module_set:
            continue
        if not record.target_module or record.target_module not in module_set:
            continue
        if record.target_module == record.source_module:
            continue
        graph[record.source_module].add(record.target_module)

    return graph, import_records, modules


def find_bidirectional_pairs(graph: dict[str, set[str]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for source in sorted(graph):
        for target in sorted(graph[source]):
            pair = tuple(sorted((source, target)))
            if source < target and source in graph.get(target, set()):
                pairs.append(pair)
    return pairs


def build_pair_details(pairs: Iterable[tuple[str, str]], import_records: Sequence[object]) -> list[dict]:
    grouped: dict[tuple[str, str], dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: {"forward": [], "reverse": []}
    )
    for record in import_records:
        if getattr(record, "source_root", None) != "apps":
            continue
        if "/tests/" in getattr(record, "source_path", ""):
            continue
        source = getattr(record, "source_module", "")
        target = getattr(record, "target_module", None)
        if not target or target == source:
            continue
        pair = tuple(sorted((source, target)))
        direction = "forward" if pair == (source, target) else "reverse"
        grouped[pair][direction].append(
            {
                "source_path": record.source_path,
                "lineno": record.lineno,
                "import_path": record.import_path,
            }
        )

    details: list[dict] = []
    for pair in pairs:
        forward = grouped[pair]["forward"]
        reverse = grouped[pair]["reverse"]
        details.append(
            {
                "pair": list(pair),
                "left_to_right_count": len(forward),
                "right_to_left_count": len(reverse),
                "left_to_right_samples": forward[:5],
                "right_to_left_samples": reverse[:5],
            }
        )
    return details


def find_cycle_components(graph: dict[str, set[str]], modules: Sequence[str]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(graph.get(node, set())):
            if target not in indices:
                strongconnect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return

        component: list[str] = []
        while stack:
            current = stack.pop()
            on_stack.remove(current)
            component.append(current)
            if current == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for module in modules:
        if module not in indices:
            strongconnect(module)

    return sorted(components, key=lambda items: (len(items), items))


def load_allowlist(allowlist_path: Path | None) -> tuple[set[tuple[str, str]], dict | None]:
    if allowlist_path is None:
        return set(), None
    payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
    pairs = {
        normalize_pair(pair)
        for pair in payload.get("allowed_bidirectional_pairs", [])
    }
    return pairs, payload


def build_report(
    *,
    graph: dict[str, set[str]],
    modules: Sequence[str],
    import_records: Sequence[object],
    bidirectional_pairs: list[tuple[str, str]],
    cycle_components: list[list[str]],
    allowed_pairs: set[tuple[str, str]],
    allowlist_path: Path | None,
    allowlist_payload: dict | None,
) -> dict:
    allowed_found = [list(pair) for pair in bidirectional_pairs if pair in allowed_pairs]
    unexpected = [list(pair) for pair in bidirectional_pairs if pair not in allowed_pairs]
    stale_allowlist = [list(pair) for pair in sorted(allowed_pairs - set(bidirectional_pairs))]
    edge_count = sum(len(targets) for targets in graph.values())
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scan_roots": ["apps"],
        "module_count": len(modules),
        "edge_count": edge_count,
        "bidirectional_pair_count": len(bidirectional_pairs),
        "cycle_component_count": len(cycle_components),
        "allowlist_path": str(allowlist_path.relative_to(REPO_ROOT)).replace("\\", "/")
        if allowlist_path
        else None,
        "allowlist_version": allowlist_payload.get("version") if allowlist_payload else None,
        "bidirectional_pairs": [list(pair) for pair in bidirectional_pairs],
        "pair_details": build_pair_details(bidirectional_pairs, import_records),
        "cycle_components": cycle_components,
        "allowed_pairs_found": allowed_found,
        "unexpected_pairs": unexpected,
        "stale_allowlist_pairs": stale_allowlist,
    }


def print_text_report(report: dict) -> None:
    print("Module cycle audit")
    print(f"Scan roots: {', '.join(report['scan_roots'])}")
    print(f"Modules: {report['module_count']}")
    print(f"Edges: {report['edge_count']}")
    print(f"Bidirectional pairs: {report['bidirectional_pair_count']}")
    print(f"Cycle components: {report['cycle_component_count']}")
    if report["allowlist_path"]:
        print(f"Allowlist: {report['allowlist_path']}")
        print(f"Allowlist version: {report['allowlist_version'] or '<unknown>'}")
        print(f"Unexpected pairs: {len(report['unexpected_pairs'])}")
        print(f"Stale allowlist pairs: {len(report['stale_allowlist_pairs'])}")

    if report["unexpected_pairs"]:
        print("")
        print("Unexpected bidirectional pairs:")
        for pair in report["unexpected_pairs"]:
            print(f"- {pair[0]} <-> {pair[1]}")

    if report["stale_allowlist_pairs"]:
        print("")
        print("Resolved allowlist pairs:")
        for pair in report["stale_allowlist_pairs"]:
            print(f"- {pair[0]} <-> {pair[1]}")

    if report["cycle_components"]:
        print("")
        print("Cycle components:")
        for component in report["cycle_components"]:
            print(f"- {', '.join(component)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect app-level module import cycles.")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--allowlist-file",
        help="JSON file containing the accepted bidirectional pair baseline.",
    )
    parser.add_argument(
        "--write-report",
        help="Write a JSON report to this path.",
    )
    parser.add_argument(
        "--fail-on-cycles",
        action="store_true",
        help="Fail on any detected cycle, or on unexpected cycles when an allowlist is provided.",
    )
    args = parser.parse_args()

    allowlist_path = (REPO_ROOT / args.allowlist_file).resolve() if args.allowlist_file else None
    allowed_pairs, allowlist_payload = load_allowlist(allowlist_path)

    graph, import_records, modules = build_app_graph(("apps",))
    bidirectional_pairs = find_bidirectional_pairs(graph)
    cycle_components = find_cycle_components(graph, modules)
    report = build_report(
        graph=graph,
        modules=modules,
        import_records=import_records,
        bidirectional_pairs=bidirectional_pairs,
        cycle_components=cycle_components,
        allowed_pairs=allowed_pairs,
        allowlist_path=allowlist_path,
        allowlist_payload=allowlist_payload,
    )

    if args.write_report:
        report_path = (REPO_ROOT / args.write_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    if not args.fail_on_cycles:
        return 0

    if allowed_pairs:
        return 1 if report["unexpected_pairs"] else 0
    return 1 if bidirectional_pairs else 0


if __name__ == "__main__":
    sys.exit(main())
