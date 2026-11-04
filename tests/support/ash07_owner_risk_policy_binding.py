"""Bind a native owner-risk test to an explicitly selected, audited v2 policy."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from apps.config_center.domain.runtime_config import hash_runtime_profile_values
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionRequest,
)
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
from tests.support.ash07_public_risk_sources import verify_source_request_units

_RISK_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"
_BALANCED_V2_PROFILE_KEY = "risk_center.simulated_portfolio_risk.draft.balanced"
_POLICY_PATH_ENV = "ASH07_REAL_RISK_POLICY_V2_PATH"
_POLICY_AUDIT_PATH_ENV = "ASH07_REAL_RISK_POLICY_V2_AUDIT_PATH"
_POLICY_CLOCK_MODES: dict[str, str] = {
    "industry_membership": "policy_bounded_date_snapshot",
    "valuation": "policy_bounded_timestamp_snapshot",
    "etf_report": "policy_bounded_disclosed_report",
    "capacity_window": "policy_bounded_timestamp_snapshot",
    "execution_session_state": "policy_bounded_close_snapshot_state",
}
_INDUSTRY_SOURCE_KINDS = frozenset({"industry_membership", "valuation", "etf_report"})
_CAPACITY_SOURCE_KINDS = frozenset({"capacity_window", "execution_session_state"})
_INDUSTRY_RESTRICTIONS = frozenset(
    {
        "same_business_date_membership_only",
        "close_snapshot_only",
        "vendor_timestamped_quote",
    }
)
_CAPACITY_RESTRICTIONS = frozenset(
    {
        "close_snapshot_only",
        "session_cumulative_quote",
        "vendor_timestamped_quote",
        "vendor_reported_at_quote_time",
    }
)
_PROHIBITED_RESTRICTIONS = frozenset({"research_only", "observation_only"})


def bind_audited_balanced_v2_policy(
    *,
    account_id: int,
    source_references: Sequence[Mapping[str, object]],
    admitted_requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    admitted_manifest_hashes: Mapping[tuple[str, str, str, str], str],
    repository_root: Path,
    unit_mapping: Mapping[str, object],
) -> dict[str, object]:
    """Copy audited balanced-v2 policy data and bind this test's account/sources.

    Both the v2 input and its saved-draft audit must be selected explicitly via
    environment paths. Only account scope, exact retained-source references,
    observation precision sets and source restriction allowlists are rebound.
    Numeric limits and the ETF report-age block come unchanged from v2.
    """

    if type(account_id) is not int or account_id < 1:
        raise AssertionError("the isolated Owner test must supply its actual account id")
    policy_path = _required_path(_POLICY_PATH_ENV, repository_root)
    audit_path = _required_path(_POLICY_AUDIT_PATH_ENV, repository_root)
    base_policy = _load_audited_balanced_v2(policy_path, audit_path)
    verify_source_request_units(admitted_requests, unit_mapping=unit_mapping, policy=base_policy)
    if not source_references or not admitted_requests:
        raise AssertionError("audited v2 policy binding requires admitted source references")

    _validate_exact_reference_bindings(
        source_references,
        admitted_requests,
        admitted_manifest_hashes,
    )
    industry_precisions = _observation_precisions(
        admitted_requests,
        _INDUSTRY_SOURCE_KINDS,
        "industry/valuation/ETF",
    )
    capacity_precisions = _observation_precisions(
        admitted_requests,
        _CAPACITY_SOURCE_KINDS,
        "capacity/state",
    )
    if capacity_precisions != {SourceObservationPrecision.TIMESTAMP.value}:
        raise AssertionError(
            "bounded capacity and close-state inputs must retain timestamp precision"
        )

    industry_restrictions = _source_restrictions(
        admitted_requests,
        _INDUSTRY_SOURCE_KINDS,
        _INDUSTRY_RESTRICTIONS,
        "industry/valuation/ETF",
    )
    capacity_restrictions = _source_restrictions(
        admitted_requests,
        _CAPACITY_SOURCE_KINDS,
        _CAPACITY_RESTRICTIONS,
        "capacity/state",
    )

    policy = copy.deepcopy(base_policy)
    industry_value = policy.get("industry")
    capacity_value = policy.get("capacity")
    if type(industry_value) is not dict or type(capacity_value) is not dict:
        raise AssertionError("audited balanced v2 policy has malformed industry/capacity blocks")
    industry_block = cast(dict[str, object], industry_value)
    capacity_block = cast(dict[str, object], capacity_value)
    policy["account_ids"] = [account_id]
    policy["source_references"] = [dict(item) for item in source_references]
    industry_block["allowed_observation_precisions"] = sorted(industry_precisions)
    industry_block["allowed_source_restrictions"] = list(industry_restrictions)
    capacity_block["allowed_observation_precisions"] = sorted(capacity_precisions)
    capacity_block["allowed_source_restrictions"] = list(capacity_restrictions)
    return cast(dict[str, object], policy)


def _required_path(environment_name: str, repository_root: Path) -> Path:
    """Resolve a required operator-selected JSON path without a code fallback."""

    raw_path = os.environ.get(environment_name, "")
    if not raw_path or raw_path.strip() != raw_path:
        raise AssertionError(f"set {environment_name} to the audited external JSON path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = repository_root / path
    if not path.is_file():
        raise AssertionError(f"selected JSON input does not exist: {path}")
    return path


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    """Read one explicitly selected JSON object and reject other top-level data."""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(value) is not dict:
        raise AssertionError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _load_audited_balanced_v2(policy_path: Path, audit_path: Path) -> dict[str, object]:
    """Require the selected value to match the recorded balanced-v2 DRAFT hash."""

    document = _read_json_object(policy_path, "balanced v2 policy input")
    if (
        document.get("profile_key") != _BALANCED_V2_PROFILE_KEY
        or document.get("environment") != "development"
        or document.get("version") != 2
    ):
        raise AssertionError("selected policy input is not the development balanced v2 data")
    raw_values = document.get("values")
    if type(raw_values) is not list or len(raw_values) != 1 or type(raw_values[0]) is not dict:
        raise AssertionError("balanced v2 input must contain exactly one typed Risk value")
    value_entry = cast(dict[str, object], raw_values[0])
    if value_entry.get("definition_key") != _RISK_DEFINITION_KEY:
        raise AssertionError("balanced v2 input is bound to the wrong runtime definition")
    raw_policy = value_entry.get("value_json")
    if type(raw_policy) is not dict:
        raise AssertionError("balanced v2 Risk value must be a JSON object")
    base_policy = cast(dict[str, object], raw_policy)
    if base_policy.get("source_references") != []:
        raise AssertionError("audited balanced v2 seed must retain its original empty source pins")
    etf_report = base_policy.get("etf_report")
    if (
        type(etf_report) is not dict
        or etf_report.get("age_basis") != "report_period_end"
        or type(etf_report.get("max_report_age_days")) is not int
        or cast(int, etf_report.get("max_report_age_days")) < 1
    ):
        raise AssertionError("balanced v2 ETF report-age block is malformed")

    audit = _read_json_object(audit_path, "balanced v2 database audit")
    if (
        audit.get("ledger_written") is not False
        or audit.get("snapshot_count_unchanged") is not True
        or audit.get("original_config_rows_unchanged") is not True
        or audit.get("source_binding_complete") is not False
        or audit.get("production_or_automatic_activation") is not False
    ):
        raise AssertionError("selected database audit does not describe the inactive v2 draft")
    profiles = audit.get("profiles")
    if type(profiles) is not list:
        raise AssertionError("database audit has no profile list")
    matching_profiles = [
        cast(dict[str, object], item)
        for item in profiles
        if type(item) is dict and item.get("profile_key") == _BALANCED_V2_PROFILE_KEY
    ]
    if len(matching_profiles) != 1:
        raise AssertionError("database audit must contain exactly one balanced v2 profile")
    audited_profile = matching_profiles[0]
    expected_profile_id = uuid5(
        NAMESPACE_URL,
        "config-center-runtime-draft:development:" f"{_BALANCED_V2_PROFILE_KEY}:2",
    ).hex
    expected_content_hash = hash_runtime_profile_values({_RISK_DEFINITION_KEY: base_policy})
    if (
        str(audited_profile.get("profile_id", "")).replace("-", "").lower() != expected_profile_id
        or audited_profile.get("status") != "draft"
        or audited_profile.get("content_hash") != expected_content_hash
        or audited_profile.get("source_references_count") != 0
        or audited_profile.get("etf_report") != etf_report
    ):
        raise AssertionError("selected v2 policy does not match its persisted draft audit")
    return base_policy


def _validate_exact_reference_bindings(
    source_references: Sequence[Mapping[str, object]],
    admitted_requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    admitted_manifest_hashes: Mapping[tuple[str, str, str, str], str],
) -> None:
    """Require one policy pin for every exact admitted request and no extras."""

    request_by_identity: dict[tuple[str, str, str, str], PortfolioRiskSourceAdmissionRequest] = {}
    for request in admitted_requests:
        if not isinstance(request, PortfolioRiskSourceAdmissionRequest):
            raise AssertionError("policy binding accepts only typed admitted-source requests")
        identity = (
            request.kind,
            request.asset_code,
            request.security_id,
            request.source_record_id,
        )
        if identity in request_by_identity:
            raise AssertionError("admitted requests contain a duplicate source identity")
        request_by_identity[identity] = request
        evidence = request.source_evidence
        if evidence.must_not_use_for_decision:
            raise AssertionError("a prohibited source cannot be allowed by a policy binding")
        if evidence.original_payload_sha256 is None:
            raise AssertionError("admitted source has no original-body hash")
        if evidence.source_id is None or not evidence.source_id.strip():
            raise AssertionError("admitted source has no source identity")

    reference_by_identity: dict[tuple[str, str, str, str], Mapping[str, object]] = {}
    for reference in source_references:
        if not isinstance(reference, Mapping):
            raise AssertionError("policy source references must be mappings")
        identity_values = tuple(
            reference.get(field_name)
            for field_name in ("kind", "asset_code", "security_id", "source_record_id")
        )
        if any(type(value) is not str or not value for value in identity_values):
            raise AssertionError("policy source reference identity is incomplete")
        identity = cast(tuple[str, str, str, str], identity_values)
        if identity in reference_by_identity:
            raise AssertionError("policy source references contain a duplicate identity")
        reference_by_identity[identity] = reference
        request = request_by_identity.get(identity)
        if request is None:
            raise AssertionError("policy contains a source pin absent from admitted requests")
        if reference.get("clock_evidence_mode") != _POLICY_CLOCK_MODES.get(request.kind):
            raise AssertionError("policy source clock mode differs from the typed source kind")
        payload_hash = reference.get("raw_payload_hash")
        if type(payload_hash) is not str or not payload_hash:
            raise AssertionError("policy source pin requires the retained RawPayload hash")
        if payload_hash != admitted_manifest_hashes.get(identity):
            raise AssertionError("policy pin differs from the persisted admission result hash")
        body_hash = request.source_evidence.original_payload_sha256
        if payload_hash == f"sha256:{body_hash}":
            raise AssertionError("manifest pin must remain distinct from the vendor body hash")

    if set(reference_by_identity) != set(request_by_identity):
        raise AssertionError("every admitted request must have exactly one policy source pin")
    if set(admitted_manifest_hashes) != set(request_by_identity):
        raise AssertionError("persisted admission results do not match the requested source set")


def _observation_precisions(
    admitted_requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    kinds: frozenset[str],
    label: str,
) -> set[str]:
    """Collect actual DATE/TIMESTAMP precision without upgrading unknown clocks."""

    precisions = {
        request.source_evidence.observation_precision.value
        for request in admitted_requests
        if request.kind in kinds
    }
    if not precisions or not precisions.issubset(
        {SourceObservationPrecision.DATE.value, SourceObservationPrecision.TIMESTAMP.value}
    ):
        raise AssertionError(f"{label} sources have missing or unknown observation precision")
    return precisions


def _source_restrictions(
    admitted_requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    kinds: frozenset[str],
    approved_tokens: frozenset[str],
    label: str,
) -> list[str]:
    """Bind only recognized restrictions actually carried by admitted sources."""

    restrictions: set[str] = set()
    for request in admitted_requests:
        if request.kind not in kinds:
            continue
        evidence = request.source_evidence
        if evidence.must_not_use_for_decision:
            raise AssertionError(f"{label} includes a globally prohibited source")
        for token in evidence.restrictions:
            if (
                token.startswith("must_not_")
                or token in _PROHIBITED_RESTRICTIONS
                or token not in approved_tokens
            ):
                raise AssertionError(f"{label} contains an unapproved source restriction: {token}")
            restrictions.add(token)
    return sorted(restrictions)
