"""Pure tests for the app-neutral legacy Broker Evidence registry."""

from __future__ import annotations

import pytest

import core.integration.legacy_broker_approval_evidence as registry


def test_registry_fails_with_a_stable_error_before_app_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_projector", None)

    with pytest.raises(
        registry.LegacyBrokerApprovalEvidenceProjectorUnavailable,
        match="^legacy_broker_approval_evidence_projector_unconfigured$",
    ):
        registry.project_legacy_broker_approval_evidence({"approval": "sealed"})


def test_registry_delegates_the_closed_payload_without_app_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_projector", None)
    captured: list[dict[str, object]] = []

    def projector(payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        captured.append(dict(payload))
        return {"permission": "display_only", "must_not_execute": True}

    registry.configure_legacy_broker_approval_evidence_projector(projector)

    result = registry.project_legacy_broker_approval_evidence({"approval": "sealed"})

    assert captured == [{"approval": "sealed"}]
    assert result == {"permission": "display_only", "must_not_execute": True}
