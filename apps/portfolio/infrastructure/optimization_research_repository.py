"""Transactional append-only repository for governed optimization research."""

from __future__ import annotations

from contextlib import AbstractContextManager

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.portfolio.application.governed_optimization import GovernedOptimizationRunBundle
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationResearchLifecycleEvent,
    derive_optimization_lifecycle_state,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)

from .optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from .optimization_research_codec import (
    lifecycle_model,
    lifecycle_to_domain,
    result_model,
    result_to_domain,
)
from .optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
    _claim_governed_optimization_insert,
)


class DjangoGovernedOptimizationResearchRepository:
    """Store one result/root atomically and extend its hash chain safely."""

    def __init__(
        self,
        *,
        unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
        receipt_provider: DjangoGovernedOptimizationInputReceiptRepository | None = None,
        using: str = "default",
    ) -> None:
        self._uow = unit_of_work or DjangoGovernedOptimizationUnitOfWork(using=using)
        if self._uow.using != using:
            raise ValueError("optimization repository database and unit of work differ")
        self._receipt_provider = receipt_provider or (
            DjangoGovernedOptimizationInputReceiptRepository(
                unit_of_work=self._uow,
                using=using,
            )
        )
        if self._receipt_provider.unit_of_work_key != self.unit_of_work_key:
            raise ValueError("result and input receipt repositories must share one unit of work")

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return self._uow.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared receipt-read/result-write transaction."""

        return self._uow.atomic()

    def append_bundle(
        self,
        bundle: GovernedOptimizationRunBundle,
    ) -> GovernedOptimizationRunBundle:
        """Append once and return only exact idempotent replays."""

        if not self._uow.is_active():
            with self.atomic():
                return self.append_bundle(bundle)
        receipt = self._receipt_provider.get_exact(
            input_set_id=bundle.result.input_set_id,
            evaluated_at=bundle.result.evaluated_at,
        )
        if receipt is None:
            raise ValueError("governed optimization input receipt is unavailable")
        if (
            receipt.input_set_hash != bundle.result.input_set_hash
            or receipt.receipt_id != bundle.result.input_receipt_id
            or receipt.content_hash != bundle.result.input_receipt_hash
            or receipt.receipt_version != bundle.result.input_receipt_schema_version
        ):
            raise ValueError("governed optimization result input receipt anchors mismatch")
        receipt_row = (
            GovernedOptimizationInputReceiptModel._default_manager.using(self._uow.using)
            .select_for_update()
            .get(receipt_id=receipt.receipt_id)
        )
        existing = (
            GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
            .select_related("input_receipt")
            .filter(
                run_key=bundle.result.run_key,
                run_version=bundle.result.run_version,
            )
            .first()
        )
        if existing is not None:
            if existing.input_receipt_id != receipt.receipt_id:
                raise ValueError("run identity is bound to a different input receipt")
            self._verify_exact_bundle(existing, bundle)
            return bundle
        try:
            with transaction.atomic(using=self._uow.using):
                winner = (
                    GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
                    .select_related("input_receipt")
                    .select_for_update()
                    .filter(
                        run_key=bundle.result.run_key,
                        run_version=bundle.result.run_version,
                    )
                    .first()
                )
                if winner is not None:
                    if winner.input_receipt_id != receipt.receipt_id:
                        raise ValueError("run identity is bound to a different input receipt")
                    self._verify_exact_bundle(winner, bundle)
                    return bundle
                result_row = result_model(bundle.result, receipt_row)
                result_row.full_clean(validate_unique=False, validate_constraints=False)
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=GovernedOptimizationResearchResultModel,
                    expected_values=_insert_values(result_row),
                ):
                    result_row.save(force_insert=True, using=self._uow.using)
                root_row = lifecycle_model(bundle.lifecycle_root, result_row)
                root_row.full_clean(validate_unique=False, validate_constraints=False)
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=OptimizationResearchLifecycleEventModel,
                    expected_values=_insert_values(root_row),
                ):
                    root_row.save(force_insert=True, using=self._uow.using)
        except IntegrityError as exc:
            winner = (
                GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
                .select_related("input_receipt")
                .filter(
                    run_key=bundle.result.run_key,
                    run_version=bundle.result.run_version,
                )
                .first()
            )
            if winner is None:
                raise ValueError("competing optimization result has no exact winner") from exc
            self._verify_exact_bundle(winner, bundle)
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid governed optimization result bundle") from exc
        return bundle

    def get_result(
        self,
        result_id: str,
    ) -> GovernedOptimizationResearchResult | None:
        """Return one integrity-checked immutable result."""

        row = (
            GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
            .select_related("input_receipt")
            .filter(result_id=result_id)
            .first()
        )
        if row is None:
            return None
        if row.input_receipt_id is None:
            raise ValueError("legacy optimization result requires explicit research-only read")
        related_receipt = row.input_receipt
        if related_receipt is None:
            raise ValueError("optimization result input receipt relation is invalid")
        with self.atomic():
            receipt = self._receipt_provider.get_exact(
                input_set_id=row.input_set_id,
                evaluated_at=row.evaluated_at,
            )
        if (
            receipt is None
            or receipt.receipt_id != row.input_receipt_id
            or receipt.content_hash != related_receipt.content_hash
            or receipt.receipt_version != related_receipt.receipt_version
            or receipt.input_set_id != row.input_set_id
            or receipt.input_set_hash != row.input_set_hash
        ):
            raise ValueError("optimization result input receipt relation is invalid")
        return result_to_domain(row)

    def get_legacy_research_result(
        self,
        result_id: str,
    ) -> GovernedOptimizationResearchResult | None:
        """Explicitly read a nullable pre-receipt result for historical research only."""

        row = (
            GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
            .select_related("input_receipt")
            .filter(result_id=result_id)
            .first()
        )
        if row is None:
            return None
        return result_to_domain(row, allow_legacy=True)

    def list_lifecycle_events(
        self,
        result_id: str,
    ) -> tuple[OptimizationResearchLifecycleEvent, ...]:
        """Return and verify the full ordered lifecycle chain."""

        rows = (
            OptimizationResearchLifecycleEventModel._default_manager.using(self._uow.using)
            .select_related("result")
            .filter(result_id=result_id)
            .order_by("sequence")
        )
        events = tuple(lifecycle_to_domain(row) for row in rows)
        result = self.get_result(result_id)
        if result is None:
            if events:
                raise ValueError("lifecycle chain refers to a missing result")
            return ()
        if events:
            derive_optimization_lifecycle_state(events)
            if events[0].result_hash != result.content_hash:
                raise ValueError("lifecycle chain result hash mismatch")
        return events

    def append_lifecycle_event(
        self,
        event: OptimizationResearchLifecycleEvent,
    ) -> OptimizationResearchLifecycleEvent:
        """Append one exact chain link with sequence-level concurrency control."""

        if not self._uow.is_active():
            with self.atomic():
                return self.append_lifecycle_event(event)
        existing = (
            OptimizationResearchLifecycleEventModel._default_manager.using(self._uow.using)
            .filter(event_id=event.event_id)
            .first()
        )
        if existing is not None:
            if lifecycle_to_domain(existing) != event:
                raise ValueError("lifecycle event identity conflicts with different evidence")
            return event
        try:
            with transaction.atomic(using=self._uow.using):
                result_row = (
                    GovernedOptimizationResearchResultModel._default_manager.using(self._uow.using)
                    .select_related("input_receipt")
                    .select_for_update()
                    .filter(result_id=event.result_id)
                    .first()
                )
                if result_row is None:
                    raise ValueError("governed optimization result is missing")
                result = result_to_domain(result_row)
                if result.content_hash != event.result_hash:
                    raise ValueError("lifecycle event result hash mismatch")
                chain = self.list_lifecycle_events(result.result_id)
                if not chain:
                    raise ValueError("lifecycle root is missing")
                if (
                    event.sequence != chain[-1].sequence + 1
                    or event.previous_event_hash != chain[-1].content_hash
                ):
                    raise ValueError("lifecycle event does not extend the current chain")
                derive_optimization_lifecycle_state((*chain, event))
                row = lifecycle_model(event, result_row)
                row.full_clean(validate_unique=False, validate_constraints=False)
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=OptimizationResearchLifecycleEventModel,
                    expected_values=_insert_values(row),
                ):
                    row.save(force_insert=True, using=self._uow.using)
        except IntegrityError as exc:
            winner = (
                OptimizationResearchLifecycleEventModel._default_manager.using(self._uow.using)
                .filter(
                    result_id=event.result_id,
                    sequence=event.sequence,
                )
                .first()
            )
            if winner is None or lifecycle_to_domain(winner) != event:
                raise ValueError("invalid optimization lifecycle event") from exc
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid optimization lifecycle event") from exc
        return event

    def _verify_exact_bundle(
        self,
        row: GovernedOptimizationResearchResultModel,
        bundle: GovernedOptimizationRunBundle,
    ) -> None:
        if row.input_receipt_id is None:
            raise ValueError("new optimization result lacks an independent input receipt")
        if result_to_domain(row) != bundle.result:
            raise ValueError("run key/version conflicts with different result evidence")
        roots = tuple(
            lifecycle_to_domain(item)
            for item in OptimizationResearchLifecycleEventModel._default_manager.using(
                self._uow.using
            ).filter(result=row, sequence=1)
        )
        if roots != (bundle.lifecycle_root,):
            raise ValueError("persisted lifecycle root differs from idempotent replay")


def _insert_values(
    model: GovernedOptimizationResearchResultModel | OptimizationResearchLifecycleEventModel,
) -> dict[str, object]:
    """Return every caller-controlled concrete field for an exact insert claim."""

    return {
        field.attname: getattr(model, field.attname)
        for field in model._meta.concrete_fields
        if field.name != "persisted_at"
    }


__all__ = ["DjangoGovernedOptimizationResearchRepository"]
