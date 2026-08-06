"""Transactional exact repository for the R5 relative-value audit ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
    R5RelativeValueInputReceipt,
    R5RelativeValuePersistenceCorruption,
    R5RelativeValueResultRecord,
)
from apps.fixed_income.domain.evidence import require_aware, require_sha256, require_token
from apps.fixed_income.infrastructure.relative_value_codec import (
    R5RelativeValueCodecError,
    decode_r5_input_receipt,
    decode_r5_result_record,
    encode_r5_input_receipt,
    encode_r5_result_record,
)
from apps.fixed_income.infrastructure.relative_value_models import (
    FixedIncomeR5ResultModel,
)


class R5RelativeValueServerClock(Protocol):
    """Repository-owned source for immutable knowledge timestamps."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoR5RelativeValueServerClock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current server timestamp."""

        return timezone.now()


class DjangoR5RelativeValueRepository:
    """Read-only exact-query adapter for the fixed-income audit ledger.

    Persistence authority deliberately does not live on this public adapter.  The
    composition root owns a closure-bound writer so callers cannot turn an exact
    query repository into a Draft-based write surface by assigning attributes.
    """

    __slots__ = ("_using",)

    def __init__(
        self,
        *,
        using: str = "default",
    ) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact Django transaction boundary key."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        """Return one hash-bound audit record known at ``as_of``."""

        require_token(result_id, "result_id")
        require_token(result_version, "result_version")
        require_sha256(expected_record_hash, "expected_record_hash")
        require_aware(as_of, "as_of")
        with transaction.atomic(using=self._using):
            model = (
                FixedIncomeR5ResultModel._default_manager.using(self._using)
                .select_related("receipt")
                .filter(
                    result_id=result_id,
                    result_version=result_version,
                )
                .first()
            )
            if model is None:
                return None
            restored = _bundle_from_model(model)
            if (
                restored.result.record_hash != expected_record_hash
                or restored.result.recorded_at > as_of
            ):
                return None
            return restored


def _get_r5_result_by_assessment_id(
    assessment_id: str,
    *,
    using: str,
) -> FixedIncomeR5ResultModel | None:
    """Return one candidate winner for the closure-bound persistence writer."""

    return (
        FixedIncomeR5ResultModel._default_manager.using(using)
        .select_related("receipt")
        .filter(assessment_id=assessment_id)
        .first()
    )


def _bundle_from_model(
    model: FixedIncomeR5ResultModel,
) -> R5PersistedRelativeValueBundle:
    """Strictly restore and cross-check every persisted header and payload."""

    receipt_model = model.receipt
    try:
        receipt = decode_r5_input_receipt(receipt_model.canonical_payload)
        result = decode_r5_result_record(model.canonical_payload)
    except R5RelativeValueCodecError as error:
        raise R5RelativeValuePersistenceCorruption(
            "R5 relative-value persisted payload is invalid"
        ) from error
    expected_receipt_values = _receipt_model_values(receipt)
    expected_result_values = _result_model_values(result)
    if any(
        getattr(receipt_model, name) != value for name, value in expected_receipt_values.items()
    ):
        raise R5RelativeValuePersistenceCorruption("R5 input receipt header or payload mismatch")
    if model.receipt_id != receipt_model.pk or any(
        getattr(model, name) != value for name, value in expected_result_values.items()
    ):
        raise R5RelativeValuePersistenceCorruption("R5 result header, payload, or FK mismatch")
    try:
        return R5PersistedRelativeValueBundle(receipt=receipt, result=result)
    except ValueError as error:
        raise R5RelativeValuePersistenceCorruption(
            "R5 persisted receipt/result graph mismatch"
        ) from error


def _receipt_model_values(
    receipt: R5RelativeValueInputReceipt,
) -> dict[str, object]:
    return {
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "owner": receipt.owner,
        "command_hash": receipt.command_hash,
        "assessment_id": receipt.assessment_id,
        "input_set_id": receipt.input_set.input_set_id,
        "input_set_version": receipt.input_set.input_set_version,
        "input_set_hash": receipt.input_set.input_set_hash,
        "policy_set_id": receipt.policy_set.policy_set_id,
        "policy_set_version": receipt.policy_set.policy_set_version,
        "policy_set_hash": receipt.policy_set.policy_set_hash,
        "evaluated_at": receipt.evaluated_at,
        "recorded_at": receipt.recorded_at,
        "evidence_clock_graph_hash": receipt.evidence_clock_graph_hash,
        "canonical_payload": encode_r5_input_receipt(receipt),
        "content_hash": receipt.receipt_hash,
        "research_only": receipt.research_only,
        "must_not_execute": receipt.must_not_execute,
        "must_not_use_for_decision": receipt.must_not_use_for_decision,
    }


def _result_model_values(
    result: R5RelativeValueResultRecord,
) -> dict[str, object]:
    assessment = result.assessment
    if assessment.input_set_hash is None or assessment.policy_set_hash is None:
        raise R5RelativeValuePersistenceCorruption(
            "persisted R5 result requires complete input and policy hashes"
        )
    return {
        "result_id": result.result_id,
        "result_version": result.result_version,
        "owner": result.owner,
        "command_hash": result.command_hash,
        "assessment_id": assessment.assessment_id,
        "input_set_hash": assessment.input_set_hash,
        "policy_set_hash": assessment.policy_set_hash,
        "input_hash": assessment.input_hash,
        "output_hash": assessment.output_hash,
        "status": assessment.status.value,
        "evaluated_at": assessment.evaluated_at,
        "recorded_at": result.recorded_at,
        "evidence_clock_graph_hash": result.evidence_clock_graph_hash,
        "canonical_payload": encode_r5_result_record(result),
        "content_hash": result.record_hash,
        "research_only": result.research_only,
        "must_not_execute": result.must_not_execute,
        "must_not_use_for_decision": result.must_not_use_for_decision,
    }


__all__ = [
    "DjangoR5RelativeValueRepository",
    "DjangoR5RelativeValueServerClock",
    "R5RelativeValueServerClock",
]
