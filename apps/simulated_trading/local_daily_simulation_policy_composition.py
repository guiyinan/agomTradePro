"""Read a configured daily-simulation policy with its actual runtime provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from django.db import DatabaseError

from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
    LocalDailySimulationPolicyRuntimeProvenance,
)
from core.exceptions import AgomTradeProException
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

LOCAL_DAILY_SIMULATION_POLICY_KEY = "config_center.market.simulated_local_daily_simulation_policy"


class ConfiguredLocalDailySimulationPolicyReader:
    """Read a stable active policy and preserve its verified profile provenance."""

    def __init__(self, *, runtime_environment: str) -> None:
        """Require an explicit runtime environment without reading configuration."""

        if (
            type(runtime_environment) is not str
            or not runtime_environment
            or any(character.isspace() for character in runtime_environment)
        ):
            raise ValueError("daily simulation runtime environment must be an explicit token")
        self._environment = runtime_environment

    def read_policy(self, *, as_of: datetime) -> LocalDailySimulationPolicyBinding | None:
        """Return one stable active binding at the caller's cutoff or fail closed."""

        try:
            if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
                return None
            profile = get_active_runtime_profile(self._environment)
            if not isinstance(profile, RuntimeConfigProfileRead):
                return None
            snapshot = get_latest_runtime_snapshot(profile.profile_key)
            if not isinstance(snapshot, RuntimeConfigSnapshotRead):
                return None
            profile.__post_init__()
            snapshot.__post_init__()
            if (
                profile.environment != self._environment
                or profile.status != "active"
                or profile.activated_at is None
                or snapshot.effective_from is None
                or snapshot.effective_from != profile.activated_at
                or (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
                != (profile.profile_id, profile.profile_key, profile.version)
                or not profile.created_at <= profile.activated_at <= snapshot.generated_at <= as_of
            ):
                return None
            value = get_active_runtime_value(
                environment=self._environment,
                definition_key=LOCAL_DAILY_SIMULATION_POLICY_KEY,
                as_of=as_of,
            )
            if (
                value is None
                or snapshot.resolved_values.get(LOCAL_DAILY_SIMULATION_POLICY_KEY) != value
            ):
                return None
            projection = json.dumps(
                dict(snapshot.resolved_values),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if hashlib.sha256(projection).hexdigest() != snapshot.snapshot_hash:
                return None
            if (
                get_active_runtime_profile(self._environment) != profile
                or get_latest_runtime_snapshot(profile.profile_key) != snapshot
            ):
                return None
            policy = LocalDailySimulationPolicy.from_payload(value)
            provenance = LocalDailySimulationPolicyRuntimeProvenance(
                runtime_environment=self._environment,
                profile_id=profile.profile_id,
                profile_key=profile.profile_key,
                profile_version=profile.version,
                profile_content_hash=profile.content_hash,
                profile_activated_at=profile.activated_at,
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.snapshot_hash,
                snapshot_generated_at=snapshot.generated_at,
                snapshot_effective_from=snapshot.effective_from,
                read_at=as_of,
            )
            return LocalDailySimulationPolicyBinding(policy=policy, provenance=provenance)
        except (
            AgomTradeProException,
            DatabaseError,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None


__all__ = ("ConfiguredLocalDailySimulationPolicyReader",)
