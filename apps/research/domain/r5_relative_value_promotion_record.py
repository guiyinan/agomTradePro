"""Compatibility exports for the FixedIncome-owned R5 record seal."""

from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
    r5_relative_value_owner_record_seal_hash,
)

__all__ = [
    "R5RelativeValueOwnerRecordSeal",
    "r5_relative_value_owner_record_seal_hash",
]
