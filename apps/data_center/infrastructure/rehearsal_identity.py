"""Strict non-secret identity input shared by rehearsal capture and offline replay."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast


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
