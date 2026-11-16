"""Reject schema warnings and preserve typed corporate-action response values."""

from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from drf_spectacular.drainage import GENERATOR_STATS, warn
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import spectacular_settings
from rest_framework.exceptions import ValidationError

from apps.simulated_trading.interface.corporate_action_workflow_serializers import (
    _StrictNullableTextField,
)


@pytest.fixture(scope="module")
def generated_schema() -> dict[str, Any]:
    """Generate every canonical endpoint with warnings enabled and no database."""
    assert spectacular_settings.DISABLE_ERRORS_AND_WARNINGS is False
    GENERATOR_STATS.reset()
    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert not GENERATOR_STATS, "OpenAPI generation emitted warnings or errors"
    return schema


def test_all_canonical_operations_generate_without_warnings(
    generated_schema: dict[str, Any],
) -> None:
    assert generated_schema["paths"]
    assert all(path.startswith("/api/") for path in generated_schema["paths"])


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("TradeSideEnum", ["buy", "sell"]),
        ("EvidenceCompletenessEnum", ["complete", "unknown"]),
        ("RiskAssessmentOutcomeEnum", ["allowed", "blocked", "partial", "unknown"]),
        ("OperationOutcomeEnum", ["success", "partial", "noop", "blocked", "failed"]),
        ("SuccessOutcomeEnum", ["success"]),
        ("PartialSuccessOutcomeEnum", ["success", "partial"]),
        ("DecisionOutcomeEnum", ["matched", "no_match"]),
        ("MetadataStatusEnum", ["metadata_selected", "blocked"]),
        ("SimulationScopeEnum", ["simulation_only"]),
        ("PublishedStatusEnum", ["published"]),
        ("CalendarReferenceReliabilityEnum", ["audited_calendar_reference"]),
        ("RiskApplicabilityEnum", ["applicable", "not_applicable", "unknown"]),
    ],
)
def test_shared_choice_sets_have_stable_component_names(
    generated_schema: dict[str, Any], name: str, values: list[str]
) -> None:
    assert generated_schema["components"]["schemas"][name]["enum"] == values


def test_distinct_choice_labels_are_preserved(generated_schema: dict[str, Any]) -> None:
    schemas = generated_schema["components"]["schemas"]
    assert schemas["TradeSideEnum"]["enum"] == schemas["TradeActionEnum"]["enum"]
    assert schemas["TradeSideEnum"]["description"] != schemas["TradeActionEnum"]["description"]


def test_strict_generation_rejects_a_warning_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "openapi.yaml"
    output.write_text("existing schema\n", encoding="utf-8")

    def warned_schema(self: SchemaGenerator, **kwargs: object) -> dict[str, object]:
        warn("Controlled schema warning for regression coverage")
        return {"openapi": "3.0.3", "paths": {}}

    monkeypatch.setattr(SchemaGenerator, "get_schema", warned_schema)
    GENERATOR_STATS.reset()
    try:
        with pytest.raises(CommandError, match="Failing as requested due to warnings"):
            call_command(
                "spectacular",
                file=str(output),
                fail_on_warn=True,
                stdout=StringIO(),
                stderr=StringIO(),
            )
    finally:
        GENERATOR_STATS.reset()
    assert output.read_text(encoding="utf-8") == "existing schema\n"


@pytest.mark.parametrize(
    ("component", "field"),
    [
        ("OwnerCorporateActionWorkflowResponse", "book_cash"),
        ("OwnerCorporateActionWorkflowResponse", "spendable_cash"),
        ("OwnerCorporateActionWorkflowResponse", "valuation_source_observed_at"),
        ("OwnerCorporateActionWorkflowAuditReceiptRow", "cash_delta"),
        ("OwnerCorporateActionWorkflowAuditReceiptRow", "share_delta"),
        ("OwnerCorporateActionReferenceReturnRow", "reference_quantity"),
        ("OwnerCorporateActionReferenceReturnRow", "source_observed_at"),
    ],
)
def test_strict_nullable_text_fields_publish_string_or_null(
    generated_schema: dict[str, Any], component: str, field: str
) -> None:
    schema = generated_schema["components"]["schemas"][component]["properties"][field]
    assert schema["type"] == "string"
    assert schema["nullable"] is True


@pytest.mark.parametrize("value", [None, "", "  1000.000000  ", "-0.01"])
def test_strict_nullable_text_preserves_exact_strings_and_null(value: str | None) -> None:
    field = _StrictNullableTextField()
    assert field.run_validation(value) == value
    assert field.to_representation(value) == value


@pytest.mark.parametrize("value", [0, 1.5, True, Decimal("0.01"), [], {}])
def test_strict_nullable_text_rejects_numeric_and_nontext_values(value: object) -> None:
    field = _StrictNullableTextField()
    with pytest.raises(ValidationError):
        field.run_validation(value)
    with pytest.raises(ValidationError):
        field.to_representation(value)
