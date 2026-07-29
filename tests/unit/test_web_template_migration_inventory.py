from __future__ import annotations

from pathlib import Path

from scripts.web_template_migration_inventory import (
    build_inventory,
    check_inventory_file,
    classify_template_role,
    discover_template_paths,
    load_rules,
    parse_template_facts,
    read_inventory,
    validate_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs" / "plans" / "web-to-tui-migration-matrix-2026-07-25.csv"


def test_parse_template_facts_extracts_dependencies_and_runtime_features(
    tmp_path: Path,
) -> None:
    template = tmp_path / "sample.html"
    template.write_text(
        """
{% extends "base.html" %}
{% include "components/card.html" %}
{% load static %}
<script>fetch("/api/sample/"); window.setInterval(refresh, 1000);</script>
<script src="{% static 'js/vendor.js' %}"></script>
<canvas id="trend"></canvas>
<a href="/download/report.csv">下载</a>
""".strip(),
        encoding="utf-8",
    )

    facts = parse_template_facts(template, chart_markers=("<canvas",))

    assert facts.extends == ("base.html",)
    assert facts.includes == ("components/card.html",)
    assert facts.api_endpoints == ("/api/sample/",)
    assert facts.static_assets == ("js/vendor.js",)
    assert facts.has_inline_script is True
    assert facts.is_chart_heavy is True
    assert facts.has_upload_download is True
    assert facts.has_streaming_or_polling is True


def test_template_role_classification_distinguishes_supporting_templates() -> None:
    assert classify_template_role("core/templates/components/card.html") == "partial_component"
    assert classify_template_role("apps/audit/templates/audit/base.html") == "layout"
    assert classify_template_role("core/templates/equity/detail.html") == "route_page"


def test_repository_inventory_matches_approved_m0_baseline() -> None:
    rules = load_rules(ROOT)
    reviewed_rows = read_inventory(MATRIX_PATH)

    validate_inventory(reviewed_rows, rules=rules)
    check_inventory_file(ROOT, rules=rules, inventory_path=MATRIX_PATH)

    assert len(reviewed_rows) == 196
    assert sum(row["destination_class"] == "C" for row in reviewed_rows) == 41
    assert sum(row["status"] == "deleted" for row in reviewed_rows) == 7
    assert len(discover_template_paths(ROOT)) == 189
    assert len({row["template_path"] for row in reviewed_rows}) == 196
    assert all(row["content_hash"] for row in reviewed_rows)
    assert all(row["resolved_template_origin"] for row in reviewed_rows)
    assert all(
        row["target_screen_key"]
        for row in reviewed_rows
        if row["template_role"] == "route_page" and row["destination_class"] in {"A", "B"}
    )
    current_rows = build_inventory(ROOT, rules=rules, resolve_django=True)
    by_path = {row["template_path"]: row for row in current_rows}
    reviewed_by_path = {row["template_path"]: row for row in reviewed_rows}
    assert by_path["core/templates/dashboard/index.html"]["url_path_pattern"] == "/dashboard/"
    assert by_path["core/templates/terminal/config.html"]["url_path_pattern"] == ""
    assert "/terminal/config/" in reviewed_by_path["core/templates/terminal/config.html"][
        "url_path_pattern"
    ]
