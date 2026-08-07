"""Exact read-only repository for Portfolio-owned R5 outcome evidence."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.fixed_income.domain.evidence import require_aware, require_sha256, require_token
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.portfolio.application.r5_relative_value_outcome import (
    ExactR5RelativeValueOwnerRecordQuery,
    R5PortfolioOutcomePersistenceConflict,
    R5PortfolioOutcomePersistenceCorruption,
    R5PortfolioOutcomePersistenceDraft,
    R5PortfolioOutcomeSource,
    R5PortfolioOutcomeSourceRecord,
    r5_portfolio_outcome_command_hash,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from apps.portfolio.infrastructure.r5_relative_value_outcome_codec import (
    R5PortfolioOutcomeCodecError,
    decode_r5_portfolio_outcome,
    encode_r5_portfolio_outcome,
)
from apps.portfolio.infrastructure.r5_relative_value_outcome_models import (
    PortfolioR5RelativeValueOutcomeModel,
)


class DjangoR5PortfolioOutcomeServerClock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current server timestamp."""

        return timezone.now()


class DjangoR5PortfolioOutcomeRepository:
    """Public read-only, exact, dynamically owner-verified adapter."""

    __slots__ = ("_fixed_income_query", "_source_provider", "_using")

    def __init__(
        self,
        *,
        source_provider: R5PortfolioOutcomeSource,
        fixed_income_query: ExactR5RelativeValueOwnerRecordQuery,
        using: str = "default",
    ) -> None:
        self._source_provider = source_provider
        self._fixed_income_query = fixed_income_query
        self._using = using
        keys = {
            self.unit_of_work_key,
            source_provider.unit_of_work_key,
            fixed_income_query.unit_of_work_key,
        }
        if len(keys) != 1:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 outcome owners must share one transaction boundary"
            )

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction boundary key."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        outcome_id: str,
        outcome_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        """Return one hash-bound outcome after strict owner replay."""

        require_token(outcome_id, "outcome_id", maximum=300)
        require_token(outcome_version, "outcome_version", maximum=300)
        require_sha256(expected_content_hash, "expected_content_hash")
        require_aware(as_of, "as_of")
        with transaction.atomic(using=self._using):
            model = (
                PortfolioR5RelativeValueOutcomeModel._default_manager.using(self._using)
                .filter(
                    outcome_id=outcome_id,
                    outcome_version=outcome_version,
                )
                .first()
            )
            if model is None:
                return None
            outcome = _outcome_from_model(model)
            if outcome.content_hash != expected_content_hash or not outcome.is_active_at(as_of):
                return None
            return _verify_owner_graph(
                model=model,
                outcome=outcome,
                source_provider=self._source_provider,
                fixed_income_query=self._fixed_income_query,
                as_of=as_of,
            )


def _get_r5_outcome_by_owner_identity(
    *,
    owner_record_id: str,
    owner_record_version: str,
    using: str,
) -> PortfolioR5RelativeValueOutcomeModel | None:
    """Return the candidate winner for the closure-bound writer."""

    return (
        PortfolioR5RelativeValueOutcomeModel._default_manager.using(using)
        .filter(
            owner_record_id=owner_record_id,
            owner_record_version=owner_record_version,
        )
        .first()
    )


def _canonical_source(
    source: R5PortfolioOutcomeSourceRecord,
) -> R5PortfolioOutcomeSourceRecord:
    """Reject nominal or mutated source-provider substitutions."""

    try:
        canonical = R5PortfolioOutcomeSourceRecord(**source.constructor_values)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 Portfolio source projection is invalid"
        ) from error
    if canonical != source:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 Portfolio source projection is noncanonical"
        )
    return canonical


def _canonical_fixed_income(
    record: R5RelativeValueOwnerRecordSeal,
) -> R5RelativeValueOwnerRecordSeal:
    """Rebuild the FixedIncome seal instead of trusting its nominal type."""

    try:
        canonical = R5RelativeValueOwnerRecordSeal.create(
            result_id=record.result_id,
            result_version=record.result_version,
            result_record_hash=record.result_record_hash,
            receipt_id=record.receipt_id,
            receipt_version=record.receipt_version,
            receipt_hash=record.receipt_hash,
            command_hash=record.command_hash,
            evidence_clock_graph_hash=record.evidence_clock_graph_hash,
            recorded_at=record.recorded_at,
            assessment=record.assessment,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 FixedIncome owner projection is invalid"
        ) from error
    if canonical != record:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 FixedIncome owner projection is noncanonical"
        )
    return canonical


