"""Typed, policy-approved references to retained portfolio-risk source manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

PolicySourceKind = Literal[
    "valuation",
    "industry_membership",
    "etf_report",
    "capacity_window",
    "execution_session_state",
]
PortfolioRiskClockEvidenceMode = Literal[
    "source_clocks_required",
    "policy_bounded_date_snapshot",
    "policy_bounded_timestamp_snapshot",
    "policy_bounded_close_snapshot_state",
    "policy_bounded_disclosed_report",
]

_SOURCE_KINDS = frozenset(
    {
        "valuation",
        "industry_membership",
        "etf_report",
        "capacity_window",
        "execution_session_state",
    }
)
_CLOCK_MODES = frozenset(
    {
        "source_clocks_required",
        "policy_bounded_date_snapshot",
        "policy_bounded_timestamp_snapshot",
        "policy_bounded_close_snapshot_state",
        "policy_bounded_disclosed_report",
    }
)
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceReference:
    """One policy-approved manifest pin bound to an asset, source record and clock mode."""

    kind: PolicySourceKind
    asset_code: str
    security_id: str
    raw_payload_hash: str
    source_record_id: str
    clock_evidence_mode: PortfolioRiskClockEvidenceMode = "source_clocks_required"

    def __post_init__(self) -> None:
        """Validate source identity, manifest digest and supported clock-mode scope."""

        if self.kind not in _SOURCE_KINDS:
            raise ValueError("source reference kind is unsupported")
        for name, value in (
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_record_id", self.source_record_id),
        ):
            _require_token(value, name)
        if (
            type(self.raw_payload_hash) is not str
            or _HASH_PATTERN.fullmatch(self.raw_payload_hash) is None
        ):
            raise ValueError("source reference raw_payload_hash must be sha256:<64 lowercase hex>")
        issue = source_clock_mode_error(self.kind, self.clock_evidence_mode)
        if issue is not None:
            raise ValueError(issue[1])


def source_clock_mode_error(kind: str, mode: str) -> tuple[str, str] | None:
    """Return the stable configuration error for an unsupported kind/mode pair."""

    if mode not in _CLOCK_MODES:
        return (
            "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_UNSUPPORTED",
            "source reference clock_evidence_mode is unsupported",
        )
    if mode == "policy_bounded_date_snapshot" and kind != "industry_membership":
        return (
            "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_KIND_UNSUPPORTED",
            "policy-bounded date mode is only available for industry membership",
        )
    if mode == "policy_bounded_timestamp_snapshot" and kind not in (
        "valuation",
        "capacity_window",
    ):
        return (
            "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_KIND_UNSUPPORTED",
            "policy-bounded timestamp mode is only available for valuation or capacity",
        )
    if mode == "policy_bounded_close_snapshot_state" and kind != "execution_session_state":
        return (
            "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_KIND_UNSUPPORTED",
            "close snapshot state mode is only available for session state",
        )
    if mode == "policy_bounded_disclosed_report" and kind != "etf_report":
        return (
            "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_KIND_UNSUPPORTED",
            "disclosed-report mode is only available for ETF reports",
        )
    return None


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


__all__ = (
    "PolicySourceKind",
    "PortfolioRiskClockEvidenceMode",
    "PortfolioRiskSourceReference",
    "source_clock_mode_error",
)
