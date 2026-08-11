"""Narrow read-only Portfolio adapters for R8 monitoring owner ports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.db import transaction
from django.db.models import Q

from apps.portfolio.domain._optimization_canonical import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    ActiveGovernedOptimizationResultEvidence,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleState,
    derive_optimization_lifecycle_state,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    _receipt_from_row,
)
from apps.portfolio.infrastructure.optimization_research_codec import (
    lifecycle_to_domain,
    result_to_domain,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
)


class R8MonitoringOwnerAdapterCorruption(ValueError):
    """Portfolio owner rows cannot be restored to the exact requested graph."""


class DjangoR8MonitoringReadUnitOfWork:
    """Read-only Django transaction without an optimization insert token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one read transaction without activating write capability."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            yield


class DjangoR8MonitoringActiveResultProvider:
    """Restore one exact Portfolio result and its complete lifecycle prefix."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        promotion_event_id: str,
        expected_promotion_event_hash: str,
        as_of: datetime,
    ) -> ActiveGovernedOptimizationResultEvidence | None:
        """Return one exact active result or preserve valid inactivity as ``None``."""

        for label, value in (
            ("result_id", result_id),
            ("result_version", result_version),
            ("promotion_event_id", promotion_event_id),
        ):
            require_token(value, f"R8 monitoring active result {label}")
        require_sha256(expected_result_hash, "R8 monitoring expected_result_hash")
        require_sha256(
            expected_promotion_event_hash,
            "R8 monitoring expected_promotion_event_hash",
        )
        require_aware(as_of, "R8 monitoring active result as_of")
        rows = tuple(
            GovernedOptimizationResearchResultModel._default_manager.using(self._using)
            .select_related("input_receipt")
            .filter(Q(result_id=result_id) | Q(content_hash=expected_result_hash))
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring result identity is aliased"
            )
        row = rows[0]
        try:
            result = result_to_domain(row)
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring result cannot be restored"
            ) from error
        if (
            result.result_id != result_id
            or result.result_version != result_version
            or result.content_hash != expected_result_hash
        ):
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring result selector was substituted"
            )
        if result.evaluated_at > as_of or as_of >= result.valid_until:
            return None
        try:
            events = tuple(
                lifecycle_to_domain(model)
                for model in OptimizationResearchLifecycleEventModel._default_manager.using(
                    self._using
                )
                .filter(result_id=result_id, recorded_at__lte=as_of)
                .order_by("sequence")
            )
            if not events:
                return None
            state = derive_optimization_lifecycle_state(events)
            if state is not OptimizationLifecycleState.PROMOTION_ATTESTED:
                return None
            evidence = ActiveGovernedOptimizationResultEvidence.create(
                result=result,
                lifecycle_events=events,
            )
            ActiveGovernedOptimizationResultEvidence.__post_init__(evidence)
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring lifecycle prefix cannot be restored"
            ) from error
        if (
            evidence.promotion_event_id != promotion_event_id
            or evidence.promotion_event_hash != expected_promotion_event_hash
        ):
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring Promotion selector was substituted"
            )
        return evidence


class DjangoR8MonitoringInputReceiptProvider:
    """Restore one exact Portfolio canonical input receipt by its own identity."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_receipt_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationInputReceipt | None:
        """Return one exact live receipt or preserve absence as ``None``."""

        require_token(receipt_id, "R8 monitoring receipt_id")
        require_token(receipt_version, "R8 monitoring receipt_version")
        require_sha256(expected_receipt_hash, "R8 monitoring expected_receipt_hash")
        require_aware(as_of, "R8 monitoring receipt as_of")
        rows = tuple(
            GovernedOptimizationInputReceiptModel._default_manager.using(self._using).filter(
                Q(receipt_id=receipt_id) | Q(content_hash=expected_receipt_hash)
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring receipt identity is aliased"
            )
        try:
            receipt = _receipt_from_row(rows[0])
            if type(receipt) is not GovernedOptimizationInputReceipt:
                raise TypeError("receipt must use the exact Domain type")
            GovernedOptimizationInputReceipt.__post_init__(receipt)
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring input receipt cannot be restored"
            ) from error
        if (
            receipt.receipt_id != receipt_id
            or receipt.receipt_version != receipt_version
            or receipt.content_hash != expected_receipt_hash
        ):
            raise R8MonitoringOwnerAdapterCorruption(
                "R8 monitoring receipt selector was substituted"
            )
        if receipt.recorded_at > as_of or as_of >= receipt.valid_until:
            return None
        return receipt


__all__ = [
    "DjangoR8MonitoringActiveResultProvider",
    "DjangoR8MonitoringInputReceiptProvider",
    "DjangoR8MonitoringReadUnitOfWork",
    "R8MonitoringOwnerAdapterCorruption",
]
