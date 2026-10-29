"""Compose an explicitly configured independent mark without enabling trading."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from django.db import DatabaseError

from apps.data_center.application.public_published_queries import get_published_price_bar_source
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
)
from apps.simulated_trading.application.initial_position_mark import InitialPositionMarkReader
from apps.simulated_trading.domain.initial_position_mark_policy import (
    InitialPositionMarkPolicy,
    InitialPositionMarkPolicyBinding,
    InitialPositionMarkRuntimeProvenance,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.published_price_initial_position_mark_reader import (
    PublishedPriceInitialPositionMarkReader,
)
from core.exceptions import AgomTradeProException
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

INITIAL_POSITION_MARK_POLICY_KEY = "config_center.market.simulated_initial_position_mark_policy"


class ConfiguredInitialPositionMarkPolicyReader:
    """Read one active policy and retain the actual runtime version and clocks."""

    def __init__(self, *, runtime_environment: str) -> None:
        """Require an explicit environment without accessing configuration."""
        if (
            type(runtime_environment) is not str
            or not runtime_environment
            or any(character.isspace() for character in runtime_environment)
        ):
            raise ValueError("mark runtime environment must be an explicit token")
        self._environment = runtime_environment

    def read_policy(self, *, as_of: datetime) -> InitialPositionMarkPolicyBinding | None:
        """Return a stable active version or no mark policy; never reconstruct history."""
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
            # This owner call validates persisted values against both the active
            # profile hash and its immutable public snapshot at the same cutoff.
            value = get_active_runtime_value(
                environment=self._environment,
                definition_key=INITIAL_POSITION_MARK_POLICY_KEY,
                as_of=as_of,
            )
            if (
                value is None
                or snapshot.resolved_values.get(INITIAL_POSITION_MARK_POLICY_KEY) != value
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
            policy = InitialPositionMarkPolicy.from_payload(value)
            provenance = InitialPositionMarkRuntimeProvenance(
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
            return InitialPositionMarkPolicyBinding(policy=policy, provenance=provenance)
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


def build_published_initial_position_mark_reader(
    *,
    runtime_environment: str,
    calendar_dataset_key: str,
) -> InitialPositionMarkReader:
    """Build an opt-in reader without configuration writes or default ledger binding."""
    return build_initial_position_mark_with_calendar(
        runtime_environment=runtime_environment,
        calendar_reader=build_current_published_execution_calendar_reader(
            dataset_key=calendar_dataset_key,
            runtime_environment=runtime_environment,
            read_publication=read_current_exchange_calendar_reference,
        ),
    )


def build_initial_position_mark_with_calendar(
    *,
    runtime_environment: str,
    calendar_reader: PublishedExecutionCalendarReader,
) -> InitialPositionMarkReader:
    """Bind independent marks to the caller's already composed calendar reader."""
    return PublishedPriceInitialPositionMarkReader(
        policy_reader=ConfiguredInitialPositionMarkPolicyReader(
            runtime_environment=runtime_environment,
        ),
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=runtime_environment,
        ),
        calendar_reader=calendar_reader,
        get_price_source=get_published_price_bar_source,
    )
