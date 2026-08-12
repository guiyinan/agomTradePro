"""Contracts for Portfolio-owned R8 raw period feedback receipts."""

from contextlib import nullcontext
from dataclasses import fields
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackRegistryUnavailable,
    RegisterPortfolioR8MonitoringFeedback,
    RegisterPortfolioR8MonitoringFeedbackCommand,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
)
from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedback,
    PortfolioR8MonitoringFeedbackDefinition,
    PortfolioR8MonitoringFeedbackSourceReceipt,
    PortfolioR8MonitoringMemberKind,
    PortfolioR8MonitoringRawRatio,
    PortfolioR8MonitoringSourceMember,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_codec import (
    PortfolioR8MonitoringFeedbackCodecError,
    decode_portfolio_r8_monitoring_feedback_definition,
    decode_portfolio_r8_monitoring_feedback_source_receipt,
    encode_portfolio_r8_monitoring_feedback_definition,
    encode_portfolio_r8_monitoring_feedback_source_receipt,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import (
    NOW,
    _calendar,
    _receipt_and_result,
)


def _members() -> tuple[PortfolioR8MonitoringSourceMember, ...]:
    period = _calendar().periods[0]
    return tuple(
        PortfolioR8MonitoringSourceMember.create(
            member_id=f"portfolio-r8:{kind.value}:1",
            member_version=f"portfolio-r8-{kind.value}.v1",
            member_kind=kind,
            content_hash=f"{index:x}" * 64,
            observed_at=period.end_at - timedelta(hours=2),
            available_at=period.end_at + timedelta(minutes=index),
        )
        for index, kind in enumerate(PortfolioR8MonitoringMemberKind, start=1)
    )


def _facts() -> tuple[PortfolioR8MonitoringRawRatio, ...]:
    hashes = {item.member_kind: item.content_hash for item in _members()}
    specifications = (
        (MonitoringMetricKey.NET_REALIZED_RETURN, Decimal("100"), Decimal("10000")),
        (MonitoringMetricKey.MAX_DRAWDOWN, Decimal("500"), Decimal("10000")),
        (MonitoringMetricKey.TURNOVER_RATE, Decimal("2000"), Decimal("10000")),
        (MonitoringMetricKey.LIQUIDITY_UTILIZATION, Decimal("4000"), Decimal("10000")),
        (MonitoringMetricKey.CAPACITY_UTILIZATION, Decimal("5000"), Decimal("10000")),
        (MonitoringMetricKey.CONSTRAINT_BREACH_RATE, Decimal("0"), Decimal("100")),
        (MonitoringMetricKey.LABEL_DRIFT_RATE, Decimal("2"), Decimal("100")),
        (MonitoringMetricKey.DATA_DRIFT_SCORE, Decimal("3"), Decimal("100")),
    )
    member_bindings = (
        PortfolioR8MonitoringMemberKind.PERFORMANCE_PATH,
        PortfolioR8MonitoringMemberKind.PERFORMANCE_PATH,
        PortfolioR8MonitoringMemberKind.TURNOVER_LEDGER,
        PortfolioR8MonitoringMemberKind.LIQUIDITY_LEDGER,
        PortfolioR8MonitoringMemberKind.CAPACITY_LEDGER,
        PortfolioR8MonitoringMemberKind.CONSTRAINT_LEDGER,
        PortfolioR8MonitoringMemberKind.LABEL_DRIFT_LEDGER,
        PortfolioR8MonitoringMemberKind.DATA_DRIFT_LEDGER,
    )
    return tuple(
        PortfolioR8MonitoringRawRatio.create(
            metric_key=metric_key,
            numerator=numerator,
            denominator=denominator,
            source_member_hashes=(hashes[member_kind],),
        )
        for (metric_key, numerator, denominator), member_kind in zip(
            specifications, member_bindings, strict=True
        )
    )


def _feedback() -> PortfolioR8MonitoringFeedback:
    receipt, result = _receipt_and_result()
    calendar = _calendar()
    period = calendar.periods[0]
    return PortfolioR8MonitoringFeedback.create(
        result_id=result.result_id,
        result_version=result.result_version,
        result_hash=result.content_hash,
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        receipt_hash=receipt.content_hash,
        calendar_id=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        calendar_hash=calendar.content_hash,
        period_id=period.period_id,
        period_start_at=period.start_at,
        period_end_at=period.end_at,
        members=_members(),
        metric_facts=_facts(),
        valid_until=NOW + timedelta(days=20),
        evidence_ref="portfolio:r8-monitoring-feedback:period-1",
    )


def _definition() -> PortfolioR8MonitoringFeedbackDefinition:
    return PortfolioR8MonitoringFeedbackDefinition.from_feedback(_feedback())


def _source() -> PortfolioR8MonitoringFeedbackSourceReceipt:
    definition = _definition()
    feedback = definition.feedback
    return PortfolioR8MonitoringFeedbackSourceReceipt.create(
        source_receipt_id="portfolio-r8-monitoring-feedback-source:1",
        source_receipt_version="portfolio-r8-monitoring-feedback-source.v1",
        feedback_id=feedback.feedback_id,
        feedback_version=feedback.feedback_version,
        definition_hash=definition.content_hash,
        available_at=feedback.available_at,
        valid_until=feedback.valid_until,
        evidence_ref="portfolio:r8-monitoring-feedback-source:period-1",
    )


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **selectors: object) -> object:
        del selectors
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.calls = 0

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def append(self, *, definition, source, ledger_recorded_at):  # type: ignore[no-untyped-def]
        assert definition == _definition()
        assert source == _source()
        assert ledger_recorded_at == NOW + timedelta(days=3)
        self.calls += 1
        return definition.feedback


