"""M5-C finalized inventory contracts for the Web-to-TUI migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.web_template_migration_inventory import (
    DEFAULT_PUBLISHED_GRAPH_PATH,
    RouteRecord,
    SourceReference,
    _legacy_alias_violations,
    check_finalized_inventory_file,
    load_rules,
    validate_finalized_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"


def _rules() -> dict[str, Any]:
    """Return the approved 41-template retained-scope count."""

    return {"retained_rules": [{"expected_count": 41}]}


def _write_graph(root: Path, aliases: dict[str, str] | None = None) -> Path:
    """Write one minimal published graph with canonical alias targets."""

    graph_path = root / "config/tui/published/graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps(
            {
                "screens": [{"key": "canonical.screen"}],
                "legacy_screen_aliases": aliases or {},
            }
        ),
        encoding="utf-8",
    )
    return graph_path


def _write_ia(root: Path, *, runtime_keys: list[str]) -> Path:
    """Write the minimal IA source used to test runtime canonical screens."""

    ia_path = root / "config/tui/ia/tui_information_architecture.v1.json"
    ia_path.parent.mkdir(parents=True, exist_ok=True)
    ia_path.write_text(
        json.dumps(
            {
                "published_screens": [{"key": "canonical.screen"}],
                "runtime_screens": [{"key": key} for key in runtime_keys],
            }
        ),
        encoding="utf-8",
    )
    return ia_path


def _retained_rows(root: Path) -> list[dict[str, str]]:
    """Create the exact 41 physical C templates required at M5-C."""

    rows: list[dict[str, str]] = []
    for index in range(41):
        relative = f"core/templates/retained/page-{index}.html"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"retained {index}\n", encoding="utf-8")
        rows.append(
            {
                "template_path": relative,
                "template_name": f"retained/page-{index}.html",
                "destination_class": "C",
                "status": "retained",
                "related_static_assets": "",
            }
        )
    return rows


def _validate(
    root: Path,
    rows: list[dict[str, str]],
    *,
    graph_path: Path,
    references: dict[str, list[SourceReference]] | None = None,
    routes: list[RouteRecord] | None = None,
) -> None:
    """Validate a synthetic final repository without importing Django."""

    validate_finalized_inventory(
        root,
        rows,
        rules=_rules(),
        graph_path=graph_path,
        template_references=references or {},
        routes=routes or [],
    )


def test_current_repository_is_explicitly_not_finalized() -> None:
    """The ordinary 196-row matrix remains valid but cannot pass M5-C today."""

    with pytest.raises(ValueError, match="Final lifecycle statuses are incomplete"):
        check_finalized_inventory_file(
            ROOT,
            rules=load_rules(ROOT),
            inventory_path=MATRIX_PATH,
            graph_path=DEFAULT_PUBLISHED_GRAPH_PATH,
        )


def test_current_alias_inventory_exposes_known_m5_c_debt() -> None:
    """The 32 published aliases expose the exact known M5-C dead-reference debt."""

    payload = json.loads(DEFAULT_PUBLISHED_GRAPH_PATH.read_text(encoding="utf-8"))
    dangling, dead = _legacy_alias_violations(
        ROOT,
        graph_path=DEFAULT_PUBLISHED_GRAPH_PATH,
    )

    assert len(payload["legacy_screen_aliases"]) == 32
    assert dead == [
        "ai-ops.prompt-workbench",
        "api-library.market-thermometer",
        "command-center.dashboard",
        "execution.trading-ledger",
        "macro-regime.beta-gate",
        "macro-regime.hedge",
        "macro-regime.navigator",
        "macro-regime.risk-controls",
        "macro-regime.rotation",
        "research.backtests",
        "research.factors",
        "research.fund-sector",
        "research.screening-sentiment",
    ]
    assert dangling == []


def test_exact_41_template_c_scope_is_finalized(tmp_path: Path) -> None:
    """Only the exact retained C scope may remain physically present."""

    rows = _retained_rows(tmp_path)

    _validate(tmp_path, rows, graph_path=_write_graph(tmp_path))


def test_a_or_b_lifecycle_must_be_deleted(tmp_path: Path) -> None:
    """A/B historical rows cannot remain migrated or backlog at finalization."""

    rows = _retained_rows(tmp_path)
    rows.append(
        {
            "template_path": "core/templates/removed/old.html",
            "template_name": "removed/old.html",
            "destination_class": "A",
            "status": "migrated",
            "related_static_assets": "",
        }
    )

    with pytest.raises(ValueError, match="Final lifecycle statuses are incomplete"):
        _validate(tmp_path, rows, graph_path=_write_graph(tmp_path))


def test_non_c_physical_template_is_rejected(tmp_path: Path) -> None:
    """A deleted matrix row cannot conceal a Classic template still on disk."""

    rows = _retained_rows(tmp_path)
    relative = "core/templates/removed/old.html"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("still here\n", encoding="utf-8")
    rows.append(
        {
            "template_path": relative,
            "template_name": "removed/old.html",
            "destination_class": "B",
            "status": "deleted",
            "related_static_assets": "",
        }
    )

    with pytest.raises(ValueError, match="non_C_remaining"):
        _validate(tmp_path, rows, graph_path=_write_graph(tmp_path))


def test_deleted_template_view_and_route_references_are_orphans(tmp_path: Path) -> None:
    """An active route/view cannot retain a literal reference to a deleted template."""

    rows = _retained_rows(tmp_path)
    rows.append(
        {
            "template_path": "core/templates/removed/old.html",
            "template_name": "removed/old.html",
            "destination_class": "A",
            "status": "deleted",
            "related_static_assets": "",
        }
    )
    reference = SourceReference(
        module="apps.example.interface.views",
        symbol="legacy_view",
        source_path="apps/example/interface/views.py",
        line=17,
    )
    route = RouteRecord(
        path="/legacy/",
        name="legacy",
        module=reference.module,
        symbol=reference.symbol,
        callable_name=f"{reference.module}.{reference.symbol}",
        methods=("GET",),
    )

    with pytest.raises(ValueError) as exc_info:
        _validate(
            tmp_path,
            rows,
            graph_path=_write_graph(tmp_path),
            references={"removed/old.html": [reference]},
            routes=[route],
        )

    assert "template_references=" in str(exc_info.value)
    assert "routes=['/legacy/" in str(exc_info.value)


def test_static_asset_used_only_by_deleted_templates_is_orphaned(tmp_path: Path) -> None:
    """A physical static asset with no live source consumer must be removed."""

    rows = _retained_rows(tmp_path)
    rows.append(
        {
            "template_path": "core/templates/removed/old.html",
            "template_name": "removed/old.html",
            "destination_class": "A",
            "status": "deleted",
            "related_static_assets": "css/legacy-only.css",
        }
    )
    asset = tmp_path / "static/css/legacy-only.css"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(".legacy { display: none; }\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"static_assets=\['css/legacy-only.css'\]"):
        _validate(tmp_path, rows, graph_path=_write_graph(tmp_path))


def test_static_asset_with_a_live_retained_consumer_is_not_orphaned(tmp_path: Path) -> None:
    """Static cleanup retains an asset that is still referenced by live C code."""

    rows = _retained_rows(tmp_path)
    rows.append(
        {
            "template_path": "core/templates/removed/old.html",
            "template_name": "removed/old.html",
            "destination_class": "A",
            "status": "deleted",
            "related_static_assets": "css/shared.css",
        }
    )
    asset = tmp_path / "static/css/shared.css"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(".shared { display: block; }\n", encoding="utf-8")
    retained = tmp_path / rows[0]["template_path"]
    retained.write_text("css/shared.css\n", encoding="utf-8")

    _validate(tmp_path, rows, graph_path=_write_graph(tmp_path))


def test_dead_legacy_alias_is_rejected_while_live_alias_is_retained(tmp_path: Path) -> None:
    """Only aliases with a live production source consumer may remain published."""

    rows = _retained_rows(tmp_path)
    source = tmp_path / "apps/example/application/navigation.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('SCREEN = "legacy.live"\n', encoding="utf-8")
    graph_path = _write_graph(
        tmp_path,
        {"legacy.live": "canonical.screen", "legacy.dead": "canonical.screen"},
    )

    with pytest.raises(ValueError, match=r"dead_aliases=\['legacy.dead'\]"):
        _validate(tmp_path, rows, graph_path=graph_path)


def test_alias_target_must_be_a_canonical_published_screen(tmp_path: Path) -> None:
    """Alias chains, self-aliases, and missing targets remain invalid at M5-C."""

    rows = _retained_rows(tmp_path)
    source = tmp_path / "apps/example/application/navigation.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('SCREEN = "legacy.one"\n', encoding="utf-8")
    graph_path = _write_graph(
        tmp_path,
        {"legacy.one": "legacy.two", "legacy.two": "canonical.screen"},
    )

    with pytest.raises(ValueError, match=r"dangling_aliases=\['legacy.one'\]"):
        _validate(tmp_path, rows, graph_path=graph_path)


def test_runtime_ia_screen_is_a_canonical_alias_target(tmp_path: Path) -> None:
    """Runtime IA screens are canonical even when absent from graph screens."""

    rows = _retained_rows(tmp_path)
    source = tmp_path / "apps/example/application/navigation.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('SCREEN = "legacy.runtime"\n', encoding="utf-8")
    graph_path = _write_graph(tmp_path, {"legacy.runtime": "runtime.screen"})
    ia_path = _write_ia(tmp_path, runtime_keys=["runtime.screen"])

    dangling, dead = _legacy_alias_violations(
        tmp_path,
        graph_path=graph_path,
        ia_path=ia_path,
    )

    assert dangling == []
    assert dead == []

    _validate(tmp_path, rows, graph_path=graph_path)
