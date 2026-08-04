"""Executable local query-count/P95 evidence for Data Center Public Ports."""

from __future__ import annotations

import json

import pytest

from apps.data_center.application.reconciliation import check_query_budget
from apps.data_center.domain.reconciliation import QueryBudget
from scripts.measure_data_center_query_ports import (
    QueryPortSpec,
    _percentile_95,
    build_default_port_specs,
    build_report,
    measure_query_port,
)


def test_percentile_95_uses_inclusive_linear_interpolation() -> None:
    """P95 is deterministic and does not silently fall back to a maximum."""

    assert _percentile_95([10.0, 20.0, 30.0, 40.0]) == 38.5
    assert _percentile_95([7.25]) == 7.25
    assert _percentile_95([]) is None


def test_default_specs_cover_d0_to_d6_without_unapproved_budget_values() -> None:
    """The measurement catalog covers only the requested ownership domains."""

    specs = build_default_port_specs()
    assert [spec.domain for spec in specs] == [
        "D0",
        "D1",
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
        "D6",
    ]
    assert all(spec.call is not None for spec in specs)
    assert all(spec.arguments is not None for spec in specs)


def test_missing_public_port_is_unmeasured_not_zero_query_success() -> None:
    """An unavailable/incompatible port must not be reported as zero queries."""

    result = measure_query_port(
        QueryPortSpec(
            domain="D6",
            dataset_key="sector.membership",
            port="test.missing_public_port",
            call=None,
            arguments={},
        ),
        samples=2,
        warmup=0,
    )

    assert result.status == "unmeasured"
    assert result.query_count is None
    assert result.p95_ms is None
    assert result.error_type == "public_port_unavailable"


@pytest.mark.django_db
def test_measure_query_port_uses_real_capture_queries_context() -> None:
    """A real SQLite test database produces repeated query-count/P95 evidence."""

    from apps.data_center.application import public

    result = measure_query_port(
        QueryPortSpec(
            domain="D0",
            dataset_key="asset.master",
            port="apps.data_center.application.public.list_active_stock_codes",
            call=public.list_active_stock_codes,
            arguments={},
        ),
        samples=3,
        warmup=1,
    )

    assert result.status == "measured"
    assert len(result.samples) == 3
    assert result.query_count == max(sample.query_count for sample in result.samples)
    assert result.p95_ms is not None
    assert result.p95_ms >= 0
    assert all(sample.query_count >= 0 for sample in result.samples)

    # Reuse the canonical budget evaluator only with an observation-derived
    # threshold; this test does not register or alter governance budgets.
    evaluation = check_query_budget(
        QueryBudget(
            "test.observed.d0",
            max_queries=result.query_count,
            max_p95_ms=result.p95_ms,
        ),
        query_count=result.query_count,
        p95_ms=result.p95_ms,
    )
    assert evaluation.passed is True
    assert json.dumps(result.to_dict(), ensure_ascii=False)


@pytest.mark.django_db
def test_report_serializes_unmeasured_state_without_governance() -> None:
    """A report remains auditable even when a port has no callable adapter."""

    report = build_report(
        specs=(
            QueryPortSpec(
                domain="D0",
                dataset_key="asset.master",
                port="test.missing_public_port",
                call=None,
                arguments={},
            ),
        ),
        samples=1,
        warmup=0,
        settings_module="core.settings.development_sqlite",
    )

    assert report["budget_source"] == "caller supplied only; no governance budgets loaded"
    ports = report["ports"]
    assert isinstance(ports, list)
    assert ports[0]["status"] == "unmeasured"
    assert json.dumps(report, ensure_ascii=False)
