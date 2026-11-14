"""Lossless original tax-window material for financial and Audit readback."""

from __future__ import annotations

from decimal import InvalidOperation
from typing import cast

from apps.audit.domain.system_audit_event import JSONValue
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.infrastructure.corporate_action_constructor_codec import (
    encode_corporate_action_constructor,
    restore_corporate_action_constructor,
)
from core.exceptions import BusinessLogicError


def encode_corporate_action_tax_window_proof(
    proof: CorporateActionTaxWindowProof,
) -> dict[str, JSONValue]:
    """Retain every original field without issuing permission or resetting any clock."""
    proof.__post_init__()
    payload = encode_corporate_action_constructor(proof)
    if type(payload) is not dict:
        raise ValueError("tax window proof constructor must encode as an object")
    return payload


def decode_corporate_action_tax_window_proof(value: object) -> CorporateActionTaxWindowProof:
    """Restore the exact trusted constructor and reject unknown or weakly typed fields."""
    try:
        if type(value) is not dict:
            raise ValueError("tax window proof must be an object")
        restored = restore_corporate_action_constructor(
            cast(dict[str, JSONValue], value), CorporateActionTaxWindowProof
        )
        if type(restored) is not CorporateActionTaxWindowProof:
            raise ValueError("tax window proof constructor differs")
        restored.__post_init__()
        if encode_corporate_action_tax_window_proof(restored) != value:
            raise ValueError("tax window proof is not canonical constructor material")
        return restored
    except (TypeError, ValueError, OverflowError, InvalidOperation) as error:
        raise BusinessLogicError(
            "税务操作的原始官方窗口无法核对。", code="TAX_CURRENT_OFFICIAL_WINDOW_INVALID"
        ) from error
