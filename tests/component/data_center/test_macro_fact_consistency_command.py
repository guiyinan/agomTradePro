"""Regression tests for the deployable macro consistency guard."""

import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError

from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.data_center.management.commands import audit_macro_fact_consistency as module


@pytest.mark.django_db
def test_strict_consistency_audit_blocks_ungoverned_cross_source_difference() -> None:
    IndicatorCatalogModel.objects.create(code="CN_AUDIT_TEST", name_cn="审计测试")
    for source, value in (("akshare", "100.000000"), ("tushare", "120.000000")):
        MacroFactModel.objects.create(
            indicator_code="CN_AUDIT_TEST",
            reporting_period=date(2026, 7, 1),
            value=value,
            unit="%",
            source=source,
            extra={"source_type": source, "provider_name": source},
        )

    with pytest.raises(CommandError, match="ungoverned blocking issues"):
        call_command("audit_macro_fact_consistency", strict=True, stdout=StringIO())


@pytest.mark.django_db
def test_strict_consistency_audit_allows_explicitly_governed_source() -> None:
    IndicatorCatalogModel.objects.create(
        code="CN_AUDIT_GOVERNED",
        name_cn="已治理审计测试",
        extra={"decision_source_type": "tushare"},
    )
    for source, value in (("akshare", "100.000000"), ("tushare", "120.000000")):
        MacroFactModel.objects.create(
            indicator_code="CN_AUDIT_GOVERNED",
            reporting_period=date(2026, 7, 1),
            value=value,
            unit="%",
            source=source,
            extra={"source_type": source, "provider_name": source},
        )
    stdout = StringIO()

    call_command("audit_macro_fact_consistency", strict=True, stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["summary"]["cross_source_conflict_count"] == 1
    assert payload["summary"]["ungoverned_cross_source_conflict_count"] == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tolerance": -0.01}, "--tolerance"),
        ({"tolerance": 1.01}, "--tolerance"),
        ({"tolerance": float("nan")}, "--tolerance"),
        ({"tolerance": float("inf")}, "--tolerance"),
        ({"tolerance": True}, "--tolerance"),
        ({"max_examples": -1}, "--max-examples"),
        ({"max_examples": True}, "--max-examples"),
        ({"max_examples": 1.5}, "--max-examples"),
        ({"strict": "false"}, "--strict"),
    ],
)
def test_consistency_audit_rejects_invalid_options_before_queries(
    monkeypatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    """Invalid dynamic options cannot produce a false-clean report or touch storage."""

    command = module.Command(stdout=StringIO())
    monkeypatch.setattr(
        command,
        "_run_audit",
        lambda **_kwargs: pytest.fail("queried macro facts"),
    )
    options: dict[str, object] = {
        "strict": False,
        "tolerance": 0.01,
        "max_examples": 20,
    }
    options.update(overrides)

    with pytest.raises(CommandError, match=message):
        command.handle(**options)


@pytest.mark.django_db
def test_consistency_audit_keeps_complete_counts_with_bounded_examples() -> None:
    """Streaming audit counts every conflict while retaining bounded evidence."""

    IndicatorCatalogModel.objects.create(code="CN_AUDIT_BOUNDED", name_cn="有界审计")
    for source, value in (
        ("akshare", "100.000000"),
        ("tushare", "120.000000"),
        ("wind", "140.000000"),
    ):
        MacroFactModel.objects.create(
            indicator_code="CN_AUDIT_BOUNDED",
            reporting_period=date(2026, 7, 1),
            value=value,
            unit="%",
            source=source,
            extra={"source_type": source, "provider_name": source},
        )
    stdout = StringIO()

    call_command(
        "audit_macro_fact_consistency",
        strict=False,
        tolerance=0.01,
        max_examples=1,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["summary"]["indicator_count"] == 1
    assert payload["summary"]["fact_count"] == 3
    assert payload["summary"]["cross_source_conflict_count"] == 3
    assert payload["summary"]["ungoverned_cross_source_conflict_count"] == 3
    assert len(payload["cross_source_conflicts"]) == 1


@pytest.mark.django_db
def test_consistency_audit_fails_on_non_object_catalog_metadata() -> None:
    """Corrupt JSON metadata cannot be interpreted as an ungoverned clean state."""

    IndicatorCatalogModel.objects.create(
        code="CN_AUDIT_CORRUPT",
        name_cn="损坏审计",
        extra=["not", "an", "object"],
    )

    with pytest.raises(CommandError, match="TypeError") as exc_info:
        call_command("audit_macro_fact_consistency", stdout=StringIO())

    assert "must be an object" not in str(exc_info.value)


def test_consistency_audit_sanitizes_database_failures(monkeypatch) -> None:
    """Operational output reports only the database exception type."""

    command = module.Command(stdout=StringIO())

    def _fail(**_kwargs: object) -> module.AuditAccumulator:
        raise DatabaseError("postgres://secret-host")

    monkeypatch.setattr(command, "_run_audit", _fail)
    with pytest.raises(CommandError, match="DatabaseError") as exc_info:
        command.handle(strict=False, tolerance=0.01, max_examples=20)

    assert "secret-host" not in str(exc_info.value)
