"""Governed MCP contracts for scenario revisions."""

from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.runtime_handlers.owners import risk_center


def test_scenario_registry_exposes_only_governed_capabilities() -> None:
    registry = CapabilityRegistryLoader().build_registry()
    expected = {
        "risk_center.stress_scenario.list",
        "risk_center.stress_scenario.read",
        "risk_center.stress_scenario.compare",
        "risk_center.stress_scenario.validate_revision",
        "risk_center.stress_scenario.preview_revision",
        "risk_center.stress_scenario.propose_revision",
        "risk_center.stress_scenario.activate_revision",
        "risk_center.stress_scenario.rollback_revision",
        "risk_center.stress_scenario.retire",
    }

    assert expected.issubset(registry)
    for key in expected:
        assert registry[key].owner_app == "risk_center"
        assert registry[key].executor_kind == "internal_handler"


def test_scenario_preview_declares_synced_audit_tags() -> None:
    manifest = CapabilityRegistryLoader().build_registry()[
        "risk_center.stress_scenario.preview_revision"
    ]

    assert manifest.audit_tags == (
        "risk_center:stress_scenario:preview",
        "mcp:read",
    )


@pytest.mark.parametrize(
    ("key", "roles"),
    [
        (
            "risk_center.stress_scenario.propose_revision",
            ("admin", "investment_manager", "ai_service"),
        ),
        ("risk_center.stress_scenario.activate_revision", ("staff",)),
        ("risk_center.stress_scenario.rollback_revision", ("staff",)),
        ("risk_center.stress_scenario.retire", ("staff",)),
    ],
)
def test_scenario_writes_require_preview_confirmation_and_persistent_idempotency(
    key: str,
    roles: tuple[str, ...],
) -> None:
    manifest = CapabilityRegistryLoader().build_registry()[key]

    assert manifest.requires_confirmation is True
    assert manifest.confirmation_preview_arguments == {"preview_only": True}
    assert manifest.confirmation_commit_arguments == {"preview_only": False}
    assert manifest.idempotency == "required"
    assert manifest.required_roles == roles
    assert "preview_id" in manifest.input_schema["required"]
    assert "correlation_id" in manifest.input_schema["required"]


def test_proposal_handler_preserves_backend_preview_and_idempotency_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _RiskCenter:
        @staticmethod
        def preview_scenario_action(
            operation: str,
            payload: dict[str, object],
        ) -> dict[str, object]:
            calls.append((f"preview:{operation}", dict(payload)))
            return {
                "status": "preview_required",
                "preview_id": "preview-1",
                "request_fingerprint": "fingerprint-1",
            }

        @staticmethod
        def propose_scenario_revision(payload: dict[str, object]) -> dict[str, object]:
            calls.append(("propose", dict(payload)))
            return {
                "status": "created",
                "proposal_id": "proposal-1",
                "correlation_id": payload["correlation_id"],
            }

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(risk_center=_RiskCenter()),
    )
    arguments = {
        "payload": {"scenario_key": "tail-risk", "based_on_version": 2},
        "preview_id": "preview-1",
        "expected_active_version": 2,
        "expected_active_hash": "base-hash",
        "change_reason": "refresh evidence",
        "correlation_id": "correlation-1",
        "idempotency_key": "idem-1",
    }

    preview = risk_center._internal_handler_risk_center_stress_scenario_propose_revision(
        **arguments,
        preview_only=True,
    )
    committed = risk_center._internal_handler_risk_center_stress_scenario_propose_revision(
        **arguments,
        preview_only=False,
    )

    assert preview["preview_only"] is True
    assert committed["status"] == "created"
    assert calls[0][0] == "preview:propose"
    assert calls[0][1]["payload"] == {
        "scenario_key": "tail-risk",
        "based_on_version": 2,
    }
    assert calls[1][1]["preview_id"] == "preview-1"
    assert calls[1][1]["idempotency_key"] == "idem-1"
    assert calls[1][1]["expected_active_hash"] == "base-hash"
