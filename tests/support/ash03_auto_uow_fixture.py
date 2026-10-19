"""Test support for composing real current-reference sources with the ledger UoW.

This helper consumes already persisted synthetic source fixtures. It does not
call an external provider, alter source clocks, or qualify production data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_at,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotRecord,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SimulatedTradeSide,
)
from apps.simulated_trading.execution_current_reference_composition import (
    CurrentReferenceIdentityReader,
    build_current_reference_identity_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
    build_execute_settlement_bound_simulated_trade_use_case,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from tests.support.ash03_auto_calendar_fixture import _runtime_public_write_clock

_CURRENT_REFERENCE_SELECTION_KEY = "config_center.market.simulated_current_reference_selection"
_EXCHANGE_TIMEZONE_MAP_KEY = "config_center.market.exchange_timezone_map"


class _FixedClock(SimulatedTradeExecutionClock):
    """Return one exact aware UTC cutoff to the settlement use case and UoW."""

    def __init__(self, value: datetime) -> None:
        """Bind a validated test cutoff without consulting the wall clock later."""

        self._value = value

    def now(self) -> datetime:
        """Return the fixture cutoff unchanged for reads and locked ledger work."""

        return self._value


@dataclass(frozen=True, slots=True)
class AutoCurrentReferenceUowFixture:
    """Expose real source readers and the real UoW for an Auto caller test."""

    as_of: datetime
    security_id: str
    asset_code: str
    source_code: str
    source_exchange: str
    rule_market: str
    board: str
    identity_reader: CurrentReferenceIdentityReader
    calendar_reader: PublishedExecutionCalendarReader
    calendar_evidence: ExecutionCalendarEvidence
    market_session: date
    rule_bundle: ExecutionSettlementBundleV3
    buy_fee_policy: SimulatedFeePolicyV2
    sell_fee_policy: SimulatedFeePolicyV2
    execution_use_case: ExecuteSettlementBoundSimulatedTradeUseCase

    def read_identity_evidence(self) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Read the exact persisted selector, mapping, and source at this cutoff."""

        return self.identity_reader.get_execution_instrument_identity(
            security_id=self.security_id,
            asset_code=self.asset_code,
            as_of=self.as_of,
        )


