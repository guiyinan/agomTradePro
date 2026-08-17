"""Runtime action patches for macro/regime historical chart contracts."""

from __future__ import annotations

from typing import Any

RUNTIME_ACTION_PATCHES_MACRO_DATA: dict[str, dict[str, Any]] = {
    # Historical published graphs may describe this action as a generic
    # datagrid.  The current IA contract is a chart, so normalize old
    # snapshots before validating/republishing rollback candidates.
    "pulse.history": {
        "view_type": "chart",
        "view_model": {
            "rows_path": "data",
            "total_path": "count",
            "kind": "chart",
            "columns": [
                {"key": "observed_at", "label": "日期"},
                {"key": "composite_score", "label": "综合脉搏"},
                {"key": "growth_score", "label": "增长"},
                {"key": "inflation_score", "label": "通胀"},
            ],
        },
    },
}


__all__ = ["RUNTIME_ACTION_PATCHES_MACRO_DATA"]
