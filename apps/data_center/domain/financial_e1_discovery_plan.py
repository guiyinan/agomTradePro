"""Explicit finite E1 capture plan with NOTICE discovery from the Main body.

This version is separate from the frozen date-predeclared E1 v1 plan. It
contains only the asset, report period, selected catalog qualification
identities, and endpoint request slots. It does not grant catalog, source-time,
publication, or production eligibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
    FinancialSharedResponseSourceTimeContractV2,
)


@dataclass(frozen=True, slots=True)
class FinancialE1DiscoveryPlanV2:
    """One explicit finite Main+Balance capture, with no caller-supplied NOTICE.

    Qualification identities are an exact finite selection supplied by the
    caller. The plan contains no default metric list, unit, scale, context,
    currency, or derived formula. Provider and catalog implementations must
    independently reload the selected rows before capture and after each raw
    response.
    """

    provider_id: int
    provider_name: str
    asset_code: str
    period_end: date
    exchange: str
    calendar_dataset_key: str
    qualification_identities: tuple[str, ...]
    main_request: FinancialE1EndpointRequest
    balance_request: FinancialE1EndpointRequest
    main_notice_contract: FinancialSharedResponseSourceTimeContractV2
    maximum_physical_attempts: int

    def __post_init__(self) -> None:
        """Require two one-attempt endpoint slots and an explicit finite set."""

        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise ValueError("provider_id must be a positive persisted identifier")
        for name, value, maximum in (
            ("provider_name", self.provider_name, 128),
            ("asset_code", self.asset_code, 64),
            ("exchange", self.exchange, 32),
            ("calendar_dataset_key", self.calendar_dataset_key, 160),
        ):
            _required_text(value, name, maximum)
        if type(self.period_end) is not date or isinstance(self.period_end, datetime):
            raise ValueError("period_end must be a date without time precision")
        if type(self.qualification_identities) is not tuple or not self.qualification_identities:
            raise ValueError("an explicit non-empty qualification identity tuple is required")
        for identity in self.qualification_identities:
            _required_text(identity, "qualification_identity", 256)
        if len(set(self.qualification_identities)) != len(self.qualification_identities):
            raise ValueError("qualification identities must be unique")
        if type(self.main_request) is not FinancialE1EndpointRequest:
            raise TypeError("main_request must be a typed E1 endpoint request")
        if type(self.balance_request) is not FinancialE1EndpointRequest:
            raise TypeError("balance_request must be a typed E1 endpoint request")
        if type(self.main_notice_contract) is not FinancialSharedResponseSourceTimeContractV2:
            raise TypeError("main NOTICE interpretation must use the shared-response v2 contract")
        self.main_notice_contract.__post_init__()
        if type(self.maximum_physical_attempts) is not int or self.maximum_physical_attempts != 2:
            raise ValueError("E1 discovery permits exactly two physical endpoint attempts")
        _validate_request(
            self.main_request,
            provider_name=self.provider_name,
            asset_code=self.asset_code,
            period_end=self.period_end,
            expected_role=FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
        )
        _validate_request(
            self.balance_request,
            provider_name=self.provider_name,
            asset_code=self.asset_code,
            period_end=self.period_end,
            expected_role=FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
        )
        if (
            self.main_request.endpoint == self.balance_request.endpoint
            or self.main_notice_contract.provider_name != self.provider_name
            or self.main_notice_contract.dataset_key != self.main_request.dataset_key
            or self.main_notice_contract.endpoint != self.main_request.endpoint
        ):
            raise ValueError("E1 discovery endpoint and NOTICE identities do not match")

    @property
    def selection_sha256(self) -> str:
        """Hash the exact explicit identity set without adding required metrics."""

        payload = {
            "schema": "financial-e1-discovery-selection.v2",
            "qualification_identities": sorted(self.qualification_identities),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _validate_request(
    request: FinancialE1EndpointRequest,
    *,
    provider_name: str,
    asset_code: str,
    period_end: date,
    expected_role: FinancialE1ResponseRole,
) -> None:
    """Keep every request bound to one exact target and one endpoint role."""

    if (
        request.provider_name != provider_name
        or request.dataset_key != "equity.financial.fact"
        or request.request_asset_code != asset_code
        or request.request_period_end != period_end
        or request.request_announcement_date is not None
        or request.roles != (expected_role,)
        or request.max_attempts != 1
        or request.pagination_policy != "one_response"
    ):
        raise ValueError("E1 discovery request must be one exact no-date one-response slot")


def _required_text(value: object, field_name: str, maximum: int) -> str:
    """Require bounded, exact text without cleaning caller identities."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be bounded canonical text")
    return value


__all__ = ["FinancialE1DiscoveryPlanV2"]
