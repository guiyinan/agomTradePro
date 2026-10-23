"""Typed value objects for one-request simulated portfolio targets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Protocol, TypedDict

_CANONICAL_SECURITY_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_PERCENT_TEXT = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,6})?$")
_MAX_TARGETS = 50
_MAX_WEIGHT_FRACTIONAL_DIGITS = 8


class TemporaryTargetAuditRecord(TypedDict):
    """Persisted explanation of the temporary target source and cash remainder."""

    scope: str
    rebalance_action: str
    source: str
    target_weights: dict[str, str]
    residual_cash_weight: str


class CanonicalSecurityCodeNormalizer(Protocol):
    """Normalize an already-canonical security code at the application boundary."""

    def __call__(self, raw_code: str) -> str: ...


class TemporaryTargetValidationError(ValueError):
    """Identify invalid temporary target input with a stable non-sensitive reason."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Store a stable reason code alongside the user-facing validation message."""

        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class TemporarySecurityTargetWeight:
    """One canonical security target expressed as an exact portfolio fraction."""

    asset_code: str
    weight: Decimal

    def __post_init__(self) -> None:
        """Reject noncanonical identities and nonfinite or out-of-range fractions."""

        if type(self.asset_code) is not str or not _CANONICAL_SECURITY_CODE.fullmatch(
            self.asset_code
        ):
            raise TemporaryTargetValidationError(
                "TARGET_SECURITY_CODE_INVALID", "请使用六位证券代码和交易所后缀，例如 600000.SH。"
            )
        if type(self.weight) is not Decimal or not self.weight.is_finite():
            raise TemporaryTargetValidationError(
                "TARGET_WEIGHT_INVALID", "目标比例必须是有限的十进制数。"
            )
        if self.weight.is_signed() or not Decimal("0") <= self.weight <= Decimal("1"):
            raise TemporaryTargetValidationError(
                "TARGET_WEIGHT_INVALID", "证券目标比例必须在 0% 至 100% 之间。"
            )
        weight_exponent = self.weight.as_tuple().exponent
        if type(weight_exponent) is not int or -weight_exponent > _MAX_WEIGHT_FRACTIONAL_DIGITS:
            raise TemporaryTargetValidationError(
                "TARGET_WEIGHT_PRECISION_EXCEEDED", "目标比例最多填写六位小数百分比。"
            )


