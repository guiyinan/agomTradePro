"""Source-derived statutory terms, separate from custody dates and authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    MAX_SUPPORTED_HOLDING_MONTHS,
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    _require_digest,
    _require_unit_decimal,
)


class StatutoryDividendTaxClausePurpose(StrEnum):
    """Normative provisions required by the supported deferred-dividend interpreter."""

    HOLDING_BANDS = "holding_bands"
    LONG_HOLDING_EXEMPTION = "long_holding_exemption"
    DEFERRED_WITHHOLDING = "deferred_withholding"
    MECHANICS_CROSS_REFERENCE = "mechanics_cross_reference"
    RECORD_DATE_BOUNDARY = "record_date_boundary"
    HOLDING_DATE_SCOPE = "holding_date_scope"
    FIFO = "fifo"
    DAILY_NET = "daily_net"
    NATURAL_CALENDAR = "natural_calendar"


_MECHANICS = frozenset(
    {
        StatutoryDividendTaxClausePurpose.HOLDING_DATE_SCOPE,
        StatutoryDividendTaxClausePurpose.FIFO,
        StatutoryDividendTaxClausePurpose.DAILY_NET,
        StatutoryDividendTaxClausePurpose.NATURAL_CALENDAR,
    }
)


def _invalid(message: str) -> DeferredDividendTaxValidationError:
    """Classify missing or contradictory interpreted statutory facts."""
    return DeferredDividendTaxValidationError(message, "DEFERRED_TAX_STATUTORY_TERMS_INVALID")


def _decimal_text(value: Decimal) -> str:
    """Canonicalize an exact bounded decimal without applying ambient context."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True, slots=True)
class StatutoryDividendTaxClause:
    """One interpreted clause bound to its complete native source revision hash.

    Text normalization and interpretation belong to the source adapter. This
    immutable value provides integrity, not independent source authenticity.
    """

    purpose: StatutoryDividendTaxClausePurpose
    source_revision_sha256: str
    normalized_text: str

    def __post_init__(self) -> None:
        """Require exact purpose, native revision pin and bounded representable text."""
        if type(self.purpose) is not StatutoryDividendTaxClausePurpose:
            raise _invalid("statutory clause purpose is unknown")
        _require_digest(self.source_revision_sha256, "clause.source_revision_sha256")
        if (
            type(self.normalized_text) is not str
            or not self.normalized_text
            or self.normalized_text != self.normalized_text.strip()
            or len(self.normalized_text) > 16000
            or any(ord(c) < 32 or ord(c) == 127 for c in self.normalized_text)
        ):
            raise _invalid("statutory clause text is invalid")
        try:
            self.normalized_text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise _invalid("statutory clause text is not UTF-8 representable") from error

    @property
    def clause_sha256(self) -> str:
        """Bind the interpreted clause and purpose to its native source revision."""
        payload = {
            "purpose": self.purpose.value,
            "source_revision_sha256": self.source_revision_sha256,
            "normalized_text": self.normalized_text,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedStatutoryDividendTaxTerms:
    """Complete supported clause interpretation with source-derived numeric terms.

    Rates and thresholds are read from source clauses. Full inclusion and
    exemption have their algebraic meanings, one and zero. This value neither
    maps trade clocks to custody dates nor chooses an accounting rounding rule.
    """

    short_maximum_months: int
    middle_maximum_months: int
    middle_taxable_ratio: Decimal
    withholding_rate: Decimal
    record_date_exclusive_boundary: date
    clauses: tuple[StatutoryDividendTaxClause, ...]

    def __post_init__(self) -> None:
        """Require complete two-document mechanics and supported finite terms."""
        if (
            type(self.short_maximum_months) is not int
            or type(self.middle_maximum_months) is not int
            or not 0
            < self.short_maximum_months
            < self.middle_maximum_months
            <= MAX_SUPPORTED_HOLDING_MONTHS
            or type(self.record_date_exclusive_boundary) is not date
        ):
            raise _invalid("statutory holding thresholds or record-date boundary are invalid")
        _require_unit_decimal(self.middle_taxable_ratio, "statutory.middle_taxable_ratio")
        _require_unit_decimal(self.withholding_rate, "statutory.withholding_rate")
        if type(self.clauses) is not tuple or any(
            type(c) is not StatutoryDividendTaxClause for c in self.clauses
        ):
            raise _invalid("statutory clauses must be a complete typed tuple")
        purposes = tuple(c.purpose for c in self.clauses)
        if len(purposes) != len(set(purposes)) or set(purposes) != set(
            StatutoryDividendTaxClausePurpose
        ):
            raise _invalid("statutory clauses are missing, duplicated or unknown")
        rate_sources = {
            c.source_revision_sha256 for c in self.clauses if c.purpose not in _MECHANICS
        }
        mechanics_sources = {
            c.source_revision_sha256 for c in self.clauses if c.purpose in _MECHANICS
        }
        if (
            len(rate_sources) != 1
            or len(mechanics_sources) != 1
            or rate_sources == mechanics_sources
        ):
            raise _invalid("supported terms require distinct exact rate and mechanics revisions")
        object.__setattr__(
            self, "clauses", tuple(sorted(self.clauses, key=lambda c: c.purpose.value))
        )

    @property
    def terms_sha256(self) -> str:
        """Hash all interpreted terms and complete clause provenance deterministically."""
        payload = {
            "schema": "listed-individual-deferred-dividend-terms.v1",
            "short_maximum_months": self.short_maximum_months,
            "middle_maximum_months": self.middle_maximum_months,
            "middle_taxable_ratio": _decimal_text(self.middle_taxable_ratio),
            "withholding_rate": _decimal_text(self.withholding_rate),
            "record_date_exclusive_boundary": self.record_date_exclusive_boundary.isoformat(),
            "clauses": [c.clause_sha256 for c in self.clauses],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def validate_policy(self, policy: DeferredDividendTaxPolicy) -> None:
        """Reject policy terms that differ from the actual supported source clauses.

        Source authenticity, present applicability, taxpayer/account scope and
        current runtime configuration remain separate qualification gates.
        Currency quantum and rounding remain explicit accounting choices.
        """
        if type(policy) is not DeferredDividendTaxPolicy:
            raise _invalid("an exact deferred-dividend tax policy is required")
        policy.__post_init__()
        if policy.effective_from <= self.record_date_exclusive_boundary or len(policy.bands) != 3:
            raise _invalid("policy record-date window or band count differs from the source")
        expected = (
            (self.short_maximum_months, Decimal("1")),
            (self.middle_maximum_months, self.middle_taxable_ratio),
            (None, Decimal("0")),
        )
        for band, (maximum, taxable_ratio) in zip(policy.bands, expected, strict=True):
            if (
                band.maximum_holding_months != maximum
                or band.taxable_dividend_ratio != taxable_ratio
                or band.withholding_rate != self.withholding_rate
            ):
                raise _invalid("explicit policy numeric terms differ from the source clauses")


__all__ = [
    "ParsedStatutoryDividendTaxTerms",
    "StatutoryDividendTaxClause",
    "StatutoryDividendTaxClausePurpose",
]