def build_auto_current_reference_uow_fixture(
    *,
    source_snapshot: InstrumentReferenceSnapshotRecord,
    account_id: int,
    user_id: int,
    security_id: str,
    asset_code: str,
    source_code: str,
    runtime_environment: str,
    exchange_timezone: str,
    as_of: datetime,
    local_reference_age_seconds: int = 600,
    include_selector_item: bool = True,
    actor: str = "auto-uow-component-test",
) -> AutoCurrentReferenceUowFixture:
    """Compose actual ConfigCenter, Data Center, Risk, calendar, Fee V2, and UoW readers.

    The caller must persist the instrument source/mapping, active calendar capture
    metadata and publication, effective Risk V3 bundle, and exact BUY/SELL Fee V2
    cases before calling this helper. ``as_of`` is explicit and must be at or after
    every source, profile, and runtime-snapshot knowledge timestamp.
    """

    if type(source_snapshot) is not InstrumentReferenceSnapshotRecord:
        raise TypeError("source_snapshot must be the exact persisted snapshot record")
    source_snapshot.__post_init__()
    for field_name, value in (
        ("account_id", account_id),
        ("user_id", user_id),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
    for field_name, value in (
        ("security_id", security_id),
        ("asset_code", asset_code),
        ("source_code", source_code),
        ("runtime_environment", runtime_environment),
        ("exchange_timezone", exchange_timezone),
        ("actor", actor),
    ):
        if type(value) is not str or not value or value.strip() != value:
            raise ValueError(f"{field_name} must be an exact nonempty token")
    if type(local_reference_age_seconds) is not int or local_reference_age_seconds <= 0:
        raise ValueError("local_reference_age_seconds must be a positive integer")
    if type(as_of) is not datetime or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be an exact aware UTC datetime")

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    expected_environment = (
        "production" if settings_module.endswith(".production") else "development"
    )
    if runtime_environment != expected_environment:
        raise ValueError("runtime_environment must match the active Django settings module")

    classification = source_snapshot.content.classify_security(source_code)
    if (
        classification is None
        or classification.blocked_reason is not None
        or classification.source_market is None
        or classification.rule_market is None
        or classification.board is None
    ):
        raise ValueError("source fixture must contain one explicitly mapped security")
    if not any(
        record.ts_code == source_code
        for fetch_round in source_snapshot.content.fetch_rounds
        for record in fetch_round.candidate.records
    ):
        raise ValueError("source_code is not present in the persisted snapshot")

    item: dict[str, object] = {
        "security_id": security_id,
        "asset_code": asset_code,
        "source_code": source_code,
        "snapshot_id": str(source_snapshot.snapshot_id),
        "snapshot_content_hash": source_snapshot.content_hash,
        "snapshot_record_digest": source_snapshot.record_digest,
        "mapping_record_id": str(source_snapshot.mapping_record.mapping_record_id),
        "mapping_id": source_snapshot.mapping_record.content.mapping_id,
        "mapping_version": source_snapshot.mapping_record.content.mapping_version,
        "mapping_content_hash": source_snapshot.mapping_record.content_hash,
        "mapping_record_digest": source_snapshot.mapping_record.record_digest,
    }
    selector: dict[str, object] = {
        "schema": "normal-simulated-current-reference-selection.v1",
        "purpose": "normal_simulated_current_reference",
        "max_local_reference_age_seconds": local_reference_age_seconds,
        "items": [item] if include_selector_item else [],
    }

    from tests.support.runtime_config import configure_critical_runtime

    with _runtime_public_write_clock():
        configure_critical_runtime()
        profile, runtime_snapshot = activate_runtime_profile_patch(
            environment=runtime_environment,
            patch={
                _CURRENT_REFERENCE_SELECTION_KEY: selector,
                _EXCHANGE_TIMEZONE_MAP_KEY: {
                    classification.source_exchange: exchange_timezone,
                },
            },
            actor=actor,
            reason="bind exact persisted test evidence to the active current selection",
        )
    if profile.activated_at is None:
        raise AssertionError("activated runtime profile did not retain its activation time")
    known_clocks = {
        "current_time": timezone.now().astimezone(UTC),
        "profile_activated_at": profile.activated_at,
        "snapshot_generated_at": runtime_snapshot.generated_at,
        "source_recorded_at": source_snapshot.recorded_at,
        "mapping_recorded_at": source_snapshot.mapping_record.recorded_at,
        "response_completed_at": source_snapshot.content.last_response_completed_at,
    }
    required_known_at = tuple(known_clocks.values())
    if any(
        type(timestamp) is not datetime or timestamp.utcoffset() is None
        for timestamp in required_known_at
    ):
        raise ValueError("all current-reference knowledge timestamps must be exact aware datetimes")
    if any(timestamp > as_of for timestamp in required_known_at):
        future_clocks = ", ".join(
            f"{name}={timestamp.isoformat()}"
            for name, timestamp in known_clocks.items()
            if timestamp > as_of
        )
        raise ValueError(f"current-reference knowledge timestamps exceed as_of: {future_clocks}")

    identity_reader = build_current_reference_identity_reader(
        runtime_environment=runtime_environment,
    )
    calendar_configuration = read_calendar_capture_configuration_at(as_of=as_of)
    calendar_reader = build_current_published_execution_calendar_reader(
        dataset_key=calendar_configuration.dataset.value,
        runtime_environment=runtime_environment,
    )
    calendar_evidence = calendar_reader.get_effective_execution_calendar(
        exchange=classification.source_exchange,
        as_of=as_of,
        coverage_start=None,
    )
    if calendar_evidence is None:
        raise AssertionError("no exact current formal calendar publication is available")
    market_session = calendar_evidence.current_open_session(as_of)

    rule_reader = build_execution_settlement_v3_rule_reader()
    rule_bundle = rule_reader.execute(security_id=security_id, as_of=as_of)
    if type(rule_bundle) is not ExecutionSettlementBundleV3:
        raise AssertionError("Risk V3 reader returned no exact active bundle")

    fee_reader = DjangoSimulatedTradeExecutionRepository(using=DEFAULT_DB_ALIAS)
    buy_fee_policy = fee_reader.get_execution_fee_policy(
        account_id=account_id,
        user_id=user_id,
        asset_type="equity",
        market=classification.rule_market,
        board=classification.board,
        side=SimulatedTradeSide.BUY,
        as_of=as_of,
    )
    sell_fee_policy = fee_reader.get_execution_fee_policy(
        account_id=account_id,
        user_id=user_id,
        asset_type="equity",
        market=classification.rule_market,
        board=classification.board,
        side=SimulatedTradeSide.SELL,
        as_of=as_of,
    )
    if type(buy_fee_policy) is not SimulatedFeePolicyV2:
        raise AssertionError("an exact effective BUY Fee V2 case is required")
    if type(sell_fee_policy) is not SimulatedFeePolicyV2:
        raise AssertionError("an exact effective SELL Fee V2 case is required")

    execution_use_case = build_execute_settlement_bound_simulated_trade_use_case(
        using=DEFAULT_DB_ALIAS,
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=_FixedClock(as_of),
    )
    return AutoCurrentReferenceUowFixture(
        as_of=as_of,
        security_id=security_id,
        asset_code=asset_code,
        source_code=source_code,
        source_exchange=classification.source_exchange,
        rule_market=classification.rule_market,
        board=classification.board,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        calendar_evidence=calendar_evidence,
        market_session=market_session,
        rule_bundle=rule_bundle,
        buy_fee_policy=buy_fee_policy,
        sell_fee_policy=sell_fee_policy,
        execution_use_case=execution_use_case,
    )