@dataclass(frozen=True, slots=True)
class TemporarySecurityTargets:
    """A bounded temporary target set with an exact residual cash allocation."""

    items: tuple[TemporarySecurityTargetWeight, ...]
    residual_cash_weight: Decimal

    def __post_init__(self) -> None:
        """Enforce the target-set invariants even for direct typed construction."""

        if type(self.items) is not tuple or not self.items or len(self.items) > _MAX_TARGETS:
            raise TemporaryTargetValidationError(
                "TARGET_ENTRY_COUNT_INVALID", "请填写 1 至 50 行证券目标。"
            )
        seen_codes: set[str] = set()
        with localcontext() as context:
            context.prec = 32
            total_weight = Decimal("0")
            for item in self.items:
                if type(item) is not TemporarySecurityTargetWeight:
                    raise TemporaryTargetValidationError(
                        "TARGET_WEIGHT_INVALID", "目标比例资料无法确认。"
                    )
                if item.asset_code in seen_codes:
                    raise TemporaryTargetValidationError(
                        "TARGET_DUPLICATE_NORMALIZED_ASSET", "同一证券只能填写一行目标比例。"
                    )
                seen_codes.add(item.asset_code)
                total_weight += item.weight
            if total_weight > Decimal("1"):
                raise TemporaryTargetValidationError(
                    "TARGET_WEIGHT_SUM_EXCEEDS_ONE", "证券目标比例合计不能超过 100%。"
                )
            expected_residual = Decimal("1") - total_weight
        if (
            type(self.residual_cash_weight) is not Decimal
            or not self.residual_cash_weight.is_finite()
            or self.residual_cash_weight.is_signed()
            or self.residual_cash_weight != expected_residual
        ):
            raise TemporaryTargetValidationError(
                "TARGET_CASH_REMAINDER_INVALID", "未分配目标现金比例无法确认。"
            )

    @classmethod
    def parse_percent_lines(
        cls,
        raw_text: str,
        *,
        normalize_code: CanonicalSecurityCodeNormalizer,
    ) -> TemporarySecurityTargets:
        """Parse ``CODE,PERCENT`` rows without a binary-float conversion."""

        if type(raw_text) is not str:
            raise TemporaryTargetValidationError(
                "TARGET_TEXT_INVALID", "请按每行一只证券的格式填写目标比例。"
            )
        rows = [line for line in raw_text.splitlines() if line.strip()]
        if not rows or len(rows) > _MAX_TARGETS:
            raise TemporaryTargetValidationError(
                "TARGET_ENTRY_COUNT_INVALID", "请填写 1 至 50 行证券目标。"
            )

        parsed: list[TemporarySecurityTargetWeight] = []
        seen_codes: set[str] = set()
        for row in rows:
            if row.count(",") != 1:
                raise TemporaryTargetValidationError(
                    "TARGET_ROW_FORMAT_INVALID", "每行请按“证券代码,目标比例(%)”填写。"
                )
            raw_code, raw_percent = row.split(",", maxsplit=1)
            if not raw_code.strip():
                raise TemporaryTargetValidationError(
                    "TARGET_SECURITY_CODE_INVALID", "证券代码不能为空。"
                )
            try:
                asset_code = normalize_code(raw_code.strip())
            except TemporaryTargetValidationError:
                raise
            except (TypeError, ValueError) as error:
                raise TemporaryTargetValidationError(
                    "TARGET_SECURITY_CODE_INVALID",
                    "请使用六位证券代码和交易所后缀，例如 600000.SH。",
                ) from error
            if (
                type(asset_code) is not str
                or asset_code != asset_code.strip().upper()
                or not _CANONICAL_SECURITY_CODE.fullmatch(asset_code)
            ):
                raise TemporaryTargetValidationError(
                    "TARGET_SECURITY_CODE_INVALID",
                    "请使用六位证券代码和交易所后缀，例如 600000.SH。",
                )
            if asset_code in seen_codes:
                raise TemporaryTargetValidationError(
                    "TARGET_DUPLICATE_NORMALIZED_ASSET", "同一证券只能填写一行目标比例。"
                )
            seen_codes.add(asset_code)

            percent_text = raw_percent.strip()
            if not percent_text.isascii() or not _PERCENT_TEXT.fullmatch(percent_text):
                raise TemporaryTargetValidationError(
                    "TARGET_WEIGHT_INVALID",
                    "目标比例请填写 0 至 100 的十进制百分数，最多六位小数。",
                )
            try:
                percent = Decimal(percent_text)
            except (InvalidOperation, TypeError, ValueError) as error:
                raise TemporaryTargetValidationError(
                    "TARGET_WEIGHT_INVALID", "目标比例格式无效。"
                ) from error
            if not percent.is_finite() or not Decimal("0") <= percent <= Decimal("100"):
                raise TemporaryTargetValidationError(
                    "TARGET_WEIGHT_INVALID", "证券目标比例必须在 0% 至 100% 之间。"
                )
            with localcontext() as context:
                context.prec = 32
                weight = percent / Decimal("100")
            parsed.append(TemporarySecurityTargetWeight(asset_code, weight))

        with localcontext() as context:
            context.prec = 32
            total_weight = sum((item.weight for item in parsed), Decimal("0"))
            if total_weight > Decimal("1"):
                raise TemporaryTargetValidationError(
                    "TARGET_WEIGHT_SUM_EXCEEDS_ONE", "证券目标比例合计不能超过 100%。"
                )
            residual_cash_weight = Decimal("1") - total_weight
        return cls(tuple(parsed), residual_cash_weight)

    def weights_by_code(self) -> dict[str, Decimal]:
        """Return exact fractions keyed by the normalized canonical security code."""

        return {item.asset_code: item.weight for item in self.items}

    def exact_weight_strings(self) -> dict[str, str]:
        """Return decimal strings suitable for JSON and preview Decimal parsing."""

        return {item.asset_code: format(item.weight, "f") for item in self.items}

    def require_current_position_coverage(self, asset_codes: Iterable[str]) -> None:
        """Require an explicit target for every current holding before audit persistence."""

        target_codes = set(self.weights_by_code())
        for raw_code in asset_codes:
            if type(raw_code) is not str:
                raise TemporaryTargetValidationError(
                    "TARGET_HOLDING_CODE_INVALID", "当前持仓证券代码无法确认，未生成巡检记录。"
                )
            code = raw_code.strip().upper()
            if not _CANONICAL_SECURITY_CODE.fullmatch(code):
                raise TemporaryTargetValidationError(
                    "TARGET_HOLDING_CODE_INVALID", "当前持仓证券代码无法确认，未生成巡检记录。"
                )
            if code not in target_codes:
                raise TemporaryTargetValidationError(
                    "TARGET_SCOPE_INCOMPLETE", "每只当前持仓证券都需要填写目标比例；清仓请填写 0。"
                )

    def audit_record(self) -> TemporaryTargetAuditRecord:
        """Build the small audit marker consumed by the preview and TUI projector."""

        return {
            "scope": "temporary_target_entry",
            "rebalance_action": "hold",
            "source": "user_entered_temporary",
            "target_weights": self.exact_weight_strings(),
            "residual_cash_weight": format(self.residual_cash_weight, "f"),
        }
