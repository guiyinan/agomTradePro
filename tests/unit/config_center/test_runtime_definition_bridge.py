"""Owner-side runtime registration and consumer bridge contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.config_center.application import runtime_public
from apps.config_center.domain.runtime_config import RuntimeConfigDefinition, RuntimeValueType
from core.integration import config_center_runtime as bridge


def test_bridge_registration_uses_owner_repository_and_preserves_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic metadata becomes an owner definition before repository writes."""

    saved: list[RuntimeConfigDefinition] = []

    def save(definition: RuntimeConfigDefinition) -> RuntimeConfigDefinition:
        saved.append(definition)
        return definition

    monkeypatch.setattr(
        runtime_public, "get_runtime_definition_repository", lambda: SimpleNamespace(save=save)
    )
    monkeypatch.setattr(bridge, "_provider", runtime_public)
    specification = bridge.RuntimeConfigDefinitionSpec(
        key="consumer.limit",
        namespace="consumer",
        owner_app="consumer",
        value_type="bytes",
        criticality="critical",
        reload_mode="restart_required",
        minimum=1,
    )

    assert bridge.register_runtime_definitions((specification,)) == ("consumer.limit",)
    assert saved[0].value_type is RuntimeValueType.BYTES
    assert saved[0].constraints == {"minimum": 1}
    with pytest.raises(ValueError):
        saved[0].validate(0)


def test_missing_owner_cannot_register_or_resolve_secret_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner registration absence does not become a writable fallback."""

    monkeypatch.setattr(bridge, "_provider", None)
    assert (
        bridge.get_active_runtime_secret_ref(environment="test", definition_key="consumer.key")
        is None
    )
    with pytest.raises(RuntimeError, match="unconfigured"):
        bridge.register_runtime_definitions(())


def test_invalid_later_definition_does_not_partially_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner validates the entire metadata batch before the first write."""

    saved: list[RuntimeConfigDefinition] = []

    def save(definition: RuntimeConfigDefinition) -> RuntimeConfigDefinition:
        saved.append(definition)
        return definition

    monkeypatch.setattr(
        runtime_public, "get_runtime_definition_repository", lambda: SimpleNamespace(save=save)
    )
    monkeypatch.setattr(bridge, "_provider", runtime_public)
    with pytest.raises(ValueError):
        bridge.register_runtime_definitions(
            (
                bridge.RuntimeConfigDefinitionSpec(
                    key="consumer.enabled",
                    namespace="consumer",
                    owner_app="consumer",
                    value_type="bool",
                ),
                bridge.RuntimeConfigDefinitionSpec(
                    key="invalid", namespace="consumer", owner_app="consumer", value_type="bool"
                ),
            )
        )
    assert saved == []


def test_bridge_activation_forwards_secret_references_without_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing activation bridge carries refs into the owner facade."""

    calls: list[dict[str, object]] = []

    def activate(**options: object) -> dict[str, object]:
        calls.append(options)
        return {"profile_version": 2, "snapshot_hash": "evidence"}

    monkeypatch.setattr(
        bridge, "_provider", SimpleNamespace(activate_runtime_profile_patch_payload=activate)
    )
    result = bridge.activate_runtime_profile_patch(
        environment="test",
        patch={"consumer.enabled": True},
        secret_ref_patch={"consumer.key": "secret-reference"},
        bootstrap_values=None,
        actor="reviewer",
        reason="explicit configuration",
    )
    assert result["profile_version"] == 2
    assert calls[0]["secret_ref_patch"] == {"consumer.key": "secret-reference"}
