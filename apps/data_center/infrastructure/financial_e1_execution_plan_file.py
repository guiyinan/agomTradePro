"""Strict file decoder for an independently pinned finite E1 plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import cast

from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
)
from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2
from apps.data_center.domain.financial_e1_execution_plan import (
    FinancialE1OfficialSourceProfilePin,
    FinancialE1PinnedExecutionPlan,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.infrastructure.financial_e1_discovery_replay import (
    build_main_shared_response_contract,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)

_PLAN_KEYS = frozenset(
    {
        "schema",
        "simulated_account_id",
        "provider_id",
        "provider_name",
        "dataset_key",
        "asset_code",
        "period_end",
        "exchange",
        "calendar_dataset_key",
        "main_endpoint",
        "balance_endpoint",
        "qualification_identities",
        "official_source_profile_pin",
    }
)


def load_pinned_financial_e1_plan(
    path: Path,
    *,
    expected_sha256: str,
) -> FinancialE1PinnedExecutionPlan:
    """Decode one closed plan file only when its external digest matches.

    The expected digest is supplied separately by the operator or reviewed
    deployment procedure. This loader never computes a digest and treats that
    computed value as its own approval.
    """

    if not isinstance(path, Path):
        raise TypeError("plan path must be a pathlib Path")
    _require_digest(expected_sha256, "expected_sha256")
    body = path.read_bytes()
    actual_sha256 = hashlib.sha256(body).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("financial E1 plan file does not match the external SHA-256 pin")
    try:
        document = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("financial E1 plan is not strict UTF-8 JSON") from error
    if not isinstance(document, Mapping) or set(document) != _PLAN_KEYS:
        raise ValueError("financial E1 plan has missing or unknown fields")

    simulated_account_id = document.get("simulated_account_id")
    provider_id = document.get("provider_id")
    provider_name = document.get("provider_name")
    dataset_key = document.get("dataset_key")
    asset_code = document.get("asset_code")
    period_text = document.get("period_end")
    exchange = document.get("exchange")
    calendar_dataset_key = document.get("calendar_dataset_key")
    main_endpoint = document.get("main_endpoint")
    balance_endpoint = document.get("balance_endpoint")
    identities_raw = document.get("qualification_identities")
    profile_raw = document.get("official_source_profile_pin")
    if (
        document.get("schema") != "financial-e1-execution-plan.v3"
        or type(simulated_account_id) is not int
        or simulated_account_id <= 0
        or type(provider_id) is not int
        or provider_id <= 0
        or provider_name != AKSHARE_PROVIDER_NAME
        or dataset_key != FINANCIAL_FACT_DATASET_KEY
        or type(asset_code) is not str
        or type(period_text) is not str
        or type(exchange) is not str
        or type(calendar_dataset_key) is not str
        or main_endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        or balance_endpoint != AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        or type(identities_raw) is not list
        or not identities_raw
        or any(type(item) is not str for item in identities_raw)
        or not isinstance(profile_raw, Mapping)
        or set(profile_raw)
        != {
            "profile_id",
            "profile_version",
            "publisher_code",
            "publisher_class",
            "profile_content_sha256",
        }
        or any(type(value) is not str for value in profile_raw.values())
    ):
        raise ValueError("financial E1 plan scope is not an exact supported request")
    try:
        period_end = date.fromisoformat(period_text)
    except ValueError as error:
        raise ValueError("period_end must be an ISO calendar date") from error
    if period_end.isoformat() != period_text:
        raise ValueError("period_end must use canonical YYYY-MM-DD text")

    plan = FinancialE1DiscoveryPlanV2(
        provider_id=provider_id,
        provider_name=AKSHARE_PROVIDER_NAME,
        asset_code=asset_code,
        period_end=period_end,
        exchange=exchange,
        calendar_dataset_key=calendar_dataset_key,
        qualification_identities=tuple(cast(list[str], identities_raw)),
        main_request=FinancialE1EndpointRequest(
            provider_name=AKSHARE_PROVIDER_NAME,
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            roles=(FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,),
            request_asset_code=asset_code,
            request_period_end=period_end,
            request_announcement_date=None,
            max_attempts=1,
            pagination_policy="one_response",
        ),
        balance_request=FinancialE1EndpointRequest(
            provider_name=AKSHARE_PROVIDER_NAME,
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
            roles=(FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,),
            request_asset_code=asset_code,
            request_period_end=period_end,
            request_announcement_date=None,
            max_attempts=1,
            pagination_policy="one_response",
        ),
        main_notice_contract=build_main_shared_response_contract(),
        maximum_physical_attempts=2,
    )
    return FinancialE1PinnedExecutionPlan(
        simulated_account_id=simulated_account_id,
        discovery_plan=plan,
        official_source_profile_pin=FinancialE1OfficialSourceProfilePin(
            profile_id=cast(str, profile_raw["profile_id"]),
            profile_version=cast(str, profile_raw["profile_version"]),
            publisher_code=cast(str, profile_raw["publisher_code"]),
            publisher_class=cast(str, profile_raw["publisher_class"]),
            profile_content_sha256=cast(str, profile_raw["profile_content_sha256"]),
        ),
        plan_file_sha256=actual_sha256,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject repeated JSON names rather than silently choosing one value."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("financial E1 plan contains a duplicate JSON field")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    """Reject JSON extensions such as NaN and Infinity."""

    raise ValueError(f"unsupported JSON constant: {value}")


def _require_digest(value: object, field_name: str) -> None:
    """Require a lowercase SHA-256 digest before file access."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


__all__ = ["load_pinned_financial_e1_plan"]
