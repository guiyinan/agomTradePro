"""Component proof for Portfolio-owned R8 raw feedback receipts."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.portfolio.application.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackRegistryUnavailable,
)
from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackSourceReceipt,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_models import (
    PortfolioR8MonitoringFeedbackReceiptModel,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_repository import (
    PortfolioR8MonitoringFeedbackRepositoryConflict,
    PortfolioR8MonitoringFeedbackRepositoryCorruption,
)
from apps.portfolio.r8_monitoring_feedback_composition import (
    _build_django_portfolio_r8_monitoring_feedback_registration_runtime,
    build_django_portfolio_r8_monitoring_feedback_runtime,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import NOW
from tests.unit.portfolio.test_r8_monitoring_feedback_registry import (
    _Clock,
    _command,
    _definition,
    _Provider,
    _source,
)


def _runtime(*, source: object | None = None):  # type: ignore[no-untyped-def]
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    definition_provider = _Provider(_definition())
    source_provider = _Provider(_source() if source is None else source)
    clock = _Clock()
    definition_provider.unit_of_work_key = unit_of_work.unit_of_work_key
    source_provider.unit_of_work_key = unit_of_work.unit_of_work_key
    clock.unit_of_work_key = unit_of_work.unit_of_work_key
    return _build_django_portfolio_r8_monitoring_feedback_registration_runtime(
        definition_provider=definition_provider,
        source_provider=source_provider,
        clock=clock,
        unit_of_work=unit_of_work,
    )


@pytest.mark.django_db(transaction=True)
def test_feedback_registry_round_trip_winner_pit_adapter_and_guards() -> None:
    """Private registration appends once and the public adapter derives eight ratios."""

    runtime = _runtime()
    feedback = runtime.register.execute(_command())
    assert runtime.register.execute(_command()) == feedback
    assert PortfolioR8MonitoringFeedbackReceiptModel._default_manager.count() == 1
    cutoff = NOW + timedelta(days=3)
    assert (
        runtime.feedback_provider.get_exact(
            feedback_id=feedback.feedback_id,
            feedback_version=feedback.feedback_version,
            expected_feedback_hash=feedback.content_hash,
            as_of=cutoff,
        )
        == feedback
    )
    assert (
        runtime.feedback_provider.get_exact(
            feedback_id=feedback.feedback_id,
            feedback_version=feedback.feedback_version,
            expected_feedback_hash=feedback.content_hash,
            as_of=cutoff - timedelta(microseconds=1),
        )
        is None
    )
    evidence = runtime.monitoring_feedback_provider.list_exact(
        result_id=feedback.result_id,
        result_hash=feedback.result_hash,
        receipt_id=feedback.receipt_id,
        receipt_hash=feedback.receipt_hash,
        calendar_id=feedback.calendar_id,
        calendar_hash=feedback.calendar_hash,
        period_ids=(feedback.period_id,),
        as_of=cutoff,
    )
    assert len(evidence) == 1
    assert len(evidence[0].metric_payload) == 8
    with pytest.raises(PortfolioR8MonitoringFeedbackRepositoryCorruption):
        runtime.feedback_provider.get_exact(
            feedback_id=feedback.feedback_id,
            feedback_version=feedback.feedback_version,
            expected_feedback_hash="0" * 64,
            as_of=cutoff,
        )

    row = PortfolioR8MonitoringFeedbackReceiptModel._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        PortfolioR8MonitoringFeedbackReceiptModel._default_manager.update(source_owner="forbidden")
    with pytest.raises(ValidationError):
        PortfolioR8MonitoringFeedbackReceiptModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        PortfolioR8MonitoringFeedbackReceiptModel(feedback_id="forbidden").save(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_feedback_registry_missing_fork_and_outer_rollback_are_zero_write() -> None:
    """Missing sources, forks, and outer rollback never create a second winner."""

    missing = _runtime(source=False)
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable):
        missing.register.execute(_command())
    assert PortfolioR8MonitoringFeedbackReceiptModel._default_manager.count() == 0

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _runtime().register.execute(_command())
            raise RuntimeError("outer rollback")
    assert PortfolioR8MonitoringFeedbackReceiptModel._default_manager.count() == 0

    _runtime().register.execute(_command())
    source = _source()
    fork = PortfolioR8MonitoringFeedbackSourceReceipt.create(
        source_receipt_id=source.source_receipt_id,
        source_receipt_version=source.source_receipt_version,
        feedback_id=source.feedback_id,
        feedback_version=source.feedback_version,
        definition_hash=source.definition_hash,
        available_at=source.available_at,
        valid_until=source.valid_until,
        evidence_ref="portfolio:r8-monitoring-feedback-source:fork",
    )
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable) as raised:
        _runtime(source=fork).register.execute(_command())
    assert isinstance(raised.value.__cause__, PortfolioR8MonitoringFeedbackRepositoryConflict)
    assert PortfolioR8MonitoringFeedbackReceiptModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_feedback_registry_detects_tamper_and_public_registration_is_inert() -> None:
    """Header substitution fails closed and public composition cannot append."""

    feedback = _runtime().register.execute(_command())
    table = connection.ops.quote_name(PortfolioR8MonitoringFeedbackReceiptModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET calendar_id = %s WHERE feedback_hash = %s",
            ["tampered", feedback.content_hash],
        )
    public = build_django_portfolio_r8_monitoring_feedback_runtime()
    with pytest.raises(PortfolioR8MonitoringFeedbackRepositoryCorruption):
        public.feedback_provider.get_exact(
            feedback_id=feedback.feedback_id,
            feedback_version=feedback.feedback_version,
            expected_feedback_hash=feedback.content_hash,
            as_of=NOW + timedelta(days=3),
        )
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable):
        public.register.execute(_command())
    assert PortfolioR8MonitoringFeedbackReceiptModel._default_manager.count() == 1
