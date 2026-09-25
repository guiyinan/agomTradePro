"""Strict non-secret identity input shared by rehearsal capture and offline replay."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

IDENTITY_ERROR_CODES = frozenset(
    {
        "REHEARSAL_PROVIDER_IDENTITY_MISMATCH",
        "REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE",
    }
)


@dataclass(frozen=True)
class RehearsalProviderIdentity:
    """Frozen association context; version does not claim an upstream version probe."""

    role: str
    provider_id: int
    source: str
    version: str
    endpoint_id: str


def parse_rehearsal_identities(value: object) -> tuple[RehearsalProviderIdentity, ...]:
    """Accept exactly the two bounded public identities, with no secret extras."""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    identities: list[RehearsalProviderIdentity] = []
    keys = {"role", "provider_id", "source", "version", "endpoint_id"}
    for item in cast(list[object], value):
        if not isinstance(item, dict) or set(item) != keys:
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
        identities.append(RehearsalProviderIdentity(provider_id=provider_id, **strings))
    if {identity.role for identity in identities} != {"quote", "valuation"}:
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_INVALID")
    # Preserve frozen input order: the release validator hashes this same ordered list.
    return tuple(identities)


def load_rehearsal_identities(path: Path) -> tuple[RehearsalProviderIdentity, ...]:
    """Read a bounded public snapshot, never a provider configuration or credential file."""
    with path.open("rb") as stream:
        data = stream.read(16_385)
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
        [asdict(identity) for identity in identities], sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def configured_rehearsal_identity(*, provider_id: int, role: str) -> RehearsalProviderIdentity:
    """Derive one non-secret identity from active config and installed provider code."""

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
    if not provider.is_active or provider.source_type != "tushare":
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    extra = provider.extra_config if isinstance(provider.extra_config, Mapping) else {}
    request_mode = str(extra.get("tushare_request_mode") or "sdk_path").strip()
    endpoint = str(provider.http_url or "").strip().rstrip("/") or "tushare-sdk-default"
    api_endpoint = str(provider.api_endpoint or "").strip().rstrip("/")
    endpoint_material = json.dumps(
        {
            "provider_id": provider_id,
            "request_mode": request_mode,
            "source": provider.source_type,
            "transport_endpoint": endpoint,
            "api_endpoint": api_endpoint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    try:
        installed_version = importlib.metadata.version("tushare")
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
            "source_type": provider.source_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = hashlib.sha256(config_material).hexdigest()
    identity = RehearsalProviderIdentity(
        role=role,
        provider_id=provider_id,
        source=provider.source_type,
        version=f"tushare-{installed_version}-cfg-{config_digest}",
        endpoint_id=f"provider-config-{hashlib.sha256(endpoint_material).hexdigest()}",
    )
    companion = RehearsalProviderIdentity(
        role="valuation" if role == "quote" else "quote",
        provider_id=provider_id,
        source=identity.source,
        version=identity.version,
        endpoint_id=identity.endpoint_id,
    )
    return parse_rehearsal_identities([asdict(identity), asdict(companion)])[0]


def verify_configured_rehearsal_identities(
    identities: tuple[RehearsalProviderIdentity, ...],
) -> tuple[RehearsalProviderIdentity, ...]:
    """Fail closed unless supplied identities equal the live non-secret identities."""

    checked = parse_rehearsal_identities([asdict(identity) for identity in identities])
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
