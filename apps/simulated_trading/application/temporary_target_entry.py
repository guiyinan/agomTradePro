"""Application adapter for exact, canonical temporary security targets."""

from __future__ import annotations

from apps.data_center.domain.rules import normalize_asset_code
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporarySecurityTargets,
    TemporaryTargetValidationError,
)


def _canonical_user_security_code(raw_code: str) -> str:
    """Accept only the existing canonical ticker form, not provider aliases."""

    canonical = normalize_asset_code(raw_code, "tushare")
    if canonical != raw_code.strip().upper():
        raise TemporaryTargetValidationError(
            "TARGET_SECURITY_CODE_INVALID", "请填写规范证券代码，例如 600000.SH，不要使用来源别名。"
        )
    return canonical


def parse_temporary_security_targets(raw_text: str) -> TemporarySecurityTargets:
    """Parse a user's percentage rows into an exact, immutable target set."""

    return TemporarySecurityTargets.parse_percent_lines(
        raw_text,
        normalize_code=_canonical_user_security_code,
    )
