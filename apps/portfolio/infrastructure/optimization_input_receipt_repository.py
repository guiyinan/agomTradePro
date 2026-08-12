"""Server-clocked append-only repository and exact PIT provider for R8 inputs."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.portfolio.domain.governed_input_set import GovernedOptimizationInputSet
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)

from .optimization_input_receipt_codec import (
    decode_input_receipt,
    encode_input_receipt,
)
from .optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    _activate_governed_optimization_uow,
    _claim_governed_optimization_insert,
    _require_active_governed_optimization_uow,
)


class GovernedOptimizationReceiptCorruption(ValueError):
    """Persisted input receipt failed strict reconstruction or redundant anchors."""


class GovernedOptimizationReceiptConflict(ValueError):
    """One immutable receipt identity is already bound to different evidence."""


class GovernedOptimizationReceiptClock(Protocol):
    """Repository-owned timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current server time."""


class DjangoGovernedOptimizationReceiptClock:
    """Use Django's configured timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current server time."""

        return timezone.now()


class DjangoGovernedOptimizationUnitOfWork:
    """One transaction and private capability shared by receipt reads and result writes."""

    def __init__(self, *, using: str = "default") -> None:
        self.using = using
        self._token = object()
        self._identity = f"django:{using}:{uuid4().hex}"

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return self._identity

    def _insert_claim_token(self) -> object:
        """Return the composition-private insert capability."""

        return self._token

    def is_active(self) -> bool:
        """Return whether this exact UoW owns the current context."""

        try:
            return _require_active_governed_optimization_uow() is self._token
        except ValidationError:
            return False

    def require_active(self) -> None:
        """Reject reads accidentally performed outside this exact transaction."""

        if not self.is_active():
            raise ValidationError(
                "Governed optimization provider requires its shared unit of work."
            )

    def atomic(self) -> AbstractContextManager[None]:
        """Open one database transaction and activate its private capability."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self.using), _activate_governed_optimization_uow(self._token):
            yield


class DjangoGovernedOptimizationInputReceiptRepository:
    """Public read-only provider for Portfolio-owned canonical input receipts."""

    def __init__(
        self,
        *,
        unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
        using: str = "default",
        clock: GovernedOptimizationReceiptClock | None = None,
    ) -> None:
        self._uow = unit_of_work or DjangoGovernedOptimizationUnitOfWork(using=using)
        if self._uow.using != using:
            raise ValueError("input receipt repository database and unit of work differ")
        self._clock = clock or DjangoGovernedOptimizationReceiptClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return self._uow.unit_of_work_key

    def _store_verified(
        self,
        input_set: GovernedOptimizationInputSet,
        server_recorded_at: datetime,
    ) -> GovernedOptimizationInputReceipt:
        """Store one graph already reconstructed by the ID-only Application use case."""

        self._uow.require_active()
        receipt = GovernedOptimizationInputReceipt.record(
            input_set=input_set,
            server_recorded_at=server_recorded_at,
        )
        receipt = decode_input_receipt(encode_input_receipt(receipt))
        try:
            with transaction.atomic(using=self._uow.using):
                winner = self._find_alias(receipt, lock=True)
                if winner is not None:
                    return self._verify_exact(winner, receipt)
                values = _receipt_values(receipt)
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=GovernedOptimizationInputReceiptModel,
                    expected_values=values,
                ):
                    GovernedOptimizationInputReceiptModel._default_manager.using(
                        self._uow.using
                    ).create(**values)
        except IntegrityError as exc:
            winner = self._find_alias(receipt, lock=True)
            if winner is None:
                raise GovernedOptimizationReceiptCorruption(
                    "competing governed optimization input receipt has no exact winner"
                ) from exc
            return self._verify_exact(winner, receipt)
        return receipt

    def get_exact(
        self,
        *,
        input_set_id: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputReceipt | None:
        """Perform an ID-only exact PIT read inside the shared run transaction."""

        self._uow.require_active()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("input receipt evaluated_at must be timezone-aware")
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise GovernedOptimizationReceiptCorruption("input receipt server clock is naive")
        if evaluated_at > now:
            raise ValueError("future input receipt PIT reads are forbidden")
        rows = list(
            GovernedOptimizationInputReceiptModel._default_manager.using(self._uow.using)
            .select_for_update()
            .filter(input_set_id=input_set_id)
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise GovernedOptimizationReceiptCorruption(
                "multiple receipts share one governed input-set identity"
            )
        receipt = _receipt_from_row(rows[0])
        if (
            receipt.input_set.created_at > evaluated_at
            or receipt.recorded_at > evaluated_at
            or receipt.valid_until <= evaluated_at
        ):
            return None
        return receipt

    def _find_alias(
        self,
        receipt: GovernedOptimizationInputReceipt,
        *,
        lock: bool,
    ) -> GovernedOptimizationInputReceiptModel | None:
        queryset = GovernedOptimizationInputReceiptModel._default_manager.using(self._uow.using)
        if lock:
            queryset = queryset.select_for_update()
        return queryset.filter(
            Q(receipt_id=receipt.receipt_id)
            | Q(input_set_id=receipt.input_set_id)
            | Q(input_set_hash=receipt.input_set_hash)
            | Q(content_hash=receipt.content_hash)
        ).first()

    def _verify_exact(
        self,
        row: GovernedOptimizationInputReceiptModel,
        receipt: GovernedOptimizationInputReceipt,
    ) -> GovernedOptimizationInputReceipt:
        persisted = _receipt_from_row(row)
        if persisted.input_set != receipt.input_set:
            raise GovernedOptimizationReceiptConflict(
                "input receipt identity conflicts with different canonical evidence"
            )
        return persisted


def _build_input_receipt_writer(
    repository: DjangoGovernedOptimizationInputReceiptRepository,
) -> Callable[[GovernedOptimizationInputSet, datetime], GovernedOptimizationInputReceipt]:
    """Return a closure without exposing a mutable repository surface at runtime."""

    def write(
        input_set: GovernedOptimizationInputSet,
        server_recorded_at: datetime,
    ) -> GovernedOptimizationInputReceipt:
        return repository._store_verified(input_set, server_recorded_at)

    return write


def _receipt_values(receipt: GovernedOptimizationInputReceipt) -> dict[str, object]:
    input_set = receipt.input_set
    return {
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "owner": receipt.owner,
        "input_set_id": input_set.input_set_id,
        "input_set_version": input_set.input_set_version,
        "contract_version": input_set.contract_version,
        "input_set_hash": input_set.content_hash,
        "portfolio_snapshot_id": input_set.portfolio_snapshot_id,
        "portfolio_snapshot_hash": input_set.portfolio_snapshot_hash,
        "universe_hash": input_set.universe.universe_hash,
        "evidence_graph_hash": receipt.evidence_graph_hash,
        "pit_manifest_set_hash": receipt.pit_manifest_set_hash,
        "created_at": input_set.created_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": input_set.valid_until,
        "payload_count": len(input_set.payloads),
        "owner_binding_count": len(input_set.owner_bindings),
        "promotion_count": len(input_set.promotions),
        "canonical_payload": encode_input_receipt(receipt),
        "content_hash": receipt.content_hash,
        "research_only": receipt.research_only,
        "must_not_use_for_decision": receipt.must_not_use_for_decision,
        "must_not_execute": receipt.must_not_execute,
    }


def _receipt_from_row(
    row: GovernedOptimizationInputReceiptModel,
) -> GovernedOptimizationInputReceipt:
    try:
        receipt = decode_input_receipt(row.canonical_payload)
    except (TypeError, ValueError) as exc:
        raise GovernedOptimizationReceiptCorruption(
            "persisted input receipt payload failed strict reconstruction"
        ) from exc
    expected = _receipt_values(receipt)
    actual = {field_name: getattr(row, field_name) for field_name in expected}
    if actual != expected:
        raise GovernedOptimizationReceiptCorruption(
            "persisted input receipt headers differ from its canonical graph"
        )
    return receipt


__all__ = [
    "DjangoGovernedOptimizationInputReceiptRepository",
    "DjangoGovernedOptimizationReceiptClock",
    "DjangoGovernedOptimizationUnitOfWork",
    "GovernedOptimizationReceiptClock",
    "GovernedOptimizationReceiptConflict",
    "GovernedOptimizationReceiptCorruption",
]
