"""Migration-state coverage for R8-O0 Portfolio evidence tables."""

from __future__ import annotations

import pytest
from django.db import connection


@pytest.mark.django_db
def test_r8_o0_migration_creates_portfolio_owned_evidence_tables() -> None:
    tables = set(connection.introspection.table_names())

    assert "portfolio_canonical_snapshot" in tables
    assert "portfolio_execution_feedback" in tables


@pytest.mark.django_db
def test_r8_o0_feedback_columns_are_stable_references_not_foreign_keys() -> None:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_execution_feedback",
        )

    foreign_keys = {
        tuple(value["columns"])
        for value in constraints.values()
        if value.get("foreign_key") is not None
    }
    assert ("transition_plan_ref",) not in foreign_keys
    assert ("order_intent_ref",) not in foreign_keys
    assert ("client_order_ref",) not in foreign_keys
    assert ("reconciliation_ref",) not in foreign_keys
