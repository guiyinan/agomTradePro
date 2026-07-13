"""audit read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="audit.read.summary",
        title="Audit Attribution Summary",
        summary="Read canonical attribution-report summaries.",
        description=(
            "Return attribution reports for one backtest, one explicit date range, or "
            "the governed rolling 30-day default. Backtest and date-range modes are exclusive."
        ),
        owner_app="audit",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_audit_summary",
        tags=("audit", "attribution", "report", "summary", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "backtest_id": {"type": ["integer", "null"]},
                "start_date": {
                    "type": ["string", "null"],
                    "format": "date",
                },
                "end_date": {
                    "type": ["string", "null"],
                    "format": "date",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "reports": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
                "error": {"type": ["string", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_audit_summary",),
    ),
    CapabilityManifest(
        capability_key="audit.read.execution_links",
        title="Audit Execution Links",
        summary="Read recommendation-to-execution audit links.",
        description=(
            "Return user-scoped recommendation execution links filtered by account, "
            "recommendation, transaction source, and bounded result limit."
        ),
        owner_app="audit",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_audit_execution_links",
        tags=("audit", "recommendation", "execution", "traceability", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["string", "integer", "null"]},
                "recommendation_id": {"type": ["string", "null"]},
                "transaction_source": {"type": ["string", "null"]},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "links": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("list_audit_execution_links",),
    ),
]