class _Clock:
    unit_of_work_key = "django:default"

    def now(self):  # type: ignore[no-untyped-def]
        return NOW + timedelta(days=3)


def _command() -> RegisterPortfolioR8MonitoringFeedbackCommand:
    feedback = _feedback()
    return RegisterPortfolioR8MonitoringFeedbackCommand(
        feedback_id=feedback.feedback_id,
        feedback_version=feedback.feedback_version,
    )


def test_feedback_command_is_identity_only_and_raw_graph_is_seven_to_eight() -> None:
    """Seven sealed source members derive eight exact Portfolio metrics."""

    assert tuple(item.name for item in fields(RegisterPortfolioR8MonitoringFeedbackCommand)) == (
        "feedback_id",
        "feedback_version",
    )
    feedback = _feedback()
    assert len(feedback.members) == 7
    assert tuple(item.metric_key for item in feedback.metric_facts) == (
        MonitoringMetricKey.NET_REALIZED_RETURN,
        MonitoringMetricKey.MAX_DRAWDOWN,
        MonitoringMetricKey.TURNOVER_RATE,
        MonitoringMetricKey.LIQUIDITY_UTILIZATION,
        MonitoringMetricKey.CAPACITY_UTILIZATION,
        MonitoringMetricKey.CONSTRAINT_BREACH_RATE,
        MonitoringMetricKey.LABEL_DRIFT_RATE,
        MonitoringMetricKey.DATA_DRIFT_SCORE,
    )
    assert tuple(item.value for item in feedback.metric_facts) == (
        Decimal("0.01"),
        Decimal("0.05"),
        Decimal("0.2"),
        Decimal("0.4"),
        Decimal("0.5"),
        Decimal("0"),
        Decimal("0.02"),
        Decimal("0.03"),
    )


def test_feedback_registration_double_reads_and_uses_trusted_clock() -> None:
    """Stable raw definition/source owners produce one exact append."""

    definition_provider = _Provider(_definition())
    source_provider = _Provider(_source())
    store = _Store()
    use_case = RegisterPortfolioR8MonitoringFeedback(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=_Clock(),
    )
    assert use_case.execute(_command()) == _feedback()
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.calls == 1


def test_missing_source_and_mutated_feedback_command_are_zero_write() -> None:
    """No source receipt or a validator bypass cannot reach persistence."""

    store = _Store()
    use_case = RegisterPortfolioR8MonitoringFeedback(
        definition_provider=_Provider(_definition()),
        source_provider=_Provider(None),
        store=store,
        clock=_Clock(),
    )
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable):
        use_case.execute(_command())
    command = _command()
    object.__setattr__(command, "feedback_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable):
        use_case.execute(command)
    assert store.calls == 0

    definition = _definition()
    object.__setattr__(definition, "content_hash", "0" * 64)
    object.__setattr__(definition, "validated_copy", lambda: definition)
    bypass = RegisterPortfolioR8MonitoringFeedback(
        definition_provider=_Provider(definition),
        source_provider=_Provider(_source()),
        store=store,
        clock=_Clock(),
    )
    with pytest.raises(PortfolioR8MonitoringFeedbackRegistryUnavailable):
        bypass.execute(_command())
    assert store.calls == 0


def test_feedback_registry_codec_is_strict_and_seal_preserving() -> None:
    """Seven-member raw payloads round-trip and reject shape or seal drift."""

    definition_payload = encode_portfolio_r8_monitoring_feedback_definition(_definition())
    source_payload = encode_portfolio_r8_monitoring_feedback_source_receipt(_source())
    assert decode_portfolio_r8_monitoring_feedback_definition(definition_payload) == _definition()
    assert decode_portfolio_r8_monitoring_feedback_source_receipt(source_payload) == _source()

    definition_payload["surplus"] = "forbidden"
    with pytest.raises(PortfolioR8MonitoringFeedbackCodecError):
        decode_portfolio_r8_monitoring_feedback_definition(definition_payload)

    source_payload["content_hash"] = "0" * 64
    with pytest.raises(PortfolioR8MonitoringFeedbackCodecError):
        decode_portfolio_r8_monitoring_feedback_source_receipt(source_payload)
