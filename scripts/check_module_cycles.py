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


def normalize_component(component: Sequence[str]) -> tuple[str, ...]:
    items = tuple(sorted(str(item).strip() for item in component))
    if len(items) < 2 or any(not item for item in items) or len(set(items)) != len(items):
        raise ValueError(f"Invalid cycle component: {component!r}")
    return items


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


def build_outbound_summary(graph: dict[str, set[str]]) -> list[dict[str, object]]:
    """Return sorted outbound dependency counts for app modules."""

    return [
        {"module": module, "outbound_count": len(targets), "targets": sorted(targets)}
        for module, targets in sorted(
            graph.items(), key=lambda item: (-len(item[1]), item[0])
        )
        if targets
    ]


def build_inbound_sources(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return app modules that import each target app module."""

    inbound: dict[str, set[str]] = {module: set() for module in graph}
    for source, targets in graph.items():
        for target in targets:
            inbound.setdefault(target, set()).add(source)
    return inbound


def build_inbound_summary(graph: dict[str, set[str]]) -> list[dict[str, object]]:
    """Return sorted inbound dependency counts for app modules."""

    inbound_sources = build_inbound_sources(graph)
    return [
        {"module": module, "inbound_count": len(sources), "sources": sorted(sources)}
        for module, sources in sorted(
            inbound_sources.items(), key=lambda item: (-len(item[1]), item[0])
        )
        if sources
    ]


def normalize_outbound_module_budgets(
    allowlist_payload: dict | None,
) -> dict[str, int]:
    """Return per-module outbound dependency budgets from the allowlist payload."""

    if not allowlist_payload or "max_outbound_modules_by_app" not in allowlist_payload:
        return {}
    raw_budgets = allowlist_payload["max_outbound_modules_by_app"]
    if not isinstance(raw_budgets, dict):
        raise ValueError("max_outbound_modules_by_app must be a JSON object")
    budgets: dict[str, int] = {}
    for module, raw_budget in raw_budgets.items():
        module_name = str(module).strip()
        if not module_name:
            raise ValueError("max_outbound_modules_by_app contains an empty module name")
        budget = int(raw_budget)
        if budget < 0:
            raise ValueError(
                f"max_outbound_modules_by_app for {module_name!r} must be non-negative"
            )
        budgets[module_name] = budget
    return budgets


def normalize_inbound_module_budgets(
    allowlist_payload: dict | None,
) -> dict[str, int]:
    """Return per-module inbound dependency budgets from the allowlist payload."""

    if not allowlist_payload or "max_inbound_modules_by_app" not in allowlist_payload:
        return {}
    raw_budgets = allowlist_payload["max_inbound_modules_by_app"]
    if not isinstance(raw_budgets, dict):
        raise ValueError("max_inbound_modules_by_app must be a JSON object")
    budgets: dict[str, int] = {}
    for module, raw_budget in raw_budgets.items():
        module_name = str(module).strip()
        if not module_name:
            raise ValueError("max_inbound_modules_by_app contains an empty module name")
        budget = int(raw_budget)
        if budget < 0:
            raise ValueError(
                f"max_inbound_modules_by_app for {module_name!r} must be non-negative"
            )
        budgets[module_name] = budget
    return budgets


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


def load_allowlist(
    allowlist_path: Path | None,
) -> tuple[set[tuple[str, str]], set[tuple[str, ...]], dict | None]:
    if allowlist_path is None:
        return set(), set(), None
    payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
    pairs = {
        normalize_pair(pair)
        for pair in payload.get("allowed_bidirectional_pairs", [])
    }
    components = {
        normalize_component(component)
        for component in payload.get("allowed_cycle_components", [])
    }
    return pairs, components, payload


def build_report(
    *,
    graph: dict[str, set[str]],
    modules: Sequence[str],
    import_records: Sequence[object],
    bidirectional_pairs: list[tuple[str, str]],
    cycle_components: list[list[str]],
    allowed_pairs: set[tuple[str, str]],
    allowed_components: set[tuple[str, ...]],
    allowlist_path: Path | None,
    allowlist_payload: dict | None,
) -> dict:
    allowed_found = [list(pair) for pair in bidirectional_pairs if pair in allowed_pairs]
    unexpected = [list(pair) for pair in bidirectional_pairs if pair not in allowed_pairs]
    stale_allowlist = [list(pair) for pair in sorted(allowed_pairs - set(bidirectional_pairs))]
    normalized_components = {tuple(component) for component in cycle_components}
    allowed_components_found = [
        list(component) for component in sorted(normalized_components & allowed_components)
    ]
    unexpected_components = [
        list(component) for component in sorted(normalized_components - allowed_components)
    ]
    stale_allowed_components = [
        list(component) for component in sorted(allowed_components - normalized_components)
    ]
    edge_count = sum(len(targets) for targets in graph.values())
    outbound_summary = build_outbound_summary(graph)
    inbound_summary = build_inbound_summary(graph)
    max_app_import_edges = (
        int(allowlist_payload["max_app_import_edges"])
        if allowlist_payload and "max_app_import_edges" in allowlist_payload
        else None
    )
    max_outbound_modules_per_app = (
        int(allowlist_payload["max_outbound_modules_per_app"])
        if allowlist_payload and "max_outbound_modules_per_app" in allowlist_payload
        else None
    )
    max_inbound_modules_per_app = (
        int(allowlist_payload["max_inbound_modules_per_app"])
        if allowlist_payload and "max_inbound_modules_per_app" in allowlist_payload
        else None
    )
    outbound_module_budgets = normalize_outbound_module_budgets(allowlist_payload)
    inbound_module_budgets = normalize_inbound_module_budgets(allowlist_payload)
    edge_budget_exceeded = (
        bool(max_app_import_edges is not None and edge_count > max_app_import_edges)
    )
    edge_budget_stale = bool(max_app_import_edges is not None and edge_count < max_app_import_edges)
    outbound_budget_exceeded = [
        item
        for item in outbound_summary
        if max_outbound_modules_per_app is not None
        and int(item["outbound_count"]) > max_outbound_modules_per_app
    ]
    observed_max_outbound_modules = (
        max((int(item["outbound_count"]) for item in outbound_summary), default=0)
    )
    inbound_budget_exceeded = [
        item
        for item in inbound_summary
        if max_inbound_modules_per_app is not None
        and int(item["inbound_count"]) > max_inbound_modules_per_app
    ]
    observed_max_inbound_modules = (
        max((int(item["inbound_count"]) for item in inbound_summary), default=0)
    )
    outbound_counts_by_module = {
        module: len(targets) for module, targets in sorted(graph.items())
    }
    outbound_targets_by_module = {
        module: sorted(targets) for module, targets in sorted(graph.items())
    }
    inbound_sources_by_module = build_inbound_sources(graph)
    inbound_counts_by_module = {
        module: len(sources) for module, sources in sorted(inbound_sources_by_module.items())
    }
    inbound_targets_by_module = {
        module: sorted(sources) for module, sources in sorted(inbound_sources_by_module.items())
    }
    outbound_app_budget_exceeded = [
        {
            "module": module,
            "outbound_count": outbound_counts_by_module[module],
            "budget": outbound_module_budgets[module],
            "targets": outbound_targets_by_module[module],
        }
        for module in sorted(outbound_module_budgets)
        if module in outbound_counts_by_module
        and outbound_counts_by_module[module] > outbound_module_budgets[module]
    ]
    outbound_app_budget_stale = [
        {
            "module": module,
            "outbound_count": outbound_counts_by_module.get(module, 0),
            "budget": budget,
            "targets": outbound_targets_by_module.get(module, []),
        }
        for module, budget in sorted(outbound_module_budgets.items())
        if module not in outbound_counts_by_module
        or outbound_counts_by_module[module] < budget
    ]
    outbound_app_budget_missing = [
        {
            "module": module,
            "outbound_count": outbound_counts_by_module[module],
            "targets": outbound_targets_by_module[module],
        }
        for module in sorted(set(graph) - set(outbound_module_budgets))
    ] if outbound_module_budgets else []
    inbound_app_budget_exceeded = [
        {
            "module": module,
            "inbound_count": inbound_counts_by_module[module],
            "budget": inbound_module_budgets[module],
            "sources": inbound_targets_by_module[module],
        }
        for module in sorted(inbound_module_budgets)
        if module in inbound_counts_by_module
        and inbound_counts_by_module[module] > inbound_module_budgets[module]
    ]
    inbound_app_budget_stale = [
        {
            "module": module,
            "inbound_count": inbound_counts_by_module.get(module, 0),
            "budget": budget,
            "sources": inbound_targets_by_module.get(module, []),
        }
        for module, budget in sorted(inbound_module_budgets.items())
        if module not in inbound_counts_by_module
        or inbound_counts_by_module[module] < budget
    ]
    inbound_app_budget_missing = [
        {
            "module": module,
            "inbound_count": inbound_counts_by_module[module],
            "sources": inbound_targets_by_module[module],
        }
        for module in sorted(set(graph) - set(inbound_module_budgets))
    ] if inbound_module_budgets else []
    outbound_budget_stale = bool(
        max_outbound_modules_per_app is not None
        and observed_max_outbound_modules < max_outbound_modules_per_app
    )
    inbound_budget_stale = bool(
        max_inbound_modules_per_app is not None
        and observed_max_inbound_modules < max_inbound_modules_per_app
    )
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scan_roots": ["apps"],
        "module_count": len(modules),
        "edge_count": edge_count,
        "max_app_import_edges": max_app_import_edges,
        "edge_budget_exceeded": edge_budget_exceeded,
        "edge_budget_stale": edge_budget_stale,
        "max_outbound_modules_per_app": max_outbound_modules_per_app,
        "observed_max_outbound_modules": observed_max_outbound_modules,
        "outbound_budget_stale": outbound_budget_stale,
        "max_inbound_modules_per_app": max_inbound_modules_per_app,
        "observed_max_inbound_modules": observed_max_inbound_modules,
        "inbound_budget_stale": inbound_budget_stale,
        "max_outbound_modules_by_app": outbound_module_budgets,
        "outbound_app_budget_exceeded": outbound_app_budget_exceeded,
        "outbound_app_budget_stale": outbound_app_budget_stale,
        "outbound_app_budget_missing": outbound_app_budget_missing,
        "max_inbound_modules_by_app": inbound_module_budgets,
        "inbound_app_budget_exceeded": inbound_app_budget_exceeded,
        "inbound_app_budget_stale": inbound_app_budget_stale,
        "inbound_app_budget_missing": inbound_app_budget_missing,
        "outbound_summary": outbound_summary,
        "outbound_budget_exceeded": outbound_budget_exceeded,
        "inbound_summary": inbound_summary,
        "inbound_budget_exceeded": inbound_budget_exceeded,
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
        "allowed_cycle_components_found": allowed_components_found,
        "unexpected_cycle_components": unexpected_components,
        "stale_allowed_cycle_components": stale_allowed_components,
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
        if report["max_app_import_edges"] is not None:
            print(f"Max app import edges: {report['max_app_import_edges']}")
            print(f"Edge budget exceeded: {report['edge_budget_exceeded']}")
            print(f"Edge budget stale: {report['edge_budget_stale']}")
        if report["max_outbound_modules_per_app"] is not None:
            print(f"Max outbound modules per app: {report['max_outbound_modules_per_app']}")
            print(f"Observed max outbound modules: {report['observed_max_outbound_modules']}")
            print(f"Outbound budget exceeded: {len(report['outbound_budget_exceeded'])}")
            print(f"Outbound budget stale: {report['outbound_budget_stale']}")
        if report["max_inbound_modules_per_app"] is not None:
            print(f"Max inbound modules per app: {report['max_inbound_modules_per_app']}")
            print(f"Observed max inbound modules: {report['observed_max_inbound_modules']}")
            print(f"Inbound budget exceeded: {len(report['inbound_budget_exceeded'])}")
            print(f"Inbound budget stale: {report['inbound_budget_stale']}")
        if report["max_outbound_modules_by_app"]:
            print(
                "Per-app outbound budgets: "
                f"{len(report['max_outbound_modules_by_app'])}"
            )
            print(
                "Per-app outbound budget exceeded: "
                f"{len(report['outbound_app_budget_exceeded'])}"
            )
            print(
                "Per-app outbound budget stale: "
                f"{len(report['outbound_app_budget_stale'])}"
            )
            print(
                "Per-app outbound budget missing: "
                f"{len(report['outbound_app_budget_missing'])}"
            )
        if report["max_inbound_modules_by_app"]:
            print(
                "Per-app inbound budgets: "
                f"{len(report['max_inbound_modules_by_app'])}"
            )
            print(
                "Per-app inbound budget exceeded: "
                f"{len(report['inbound_app_budget_exceeded'])}"
            )
            print(
                "Per-app inbound budget stale: "
                f"{len(report['inbound_app_budget_stale'])}"
            )
            print(
                "Per-app inbound budget missing: "
                f"{len(report['inbound_app_budget_missing'])}"
            )
        print(f"Unexpected pairs: {len(report['unexpected_pairs'])}")
        print(f"Unexpected cycle components: {len(report['unexpected_cycle_components'])}")
        print(f"Stale allowlist pairs: {len(report['stale_allowlist_pairs'])}")
        print(f"Stale allowed cycle components: {len(report['stale_allowed_cycle_components'])}")

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

    if report["unexpected_cycle_components"]:
        print("")
        print("Unexpected cycle components:")
        for component in report["unexpected_cycle_components"]:
            print(f"- {', '.join(component)}")

    if report["stale_allowed_cycle_components"]:
        print("")
        print("Resolved allowed cycle components:")
        for component in report["stale_allowed_cycle_components"]:
            print(f"- {', '.join(component)}")

    if report["outbound_budget_exceeded"]:
        print("")
        print("Outbound dependency budget exceeded:")
        for item in report["outbound_budget_exceeded"]:
            targets = ", ".join(item["targets"])
            print(f"- {item['module']}: {item['outbound_count']} -> {targets}")

    if report["outbound_app_budget_exceeded"]:
        print("")
        print("Per-app outbound dependency budget exceeded:")
        for item in report["outbound_app_budget_exceeded"]:
            targets = ", ".join(item["targets"])
            print(
                f"- {item['module']}: {item['outbound_count']} "
                f"> {item['budget']} -> {targets}"
            )

    if report["outbound_app_budget_stale"]:
        print("")
        print("Per-app outbound dependency budget stale:")
        for item in report["outbound_app_budget_stale"]:
            print(
                f"- {item['module']}: {item['outbound_count']} "
                f"< {item['budget']}"
            )

    if report["outbound_app_budget_missing"]:
        print("")
        print("Per-app outbound dependency budget missing:")
        for item in report["outbound_app_budget_missing"]:
            print(f"- {item['module']}: {item['outbound_count']}")

    if report["inbound_budget_exceeded"]:
        print("")
        print("Inbound dependency budget exceeded:")
        for item in report["inbound_budget_exceeded"]:
            sources = ", ".join(item["sources"])
            print(f"- {item['module']}: {item['inbound_count']} <- {sources}")

    if report["inbound_app_budget_exceeded"]:
        print("")
        print("Per-app inbound dependency budget exceeded:")
        for item in report["inbound_app_budget_exceeded"]:
            sources = ", ".join(item["sources"])
            print(
                f"- {item['module']}: {item['inbound_count']} "
                f"> {item['budget']} <- {sources}"
            )

    if report["inbound_app_budget_stale"]:
        print("")
        print("Per-app inbound dependency budget stale:")
        for item in report["inbound_app_budget_stale"]:
            print(
                f"- {item['module']}: {item['inbound_count']} "
                f"< {item['budget']}"
            )

    if report["inbound_app_budget_missing"]:
        print("")
        print("Per-app inbound dependency budget missing:")
        for item in report["inbound_app_budget_missing"]:
            print(f"- {item['module']}: {item['inbound_count']}")

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
    allowed_pairs, allowed_components, allowlist_payload = load_allowlist(allowlist_path)

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
        allowed_components=allowed_components,
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

    has_unexpected_pairs = bool(report["unexpected_pairs"])
    has_unexpected_components = bool(report["unexpected_cycle_components"])
    has_budget_regression = bool(
        report["edge_budget_exceeded"]
        or report["outbound_budget_exceeded"]
        or report["outbound_app_budget_exceeded"]
        or report["outbound_app_budget_missing"]
        or report["inbound_budget_exceeded"]
        or report["inbound_app_budget_exceeded"]
        or report["inbound_app_budget_missing"]
    )
    has_stale_baseline = bool(
        report["stale_allowlist_pairs"]
        or report["stale_allowed_cycle_components"]
        or report["edge_budget_stale"]
        or report["outbound_budget_stale"]
        or report["outbound_app_budget_stale"]
        or report["inbound_budget_stale"]
        or report["inbound_app_budget_stale"]
    )
    if allowlist_payload is not None:
        return (
            1
            if has_unexpected_pairs
            or has_unexpected_components
            or has_budget_regression
            or has_stale_baseline
            else 0
        )
    return 1 if bidirectional_pairs or cycle_components else 0


if __name__ == "__main__":
    sys.exit(main())
