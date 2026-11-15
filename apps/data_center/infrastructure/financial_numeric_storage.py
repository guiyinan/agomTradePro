"""Strict native financial wire decoding and portable JSON storage shape."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import BooleanField, Func, Model
from django.db.models.sql.compiler import SQLCompiler

from apps.data_center.domain.financial_numeric_evidence import (
    NativeFinancialMetricObservation,
)


class IsFinancialNumericJSONObject(Func):
    """Require an actual JSON object on both SQLite and PostgreSQL."""

    function = "JSON_TYPE"
    template = "(%(function)s(%(expressions)s) = 'object')"
    output_field = BooleanField()

    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        """Use the PostgreSQL jsonb type inspection without accepting JSON null."""

        sql, parameters = self.as_sql(
            compiler, connection, function="jsonb_typeof", **extra_context
        )
        return sql, list(parameters)


def decode_native_financial_numeric_evidence(
    value: object,
) -> NativeFinancialMetricObservation | None:
    """Reconstruct every numeric claim and reject altered or extended wire payloads.

    This checks internal consistency only. The caller must independently verify
    retained bytes and the approved catalog before writing or publishing v2.
    """

    if value is None:
        return None
    return NativeFinancialMetricObservation.from_payload(value)


@dataclass(frozen=True, slots=True)
class StoredFinancialNumericValue:
    """Internally consistent storage, without claiming independent qualification."""

    value: float | Decimal
    numeric_schema: Literal["legacy-decimal-v1", "native-decimal-v2"]
    evidence: NativeFinancialMetricObservation | None


def decode_financial_numeric_row(row: Model) -> StoredFinancialNumericValue:
    """Read exactly one supported storage state without rounding or null fallbacks."""

    schema: object = getattr(row, "numeric_schema", None)
    value: object = getattr(row, "value", None)
    exact: object = getattr(row, "exact_value_text", None)
    payload: object = getattr(row, "numeric_evidence", None)
    if schema == "legacy-decimal-v1":
        if (
            isinstance(value, bool)
            or not isinstance(value, (Decimal, int, float))
            or exact is not None
            or payload is not None
        ):
            raise ValueError("Legacy financial numeric storage is inconsistent")
        legacy_value = float(value)
        if not math.isfinite(legacy_value):
            raise ValueError("Legacy financial value must be finite")
        return StoredFinancialNumericValue(legacy_value, "legacy-decimal-v1", None)
    if schema != "native-decimal-v2":
        raise ValueError("Financial numeric storage schema is unsupported")
    evidence = decode_native_financial_numeric_evidence(payload)
    if (
        value is not None
        or evidence is None
        or exact != evidence.canonical_value
        or getattr(row, "metric_code", None) != evidence.contract.metric_code
        or getattr(row, "unit", None) != evidence.contract.canonical_unit
        or getattr(row, "source", None) != evidence.contract.provider
        or evidence.contract.dataset_key != "equity.financial.fact"
        or getattr(row, "source_record_id", None) != evidence.native_row_id
        or getattr(row, "raw_payload_hash", None) != evidence.body_sha256
    ):
        raise ValueError("Native financial numeric storage does not match its evidence")
    return StoredFinancialNumericValue(
        Decimal(evidence.canonical_value), "native-decimal-v2", evidence
    )


__all__ = [
    "IsFinancialNumericJSONObject",
    "StoredFinancialNumericValue",
    "decode_financial_numeric_row",
    "decode_native_financial_numeric_evidence",
]
