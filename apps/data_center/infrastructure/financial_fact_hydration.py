"""Restore financial fact storage without coercing native decimals to floats."""

from __future__ import annotations

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType

from .financial_decision_evidence_codec import decode_financial_decision_evidence
from .financial_fact_write_guard import source_evidence_from_model
from .financial_numeric_storage import decode_financial_numeric_row
from .models import FinancialFactModel


def financial_fact_from_model(row: FinancialFactModel) -> FinancialFact:
    """Reconstruct typed values; qualification remains a separate verifier gate."""

    numeric = decode_financial_numeric_row(row)
    return FinancialFact(
        asset_code=row.asset_code,
        period_end=row.period_end,
        period_type=FinancialPeriodType(row.period_type),
        metric_code=row.metric_code,
        value=numeric.value,
        unit=row.unit,
        source=row.source,
        report_date=row.report_date,
        available_at=row.available_at,
        fetched_at=row.fetched_at,
        extra=row.extra or {},
        source_evidence=source_evidence_from_model(row),
        decision_evidence=decode_financial_decision_evidence(row.decision_evidence),
        numeric_schema=numeric.numeric_schema,
        numeric_evidence=numeric.evidence,
    )
