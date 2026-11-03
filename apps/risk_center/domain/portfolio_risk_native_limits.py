"""Known native-account risk boundaries retained beside governed policies."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

NativeLimitBasis = Literal["simulated_account_percent_fields"]


@dataclass(frozen=True, slots=True)
class PortfolioRiskNativeAccountLimits:
    """Exact fractional limits decoded from the locked simulated account settings."""

    max_single_weight: Decimal | None
    max_total_weight: Decimal | None
    reason_codes: tuple[str, ...]
    basis: NativeLimitBasis

    def __post_init__(self) -> None:
        """Preserve unavailable fields explicitly and constrain known weights to [0, 1]."""

        expected_reasons: list[str] = []
        for field_name, value, reason in (
            ("max_single_weight", self.max_single_weight, "native_single_weight_unknown"),
            ("max_total_weight", self.max_total_weight, "native_total_weight_unknown"),
        ):
            if value is not None and (
                type(value) is not Decimal or not value.is_finite() or value < 0 or value > 1
            ):
                raise ValueError(f"{field_name} must be an exact fraction in [0, 1]")
            if value is None:
                expected_reasons.append(reason)
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain nonempty strings")
        if self.reason_codes != tuple(expected_reasons):
            raise ValueError("reason_codes must exactly describe unavailable native limits")
        if self.basis != "simulated_account_percent_fields":
            raise ValueError("native account limit basis is unsupported")


__all__ = ["PortfolioRiskNativeAccountLimits"]
