"""Authorize one exact financial scope discovery in a disposable S6 database."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from argparse import ArgumentParser
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.financial_scope_s6_authorization import (
    S6_PERSONAL_SYSTEM_RECORDER,
    build_s6_personal_system_authorization_record,
)
from apps.data_center.composition import preflight_financial_capacity_isolation
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryError,
    universe_sha256,
)
from apps.data_center.financial_scope_discovery_composition import (
    TargetDateFinancialScopeDiscoveryUniverseSource,
    build_financial_scope_discovery_binding,
)
from apps.data_center.infrastructure.akshare_financial_slice_rehearsal import (
    verify_configured_rehearsal_identities,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeDiscoveryAuthorizationSource,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
    ProviderConfigModel,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    akshare_financial_route_role,
    load_rehearsal_identities,
    rehearsal_identities_digest,
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PASSWORD_BYTES = 1024
_AUTHORIZATION_LIFETIME = timedelta(hours=24)


class _AuthenticatedOwner(Protocol):
    """Narrow the dynamic Django user returned by the authentication backend."""

    is_active: bool
    is_superuser: bool

    def get_username(self) -> str:
        """Return the canonical username."""


class Command(BaseCommand):
    """Authenticate the owner and append an isolated, candidate-bound authorization."""

    help = "Authorize exact S6 financial scope discovery before any provider egress."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require exact frozen identities and a password delivered only on stdin."""

        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True)
        parser.add_argument("--release-universe-sha256", required=True)
        parser.add_argument("--provider-identities", required=True, type=Path)
        parser.add_argument("--provider-identities-sha256", required=True)
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--expected-database-host", required=True)
        parser.add_argument("--owner", required=True)
        credential_mode = parser.add_mutually_exclusive_group(required=True)
        credential_mode.add_argument("--password-stdin", action="store_true")
        credential_mode.add_argument("--verify-existing", action="store_true")
        parser.add_argument("--output", required=True, type=Path)

    def handle(
        self,
        *args: object,
        candidate_sha: str,
        target_trade_date: str,
        release_universe_sha256: str,
        provider_identities: Path,
        provider_identities_sha256: str,
        expected_database_name: str,
        expected_database_host: str,
        owner: str,
        password_stdin: bool,
        verify_existing: bool,
        output: Path,
        **options: object,
    ) -> str | None:
        """Persist and re-read one owner event in the exact disposable database."""

        started_at = timezone.now().astimezone(UTC)
        try:
            if password_stdin is verify_existing:
                raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID")
            _validate_static_inputs(
                candidate_sha=candidate_sha,
                release_universe_sha256=release_universe_sha256,
                provider_identities_sha256=provider_identities_sha256,
                expected_database_name=expected_database_name,
                expected_database_host=expected_database_host,
                owner=owner,
                output=output,
            )
            parsed_target_trade_date = _parse_target_trade_date(target_trade_date)
            source_commit = FileFinancialCapacityBuildIdentitySource(
                Path(settings.AGOM_BUILD_IDENTITY_PATH)
            ).source_commit()
            if source_commit != candidate_sha:
                raise _AuthorizationFailure(
                    "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_BINDING_INVALID"
                )
            identities = load_rehearsal_identities(provider_identities)
            if rehearsal_identities_digest(identities) != provider_identities_sha256:
                raise _AuthorizationFailure(
                    "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_BINDING_INVALID"
                )
            verified = verify_configured_rehearsal_identities(identities)
            financial_identities = tuple(
                item
                for item in verified
                if item.source == "akshare_financial"
                and item.role == akshare_financial_route_role(item.provider_id)
            )
            if len(financial_identities) != 1:
                raise _AuthorizationFailure(
                    "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_BINDING_INVALID"
                )
            provider_identity = financial_identities[0]
            provider_row = ProviderConfigModel._default_manager.get(
                pk=provider_identity.provider_id,
                source_type="akshare",
                is_active=True,
            )
            binding = build_financial_scope_discovery_binding(
                provider=provider_row.to_domain(),
                candidate_sha=candidate_sha,
            )
            asset_codes = TargetDateFinancialScopeDiscoveryUniverseSource(
                parsed_target_trade_date
            ).get_active_asset_codes()
            if universe_sha256(asset_codes) != release_universe_sha256:
                raise _AuthorizationFailure(
                    "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_BINDING_INVALID"
                )
            isolation_sha256 = preflight_financial_capacity_isolation(
                candidate_sha=candidate_sha,
                expected_database_name=expected_database_name,
                expected_database_host=expected_database_host,
            )
            observed_at = timezone.now().astimezone(UTC)
            if verify_existing:
                authorization = DjangoFinancialScopeDiscoveryAuthorizationSource().get(
                    binding=binding,
                    asset_codes=asset_codes,
                    now=observed_at,
                )
                if authorization is None or authorization.approved_by != owner:
                    raise _AuthorizationFailure(
                        "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_READBACK_FAILED"
                    )
                record = FinancialCapacityGovernanceRecordModel._default_manager.get(
                    approval_id=authorization.approval_id,
                    stage=FinancialCapacityGovernanceRecordModel.SCOPE_DISCOVERY,
                    revocation__isnull=True,
                )
                record_sha256 = _canonical_sha256(record.record)
            else:
                password = _read_password_from_stdin()
                owner_user = _authenticate_owner(owner=owner, password=password)
                del password
                authorization, payload = build_s6_personal_system_authorization_record(
                    binding=binding,
                    asset_codes=asset_codes,
                    approved_by=owner_user.get_username(),
                    approval_id=f"s6-scope-discovery:{uuid4()}",
                    event_id=f"s6-scope-discovery-owner:{uuid4()}",
                    approved_at=observed_at,
                    expires_at=observed_at + _AUTHORIZATION_LIFETIME,
                )
                record_sha256 = _canonical_sha256(payload)
                with transaction.atomic():
                    if FinancialCapacityGovernanceRecordModel._default_manager.filter(
                        stage=FinancialCapacityGovernanceRecordModel.SCOPE_DISCOVERY,
                        revocation__isnull=True,
                    ).exists():
                        raise _AuthorizationFailure(
                            "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_ALREADY_EXISTS"
                        )
                    record = FinancialCapacityGovernanceRecordModel._default_manager.create(
                        approval_id=authorization.approval_id,
                        stage=FinancialCapacityGovernanceRecordModel.SCOPE_DISCOVERY,
                        record=payload,
                        created_by=S6_PERSONAL_SYSTEM_RECORDER,
                    )
                    FinancialCapacityOwnerApprovalEventModel._default_manager.create(
                        governance_record=record,
                        event_id=authorization.event_id,
                        approved_by=authorization.approved_by,
                        approved_at=authorization.approved_at,
                        approval_receipt_sha256=authorization.receipt_sha256,
                        record_sha256=record_sha256,
                    )
                    observed = DjangoFinancialScopeDiscoveryAuthorizationSource().get(
                        binding=binding,
                        asset_codes=asset_codes,
                        now=observed_at,
                    )
                    if observed != authorization:
                        raise _AuthorizationFailure(
                            "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_READBACK_FAILED"
                        )
            finished_at = timezone.now().astimezone(UTC)
            report: dict[str, object] = {
                "schema": "release.financial-scope-authorization.v1",
                "kind": "financial_scope_authorization",
                "outcome": "success",
                "evidence_mode": "isolated_personal_system_owner_authorization",
                "candidate_sha": candidate_sha,
                "candidate_image_id": _candidate_image_id(),
                "candidate_source_attestation": "image_release_manifest",
                "target_trade_date": target_trade_date,
                "universe_sha256": release_universe_sha256,
                "provider_identities_sha256": provider_identities_sha256,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "database": {
                    "vendor": "postgresql",
                    "scope": "disposable",
                    "release_rehearsal_guard": True,
                    "name": expected_database_name,
                    "host": expected_database_host,
                    "isolation_attestation_sha256": isolation_sha256,
                },
                "authorization": {
                    "mode": "personal_system_owner",
                    "approval_id": authorization.approval_id,
                    "owner_event_id": authorization.event_id,
                    "approved_by": authorization.approved_by,
                    "recorded_by": authorization.recorded_by,
                    "approval_receipt_sha256": authorization.receipt_sha256,
                    "record_sha256": record_sha256,
                    "approved_at": authorization.approved_at.isoformat(),
                    "expires_at": authorization.expires_at.isoformat(),
                },
                "binding": {
                    "provider_id": binding.provider_id,
                    "provider_name": binding.provider_name,
                    "provider_identity_sha256": binding.provider_identity_sha256,
                    "contract_id": binding.contract_id,
                    "contract_version": binding.contract_version,
                    "contract_sha256": binding.contract_sha256,
                    "parser_id": binding.parser_id,
                    "parser_sha256": binding.parser_sha256,
                    "deployment_region": binding.deployment_region,
                },
                "universe": {
                    "asset_count": len(asset_codes),
                    "sha256": authorization.universe_sha256,
                },
                "budget": {
                    "maximum_logical_requests": authorization.maximum_logical_requests,
                    "maximum_physical_attempts": authorization.maximum_physical_attempts,
                    "maximum_rows_per_asset": authorization.maximum_rows_per_asset,
                },
                "provider_request_count": 0,
                "fact_writes": 0,
                "publication_writes": 0,
                "production_writes": 0,
                "production_manifest_review_satisfied": False,
            }
            _write_exclusive_report(output, report)
        except _AuthorizationFailure as exc:
            raise CommandError(exc.code) from None
        except (
            DatabaseError,
            FinancialCapacityGovernanceRecordModel.DoesNotExist,
            FinancialCapacityGovernanceRecordModel.MultipleObjectsReturned,
            IntegrityError,
            FinancialScopeDiscoveryError,
            ProviderConfigModel.DoesNotExist,
            OSError,
            UnicodeError,
            ValueError,
        ):
            raise CommandError("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_FAILED") from None
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return None


