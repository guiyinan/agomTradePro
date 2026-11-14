"""Public correction selection must be explicit and type-exact."""

import pytest

from apps.simulated_trading.interface.corporate_action_workflow_serializers import (
    OwnerCorporateActionWorkflowPrepareRequestSerializer,
)


@pytest.mark.parametrize(
    "mode", [True, False, 1, 0, None, [], {}, "", "correct", "CORRECT_EXISTING"]
)
def test_invalid_correction_mode_is_rejected(mode: object) -> None:
    serializer = OwnerCorporateActionWorkflowPrepareRequestSerializer(
        data={"event_id": "event-1", "action": "cash_payment", "correction_mode": mode}
    )
    assert not serializer.is_valid()
    assert "correction_mode" in serializer.errors


def test_omitted_mode_never_selects_a_correction() -> None:
    serializer = OwnerCorporateActionWorkflowPrepareRequestSerializer(
        data={"event_id": "event-1", "action": "cash_payment"}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["correction_mode"] == "ordinary"


def test_only_explicit_mode_selects_full_correction() -> None:
    serializer = OwnerCorporateActionWorkflowPrepareRequestSerializer(
        data={
            "event_id": "event-1",
            "action": "cash_payment",
            "correction_mode": "correct_existing",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["correction_mode"] == "correct_existing"