def _verify_owner_graph(
    *,
    model: PortfolioR5RelativeValueOutcomeModel,
    outcome: R5PortfolioOutcomeSeal,
    source_provider: R5PortfolioOutcomeSource,
    fixed_income_query: ExactR5RelativeValueOwnerRecordQuery,
    as_of: datetime,
) -> R5PortfolioOutcomeSeal | None:
    """Dynamically reread Portfolio and FixedIncome owner evidence."""

    try:
        source_value = source_provider.get_exact(
            owner_record_id=outcome.owner_record_id,
            owner_record_version=outcome.owner_record_version,
            as_of=as_of,
        )
        if source_value is None:
            return None
        source = _canonical_source(source_value)
        if not source.outcome_available_at <= as_of < source.valid_until:
            return None
        fixed_income_value = fixed_income_query.execute(
            GetExactR5RelativeValueOwnerRecordCommand(
                result_id=outcome.fixed_income_result_id,
                result_version=outcome.fixed_income_result_version,
                expected_record_hash=outcome.fixed_income_result_record_hash,
                as_of=as_of,
            )
        )
        if fixed_income_value is None:
            return None
        fixed_income = _canonical_fixed_income(fixed_income_value)
        draft = R5PortfolioOutcomePersistenceDraft(
            source_record=source,
            fixed_income_record=fixed_income,
        )
        expected = draft.to_outcome(recorded_at=outcome.recorded_at)
    except R5PortfolioOutcomePersistenceCorruption:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 outcome owner graph cannot be replayed"
        ) from error
    if (
        source.owner_record_hash != outcome.owner_record_hash
        or fixed_income.content_hash != outcome.fixed_income_owner_seal_hash
        or draft.draft_hash != model.draft_hash
        or expected != outcome
    ):
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 outcome differs from its current exact owner graph"
        )
    return outcome


def _outcome_from_model(
    model: PortfolioR5RelativeValueOutcomeModel,
) -> R5PortfolioOutcomeSeal:
    """Strictly restore and cross-check every persisted header and payload."""

    try:
        outcome = decode_r5_portfolio_outcome(model.canonical_payload)
        require_sha256(model.command_hash, "persisted command_hash")
        require_sha256(model.draft_hash, "persisted draft_hash")
    except (R5PortfolioOutcomeCodecError, TypeError, ValueError) as error:
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 outcome persisted payload is invalid"
        ) from error
    if model.command_hash != r5_portfolio_outcome_command_hash(
        owner_record_id=outcome.owner_record_id,
        owner_record_version=outcome.owner_record_version,
    ):
        raise R5PortfolioOutcomePersistenceCorruption("R5 outcome command header is invalid")
    expected_values = _outcome_model_values(
        outcome,
        command_hash=model.command_hash,
        draft_hash=model.draft_hash,
    )
    if any(getattr(model, name) != value for name, value in expected_values.items()):
        raise R5PortfolioOutcomePersistenceCorruption(
            "R5 outcome header or canonical payload mismatch"
        )
    return outcome


def _outcome_model_values(
    outcome: R5PortfolioOutcomeSeal,
    *,
    command_hash: str,
    draft_hash: str,
) -> dict[str, object]:
    """Return the complete semantic ORM projection for one outcome."""

    return {
        "outcome_id": outcome.outcome_id,
        "outcome_version": outcome.outcome_version,
        "owner": outcome.owner,
        "owner_record_id": outcome.owner_record_id,
        "owner_record_version": outcome.owner_record_version,
        "owner_record_hash": outcome.owner_record_hash,
        "observation_id": outcome.observation_id,
        "fixed_income_result_id": outcome.fixed_income_result_id,
        "fixed_income_result_version": outcome.fixed_income_result_version,
        "fixed_income_result_record_hash": outcome.fixed_income_result_record_hash,
        "fixed_income_owner_seal_hash": outcome.fixed_income_owner_seal_hash,
        "selection_as_of": outcome.selection_as_of,
        "outcome_observed_at": outcome.outcome_observed_at,
        "outcome_available_at": outcome.outcome_available_at,
        "recorded_at": outcome.recorded_at,
        "valid_until": outcome.valid_until,
        "target_gross_return": outcome.target_gross_return,
        "target_cost": outcome.target_cost,
        "benchmark_gross_return": outcome.benchmark_gross_return,
        "benchmark_cost": outcome.benchmark_cost,
        "target_maximum_drawdown": outcome.target_maximum_drawdown,
        "benchmark_maximum_drawdown": outcome.benchmark_maximum_drawdown,
        "capacity_utilization": outcome.capacity_utilization,
        "liquidity_breached": outcome.liquidity_breached,
        "realized_credit_loss": outcome.realized_credit_loss,
        "command_hash": command_hash,
        "draft_hash": draft_hash,
        "canonical_payload": encode_r5_portfolio_outcome(outcome),
        "content_hash": outcome.content_hash,
        "research_only": outcome.research_only,
        "must_not_use_for_decision": outcome.must_not_use_for_decision,
        "must_not_execute": outcome.must_not_execute,
    }


__all__ = [
    "DjangoR5PortfolioOutcomeRepository",
    "DjangoR5PortfolioOutcomeServerClock",
]
