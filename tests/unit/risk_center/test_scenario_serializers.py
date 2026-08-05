"""Boundary tests for strict scenario serializers."""

from datetime import UTC, datetime

from apps.risk_center.interface.scenario_serializers import (
    ScenarioActivationSerializer,
    ScenarioRevisionSerializer,
)


def _historical_payload() -> dict[str, object]:
    return {
        "scenario_key": "legacy-crash",
        "name": "Legacy crash",
        "category": "historical",
        "owner": "risk-team",
        "scenario_type": "historical_window",
        "parameters": {
            "start_date": "2015-06-12",
            "end_date": "2015-08-26",
            "source": "data-center:price-bars",
            "event_description": "Historical equity drawdown",
        },
        "assumptions": ("market is equity",),
        "evidence": [
            {
                "source": "data-center:price-bars",
                "publication_id": "publication-1",
                "observed_at": datetime(2015, 8, 26, tzinfo=UTC).isoformat(),
                "freshness_state": "fresh",
            }
        ],
        "invalidation_logic": "historical replay has a fixed window",
        "review_date": "2026-09-01",
        "change_reason": "migrate legacy scenario",
    }


def test_revision_serializer_rejects_unknown_top_level_and_parameter_fields() -> None:
    top_level = ScenarioRevisionSerializer(
        data={**_historical_payload(), "python_expression": "eval('bad')"}
    )
    assert top_level.is_valid() is False
    assert "python_expression" in top_level.errors

    payload = _historical_payload()
    payload["parameters"] = {
        **payload["parameters"],
        "script": "import os",
    }
    parameters = ScenarioRevisionSerializer(data=payload)
    assert parameters.is_valid() is False
    assert "script" in str(parameters.errors)


def test_revision_serializer_validates_typed_historical_window() -> None:
    serializer = ScenarioRevisionSerializer(data=_historical_payload())

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["parameters"]["start_date"].isoformat() == "2015-06-12"


def test_activation_requires_persisted_confirmation_and_optimistic_scope() -> None:
    serializer = ScenarioActivationSerializer(
        data={
            "scenario_set_revision_id": "set-revision-3",
            "proposal_id": 9,
            "preview_id": "preview-7",
            "environment": "production",
            "purpose": "portfolio_stress",
            "expected_active_version": 2,
            "expected_active_hash": "a" * 64,
            "idempotency_key": "activate-9",
            "change_reason": "approved by operator",
            "correlation_id": "correlation-9",
        }
    )

    assert serializer.is_valid(), serializer.errors