class _AuthorizationFailure(RuntimeError):
    """Carry one allowlisted, secret-free authorization failure code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_target_trade_date(value: str) -> date:
    """Parse one canonical ISO target date before reading owner credentials."""

    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _AuthorizationFailure(
            "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID"
        ) from None
    if parsed.isoformat() != value:
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID")
    return parsed


def _validate_static_inputs(
    *,
    candidate_sha: str,
    release_universe_sha256: str,
    provider_identities_sha256: str,
    expected_database_name: str,
    expected_database_host: str,
    owner: str,
    output: Path,
) -> None:
    """Reject malformed or non-disposable inputs before reading a credential."""

    if (
        _COMMIT.fullmatch(candidate_sha) is None
        or _SHA256.fullmatch(release_universe_sha256) is None
        or _SHA256.fullmatch(provider_identities_sha256) is None
        or not expected_database_name.startswith("agom_release_rehearsal_")
        or not expected_database_host.startswith("agom-s6-postgres-")
        or not owner
        or owner != owner.strip()
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
        or output.parent.is_symlink()
    ):
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID")


def _read_password_from_stdin() -> str:
    """Read one bounded UTF-8 password line without logging or persisting it."""

    raw = sys.stdin.buffer.readline(_MAX_PASSWORD_BYTES + 2)
    trailing = sys.stdin.buffer.read(1)
    if (
        not raw
        or len(raw) > _MAX_PASSWORD_BYTES + 1
        or trailing
        or b"\x00" in raw
        or not raw.endswith(b"\n")
    ):
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID")
    try:
        password = raw[:-1].decode("utf-8")
    except UnicodeError:
        raise _AuthorizationFailure(
            "REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID"
        ) from None
    if not password or "\r" in password or "\n" in password:
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID")
    return password


def _authenticate_owner(*, owner: str, password: str) -> _AuthenticatedOwner:
    """Authenticate the exact active Django superuser owner."""

    user_model = get_user_model()
    owner_user = cast(
        _AuthenticatedOwner | None,
        authenticate(
            request=None,
            **{user_model.USERNAME_FIELD: owner, "password": password},
        ),
    )
    if (
        owner_user is None
        or owner_user.is_active is not True
        or owner_user.is_superuser is not True
        or owner_user.get_username() != owner
    ):
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_AUTHENTICATION_FAILED")
    return owner_user


def _candidate_image_id() -> str:
    """Return the exact candidate image identity supplied by the S6 launcher."""

    value = os.environ.get("AGOM_CANDIDATE_IMAGE_ID", "")
    if _IMAGE_ID.fullmatch(value) is None:
        raise _AuthorizationFailure("REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_BINDING_INVALID")
    return value


def _canonical_sha256(value: object) -> str:
    """Hash the canonical JSON record stored beside the owner event."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_exclusive_report(path: Path, payload: dict[str, object]) -> None:
    """Write the secret-free authorization report exactly once."""

    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


__all__ = ["Command"]
