"""Concrete composition for Portfolio-owned R5 outcome persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.portfolio.application.r5_relative_value_outcome import (
    ExactR5RelativeValueOwnerRecordQuery,
    GetExactPersistedR5PortfolioOutcome,
    PersistR5PortfolioOutcome,
    PersistR5PortfolioOutcomeCommand,
    R5PortfolioOutcomePersistenceConflict,
    R5PortfolioOutcomePersistenceDraft,
    R5PortfolioOutcomeSource,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from apps.portfolio.infrastructure.r5_relative_value_outcome_models import (
    PortfolioR5RelativeValueOutcomeModel,
    _activate_r5_outcome_unit_of_work,
    _claim_r5_outcome_insert,
)
from apps.portfolio.infrastructure.r5_relative_value_outcome_repository import (
    DjangoR5PortfolioOutcomeRepository,
    DjangoR5PortfolioOutcomeServerClock,
    _canonical_fixed_income,
    _canonical_source,
    _get_r5_outcome_by_owner_identity,
    _outcome_from_model,
    _outcome_model_values,
)


class R5PortfolioOutcomeServerClock(Protocol):
    """Composition-owned source for the immutable knowledge timestamp."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


@dataclass(frozen=True)
class DjangoR5PortfolioOutcomeRuntime:
    """Closure-bound ID-only writer and public exact-query surface."""

    persist: PersistR5PortfolioOutcome
    query: GetExactPersistedR5PortfolioOutcome


def build_django_r5_portfolio_outcome_runtime(
    *,
    source_provider: R5PortfolioOutcomeSource,
    fixed_income_query: ExactR5RelativeValueOwnerRecordQuery,
    clock: R5PortfolioOutcomeServerClock | None = None,
    using: str = "default",
) -> DjangoR5PortfolioOutcomeRuntime:
    """Wire both owners and the ledger to one shared Django transaction."""

    repository = DjangoR5PortfolioOutcomeRepository(
        source_provider=source_provider,
        fixed_income_query=fixed_income_query,
        using=using,
    )
    unit_of_work_token = object()
    server_clock = clock or DjangoR5PortfolioOutcomeServerClock()

    def match_draft(
        model: PortfolioR5RelativeValueOutcomeModel,
        draft: R5PortfolioOutcomePersistenceDraft,
    ) -> R5PortfolioOutcomeSeal:
        persisted = _outcome_from_model(model)
        try:
            expected = draft.to_outcome(recorded_at=persisted.recorded_at)
        except ValueError as error:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 outcome winner cannot be replayed from the exact owner graph"
            ) from error
        if model.draft_hash != draft.draft_hash or expected != persisted:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 outcome owner identity conflicts with different evidence"
            )
        return persisted

    def append_verified(
        draft: R5PortfolioOutcomePersistenceDraft,
        *,
        command_hash: str,
        recorded_at: datetime,
    ) -> R5PortfolioOutcomeSeal:
        if command_hash != draft.expected_command_hash:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 outcome command differs from the verified owner graph"
            )
        existing = _get_r5_outcome_by_owner_identity(
            owner_record_id=draft.source_record.owner_record_id,
            owner_record_version=draft.source_record.owner_record_version,
            using=using,
        )
        if existing is not None:
            return match_draft(existing, draft)
        try:
            candidate = draft.to_outcome(recorded_at=recorded_at)
        except ValueError as error:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 outcome repository server clock is invalid"
            ) from error
        values = _outcome_model_values(
            candidate,
            command_hash=command_hash,
            draft_hash=draft.draft_hash,
        )
        try:
            with transaction.atomic(using=using):
                with _claim_r5_outcome_insert(
                    token=unit_of_work_token,
                    command_hash=command_hash,
                    draft_hash=draft.draft_hash,
                    expected_values=values,
                ):
                    model = PortfolioR5RelativeValueOutcomeModel(**values)
                    model.full_clean()
                    model.save(force_insert=True, using=using)
        except (IntegrityError, ValidationError, ValueError) as error:
            winner = _get_r5_outcome_by_owner_identity(
                owner_record_id=draft.source_record.owner_record_id,
                owner_record_version=draft.source_record.owner_record_version,
                using=using,
            )
            if winner is None:
                raise R5PortfolioOutcomePersistenceConflict(
                    "R5 Portfolio outcome append conflict"
                ) from error
            return match_draft(winner, draft)
        restored = _outcome_from_model(model)
        if restored != candidate:
            raise R5PortfolioOutcomePersistenceConflict(
                "R5 Portfolio outcome append did not round-trip exactly"
            )
        return restored

    class ClosureBoundPersistenceWriter:
        """ID-only writer whose capability stays inside enclosing locals."""

        __slots__ = ()

        def persist(
            self,
            command: PersistR5PortfolioOutcomeCommand,
        ) -> R5PortfolioOutcomeSeal:
            """Reread both owners and append inside one shared transaction."""

            try:
                with transaction.atomic(using=using):
                    with _activate_r5_outcome_unit_of_work(unit_of_work_token):
                        recorded_at = server_clock.now()
                        source_value = source_provider.get_exact(
                            owner_record_id=command.owner_record_id,
                            owner_record_version=command.owner_record_version,
                            as_of=recorded_at,
                        )
                        if source_value is None:
                            raise R5PortfolioOutcomePersistenceConflict(
                                "R5 Portfolio outcome source is unavailable"
                            )
                        source = _canonical_source(source_value)
                        if (
                            source.owner_record_id != command.owner_record_id
                            or source.owner_record_version != command.owner_record_version
                            or not source.outcome_available_at <= recorded_at < source.valid_until
                        ):
                            raise R5PortfolioOutcomePersistenceConflict(
                                "R5 Portfolio outcome source identity or clock is invalid"
                            )
                        fixed_income_value = fixed_income_query.execute(
                            GetExactR5RelativeValueOwnerRecordCommand(
                                result_id=source.fixed_income_result_id,
                                result_version=source.fixed_income_result_version,
                                expected_record_hash=source.fixed_income_result_record_hash,
                                as_of=recorded_at,
                            )
                        )
                        if fixed_income_value is None:
                            raise R5PortfolioOutcomePersistenceConflict(
                                "R5 FixedIncome owner result is unavailable"
                            )
                        fixed_income = _canonical_fixed_income(fixed_income_value)
                        draft = R5PortfolioOutcomePersistenceDraft(
                            source_record=source,
                            fixed_income_record=fixed_income,
                        )
                        if command.command_hash != draft.expected_command_hash:
                            raise R5PortfolioOutcomePersistenceConflict(
                                "R5 outcome command does not authorize this owner graph"
                            )
                        return append_verified(
                            draft,
                            command_hash=command.command_hash,
                            recorded_at=recorded_at,
                        )
            except R5PortfolioOutcomePersistenceConflict:
                raise
            except (AttributeError, TypeError, ValueError) as error:
                raise R5PortfolioOutcomePersistenceConflict(
                    "R5 outcome owner reread failed closed"
                ) from error

    return DjangoR5PortfolioOutcomeRuntime(
        persist=PersistR5PortfolioOutcome(writer=ClosureBoundPersistenceWriter()),
        query=GetExactPersistedR5PortfolioOutcome(repository),
    )


__all__ = [
    "DjangoR5PortfolioOutcomeRuntime",
    "R5PortfolioOutcomeServerClock",
    "build_django_r5_portfolio_outcome_runtime",
]
