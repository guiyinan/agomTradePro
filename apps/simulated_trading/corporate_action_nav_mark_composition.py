"""Compose purpose-specific current raw-price inputs for company-action simulation valuation."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.application.public_published_queries import get_published_price_bar_source
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkPolicyBinding,
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.corporate_action_configuration_composition import (
    read_corporate_action_configuration,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_nav_mark_reader import (
    PublishedPriceCorporateActionNavRawMarkReader,
)
from core.exceptions import AgomTradeProException

CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY = (
    "config_center.simulated_trading.corporate_action_nav_raw_mark_policy"
)


def _instant(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("raw mark policy clock must be explicit")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("raw mark policy clock must be aware")
    return result


class ConfiguredCorporateActionNavRawMarkPolicyReader:
    """Read a distinct explicit NAV-purpose policy; initial-position policy is never reused."""

    def __init__(self, *, environment: str) -> None:
        """Bind the server-selected Config Center environment without defaults."""
        self._environment = environment

    def read_policy(
        self, *, query: SimulatedCorporateActionNavRawMarkQuery, as_of: datetime
    ) -> SimulatedCorporateActionNavRawMarkPolicyBinding | None:
        """Return actual full profile/snapshot provenance or unavailable, without activation."""
        try:
            query.validate()
            evidence = read_corporate_action_configuration(
                definition_key=CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY,
                environment=self._environment,
                as_of=as_of,
            )
            if (
                evidence.environment != self._environment
                or evidence.definition_key != CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY
            ):
                return None
            raw: object = json.loads(evidence.value_json)
            if type(raw) is not dict or set(raw) != {
                "schema",
                "policy",
                "valid_from",
                "valid_until",
            }:
                return None
            fields = cast(dict[str, object], raw)
            if fields["schema"] != "simulated.corporate_action.nav_raw_mark_configuration.v1":
                return None
            policy = SimulatedCorporateActionNavRawMarkPolicy.from_payload(fields["policy"])
            if query.asset_type not in policy.supported_asset_types:
                return None
            binding = SimulatedCorporateActionNavRawMarkPolicyBinding(
                policy,
                self._environment,
                evidence.profile_id,
                evidence.profile_key,
                evidence.profile_version,
                evidence.profile_content_sha256,
                evidence.profile_activated_at,
                evidence.snapshot_id,
                evidence.snapshot_sha256,
                evidence.snapshot_generated_at,
                evidence.effective_at,
                evidence.known_at,
                _instant(fields["valid_from"]),
                _instant(fields["valid_until"]),
                evidence.checked_at,
            )
            binding.validate_for(as_of=evidence.checked_at)
            return binding
        except (AgomTradeProException, ArithmeticError, AttributeError, TypeError, ValueError):
            return None


class _ServerClock:
    """Supply real completion clocks independently of HTTP input."""

    def now(self) -> datetime:
        """Return Django's aware server clock."""
        return timezone.now()


def build_corporate_action_nav_raw_mark_reader(
    *, runtime_environment: str, calendar_dataset_key: str, using: str = DEFAULT_DB_ALIAS
) -> PublishedPriceCorporateActionNavRawMarkReader:
    """Wire exact retained publication, classification and formal calendar read-only ports."""
    if using != DEFAULT_DB_ALIAS:
        raise ValueError("raw mark public source reader requires the default source alias")
    return PublishedPriceCorporateActionNavRawMarkReader(
        policy_reader=ConfiguredCorporateActionNavRawMarkPolicyReader(
            environment=runtime_environment
        ),
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=runtime_environment
        ),
        calendar_reader=build_current_published_execution_calendar_reader(
            dataset_key=calendar_dataset_key,
            runtime_environment=runtime_environment,
            read_publication=read_current_exchange_calendar_reference,
        ),
        get_price_source=get_published_price_bar_source,
        clock=_ServerClock(),
    )
