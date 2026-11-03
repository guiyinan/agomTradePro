"""Typed projection and command values for explicit simulated-account pressure runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.application.portfolio_risk_snapshot import AccountSnapshot
from apps.risk_center.domain.portfolio_exit_pressure import ExitPressurePosition
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_sources import PortfolioRiskSourceEvidence

MoneyUnitBasis = Literal["native_simulated_ledger_config", "unknown"]


def _require_token(field_name: str, value: str, *, max_length: int = 160) -> None:
    """Reject blank, padded, or oversized identifiers at the application boundary."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        or len(value) > max_length
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_tokens(field_name: str, values: tuple[str, ...]) -> None:
    """Require unique typed evidence identifiers while allowing an empty set."""

    if type(values) is not tuple or any(
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        for value in values
    ):
        raise ValueError(f"{field_name} must be a tuple of canonical evidence identifiers")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class PortfolioPressureProjection:
    """One locked owner projection, source bundle, and per-session capacity set."""

    portfolio_snapshot_id: str
    allocation_policy_version: str
    code_version: str
    scenario_revision_id: str
    scenario_revision_hash: str
    positions: tuple[ExitPressurePosition, ...]
    source_evidence_ids: tuple[str, ...]
    source_evidence: tuple[PortfolioRiskSourceEvidence, ...]
    account_snapshot: AccountSnapshot
    identity_bindings: tuple[PortfolioRiskIdentityBinding, ...]
    native_account_limits: PortfolioRiskNativeAccountLimits
    money_unit_basis: MoneyUnitBasis
    calendar_evidence_json: str | None = None
    original_report_json: str | None = None
    scenario_label: str | None = None

    def __post_init__(self) -> None:
        """Keep resource, policy, source and asset identities exact and immutable."""

        _require_token("portfolio_snapshot_id", self.portfolio_snapshot_id, max_length=120)
        _require_token("allocation_policy_version", self.allocation_policy_version, max_length=120)
        _require_token("code_version", self.code_version, max_length=120)
        _require_token("scenario_revision_id", self.scenario_revision_id, max_length=120)
        if type(self.scenario_revision_hash) is not str or (
            len(self.scenario_revision_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.scenario_revision_hash)
        ):
            raise ValueError("scenario_revision_hash must be a lowercase SHA-256 digest")
        _require_tokens("source_evidence_ids", self.source_evidence_ids)
        if type(self.positions) is not tuple or any(
            type(item) is not ExitPressurePosition for item in self.positions
        ):
            raise TypeError("positions must be a tuple of ExitPressurePosition")
        asset_codes = tuple(item.asset_code for item in self.positions)
        if len(asset_codes) != len(set(asset_codes)):
            raise ValueError("pressure projection assets must be unique")
        if type(self.source_evidence) is not tuple or any(
            type(item) is not PortfolioRiskSourceEvidence for item in self.source_evidence
        ):
            raise TypeError("source_evidence must be a tuple of PortfolioRiskSourceEvidence")
        source_pairs = tuple(
            (item.source_id, item.source_record_id) for item in self.source_evidence
        )
        if len(source_pairs) != len(set(source_pairs)):
            raise ValueError("pressure projection source records must be unique")
        if type(self.account_snapshot) is not AccountSnapshot:
            raise TypeError("account_snapshot must be the exact public risk snapshot DTO")
        if self.account_snapshot.snapshot_id != self.portfolio_snapshot_id:
            raise ValueError("account and pressure snapshot identities must match")
        if self.money_unit_basis not in {"native_simulated_ledger_config", "unknown"}:
            raise ValueError("money_unit_basis is unsupported")
        if self.account_snapshot.money_unit is None:
            if self.money_unit_basis != "unknown":
                raise ValueError("an unknown money unit must keep an unknown basis")
        elif self.money_unit_basis != "native_simulated_ledger_config":
            raise ValueError("a configured money unit requires its explicit basis")
        if self.calendar_evidence_json is not None and (
            type(self.calendar_evidence_json) is not str or not self.calendar_evidence_json
        ):
            raise ValueError("calendar evidence must be canonical JSON or None")
        if self.calendar_evidence_json is not None:
            try:
                calendar_payload: object = json.loads(self.calendar_evidence_json)
            except json.JSONDecodeError as error:
                raise ValueError("calendar evidence must be canonical JSON") from error
            if not isinstance(calendar_payload, dict) or any(
                type(key) is not str for key in calendar_payload
            ):
                raise ValueError("calendar evidence must be a JSON object")
            calendar_mapping = cast(Mapping[str, object], calendar_payload)
            if canonical_portfolio_risk_json(calendar_mapping) != self.calendar_evidence_json:
                raise ValueError("calendar evidence must use the lossless canonical encoding")
        if (self.original_report_json is None) != (self.scenario_label is None):
            raise ValueError("original report and scenario label must be bound together")
        if self.original_report_json is not None:
            if type(self.original_report_json) is not str or not self.original_report_json:
                raise ValueError("original report must be canonical JSON or None")
            try:
                report_payload: object = json.loads(self.original_report_json)
            except json.JSONDecodeError as error:
                raise ValueError("original report must be canonical JSON") from error
            if not isinstance(report_payload, dict) or any(
                type(key) is not str for key in report_payload
            ):
                raise ValueError("original report must be a JSON object")
            report_mapping = cast(Mapping[str, object], report_payload)
            if canonical_portfolio_risk_json(report_mapping) != self.original_report_json:
                raise ValueError("original report must use the lossless canonical encoding")
            if (
                type(report_mapping.get("account_id")) is not int
                or report_mapping.get("account_id") != self.account_snapshot.account_id
                or report_mapping.get("scope") != "simulation_only"
                or report_mapping.get("must_not_execute") is not True
            ):
                raise ValueError("original report must bind the exact simulated account")
            if (
                type(self.scenario_label) is not str
                or not self.scenario_label.strip()
                or self.scenario_label.strip() != self.scenario_label
                or len(self.scenario_label) > 240
            ):
                raise ValueError("scenario_label must be bounded nonblank display text")
        if type(self.identity_bindings) is not tuple or any(
            type(item) is not PortfolioRiskIdentityBinding for item in self.identity_bindings
        ):
            raise TypeError("identity_bindings must be typed proof values")
        binding_by_asset = {item.asset_code: item for item in self.identity_bindings}
        if len(binding_by_asset) != len(self.identity_bindings):
            raise ValueError("identity bindings must be unique by asset code")
        if type(self.native_account_limits) is not PortfolioRiskNativeAccountLimits:
            raise TypeError("native_account_limits must preserve the exact native account limits")
        for holding in self.account_snapshot.holdings:
            binding = binding_by_asset.get(holding.asset_code)
            if binding is None:
                raise ValueError("every account holding requires one identity proof")
            if holding.security_id is None:
                if binding.ledger_security_id is not None:
                    raise ValueError("missing ledger identity cannot be replaced in the snapshot")
                if binding.basis != "pinned_policy_source_mapping":
                    raise ValueError("missing ledger identity requires a pinned source mapping")
            elif (
                binding.ledger_security_id != holding.security_id
                or binding.source_security_id != holding.security_id
                or binding.basis != "ledger"
            ):
                raise ValueError("known ledger identity must match the source binding")
        for order in self.account_snapshot.active_orders:
            binding = binding_by_asset.get(order.asset_code)
            if binding is None or (
                binding.ledger_security_id != order.security_id
                or binding.source_security_id != order.security_id
                or binding.basis != "ledger"
            ):
                raise ValueError("active order identity must match its exact ledger binding")
        for usage in self.account_snapshot.executed_usage:
            if usage.security_id is None:
                continue
            binding = binding_by_asset.get(usage.asset_code)
            if binding is None or (
                binding.ledger_security_id != usage.security_id
                or binding.source_security_id != usage.security_id
                or binding.basis != "ledger"
            ):
                raise ValueError("known execution identity must match its ledger binding")
        source_id_set = set(self.source_evidence_ids)
        typed_source_ids = {
            f"{item.source_id}:{item.source_record_id}" for item in self.source_evidence
        }
        if not typed_source_ids.issubset(source_id_set):
            raise ValueError("every typed source record must be locatable by its canonical id")
        capacity_source_ids = {
            source_id
            for position in self.positions
            for window in position.capacity_windows
            for source_id in window.source_evidence_ids
        }
        if not capacity_source_ids.issubset(typed_source_ids):
            raise ValueError("capacity source ids must resolve to retained typed source evidence")


@dataclass(frozen=True, slots=True)
class RunPortfolioExitPressureCommand:
    """Explicit actor, account, scenario, idempotency and confirmation intent."""

    actor_user_id: int
    account_id: int
    scenario_version_id: str
    idempotency_key: str
    confirmed: bool

    def __post_init__(self) -> None:
        """Reject invalid actors and missing explicit write confirmation."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be a positive integer")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        _require_token("scenario_version_id", self.scenario_version_id)
        _require_token("idempotency_key", self.idempotency_key, max_length=192)
        if type(self.confirmed) is not bool or self.confirmed is not True:
            raise ValueError("pressure run requires literal confirmation")


__all__ = ["PortfolioPressureProjection", "RunPortfolioExitPressureCommand"]
