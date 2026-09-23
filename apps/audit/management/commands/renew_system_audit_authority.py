"""Preview or atomically renew the production System Audit authority bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_capture,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.owner_tenant_authority_v3_composition import (
    OwnerTenantAuthorityV3Facade,
    build_owner_tenant_authority_v3_facade,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_renewal import (
    RenewSystemAuditAuthority,
    SystemAuditAuthorityRenewalUnavailable,
)
from apps.audit.infrastructure.system_audit_authority_renewal_request import (
    RenewalProfileInput,
    SystemAuditAuthorityRenewalInput,
    parse_system_audit_authority_renewal_request,
)
from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch_payload,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from core.exceptions import AgomTradeProException


class _OwnerFactory:
    """Build an owner successor facade from one fresh actor source."""

    def __init__(self, request: SystemAuditAuthorityRenewalInput) -> None:
        """Bind the server-owned principal, policy, and source alias."""

        self._request = request
        self._physical_rows = build_account_physical_row_v2_provider(using=request.database_alias)

    def build(
        self, actor: AccountOwnerAssignmentActorAuthoritySourceV3
    ) -> OwnerTenantAuthorityV3Facade:
        """Return an owner facade bound to the captured actor selector."""

        if type(actor) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise TypeError("captured actor selector is unavailable")
        return build_owner_tenant_authority_v3_facade(
            principal=self._request.principal,
            policy_binding=self._request.policy_binding,
            actor_source_id=actor.source_id,
            actor_source_version=actor.source_version,
            actor_source_content_hash=actor.content_hash,
            validity_period=self._request.authority_validity_period,
            physical_row_provider=self._physical_rows,
            using=self._request.database_alias,
        )


class Command(BaseCommand):
    """Run a dry-run-first, hash-bound System Audit authority renewal."""

    help = (
        "Preview or atomically renew the System Audit actor/scope authority "
        "and activate a required runtime successor."
    )
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the request path and explicit production write opt-in."""

        parser.add_argument("--input", required=True, type=str)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:
        """Validate one renewal envelope or perform its atomic write path."""

        del args
        input_path = options.get("input")
        execute = options.get("execute")
        if type(input_path) is not str or not input_path:
            raise CommandError("input must be an exact path string")
        if type(execute) is not bool:
            raise CommandError("execute must be an exact boolean")
        try:
            request = parse_system_audit_authority_renewal_request(Path(input_path).read_bytes())
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise CommandError("renewal request could not be validated") from error

        if not execute:
            self._write(
                {
                    "outcome": "noop",
                    "mode": "dry_run",
                    "authority_persisted": False,
                    "runtime_enabled": False,
                    "reason": "request_validated_only",
                    "database_alias": request.database_alias,
                    "actor_source_id": request.renewal.actor_capture.source_id,
                    "actor_source_version": request.renewal.actor_capture.source_version,
                    "owner_authority_id": request.renewal.owner_successor.authority_id,
                    "owner_authority_version": request.renewal.owner_successor.authority_version,
                    "profile_predecessor_bound": _profile_predecessor_is_complete(request.profile),
                }
            )
            return

        _require_execution_bindings(request)
        if request.database_alias != "default":
            raise CommandError("System Audit renewal currently requires the default database alias")
        try:
            actor_capture = build_account_actor_authority_capture(
                recorder_service_id=request.actor_recorder_service_id,
                validity_period=request.actor_validity_period,
                using=request.database_alias,
            )
            renewal = RenewSystemAuditAuthority(
                actor_capture=actor_capture,
                owner_factory=_OwnerFactory(request),
                clock=timezone.now,
            )
            with transaction.atomic(using=request.database_alias):
                renewed = renewal.execute(request.renewal)
                selector = _selector_payload(renewed.selector)
                profile = _activate_runtime_successor(request.profile, selector)
        except SystemAuditAuthorityRenewalUnavailable as error:
            self._write(
                {
                    "outcome": "blocked",
                    "mode": "execute",
                    "authority_persisted": False,
                    "runtime_enabled": False,
                    "blocked_reason": error.reason_code,
                }
            )
            return
        except (AgomTradeProException, DatabaseError, OSError, TypeError, ValueError) as error:
            del error
            self._write(
                {
                    "outcome": "blocked",
                    "mode": "execute",
                    "authority_persisted": False,
                    "runtime_enabled": False,
                    "blocked_reason": "renewal_transaction_rejected",
                }
            )
            return

        self._write(
            {
                "outcome": "success",
                "mode": "execute",
                "authority_persisted": True,
                "runtime_enabled": True,
                "actor_source_id": renewed.actor.source_id,
                "actor_source_version": renewed.actor.source_version,
                "actor_content_hash": renewed.actor.content_hash,
                "scope_source_id": renewed.scope.authority_id,
                "scope_source_version": renewed.scope.authority_version,
                "scope_content_hash": renewed.scope.content_hash,
                "authority_valid_until": renewed.valid_until.isoformat(),
                "selector": _selector_payload(renewed.selector),
                "profile": profile,
            }
        )

    def _write(self, payload: dict[str, object]) -> None:
        """Write one stable secret-free JSON result."""

        self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _require_execution_bindings(request: SystemAuditAuthorityRenewalInput) -> None:
    """Require all predecessor hashes before a production mutation."""

    profile = request.profile
    missing = [
        name
        for name, value in (
            ("expected_active_profile_id", profile.expected_active_profile_id),
            ("expected_active_profile_version", profile.expected_active_profile_version),
            ("expected_active_profile_hash", profile.expected_active_profile_hash),
            ("expected_active_snapshot_hash", profile.expected_active_snapshot_hash),
        )
        if value is None
    ]
    if missing:
        raise CommandError(
            "System Audit renewal execution requires approved profile predecessors: "
            + ", ".join(missing)
        )
    if profile.environment != "production":
        raise CommandError("System Audit renewal is restricted to the production environment")


def _profile_predecessor_is_complete(profile: RenewalProfileInput) -> bool:
    """Return whether the dry-run envelope carries all predecessor bindings."""

    return all(
        value is not None
        for value in (
            profile.expected_active_profile_id,
            profile.expected_active_profile_version,
            profile.expected_active_profile_hash,
            profile.expected_active_snapshot_hash,
        )
    )


def _selector_payload(selector: SystemAuditAuthorityBundleSelector) -> dict[str, str]:
    """Project a validated selector without exposing credentials."""

    return {
        "actor_source_id": selector.actor_source_id,
        "actor_source_version": selector.actor_source_version,
        "actor_content_hash": selector.actor_content_hash,
        "scope_source_id": selector.scope_source_id,
        "scope_source_version": selector.scope_source_version,
        "scope_content_hash": selector.scope_content_hash,
        "scope_schema": selector.scope_schema,
    }


def _activate_runtime_successor(
    profile: RenewalProfileInput,
    selector: dict[str, str],
) -> dict[str, object]:
    """Publish the selector and required audit mode as one profile successor."""

    return activate_runtime_profile_patch_payload(
        environment=profile.environment,
        patch={
            "audit.system_event.mode": "required",
            "audit.system_event.outbox_enabled": True,
            "audit.system_event.authority_selector": selector,
        },
        actor=profile.actor,
        reason=profile.reason,
        release_ref=profile.release_ref,
        expected_active_profile_id=profile.expected_active_profile_id,
        expected_active_profile_version=profile.expected_active_profile_version,
        expected_active_profile_hash=profile.expected_active_profile_hash,
        expected_active_snapshot_hash=profile.expected_active_snapshot_hash,
    )


__all__ = ["Command"]
