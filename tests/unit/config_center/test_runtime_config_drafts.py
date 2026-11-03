"""Unit contracts for create-only, generic Config Center drafts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.config_center.application.runtime_config_drafts import (
    RuntimeConfigDraftCreateResult,
    RuntimeConfigDraftRequest,
    RuntimeConfigDraftService,
    RuntimeConfigDraftValidationError,
    RuntimeConfigDraftValueInput,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigReloadMode,
    RuntimeConfigRevision,
    RuntimeConfigValue,
    RuntimeValueType,
    hash_runtime_profile_values,
)


class _Definitions:
    """Minimal registered definition catalog for generic service tests."""

    def __init__(self) -> None:
        self.definitions = [
            RuntimeConfigDefinition(
                key="test.draft.typed_json",
                namespace="test",
                owner_app="test",
                value_type=RuntimeValueType.TYPED_JSON,
                criticality=RuntimeConfigCriticality.NORMAL,
                reload_mode=RuntimeConfigReloadMode.IMMEDIATE,
            )
        ]

    def list_all(self) -> list[RuntimeConfigDefinition]:
        """Return the configured test definition."""

        return list(self.definitions)


class _Persistence:
    """In-memory persistence spy that never mutates runtime state."""

    def __init__(self) -> None:
        self.calls: list[RuntimeConfigDraftCreateResult] = []

    def create_draft(
        self,
        *,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
        revision: RuntimeConfigRevision,
    ) -> RuntimeConfigDraftCreateResult:
        """Capture one planned transaction for the service contract."""

        result = RuntimeConfigDraftCreateResult(
            profile=profile,
            values=values,
            revision=revision,
            created=True,
        )
        self.calls.append(result)
        return result


def _request(value: object | None = None) -> RuntimeConfigDraftRequest:
    """Return one generic typed_json draft request."""

    return RuntimeConfigDraftRequest(
        profile_key="test.profile.draft",
        environment="development",
        version=1,
        actor="operator@example.test",
        reason="draft-only validation fixture",
        values=(
            RuntimeConfigDraftValueInput(
                definition_key="test.draft.typed_json",
                value_json={"setting": "candidate"} if value is None else value,
                source="test_fixture",
            ),
        ),
    )


def test_preview_is_deterministic_and_has_no_persistence_side_effect() -> None:
    definitions = _Definitions()
    persistence = _Persistence()
    service = RuntimeConfigDraftService(definitions, persistence)

    first = service.preview(_request())
    second = service.preview(_request())

    assert first.profile.profile_id == second.profile.profile_id
    assert first.revision.revision_id == second.revision.revision_id
    assert first.profile.status.value == "draft"
    assert first.profile.content_hash == hash_runtime_profile_values(
        {"test.draft.typed_json": {"setting": "candidate"}}
    )
    assert first.revision.validation_evidence == {
        "draft_only": True,
        "generic_definition_validation": "passed",
        "consumer_schema_validation": "not_performed",
        "snapshot_created": False,
        "active_pointer_changed": False,
    }
    assert persistence.calls == []


def test_create_delegates_one_prepared_bundle_to_the_atomic_port() -> None:
    persistence = _Persistence()
    service = RuntimeConfigDraftService(_Definitions(), persistence)

    result = service.create(_request())

    assert result.created is True
    assert len(result.values) == 1
    assert result.profile.status.value == "draft"
    assert len(persistence.calls) == 1


def test_unknown_definition_is_rejected_without_persistence() -> None:
    persistence = _Persistence()
    service = RuntimeConfigDraftService(_Definitions(), persistence)
    request = RuntimeConfigDraftRequest(
        profile_key="test.profile.draft",
        environment="development",
        version=1,
        actor="operator@example.test",
        reason="unknown definition contract",
        values=(
            RuntimeConfigDraftValueInput(
                definition_key="test.missing",
                value_json={"x": 1},
                source="test_fixture",
            ),
        ),
    )

    with pytest.raises(RuntimeConfigDraftValidationError) as exc_info:
        service.create(request)

    assert exc_info.value.reason_code == "DRAFT_DEFINITION_UNKNOWN"
    assert persistence.calls == []


def test_non_json_decimal_is_rejected_before_profile_hashing() -> None:
    persistence = _Persistence()
    service = RuntimeConfigDraftService(_Definitions(), persistence)

    with pytest.raises(RuntimeConfigDraftValidationError) as exc_info:
        service.create(_request({"threshold": Decimal("0.25")}))

    assert exc_info.value.reason_code == "DRAFT_VALUE_NOT_JSON"
    assert persistence.calls == []


def test_duplicate_definition_keys_are_rejected() -> None:
    persistence = _Persistence()
    service = RuntimeConfigDraftService(_Definitions(), persistence)
    entry = RuntimeConfigDraftValueInput(
        definition_key="test.draft.typed_json",
        value_json={"setting": "candidate"},
        source="test_fixture",
    )
    request = RuntimeConfigDraftRequest(
        profile_key="test.profile.draft",
        environment="development",
        version=1,
        actor="operator@example.test",
        reason="duplicate key contract",
        values=(entry, entry),
    )

    with pytest.raises(RuntimeConfigDraftValidationError) as exc_info:
        service.create(request)

    assert exc_info.value.reason_code == "DRAFT_DUPLICATE_DEFINITION"
    assert persistence.calls == []
