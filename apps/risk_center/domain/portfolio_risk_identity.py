"""Identity proof binding simulated asset codes to qualified risk sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IdentityBasis = Literal["ledger", "pinned_policy_source_mapping"]


@dataclass(frozen=True, slots=True)
class PortfolioRiskIdentityBinding:
    """Preserve whether a risk source mapping came from ledger identity or policy pin."""

    asset_code: str
    ledger_security_id: str | None
    source_security_id: str
    basis: IdentityBasis

    def __post_init__(self) -> None:
        """Reject identity claims that do not match their declared proof basis."""

        _require_token(self.asset_code, "asset_code")
        _require_token(self.source_security_id, "source_security_id")
        if self.ledger_security_id is not None:
            _require_token(self.ledger_security_id, "ledger_security_id")
        if self.basis not in {"ledger", "pinned_policy_source_mapping"}:
            raise ValueError("identity basis is unsupported")
        if self.basis == "ledger":
            if self.ledger_security_id is None:
                raise ValueError("ledger identity proof requires a ledger security id")
            if self.ledger_security_id != self.source_security_id:
                raise ValueError("ledger and source security identities do not match")
        elif self.ledger_security_id is not None:
            raise ValueError("policy-pinned identity must preserve missing ledger identity")


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a canonical nonempty token")


__all__ = ["PortfolioRiskIdentityBinding"]
