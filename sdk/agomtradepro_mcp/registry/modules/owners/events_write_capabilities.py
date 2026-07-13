"""events write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="events.publish.event",
        title="Publish Domain Event",
        summary="Preview a stable event identity, then confirm staff-only synchronous publication.",
        description=(
            "Validate an explicit canonical domain event, disclose that subscribers may perform "
            "cross-module writes, then require confirmation before persisting the event and "
            "synchronously notifying subscribers through the formal Events SDK."
        ),
        owner_app="events",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="events_publish_event",
        tags=("events", "domain-event", "publish", "workflow", "write"),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "event_type": {
                    "type": "string",
                    "enum": [
                        "regime_changed",
                        "regime_confidence_low",
                        "regime_distribution_shift",
                        "policy_level_changed",
                        "policy_event_created",
                        "policy_event_updated",
                        "signal_created",
                        "signal_approved",
                        "signal_rejected",
                        "signal_triggered",
                        "signal_invalidated",
                        "signal_expired",
                        "alpha_trigger_activated",
                        "alpha_trigger_fired",
                        "alpha_trigger_invalidated",
                        "alpha_trigger_expired",
                        "beta_gate_evaluated",
                        "beta_gate_passed",
                        "beta_gate_blocked",
                        "decision_requested",
                        "decision_approved",
                        "decision_rejected",
                        "decision_executed",
                        "decision_execution_failed",
                        "quota_exceeded",
                        "quota_reset",
                        "position_opened",
                        "position_closed",
                        "position_stopped",
                        "position_adjusted",
                        "stop_loss_triggered",
                        "take_profit_triggered",
                        "system_error",
                        "audit_completed",
                        "backtest_completed",
                    ],
                },
                "payload": {"type": "object"},
                "metadata": {"type": "object"},
                "occurred_at": {"type": "string", "format": "date-time"},
                "correlation_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
                "causation_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
                "idempotency_key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
            },
            "required": [
                "event_type",
                "payload",
                "occurred_at",
                "idempotency_key",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event_id": {"type": "string"},
                "published_at": {"type": "string"},
                "subscribers_notified": {"type": "integer"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("events:publish", "mcp:write"),
        legacy_tool_names=("publish_event",),
    ),
]
