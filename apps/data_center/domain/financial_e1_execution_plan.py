"""Pinned simulated-account and finite-scope envelope for one E1 execution."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2


@dataclass(frozen=True, slots=True)
class FinancialE1OfficialSourceProfilePin:
    """Carry an independently reviewed existing official-profile identity."""

    profile_id: str
    profile_version: str
    publisher_code: str
    publisher_class: str
    profile_content_sha256: str

    def __post_init__(self) -> None:
        """Validate all pinned identity fields without reading mutable catalog data."""

        for name, value, maximum in (
            ("profile_id", self.profile_id, 128),
            ("profile_version", self.profile_version, 128),
            ("publisher_code", self.publisher_code, 40),
            ("publisher_class", self.publisher_class, 30),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} must be explicit bounded text")
        if (
            type(self.profile_content_sha256) is not str
            or len(self.profile_content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.profile_content_sha256)
        ):
            raise ValueError("profile_content_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class FinancialE1PinnedExecutionPlan:
    """Bind one finite capture plan to its simulated account and external pin.

    ``plan_file_sha256`` must be checked against a separately supplied digest
    before constructing this value. The object is an execution scope carrier;
    its hash does not grant authority or qualify any source metric.
    """

    simulated_account_id: int
    discovery_plan: FinancialE1DiscoveryPlanV2
    official_source_profile_pin: FinancialE1OfficialSourceProfilePin
    plan_file_sha256: str

    def __post_init__(self) -> None:
        """Reject an incomplete account scope or malformed independent pin."""

        if type(self.simulated_account_id) is not int or self.simulated_account_id <= 0:
            raise ValueError("simulated_account_id must be a positive persisted identifier")
        if type(self.discovery_plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("discovery_plan must be the exact typed E1 plan")
        if type(self.official_source_profile_pin) is not FinancialE1OfficialSourceProfilePin:
            raise TypeError("official_source_profile_pin must be the exact typed profile pin")
        if (
            type(self.plan_file_sha256) is not str
            or len(self.plan_file_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.plan_file_sha256)
        ):
            raise ValueError("plan_file_sha256 must be a lowercase SHA-256 digest")


__all__ = ["FinancialE1OfficialSourceProfilePin", "FinancialE1PinnedExecutionPlan"]
