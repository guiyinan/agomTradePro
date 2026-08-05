"""Transactional append-only repository for governed optimization research."""

from __future__ import annotations

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

from .optimization_research_codec import (
    lifecycle_model,
    lifecycle_to_domain,
    result_model,
    result_to_domain,
)
from .optimization_research_models import (
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
)


class DjangoGovernedOptimizationResearchRepository:
    """Store one result/root atomically and extend its hash chain safely."""

    def append_bundle(
        self,
        bundle: GovernedOptimizationRunBundle,
    ) -> GovernedOptimizationRunBundle:
        """Append once and return only exact idempotent replays."""

        existing = GovernedOptimizationResearchResultModel._default_manager.filter(
            run_key=bundle.result.run_key,
            run_version=bundle.result.run_version,
        ).first()
        if existing is not None:
            self._verify_exact_bundle(existing, bundle)
            return bundle
        try:
            with transaction.atomic():
                winner = (
                    GovernedOptimizationResearchResultModel._default_manager.select_for_update()
                    .filter(
                        run_key=bundle.result.run_key,
                        run_version=bundle.result.run_version,
                    )
                    .first()
                )
                if winner is not None:
                    self._verify_exact_bundle(winner, bundle)
                    return bundle
                result_row = result_model(bundle.result)
                result_row.full_clean()
                result_row.save(force_insert=True)
                root_row = lifecycle_model(bundle.lifecycle_root, result_row)
                root_row.full_clean()
                root_row.save(force_insert=True)
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = GovernedOptimizationResearchResultModel._default_manager.filter(
                run_key=bundle.result.run_key,
                run_version=bundle.result.run_version,
            ).first()
            if winner is None:
                raise ValueError("invalid governed optimization result bundle") from exc
            self._verify_exact_bundle(winner, bundle)
        return bundle

    def get_result(
        self,
        result_id: str,
    ) -> GovernedOptimizationResearchResult | None:
        """Return one integrity-checked immutable result."""

        row = GovernedOptimizationResearchResultModel._default_manager.filter(
            result_id=result_id
        ).first()
        return None if row is None else result_to_domain(row)

    def list_lifecycle_events(
        self,
        result_id: str,
    ) -> tuple[OptimizationResearchLifecycleEvent, ...]:
        """Return and verify the full ordered lifecycle chain."""

        rows = (
            OptimizationResearchLifecycleEventModel._default_manager.select_related("result")
            .filter(result_id=result_id)
            .order_by("sequence")
        )
        events = tuple(lifecycle_to_domain(row) for row in rows)
        if events:
            derive_optimization_lifecycle_state(events)
            result = self.get_result(result_id)
            if result is None:
                raise ValueError("lifecycle chain refers to a missing result")
            if events[0].result_hash != result.content_hash:
                raise ValueError("lifecycle chain result hash mismatch")
        return events

    def append_lifecycle_event(
        self,
        event: OptimizationResearchLifecycleEvent,
    ) -> OptimizationResearchLifecycleEvent:
        """Append one exact chain link with sequence-level concurrency control."""

        existing = OptimizationResearchLifecycleEventModel._default_manager.filter(
            event_id=event.event_id
        ).first()
        if existing is not None:
            if lifecycle_to_domain(existing) != event:
                raise ValueError("lifecycle event identity conflicts with different evidence")
            return event
        try:
            with transaction.atomic():
                result_row = (
                    GovernedOptimizationResearchResultModel._default_manager.select_for_update()
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
                row.full_clean()
                row.save(force_insert=True)
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = OptimizationResearchLifecycleEventModel._default_manager.filter(
                result_id=event.result_id,
                sequence=event.sequence,
            ).first()
            if winner is None or lifecycle_to_domain(winner) != event:
                raise ValueError("invalid optimization lifecycle event") from exc
        return event

    def _verify_exact_bundle(
        self,
        row: GovernedOptimizationResearchResultModel,
        bundle: GovernedOptimizationRunBundle,
    ) -> None:
        if result_to_domain(row) != bundle.result:
            raise ValueError("run key/version conflicts with different result evidence")
        roots = tuple(
            lifecycle_to_domain(item)
            for item in OptimizationResearchLifecycleEventModel._default_manager.filter(
                result=row,
                sequence=1,
            )
        )
        if roots != (bundle.lifecycle_root,):
            raise ValueError("persisted lifecycle root differs from idempotent replay")


__all__ = ["DjangoGovernedOptimizationResearchRepository"]
