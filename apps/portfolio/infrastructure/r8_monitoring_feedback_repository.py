"""Exact PIT repository for Portfolio-owned raw R8 monitoring feedback."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.fixed_income.domain.evidence import canonical_hash
from apps.portfolio.application.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackRegistryClock,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
)
from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedback,
    PortfolioR8MonitoringFeedbackDefinition,
    PortfolioR8MonitoringFeedbackSourceReceipt,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    _claim_governed_optimization_insert,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_codec import (
    PortfolioR8MonitoringFeedbackCodecError,
    decode_portfolio_r8_monitoring_feedback_definition,
    decode_portfolio_r8_monitoring_feedback_source_receipt,
    encode_portfolio_r8_monitoring_feedback_definition,
    encode_portfolio_r8_monitoring_feedback_source_receipt,
)
from apps.portfolio.infrastructure.r8_monitoring_feedback_models import (
    PortfolioR8MonitoringFeedbackReceiptModel,
)


class PortfolioR8MonitoringFeedbackRepositoryConflict(RuntimeError):
    """A stable raw feedback identity already has another winner."""


class PortfolioR8MonitoringFeedbackRepositoryCorruption(RuntimeError):
    """A persisted raw feedback header or payload was substituted."""


class DjangoPortfolioR8MonitoringFeedbackClock:
    """Trusted Django clock bound to one Portfolio UoW identity."""

    __slots__ = ("_uow_key",)

    def __init__(self, *, unit_of_work_key: str) -> None:
        self._uow_key = unit_of_work_key

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact registration UoW identity."""

        return self._uow_key

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoPortfolioR8MonitoringFeedbackRepository:
    """Public exact PIT receipt reader with no append token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity used by Phase A."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        feedback_id: str,
        feedback_version: str,
        expected_feedback_hash: str,
        as_of: datetime,
    ) -> PortfolioR8MonitoringFeedback | None:
        """Return one exact raw feedback known and active at the cutoff."""

        _query(feedback_id, feedback_version, expected_feedback_hash, as_of)
        rows = tuple(
            PortfolioR8MonitoringFeedbackReceiptModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .filter(
                Q(feedback_id=feedback_id, feedback_version=feedback_version)
                | Q(feedback_hash=expected_feedback_hash)
            )
        )
        if not rows:
            return None
        restored = tuple(_owner_graph_from_model(item)[0].feedback for item in rows)
        matches = tuple(
            item
            for item in restored
            if item.feedback_id == feedback_id
            and item.feedback_version == feedback_version
            and item.content_hash == expected_feedback_hash
            and item.available_at <= as_of < item.valid_until
        )
        if len(rows) != 1 or len(matches) != 1:
            raise PortfolioR8MonitoringFeedbackRepositoryCorruption(
                "Portfolio R8 feedback identity is aliased or substituted"
            )
        return matches[0]

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[PortfolioR8MonitoringFeedback, ...] | None:
        """Return the exact ordered complete Portfolio period set or absence."""

        for value, label in (
            (result_id, "result_id"),
            (receipt_id, "receipt_id"),
            (calendar_id, "calendar_id"),
        ):
            _token(value, f"Portfolio R8 feedback {label}")
        for value, label in (
            (result_hash, "result_hash"),
            (receipt_hash, "receipt_hash"),
            (calendar_hash, "calendar_hash"),
        ):
            _hash(value, f"Portfolio R8 feedback {label}")
        if type(period_ids) is not tuple or not period_ids:
            raise ValueError("Portfolio R8 feedback period ids must be a non-empty tuple")
        if len(set(period_ids)) != len(period_ids):
            raise ValueError("Portfolio R8 feedback period ids must be unique")
        for period_id in period_ids:
            _token(period_id, "Portfolio R8 feedback period_id")
        _aware(as_of, "Portfolio R8 feedback as_of")
        rows = tuple(
            PortfolioR8MonitoringFeedbackReceiptModel._default_manager.using(self._using).filter(
                result_id=result_id,
                calendar_id=calendar_id,
                period_id__in=period_ids,
                ledger_recorded_at__lte=as_of,
                source_valid_until__gt=as_of,
            )
        )
        if not rows:
            return None
        restored = tuple(_owner_graph_from_model(item)[0].feedback for item in rows)
        if any(
            item.result_id != result_id
            or item.result_hash != result_hash
            or item.receipt_id != receipt_id
            or item.receipt_hash != receipt_hash
            or item.calendar_id != calendar_id
            or item.calendar_hash != calendar_hash
            or not item.available_at <= as_of < item.valid_until
            for item in restored
        ):
            raise PortfolioR8MonitoringFeedbackRepositoryCorruption(
                "Portfolio R8 feedback target selector was substituted"
            )
        by_period = {item.period_id: item for item in restored}
        if len(by_period) != len(restored):
            raise PortfolioR8MonitoringFeedbackRepositoryCorruption(
                "Portfolio R8 feedback period identity is aliased"
            )
        if set(by_period) != set(period_ids):
            return None
        return tuple(by_period[period_id] for period_id in period_ids)


class _DjangoPortfolioR8MonitoringFeedbackStore(DjangoPortfolioR8MonitoringFeedbackRepository):
    """Private claimed-append capability for owner registration tests."""

    __slots__ = ("_clock", "_uow")

    def __init__(
        self,
        *,
        unit_of_work: DjangoGovernedOptimizationUnitOfWork,
        clock: PortfolioR8MonitoringFeedbackRegistryClock,
    ) -> None:
        super().__init__(using=unit_of_work.using)
        self._uow = unit_of_work
        self._clock = clock

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact private registration UoW identity."""

        return self._uow.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact UoW and activate its private insert claim."""

        return self._uow.atomic()

    def append(
        self,
        *,
        definition: PortfolioR8MonitoringFeedbackDefinition,
        source: PortfolioR8MonitoringFeedbackSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> PortfolioR8MonitoringFeedback:
        """Append or replay one exact raw feedback winner."""

        self._uow.require_active()
        if type(definition) is not PortfolioR8MonitoringFeedbackDefinition:
            raise TypeError("Portfolio R8 feedback definition type differs")
        if type(source) is not PortfolioR8MonitoringFeedbackSourceReceipt:
            raise TypeError("Portfolio R8 feedback source type differs")
        exact_definition = PortfolioR8MonitoringFeedbackDefinition.validated_copy(definition)
        exact_source = PortfolioR8MonitoringFeedbackSourceReceipt.validated_copy(source)
        _validate_append(exact_definition, exact_source, ledger_recorded_at)
        rows = self._collisions(exact_definition, exact_source)
        if rows:
            return _match_winner(rows, exact_definition, exact_source)
        values = _model_values(exact_definition, exact_source, ledger_recorded_at)
        model = PortfolioR8MonitoringFeedbackReceiptModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=PortfolioR8MonitoringFeedbackReceiptModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = self._collisions(exact_definition, exact_source)
            if not rows:
                raise PortfolioR8MonitoringFeedbackRepositoryConflict(
                    "Portfolio R8 feedback append has no exact winner"
                ) from error
            return _match_winner(rows, exact_definition, exact_source)
        return _owner_graph_from_model(model)[0].feedback

    def _collisions(
        self,
        definition: PortfolioR8MonitoringFeedbackDefinition,
        source: PortfolioR8MonitoringFeedbackSourceReceipt,
    ) -> tuple[PortfolioR8MonitoringFeedbackReceiptModel, ...]:
        feedback = definition.feedback
        return tuple(
            PortfolioR8MonitoringFeedbackReceiptModel._default_manager.using(self._using).filter(
                Q(
                    feedback_id=feedback.feedback_id,
                    feedback_version=feedback.feedback_version,
                )
                | Q(feedback_hash=feedback.content_hash)
                | Q(definition_hash=definition.content_hash)
                | Q(
                    source_receipt_id=source.source_receipt_id,
                    source_receipt_version=source.source_receipt_version,
                )
                | Q(source_receipt_hash=source.content_hash)
                | Q(
                    result_id=feedback.result_id,
                    calendar_id=feedback.calendar_id,
                    period_id=feedback.period_id,
                )
            )
        )


def _build_portfolio_r8_monitoring_feedback_store(
    *,
    unit_of_work: DjangoGovernedOptimizationUnitOfWork,
    clock: PortfolioR8MonitoringFeedbackRegistryClock,
) -> _DjangoPortfolioR8MonitoringFeedbackStore:
    """Build the private claimed store without exporting its token."""

    return _DjangoPortfolioR8MonitoringFeedbackStore(
        unit_of_work=unit_of_work,
        clock=clock,
    )


def _match_winner(
    rows: tuple[PortfolioR8MonitoringFeedbackReceiptModel, ...],
    definition: PortfolioR8MonitoringFeedbackDefinition,
    source: PortfolioR8MonitoringFeedbackSourceReceipt,
) -> PortfolioR8MonitoringFeedback:
    if len(rows) != 1:
        raise PortfolioR8MonitoringFeedbackRepositoryConflict(
            "Portfolio R8 feedback has multiple collision candidates"
        )
    restored_definition, restored_source = _owner_graph_from_model(rows[0])
    if restored_definition != definition or restored_source != source:
        raise PortfolioR8MonitoringFeedbackRepositoryConflict(
            "Portfolio R8 feedback identity forks to different evidence"
        )
    return restored_definition.feedback


def _validate_append(
    definition: PortfolioR8MonitoringFeedbackDefinition,
    source: PortfolioR8MonitoringFeedbackSourceReceipt,
    ledger_recorded_at: datetime,
) -> None:
    _aware(ledger_recorded_at, "Portfolio R8 feedback ledger_recorded_at")
    feedback = definition.feedback
    if not (
        source.feedback_id == feedback.feedback_id
        and source.feedback_version == feedback.feedback_version
        and source.definition_hash == definition.content_hash
        and feedback.available_at <= ledger_recorded_at < feedback.valid_until
        and source.available_at <= ledger_recorded_at < source.valid_until
        and source.valid_until >= feedback.valid_until
    ):
        raise PortfolioR8MonitoringFeedbackRepositoryConflict(
            "Portfolio R8 feedback owner graph or clocks differ"
        )


def _owner_graph_from_model(
    model: PortfolioR8MonitoringFeedbackReceiptModel,
) -> tuple[
    PortfolioR8MonitoringFeedbackDefinition,
    PortfolioR8MonitoringFeedbackSourceReceipt,
]:
    try:
        definition = decode_portfolio_r8_monitoring_feedback_definition(model.definition_payload)
        source = decode_portfolio_r8_monitoring_feedback_source_receipt(model.source_payload)
    except (PortfolioR8MonitoringFeedbackCodecError, TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackRepositoryCorruption(
            "Portfolio R8 feedback payload cannot be restored"
        ) from error
    values = _model_values(definition, source, model.ledger_recorded_at)
    if any(getattr(model, key) != expected for key, expected in values.items()):
        raise PortfolioR8MonitoringFeedbackRepositoryCorruption(
            "Portfolio R8 feedback headers differ from strict payloads"
        )
    return definition, source


def _model_values(
    definition: PortfolioR8MonitoringFeedbackDefinition,
    source: PortfolioR8MonitoringFeedbackSourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    feedback = definition.feedback
    facts = {item.metric_key: item for item in feedback.metric_facts}
    values: dict[str, object] = {
        "feedback_id": feedback.feedback_id,
        "feedback_version": feedback.feedback_version,
        "feedback_hash": feedback.content_hash,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_owner": source.source_owner,
        "result_id": feedback.result_id,
        "result_version": feedback.result_version,
        "result_hash": feedback.result_hash,
        "receipt_id": feedback.receipt_id,
        "receipt_version": feedback.receipt_version,
        "receipt_hash": feedback.receipt_hash,
        "calendar_id": feedback.calendar_id,
        "calendar_version": feedback.calendar_version,
        "calendar_hash": feedback.calendar_hash,
        "period_id": feedback.period_id,
        "period_start_at": feedback.period_start_at,
        "period_end_at": feedback.period_end_at,
        "source_observed_at": feedback.observed_at,
        "source_available_at": feedback.available_at,
        "source_valid_until": feedback.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "net_realized_pnl_after_flows": facts[MonitoringMetricKey.NET_REALIZED_RETURN].numerator,
        "opening_portfolio_value": facts[MonitoringMetricKey.NET_REALIZED_RETURN].denominator,
        "maximum_peak_to_trough_loss": facts[MonitoringMetricKey.MAX_DRAWDOWN].numerator,
        "peak_portfolio_value": facts[MonitoringMetricKey.MAX_DRAWDOWN].denominator,
        "absolute_traded_notional": facts[MonitoringMetricKey.TURNOVER_RATE].numerator,
        "average_portfolio_value": facts[MonitoringMetricKey.TURNOVER_RATE].denominator,
        "liquidity_consumed_notional": facts[MonitoringMetricKey.LIQUIDITY_UTILIZATION].numerator,
        "liquidity_budget_notional": facts[MonitoringMetricKey.LIQUIDITY_UTILIZATION].denominator,
        "position_exposure_notional": facts[MonitoringMetricKey.CAPACITY_UTILIZATION].numerator,
        "capacity_limit_notional": facts[MonitoringMetricKey.CAPACITY_UTILIZATION].denominator,
        "constraint_breach_count": int(facts[MonitoringMetricKey.CONSTRAINT_BREACH_RATE].numerator),
        "constraint_evaluation_count": int(
            facts[MonitoringMetricKey.CONSTRAINT_BREACH_RATE].denominator
        ),
        "changed_label_count": int(facts[MonitoringMetricKey.LABEL_DRIFT_RATE].numerator),
        "comparable_label_count": int(facts[MonitoringMetricKey.LABEL_DRIFT_RATE].denominator),
        "aggregate_drift_distance": facts[MonitoringMetricKey.DATA_DRIFT_SCORE].numerator,
        "drift_normalization_bound": facts[MonitoringMetricKey.DATA_DRIFT_SCORE].denominator,
        "member_manifest_hash": canonical_hash(
            {"schema": "portfolio-r8-monitoring-members.v1", "members": feedback.members}
        ),
        "raw_fact_manifest_hash": canonical_hash(
            {"schema": "portfolio-r8-monitoring-raw-facts.v1", "facts": feedback.metric_facts}
        ),
        "definition_payload": encode_portfolio_r8_monitoring_feedback_definition(definition),
        "source_payload": encode_portfolio_r8_monitoring_feedback_source_receipt(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash(values)
    return values


def _header_hash(values: dict[str, object]) -> str:
    return canonical_hash(
        {
            "schema": "portfolio-r8-monitoring-feedback-ledger-header.v1",
            "values": {
                key: value
                for key, value in values.items()
                if key not in {"definition_payload", "source_payload"}
            },
        }
    )


def _query(
    feedback_id: object,
    feedback_version: object,
    expected_feedback_hash: object,
    as_of: datetime,
) -> None:
    _token(feedback_id, "Portfolio R8 feedback query feedback_id")
    _token(feedback_version, "Portfolio R8 feedback query feedback_version")
    _hash(expected_feedback_hash, "Portfolio R8 feedback query hash")
    _aware(as_of, "Portfolio R8 feedback query as_of")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _hash(value: object, label: str) -> str:
    text = _token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "DjangoPortfolioR8MonitoringFeedbackRepository",
    "PortfolioR8MonitoringFeedbackRepositoryConflict",
    "PortfolioR8MonitoringFeedbackRepositoryCorruption",
]
