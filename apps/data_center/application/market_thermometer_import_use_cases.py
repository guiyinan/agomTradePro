"""Investor-account CSV import use case for market thermometer inputs."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.domain.protocols import MacroFactRepositoryProtocol

from .investor_account_import import (
    INVESTOR_ACCOUNT_IMPORT_UNITS,
    build_investor_account_import_warnings,
    normalize_investor_account_import_value,
)
from .macro_fact_governance import MacroFactGovernanceNormalizer
from .market_thermometer_specs import MARKET_COMPONENT_SPECS


class ImportInvestorAccountsUseCase:
    """Import investor-account time series rows into canonical MacroFact storage."""

    def __init__(
        self,
        macro_repo: MacroFactRepositoryProtocol,
        macro_normalizer: MacroFactGovernanceNormalizer,
    ) -> None:
        self._macro_repo = macro_repo
        self._macro_normalizer = macro_normalizer

    def execute(
        self,
        csv_text: str,
        *,
        source: str = "manual_import",
        dry_run: bool = False,
        value_unit: str = "户",
    ) -> dict[str, Any]:
        """Parse CSV text and upsert investor-account rows.

        Accepted columns:
        - reporting_period / date / month
        - value / accounts / new_accounts
        """

        if value_unit not in INVESTOR_ACCOUNT_IMPORT_UNITS:
            raise ValueError(f"Unsupported investor-account unit: {value_unit}")

        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        facts: list[MacroFact] = []
        for row in reader:
            raw_period = str(
                row.get("reporting_period") or row.get("date") or row.get("month") or ""
            ).strip()
            raw_value = str(
                row.get("value") or row.get("accounts") or row.get("new_accounts") or ""
            ).strip()
            if not raw_period or not raw_value:
                continue
            normalized_period = raw_period[:10]
            reporting_period = date.fromisoformat(normalized_period)
            raw_numeric_value = float(raw_value.replace(",", ""))
            value = normalize_investor_account_import_value(
                raw_numeric_value,
                value_unit=value_unit,
            )
            facts.append(
                MacroFact(
                    indicator_code=MARKET_COMPONENT_SPECS["new_investor_accounts"][
                        "indicator_code"
                    ],
                    reporting_period=reporting_period,
                    value=value,
                    unit="户",
                    source=source,
                    quality=DataQualityStatus.VALID,
                    extra={
                        "source_type": source,
                        "provider_name": source,
                        "original_unit": value_unit,
                        "raw_value": raw_numeric_value,
                    },
                )
            )
        warnings = build_investor_account_import_warnings(facts)
        if dry_run:
            periods = [fact.reporting_period for fact in facts]
            return {
                "dry_run": True,
                "parsed_count": len(facts),
                "stored_count": 0,
                "indicator_code": MARKET_COMPONENT_SPECS["new_investor_accounts"]["indicator_code"],
                "source_unit": value_unit,
                "unit": "户",
                "first_period": min(periods).isoformat() if periods else None,
                "last_period": max(periods).isoformat() if periods else None,
                "warnings": warnings,
            }
        normalized = self._macro_normalizer.normalize_many(
            facts,
            source_type=source,
            provider_name=source,
        )
        stored_count = self._macro_repo.bulk_upsert(normalized)
        return {"stored_count": stored_count, "parsed_count": len(facts), "warnings": warnings}
