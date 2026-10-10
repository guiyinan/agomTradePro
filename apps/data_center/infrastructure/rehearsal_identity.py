"""Strict non-secret identity input shared by rehearsal capture and offline replay."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from shared.release_rehearsal_file_io import RehearsalFileReadError, read_regular_file

IDENTITY_ERROR_CODES = frozenset(
    {
        "REHEARSAL_PROVIDER_IDENTITY_MISMATCH",
        "REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE",
    }
)

_CORE_ROLES = frozenset({"quote", "valuation"})
_ROUTE_ROLE_PREFIX = "model_market_route:"
_AKSHARE_FINANCIAL_ROUTE_ROLE_PREFIX = "akshare_financial_route:"
_AKSHARE_FINANCIAL_IDENTITY_SOURCE = "akshare_financial"
_MAX_IDENTITIES = 32


@dataclass(frozen=True)
class RehearsalProviderIdentity:
    """Frozen association context; version does not claim an upstream version probe."""

    role: str
    provider_id: int
    source: str
    version: str
    endpoint_id: str
    deployment_region: str | None = None


def parse_rehearsal_identities(value: object) -> tuple[RehearsalProviderIdentity, ...]:
    """Accept core provider identities plus bounded model-market route identities."""
    if not isinstance(value, list) or not 2 <= len(value) <= _MAX_IDENTITIES:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    identities: list[RehearsalProviderIdentity] = []
    roles: set[str] = set()
    keys = {"role", "provider_id", "source", "version", "endpoint_id"}
    for item in cast(list[object], value):
        if not isinstance(item, dict) or frozenset(item) not in {
            frozenset(keys),
            frozenset(keys | {"deployment_region"}),
        }:
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        record = cast(dict[str, object], item)
        provider_id = record["provider_id"]
        if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        strings: dict[str, str] = {}
        for key in keys - {"provider_id"}:
            raw = record[key]
            if not isinstance(raw, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", raw) is None:
                raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
            strings[key] = raw
        role = strings["role"]
        if role in roles or (
            role not in _CORE_ROLES
            and role != model_market_route_role(provider_id)
            and role != akshare_financial_route_role(provider_id)
        ):
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        if role == akshare_financial_route_role(provider_id) and (
            strings["source"] != _AKSHARE_FINANCIAL_IDENTITY_SOURCE
            or "deployment_region" not in record
            or not isinstance(record.get("deployment_region"), str)
            or re.fullmatch(r"[a-z0-9_.:-]{1,128}", cast(str, record.get("deployment_region")))
            is None
        ):
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        if (
            role != akshare_financial_route_role(provider_id)
            and record.get("deployment_region") is not None
        ):
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        roles.add(role)
        identities.append(
            RehearsalProviderIdentity(
                provider_id=provider_id,
                deployment_region=(
                    cast(str, record.get("deployment_region"))
                    if record.get("deployment_region") is not None
                    else None
                ),
                **strings,
            )
        )
    if not _CORE_ROLES.issubset(roles):
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    # Preserve frozen input order: the release validator hashes this same ordered list.
    return tuple(identities)


def parse_complete_rehearsal_identities(
    value: object,
) -> tuple[RehearsalProviderIdentity, ...]:
    """Parse the complete S6 graph, including one financial route identity."""

    identities = parse_rehearsal_identities(value)
    financial_routes = tuple(
        identity
        for identity in identities
        if identity.role.startswith(_AKSHARE_FINANCIAL_ROUTE_ROLE_PREFIX)
    )
    if len(financial_routes) != 1:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    return identities


def model_market_route_role(provider_id: int) -> str:
    """Return the canonical frozen-identity role for one model-market route."""

    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    return f"{_ROUTE_ROLE_PREFIX}{provider_id}"


def akshare_financial_route_role(provider_id: int) -> str:
    """Return the canonical frozen-identity role for one financial data route."""

    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    return f"{_AKSHARE_FINANCIAL_ROUTE_ROLE_PREFIX}{provider_id}"


def load_rehearsal_identities(path: Path) -> tuple[RehearsalProviderIdentity, ...]:
    """Read a bounded public snapshot, never a provider configuration or credential file."""
    try:
        data = read_regular_file(path.parent, path.name, 16_384)
    except RehearsalFileReadError as exc:
        code = (
            "REHEARSAL_PROVIDER_IDENTITY_LIMIT"
            if str(exc) == "file_too_large"
            else ("REHEARSAL_PROVIDER_IDENTITY_INVALID")
        )
        raise ValueError(code) from None
    if len(data) > 16_384:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_LIMIT")
    try:
        value: object = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID") from exc
    return parse_rehearsal_identities(value)


def rehearsal_identities_digest(identities: tuple[RehearsalProviderIdentity, ...]) -> str:
    """Match the release validator's canonical JSON digest, including input order."""
    encoded = json.dumps(
        [rehearsal_identity_dict(identity) for identity in identities],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def rehearsal_identity_dict(identity: RehearsalProviderIdentity) -> dict[str, object]:
    """Serialize one frozen identity while retaining region only for the financial route."""

    value: dict[str, object] = {
        "role": identity.role,
        "provider_id": identity.provider_id,
        "source": identity.source,
        "version": identity.version,
        "endpoint_id": identity.endpoint_id,
    }
    if identity.deployment_region is not None:
        value["deployment_region"] = identity.deployment_region
    return value


def rehearsal_identities_payload(
    identities: Iterable[RehearsalProviderIdentity],
) -> list[dict[str, object]]:
    """Serialize a provider identity graph with the canonical optional-field policy."""

    return [rehearsal_identity_dict(identity) for identity in identities]


def configured_rehearsal_identity(*, provider_id: int, role: str) -> RehearsalProviderIdentity:
    """Derive one non-secret identity from active config and installed provider code."""

    if role == akshare_financial_route_role(provider_id):
        return configured_akshare_financial_identity(provider_id=provider_id)

    from .models import ProviderConfigModel

    try:
        provider = ProviderConfigModel._default_manager.only(
            "id",
            "name",
            "source_type",
            "is_active",
            "priority",
            "http_url",
            "api_endpoint",
            "extra_config",
        ).get(pk=provider_id)
    except ProviderConfigModel.DoesNotExist as exc:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH") from exc
    source_type = str(provider.source_type or "").strip().lower()
    if not provider.is_active or source_type not in {"tushare", "akshare"}:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    is_route_role = role == model_market_route_role(provider_id)
    if role not in _CORE_ROLES and not is_route_role:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    if source_type == "akshare" and role != "valuation" and not is_route_role:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    extra = provider.extra_config if isinstance(provider.extra_config, Mapping) else {}
    request_mode = (
        str(extra.get("tushare_request_mode") or "sdk_path").strip()
        if source_type == "tushare"
        else "tencent_quote_batch"
    )
    endpoint = (
        str(provider.http_url or "").strip().rstrip("/") or "tushare-sdk-default"
        if source_type == "tushare"
        else "https://qt.gtimg.cn"
    )
    api_endpoint = str(provider.api_endpoint or "").strip().rstrip("/")
    endpoint_material = json.dumps(
        {
            "provider_id": provider_id,
            "request_mode": request_mode,
            "source": source_type,
            "upstream_source": "tencent" if source_type == "akshare" else source_type,
            "transport_endpoint": endpoint,
            "api_endpoint": api_endpoint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    try:
        package_name = "tushare" if source_type == "tushare" else "requests"
        installed_version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE") from exc
    config_material = json.dumps(
        {
            "api_endpoint": api_endpoint,
            "http_url": endpoint,
            "is_active": provider.is_active,
            "name": provider.name,
            "priority": provider.priority,
            "request_mode": request_mode,
            "source_type": source_type,
            "upstream_source": "tencent" if source_type == "akshare" else source_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = hashlib.sha256(config_material).hexdigest()
    identity = RehearsalProviderIdentity(
        role=role,
        provider_id=provider_id,
        source="tencent" if source_type == "akshare" else source_type,
        version=(
            f"tushare-{installed_version}-cfg-{config_digest}"
            if source_type == "tushare"
            else f"tencent-quote-batch-v1-requests-{installed_version}-cfg-{config_digest}"
        ),
        endpoint_id=f"provider-config-{hashlib.sha256(endpoint_material).hexdigest()}",
    )
    return identity


def configured_akshare_financial_identity(*, provider_id: int) -> RehearsalProviderIdentity:
    """Bind the active provider row to the governed AKShare announcement-date route."""

    from .akshare_financial_slice_sync import akshare_financial_deployment_region
    from .financial_source_time_matchers import (
        AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        akshare_notice_date_match_contract,
    )
    from .models import ProviderConfigModel

    try:
        provider = ProviderConfigModel._default_manager.only(
            "id",
            "name",
            "source_type",
            "is_active",
            "priority",
            "api_endpoint",
        ).get(pk=provider_id)
    except ProviderConfigModel.DoesNotExist as exc:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH") from exc
    if not provider.is_active or str(provider.source_type or "").strip().lower() != "akshare":
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    contract = akshare_notice_date_match_contract()
    try:
        requests_version = importlib.metadata.version("requests")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE") from exc
    config_material = json.dumps(
        {
            "api_endpoint": str(provider.api_endpoint or "").strip().rstrip("/"),
            "is_active": provider.is_active,
            "name": provider.name,
            "priority": provider.priority,
            "provider_id": provider_id,
            "source_type": "akshare",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = hashlib.sha256(config_material).hexdigest()
    endpoint_material = json.dumps(
        {
            "contract_id": contract.contract_id,
            "contract_sha256": contract.contract_sha256,
            "contract_version": contract.contract_version,
            "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            "provider_config_sha256": config_digest,
            "provider_id": provider_id,
            "route": _AKSHARE_FINANCIAL_IDENTITY_SOURCE,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return RehearsalProviderIdentity(
        role=akshare_financial_route_role(provider_id),
        provider_id=provider_id,
        source=_AKSHARE_FINANCIAL_IDENTITY_SOURCE,
        version=(
            f"akshare-financial-v1-requests-{requests_version}-"
            f"contract-{contract.contract_sha256[:12]}"
        ),
        endpoint_id=f"akshare-financial-{hashlib.sha256(endpoint_material).hexdigest()}",
        deployment_region=akshare_financial_deployment_region(),
    )


def active_akshare_financial_provider_ids() -> tuple[int, ...]:
    """Return sorted active AKShare rows eligible for the explicit financial route."""

    from .models import ProviderConfigModel

    return tuple(
        int(provider_id)
        for provider_id in ProviderConfigModel._default_manager.filter(
            source_type="akshare",
            is_active=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def rehearsal_identity_matches_adapter_source(
    identity: RehearsalProviderIdentity,
    *,
    adapter_source: str,
) -> bool:
    """Match a configured adapter to the upstream source it actually exercises."""

    normalized = str(adapter_source or "").strip().lower()
    if identity.role == akshare_financial_route_role(identity.provider_id):
        return normalized == _AKSHARE_FINANCIAL_IDENTITY_SOURCE and identity.source == normalized
    return normalized == identity.source or (
        (
            identity.role == "valuation"
            or identity.role == model_market_route_role(identity.provider_id)
        )
        and normalized == "akshare"
        and identity.source == "tencent"
    )


def verify_configured_rehearsal_identities(
    identities: tuple[RehearsalProviderIdentity, ...],
) -> tuple[RehearsalProviderIdentity, ...]:
    """Fail closed unless supplied identities equal the live non-secret identities."""

    checked = parse_rehearsal_identities(rehearsal_identities_payload(identities))
    actual = tuple(
        configured_rehearsal_identity(provider_id=identity.provider_id, role=identity.role)
        for identity in checked
    )
    if actual != checked:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    return actual


def safe_rehearsal_identity_error_code(exc: Exception, *, default: str) -> str:
    """Expose only allowlisted identity codes from otherwise opaque exceptions."""

    value = str(exc)
    return value if value in IDENTITY_ERROR_CODES else default
