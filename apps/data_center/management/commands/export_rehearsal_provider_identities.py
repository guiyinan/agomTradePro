"""Export all provider identities used by one frozen S6 policy snapshot."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.full_market_publication_preflight import (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
)
from apps.data_center.full_market_publication_preflight_composition import (
    build_full_market_publication_preflight_use_case,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    configured_rehearsal_identity,
    model_market_route_role,
    parse_rehearsal_identities,
    rehearsal_identities_digest,
    rehearsal_identity_matches_adapter_source,
)


def build_rehearsal_provider_identity_snapshot(
    *,
    quote_provider_id: int,
    valuation_provider_id: int,
    provider_settings: dict[str, object],
) -> tuple[RehearsalProviderIdentity, ...]:
    """Freeze core providers and every route resolved by the exact policy snapshot."""

    core = (
        configured_rehearsal_identity(provider_id=quote_provider_id, role="quote"),
        configured_rehearsal_identity(provider_id=valuation_provider_id, role="valuation"),
    )
    report = build_full_market_publication_preflight_use_case(
        provider_settings_override=provider_settings,
    ).execute(checks=(CHECK_PROVIDER_POLICY_AND_ROUTES,))
    check = report.checks[0]
    if check.name != CHECK_PROVIDER_POLICY_AND_ROUTES or check.status != "pass":
        raise ValueError("REHEARSAL_PROVIDER_ROUTES_UNAVAILABLE")
    capabilities = check.evidence.get("route_capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("REHEARSAL_PROVIDER_ROUTES_UNAVAILABLE")

    routes: dict[int, RehearsalProviderIdentity] = {}
    for raw_capability in cast(list[object], capabilities):
        if not isinstance(raw_capability, dict):
            raise ValueError("REHEARSAL_PROVIDER_ROUTES_UNAVAILABLE")
        capability = cast(dict[str, object], raw_capability)
        provider_id = capability.get("provider_id")
        source_type = capability.get("source_type")
        if (
            isinstance(provider_id, bool)
            or not isinstance(provider_id, int)
            or provider_id <= 0
            or not isinstance(source_type, str)
            or not source_type
        ):
            raise ValueError("REHEARSAL_PROVIDER_ROUTES_UNAVAILABLE")
        if any(
            identity.provider_id == provider_id
            and rehearsal_identity_matches_adapter_source(
                identity,
                adapter_source=source_type,
            )
            for identity in core
        ):
            continue
        route_identity = configured_rehearsal_identity(
            provider_id=provider_id,
            role=model_market_route_role(provider_id),
        )
        if not rehearsal_identity_matches_adapter_source(
            route_identity,
            adapter_source=source_type,
        ):
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
        previous = routes.get(provider_id)
        if previous is not None and previous != route_identity:
            raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
        routes[provider_id] = route_identity
    return parse_rehearsal_identities(
        [asdict(identity) for identity in (*core, *(routes[key] for key in sorted(routes)))]
    )


class Command(BaseCommand):
    """Export bounded, non-secret identities for core and policy route providers."""

    help = (
        "Export quote, valuation and all model-market route provider identities "
        "for an exact provider settings snapshot; strictly read-only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register exact core providers, policy snapshot and output path."""

        parser.add_argument("--quote-provider-id", type=int, required=True)
        parser.add_argument("--valuation-provider-id", type=int, required=True)
        parser.add_argument("--provider-settings-json", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)

    def handle(self, *args: object, **options: Any) -> None:
        """Write the canonical public identity array and report its digest."""

        del args
        settings_path = Path(options["provider_settings_json"])
        try:
            raw = settings_path.read_bytes()
            if len(raw) > 65_536:
                raise ValueError("provider settings snapshot is too large")
            decoded: object = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("provider settings snapshot must be an object")
            settings = cast(dict[str, object], decoded)
            identities = build_rehearsal_provider_identity_snapshot(
                quote_provider_id=options["quote_provider_id"],
                valuation_provider_id=options["valuation_provider_id"],
                provider_settings=settings,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            code = str(exc)
            if not code.startswith("REHEARSAL_"):
                code = "REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE"
            raise CommandError(code) from None

        payload = [asdict(identity) for identity in identities]
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        output = options.get("output")
        if output is None:
            self.stdout.write(encoded.decode())
        else:
            path = Path(output)
            if path.is_symlink() or path.exists():
                raise CommandError(f"identity output already exists: {path}")
            path.write_bytes(encoded)
        self.stderr.write(
            json.dumps(
                {
                    "outcome": "exported",
                    "provider_count": len(identities),
                    "provider_identities_sha256": rehearsal_identities_digest(identities),
                    **({"output": str(output)} if output is not None else {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
