"""realtime read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="realtime.read.price",
        title="Realtime Asset Price",
        summary="Read the latest normalized price for one asset.",
        description=(
            "Return the latest available price snapshot for one asset, including normalized "
            "price, change, volume, source, and update timestamp fields."
        ),
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_realtime_price",
        tags=("realtime", "market_data", "price", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "current_price": {"type": ["number", "null"]},
                "price_change": {"type": ["number", "null"]},
                "price_change_percent": {"type": ["number", "null"]},
                "volume": {"type": ["number", "null"]},
                "updated_at": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_realtime_price",),
    ),
    CapabilityManifest(
        capability_key="realtime.read.price_batch",
        title="Realtime Asset Price Batch",
        summary="Read the latest normalized prices for multiple assets.",
        description=(
            "Return the latest available normalized price snapshots for a bounded list of "
            "asset codes."
        ),
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_multiple_realtime_prices",
        tags=("realtime", "market_data", "price", "batch", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 100,
                },
            },
            "required": ["asset_codes"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "prices": {"type": "object"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_multiple_realtime_prices",),
    ),
    CapabilityManifest(
        capability_key="realtime.read.market_summary",
        title="Realtime Market Summary",
        summary="Read the current major-index market summary snapshot.",
        description=(
            "Return the current major-index snapshot and explicitly report whether broader "
            "market breadth statistics are available."
        ),
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_market_summary",
        tags=("realtime", "market_data", "market", "summary", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "stats_available": {"type": "boolean"},
                "message": {"type": "string"},
                "timestamp": {"type": ["string", "null"]},
                "sh_index": {"type": ["number", "null"]},
                "sz_index": {"type": ["number", "null"]},
                "cyb_index": {"type": ["number", "null"]},
                "up_count": {"type": "integer"},
                "down_count": {"type": "integer"},
                "flat_count": {"type": "integer"},
                "limit_up_count": {"type": "integer"},
                "limit_down_count": {"type": "integer"},
                "total_volume": {"type": "number"},
                "total_value": {"type": "number"},
            },
            "required": [],
        },
        legacy_tool_names=("get_market_summary",),
    ),
]
