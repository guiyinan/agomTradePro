"""Compose ownership replay with versioned Config Center timezone evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
    QualifiedExchangeTimezone,
)
from core.integration.config_center_runtime import (
    ActiveRuntimeValueEvidence,
    get_active_runtime_value_evidence,
)

_TIMEZONE_MAP_DEFINITION = "config_center.market.exchange_timezone_map"


def _blocked(message: str) -> SimulatedTradeExecutionBlocked:
    """Return the stable blocked result for unavailable timezone provenance."""

    return SimulatedTradeExecutionBlocked(
        message,
        code="CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
    )


def _utc_text(value: datetime) -> str:
    """Return a canonical UTC timestamp for policy evidence hashing."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256_payload(payload: dict[str, object]) -> str:
    """Hash one stable JSON policy payload."""

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class _RuntimeExchangeTimezonePolicyReader:
    """Read one explicit exchange timezone from active immutable runtime evidence."""

    runtime_environment: str

    def __post_init__(self) -> None:
        """Require a literal nonempty runtime environment name."""

        if type(self.runtime_environment) is not str or not self.runtime_environment.strip():
            raise _blocked("runtime environment for exchange timezone policy is invalid")

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Return exchange-local timezone and its exact profile/snapshot provenance."""

        if (
            type(exchange) is not str
            or not exchange
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise _blocked("exchange timezone policy query is invalid")
        try:
            evidence = get_active_runtime_value_evidence(
                environment=self.runtime_environment,
                definition_key=_TIMEZONE_MAP_DEFINITION,
                as_of=as_of,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            raise _blocked("versioned exchange timezone evidence is unavailable") from error
        if type(evidence) is not ActiveRuntimeValueEvidence:
            raise _blocked("versioned exchange timezone evidence is unavailable")
        if (
            evidence.environment != self.runtime_environment
            or evidence.definition_key != _TIMEZONE_MAP_DEFINITION
            or evidence.as_of != as_of
            or type(evidence.profile_version) is not int
            or evidence.profile_version <= 0
            or type(evidence.value) is not dict
        ):
            raise _blocked("exchange timezone evidence is not bound to the requested cutoff")
        clocks = (
            evidence.created_at,
            evidence.known_at,
            evidence.activated_at,
            evidence.snapshot_generated_at,
            evidence.effective_at,
        )
        if any(
            type(value) is not datetime
            or value.tzinfo is None
            or value.utcoffset() is None
            or value > as_of
            for value in clocks
        ):
            raise _blocked("exchange timezone profile or snapshot was not known at the cutoff")
        value_map = cast(dict[object, object], evidence.value)
        if any(type(key) is not str or type(value) is not str for key, value in value_map.items()):
            raise _blocked("exchange timezone map must contain only exact string pairs")
        timezone_name = value_map.get(exchange)
        if type(timezone_name) is not str or not timezone_name:
            raise _blocked("no exchange timezone is configured for the target instrument")
        for name in (
            evidence.profile_id,
            evidence.profile_key,
            evidence.profile_content_hash,
            evidence.snapshot_id,
            evidence.snapshot_hash,
        ):
            if type(name) is not str or not name:
                raise _blocked("timezone policy provenance identity is incomplete")
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in (evidence.profile_content_hash, evidence.snapshot_hash)
        ):
            raise _blocked("timezone policy profile or snapshot digest is malformed")
        policy_id = (
            f"{evidence.definition_key}:{evidence.profile_id}:"
            f"v{evidence.profile_version}:{evidence.snapshot_id}"
        )
        policy_sha256 = _sha256_payload(
            {
                "definition_key": evidence.definition_key,
                "environment": evidence.environment,
                "exchange": exchange,
                "timezone_name": timezone_name,
                "profile_id": evidence.profile_id,
                "profile_key": evidence.profile_key,
                "profile_version": evidence.profile_version,
                "profile_content_hash": evidence.profile_content_hash,
                "snapshot_id": evidence.snapshot_id,
                "snapshot_hash": evidence.snapshot_hash,
                "created_at": _utc_text(evidence.created_at),
                "known_at": _utc_text(evidence.known_at),
                "activated_at": _utc_text(evidence.activated_at),
                "snapshot_generated_at": _utc_text(evidence.snapshot_generated_at),
                "effective_at": _utc_text(evidence.effective_at),
            }
        )
        return QualifiedExchangeTimezone(
            exchange=exchange,
            timezone_name=timezone_name,
            policy_id=policy_id,
            policy_sha256=policy_sha256,
        )


def build_corporate_action_ownership_history_repository(
    *,
    runtime_environment: str,
    using: str = "default",
) -> DjangoCorporateActionOwnershipHistoryRepository:
    """Build the read-only ownership verifier for an explicit runtime environment."""

    return DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_RuntimeExchangeTimezonePolicyReader(
            runtime_environment=runtime_environment,
        ),
        using=using,
    )


__all__: tuple[str, ...] = ("build_corporate_action_ownership_history_repository",)
