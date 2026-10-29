"""Compose the explicit current-reference reader for simulated execution.

This reader uses only an operator-selected Config Center selector and exact
persisted instrument-reference receipts. It preserves unknown upstream clocks
and restrictive source flags; a local age window is not provider freshness,
historical PIT evidence, or broker authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn, Protocol, cast
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfiguration,
    CalendarCaptureConfigurationError,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.application.price_service import UnifiedPriceService
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_at,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceClassification,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceOccurrence,
    InstrumentReferenceRecord,
)
from apps.data_center.instrument_reference_snapshot_composition import (
    read_instrument_reference_mapping,
    read_instrument_reference_snapshot,
)
from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.automatic_trade_execution import (
    AutomaticTradeExecutionBridge,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.manual_trade_execution import (
    ExecuteCurrentReferenceManualTradeUseCase,
)
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    ExecutionCurrentReferenceSelectorV2,
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
    build_execute_settlement_bound_simulated_trade_use_case,
)
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.automatic_trading_invocation_repository import (
    DjangoAutoTradingInvocationRepository,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

_RUNTIME_SELECTION_KEY = "config_center.market.simulated_current_reference_selection"
_RUNTIME_SELECTION_SCHEMA = "normal-simulated-current-reference-selection.v1"
_RUNTIME_SELECTION_SCHEMA_V2 = "normal-simulated-current-reference-selection.v2"
_SELECTION_PURPOSE = "normal_simulated_current_reference"
_TOKEN_LIMIT = 192
_BARE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SELECTOR_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "max_local_reference_age_seconds",
        "items",
    }
)
_ITEM_KEYS = frozenset(
    {
        "security_id",
        "asset_code",
        "source_code",
        "snapshot_id",
        "snapshot_content_hash",
        "snapshot_record_digest",
        "mapping_record_id",
        "mapping_id",
        "mapping_version",
        "mapping_content_hash",
        "mapping_record_digest",
    }
)


class CurrentReferenceIdentityReader(Protocol):
    """Read exact selected identity evidence for normal simulated use."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Return the exact selected source identity or no configured match."""

    def resolve_current_reference_identity(
        self,
        *,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Resolve one asset code through the explicit current selector."""


@dataclass(frozen=True, slots=True)
class _SelectorItem:
    """Typed, exact selector row after narrowing the Config Center JSON boundary."""

    security_id: str
    asset_code: str
    source_code: str
    snapshot_id: UUID
    snapshot_content_hash: str
    snapshot_record_digest: str
    mapping_record_id: UUID
    mapping_id: str
    mapping_version: str
    mapping_content_hash: str
    mapping_record_digest: str
    simulated_asset_type: str | None = None


@dataclass(frozen=True, slots=True)
class _RuntimeSelection:
    """One stable before-read Config Center snapshot and its parsed selector."""

    profile: RuntimeConfigProfileRead
    snapshot: RuntimeConfigSnapshotRead
    selection: CurrentReferenceSelectionV1
    items: tuple[_SelectorItem, ...]
    selector_v2: ExecutionCurrentReferenceSelectorV2 | None


def _blocked(message: str, cause: Exception | None = None) -> NoReturn:
    """Raise the application-owned typed execution block at this boundary."""

    if cause is None:
        raise SimulatedTradeExecutionBlocked(message)
    raise SimulatedTradeExecutionBlocked(message) from cause


def _require_token(value: object, field_name: str) -> str:
    """Accept only a bounded exact token and never trim or invent one."""

    if (
        type(value) is not str
        or not value
        or len(value) > _TOKEN_LIMIT
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _blocked(f"current-reference selector has an invalid {field_name}")
    return value


def _require_prefixed_digest(value: object, field_name: str) -> str:
    """Require the Data Center's exact sha256-prefixed content/seal format."""

    if type(value) is not str or _PREFIXED_SHA256.fullmatch(value) is None:
        _blocked(f"current-reference selector has an invalid {field_name}")
    return value


def _require_bare_digest(value: object, field_name: str) -> str:
    """Require one bare lowercase runtime-profile or runtime-snapshot digest."""

    if type(value) is not str or _BARE_SHA256.fullmatch(value) is None:
        _blocked(f"current-reference runtime metadata has an invalid {field_name}")
    return value


def _parse_uuid(value: object, field_name: str) -> UUID:
    """Parse one canonical lowercase hyphenated UUID selector pin."""

    if type(value) is not str:
        _blocked(f"current-reference selector has an invalid {field_name}")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        _blocked(f"current-reference selector has an invalid {field_name}", error)
    if str(parsed) != value:
        _blocked(f"current-reference selector has a noncanonical {field_name}")
    return parsed


def _require_object(value: object, keys: frozenset[str], field_name: str) -> dict[str, object]:
    """Narrow one JSON object only when its key set is exact."""

    if type(value) is not dict or set(value) != keys:
        _blocked(f"current-reference selector has an invalid {field_name} object")
    return cast(dict[str, object], value)


def _canonical_json_hash(value: dict[str, object]) -> str:
    """Hash one exact JSON value using the Config Center canonical public format."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        _blocked("current-reference selector is not canonical JSON", error)
    return hashlib.sha256(encoded).hexdigest()


def _selector_items(value: object) -> tuple[int, tuple[_SelectorItem, ...], str]:
    """Validate the complete selector schema, item types, pins, and uniqueness."""

    fields = _require_object(value, _SELECTOR_KEYS, "root")
    if (
        type(fields["schema"]) is not str
        or fields["schema"] != _RUNTIME_SELECTION_SCHEMA
        or type(fields["purpose"]) is not str
        or fields["purpose"] != _SELECTION_PURPOSE
    ):
        _blocked("current-reference selector schema or purpose is unsupported")
    age = fields["max_local_reference_age_seconds"]
    if type(age) is not int or age <= 0:
        _blocked("current-reference selector local age must be a positive integer")
    raw_items = fields["items"]
    if type(raw_items) is not list:
        _blocked("current-reference selector items must be a JSON array")

    items: list[_SelectorItem] = []
    security_ids: set[str] = set()
    asset_codes: set[str] = set()
    source_codes: set[str] = set()
    for raw_item in raw_items:
        item = _require_object(raw_item, _ITEM_KEYS, "item")
        parsed = _SelectorItem(
            security_id=_require_token(item["security_id"], "security_id"),
            asset_code=_require_token(item["asset_code"], "asset_code"),
            source_code=_require_token(item["source_code"], "source_code"),
            snapshot_id=_parse_uuid(item["snapshot_id"], "snapshot_id"),
            snapshot_content_hash=_require_prefixed_digest(
                item["snapshot_content_hash"], "snapshot_content_hash"
            ),
            snapshot_record_digest=_require_prefixed_digest(
                item["snapshot_record_digest"], "snapshot_record_digest"
            ),
            mapping_record_id=_parse_uuid(item["mapping_record_id"], "mapping_record_id"),
            mapping_id=_require_token(item["mapping_id"], "mapping_id"),
            mapping_version=_require_token(item["mapping_version"], "mapping_version"),
            mapping_content_hash=_require_prefixed_digest(
                item["mapping_content_hash"], "mapping_content_hash"
            ),
            mapping_record_digest=_require_prefixed_digest(
                item["mapping_record_digest"], "mapping_record_digest"
            ),
        )
        if (
            parsed.security_id in security_ids
            or parsed.asset_code in asset_codes
            or parsed.source_code in source_codes
        ):
            _blocked("current-reference selector contains duplicate security identifiers")
        security_ids.add(parsed.security_id)
        asset_codes.add(parsed.asset_code)
        source_codes.add(parsed.source_code)
        items.append(parsed)

    return age, tuple(items), _canonical_json_hash(fields)


def _as_utc(value: object, field_name: str) -> datetime:
    """Require an aware zero-offset clock and normalize it without using wall time."""

    if type(value) is not datetime:
        _blocked(f"{field_name} must be an aware UTC datetime")
    try:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            _blocked(f"{field_name} must be an aware UTC datetime")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        _blocked(f"{field_name} must be an aware UTC datetime", error)


def _validate_runtime_pair(
    profile: object,
    snapshot: object,
    *,
    runtime_environment: str,
    as_of: datetime,
) -> tuple[RuntimeConfigProfileRead, RuntimeConfigSnapshotRead]:
    """Verify one active profile and its exact public snapshot at the cutoff."""

    if not isinstance(profile, RuntimeConfigProfileRead) or not isinstance(
        snapshot, RuntimeConfigSnapshotRead
    ):
        _blocked("current-reference runtime profile or snapshot has an invalid type")
    try:
        profile.__post_init__()
        snapshot.__post_init__()
        if (
            type(profile.version) is not int
            or profile.version <= 0
            or profile.environment != runtime_environment
            or profile.status != "active"
            or profile.activated_at is None
            or type(snapshot.profile_version) is not int
            or snapshot.profile_id != profile.profile_id
            or snapshot.profile_key != profile.profile_key
            or snapshot.profile_version != profile.version
            or snapshot.effective_from is None
            or type(snapshot.resolved_values) is not dict
        ):
            _blocked("current-reference runtime profile and snapshot do not match")
        _require_token(profile.profile_id, "runtime profile id")
        _require_token(profile.profile_key, "runtime profile key")
        _require_token(profile.environment, "runtime profile environment")
        _require_token(snapshot.snapshot_id, "runtime snapshot id")
        _require_bare_digest(profile.content_hash, "profile content hash")
        _require_bare_digest(snapshot.snapshot_hash, "snapshot hash")
        created_at = _as_utc(profile.created_at, "runtime profile created_at")
        activated_at = _as_utc(profile.activated_at, "runtime profile activated_at")
        generated_at = _as_utc(snapshot.generated_at, "runtime snapshot generated_at")
        effective_from = _as_utc(snapshot.effective_from, "runtime snapshot effective_from")
        if (
            created_at > as_of
            or activated_at > generated_at
            or generated_at > as_of
            or effective_from != activated_at
        ):
            _blocked("current-reference runtime clocks do not qualify at the requested cutoff")
        if _canonical_json_hash(cast(dict[str, object], snapshot.resolved_values)) != (
            snapshot.snapshot_hash
        ):
            _blocked("current-reference runtime snapshot public hash is inconsistent")
    except SimulatedTradeExecutionBlocked:
        raise
    except Exception as error:
        _blocked("current-reference runtime profile or snapshot failed validation", error)
    return profile, snapshot


def _parse_as_of(value: datetime) -> datetime:
    """Require the application cutoff to be aware UTC before any source read."""

    return _as_utc(value, "current-reference as_of")


class _CurrentReferenceIdentityReader:
    """Resolve only explicit, exact current-reference selections."""

    def __init__(self, *, runtime_environment: str) -> None:
        """Bind an explicit runtime environment without reading any service."""

        self._runtime_environment = _require_token(runtime_environment, "runtime environment")

    def _capture_runtime_selection(self, *, as_of: datetime) -> _RuntimeSelection | None:
        """Read one current profile, snapshot, and selector at the exact cutoff."""

        cutoff = _parse_as_of(as_of)
        try:
            profile_value = get_active_runtime_profile(self._runtime_environment)
            if profile_value is None:
                return None
            if not isinstance(profile_value, RuntimeConfigProfileRead):
                _blocked("current-reference runtime profile has an invalid type")
            snapshot_value = get_latest_runtime_snapshot(profile_value.profile_key)
            if snapshot_value is None:
                return None
            profile, snapshot = _validate_runtime_pair(
                profile_value,
                snapshot_value,
                runtime_environment=self._runtime_environment,
                as_of=cutoff,
            )
            runtime_value = get_active_runtime_value(
                environment=self._runtime_environment,
                definition_key=_RUNTIME_SELECTION_KEY,
                as_of=cutoff,
            )
            saved_present = _RUNTIME_SELECTION_KEY in snapshot.resolved_values
            saved_value = snapshot.resolved_values.get(_RUNTIME_SELECTION_KEY)
            if not saved_present:
                if runtime_value is not None:
                    _blocked("current-reference runtime value is absent from its exact snapshot")
                return None
            if runtime_value is None or runtime_value != saved_value:
                _blocked("current-reference runtime value differs from its exact snapshot")
            selector_v2: ExecutionCurrentReferenceSelectorV2 | None = None
            if isinstance(runtime_value, dict) and runtime_value.get("schema") == (
                _RUNTIME_SELECTION_SCHEMA_V2
            ):
                selector_v2 = ExecutionCurrentReferenceSelectorV2.from_payload(runtime_value)
                age_seconds = selector_v2.max_local_reference_age_seconds
                items = tuple(
                    _SelectorItem(
                        security_id=item.security_id,
                        asset_code=item.asset_code,
                        source_code=item.source_code,
                        snapshot_id=item.snapshot_id,
                        snapshot_content_hash=item.snapshot_content_hash,
                        snapshot_record_digest=item.snapshot_record_digest,
                        mapping_record_id=item.mapping_record_id,
                        mapping_id=item.mapping_id,
                        mapping_version=item.mapping_version,
                        mapping_content_hash=item.mapping_content_hash,
                        mapping_record_digest=item.mapping_record_digest,
                        simulated_asset_type=item.simulated_asset_type,
                    )
                    for item in selector_v2.items
                )
                selector_hash = selector_v2.content_hash
            else:
                age_seconds, items, selector_hash = _selector_items(runtime_value)
            if profile.activated_at is None:
                _blocked("current-reference profile has no activation clock")
            selection = CurrentReferenceSelectionV1(
                purpose=_SELECTION_PURPOSE,
                profile_id=profile.profile_id,
                profile_key=profile.profile_key,
                environment=profile.environment,
                profile_version=profile.version,
                profile_content_hash=profile.content_hash,
                runtime_snapshot_id=snapshot.snapshot_id,
                runtime_snapshot_hash=snapshot.snapshot_hash,
                selector_content_hash=selector_hash,
                profile_activated_at=profile.activated_at,
                runtime_snapshot_generated_at=snapshot.generated_at,
                selected_at=cutoff,
                max_local_reference_age_seconds=age_seconds,
            )
            return _RuntimeSelection(
                profile=profile,
                snapshot=snapshot,
                selection=selection,
                items=items,
                selector_v2=selector_v2,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except Exception as error:
            _blocked("current-reference Config Center read failed exact validation", error)

    def _confirm_runtime_selection(
        self,
        selection: _RuntimeSelection,
        *,
        as_of: datetime,
    ) -> None:
        """Re-read the current profile and snapshot after source reads to detect changes."""

        cutoff = _parse_as_of(as_of)
        try:
            profile_value = get_active_runtime_profile(self._runtime_environment)
            if profile_value is None:
                _blocked("current-reference runtime profile changed during exact reads")
            if not isinstance(profile_value, RuntimeConfigProfileRead):
                _blocked("current-reference runtime profile changed to an invalid type")
            snapshot_value = get_latest_runtime_snapshot(profile_value.profile_key)
            if snapshot_value is None:
                _blocked("current-reference runtime snapshot changed during exact reads")
            profile, snapshot = _validate_runtime_pair(
                profile_value,
                snapshot_value,
                runtime_environment=self._runtime_environment,
                as_of=cutoff,
            )
            if profile != selection.profile or snapshot != selection.snapshot:
                _blocked("current-reference runtime profile or snapshot changed during exact reads")
        except SimulatedTradeExecutionBlocked:
            raise
        except Exception as error:
            _blocked("current-reference Config Center changed during exact reads", error)

    def _item_for(
        self,
        selection: _RuntimeSelection,
        *,
        asset_code: str,
        security_id: str | None,
    ) -> _SelectorItem | None:
        """Resolve one unique operator-mapped item without inferring either identity."""

        exact_asset_code = _require_token(asset_code, "asset_code")
        exact_security_id = (
            _require_token(security_id, "security_id") if security_id is not None else None
        )
        item = next(
            (
                candidate
                for candidate in selection.items
                if candidate.asset_code == exact_asset_code
            ),
            None,
        )
        if item is None:
            return None
        if exact_security_id is not None and item.security_id != exact_security_id:
            _blocked("current-reference selector security differs from the requested security")
        return item

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Return an exact current-reference identity for one requested security."""

        selection = self._capture_runtime_selection(as_of=as_of)
        if selection is None:
            return None
        item = self._item_for(
            selection,
            asset_code=asset_code,
            security_id=security_id,
        )
        if item is None:
            return None
        evidence = self._read_exact_source_identity(selection, item)
        if evidence is None:
            return None
        self._confirm_runtime_selection(selection, as_of=as_of)
        return evidence

    def resolve_simulated_instrument_classification(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
        """Return classification only from an active exact v2 selector item."""

        selection = self._capture_runtime_selection(as_of=as_of)
        if selection is None or selection.selector_v2 is None:
            return None
        item = self._item_for(
            selection,
            asset_code=asset_code,
            security_id=security_id,
        )
        if item is None:
            return None
        if type(item.simulated_asset_type) is not str:
            _blocked("current-reference v2 selector lacks an explicit simulated asset type")
        identity = self._read_exact_source_identity(selection, item)
        if identity is None:
            return None
        self._confirm_runtime_selection(selection, as_of=as_of)
        return SimulatedInstrumentClassificationEvidenceV1(
            selector=selection.selector_v2,
            identity_evidence=identity,
            read_at=_parse_as_of(as_of),
        )

    def resolve_current_reference_identity(
        self,
        *,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Resolve one asset code using the explicit active selector only."""

        selection = self._capture_runtime_selection(as_of=as_of)
        if selection is None:
            return None
        item = self._item_for(selection, asset_code=asset_code, security_id=None)
        if item is None:
            return None
        evidence = self._read_exact_source_identity(selection, item)
        if evidence is None:
            return None
        self._confirm_runtime_selection(selection, as_of=as_of)
        return evidence

    def _read_exact_source_identity(
        self,
        selection: _RuntimeSelection,
        item: _SelectorItem,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Read both exact persisted receipts and construct their typed V2 envelope."""

        try:
            snapshot = read_instrument_reference_snapshot(snapshot_id=item.snapshot_id)
            if snapshot is None:
                return None
            if type(snapshot) is not InstrumentReferenceSnapshotRecord:
                _blocked("Data Center returned an invalid instrument snapshot type")
            snapshot.__post_init__()
            if (
                snapshot.snapshot_id != item.snapshot_id
                or snapshot.content_hash != item.snapshot_content_hash
                or snapshot.record_digest != item.snapshot_record_digest
            ):
                _blocked("Data Center snapshot differs from the exact selector pins")

            mapping = read_instrument_reference_mapping(mapping_record_id=item.mapping_record_id)
            if mapping is None:
                return None
            if type(mapping) is not InstrumentReferenceMappingRecord:
                _blocked("Data Center returned an invalid instrument mapping type")
            mapping.__post_init__()
            if (
                mapping.mapping_record_id != item.mapping_record_id
                or mapping.content.mapping_id != item.mapping_id
                or mapping.content.mapping_version != item.mapping_version
                or mapping.content_hash != item.mapping_content_hash
                or mapping.record_digest != item.mapping_record_digest
                or snapshot.mapping_record != mapping
            ):
                _blocked("Data Center mapping differs from the exact selector or snapshot pins")

            classification = snapshot.content.classify_security(item.source_code)
            if (
                type(classification) is not InstrumentReferenceClassification
                or classification.blocked_reason is not None
                or classification.source_market is None
                or classification.rule_market is None
                or classification.board is None
            ):
                _blocked("Data Center source identity is missing an exact mapped classification")
            occurrence, source_record = self._latest_matching_occurrence(
                snapshot=snapshot,
                source_code=item.source_code,
            )
            if (
                source_record.source_exchange != classification.source_exchange
                or source_record.source_market != classification.source_market
            ):
                _blocked("latest source occurrence differs from the sealed classification")

            content = snapshot.content
            start = max(
                selection.selection.profile_activated_at,
                snapshot.recorded_at,
                mapping.recorded_at,
            )
            try:
                end = occurrence.response_completed_at + timedelta(
                    seconds=selection.selection.max_local_reference_age_seconds
                )
            except OverflowError as error:
                _blocked("current-reference local age window overflows", error)
            source_evidence = ExecutionInstrumentIdentityEvidenceV1(
                security_id=item.security_id,
                asset_code=item.asset_code,
                source_code=item.source_code,
                source_exchange=classification.source_exchange,
                source_market=classification.source_market,
                rule_market=classification.rule_market,
                board=classification.board,
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.content_hash,
                snapshot_record_digest=snapshot.record_digest,
                first_seen_at=content.last_response_completed_at,
                snapshot_recorded_at=snapshot.recorded_at,
                mapping_record_id=mapping.mapping_record_id,
                mapping_id=mapping.content.mapping_id,
                mapping_version=mapping.content.mapping_version,
                mapping_content_hash=mapping.content_hash,
                mapping_record_digest=mapping.record_digest,
                mapping_recorded_at=mapping.recorded_at,
                response_completed_at=content.last_response_completed_at,
                source_observed_at=content.source_observed_at,
                source_available_at=content.source_available_at,
                identity_valid_from=start,
                identity_valid_until=end,
                must_not_use_for_decision=content.must_not_use_for_decision,
                must_not_execute=content.must_not_execute,
            )
            return ExecutionInstrumentIdentityEvidenceV2(
                source_evidence=source_evidence,
                selection=selection.selection,
                source_occurrence_id=occurrence.occurrence_id,
                reference_response_completed_at=occurrence.response_completed_at,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except Exception as error:
            _blocked("exact Data Center instrument evidence failed validation", error)

    @staticmethod
    def _latest_matching_occurrence(
        *,
        snapshot: InstrumentReferenceSnapshotRecord,
        source_code: str,
    ) -> tuple[InstrumentReferenceOccurrence, InstrumentReferenceRecord]:
        """Select the latest occurrence containing the exact source code, tie by UUID."""

        matches: list[tuple[InstrumentReferenceOccurrence, InstrumentReferenceRecord]] = []
        for fetch_round in snapshot.content.fetch_rounds:
            candidate = fetch_round.candidate
            for occurrence in candidate.occurrences:
                records = [
                    record
                    for record in candidate.records
                    if record.ts_code == source_code
                    and record.occurrence_id == occurrence.occurrence_id
                ]
                if len(records) > 1:
                    _blocked("one source occurrence contains duplicate selected security rows")
                if records:
                    matches.append((occurrence, records[0]))
        if not matches:
            _blocked("the exact source snapshot does not contain the selected security code")
        return max(
            matches,
            key=lambda pair: (
                pair[0].response_completed_at,
                str(pair[0].occurrence_id),
            ),
        )


def build_current_reference_identity_reader(
    *,
    runtime_environment: str,
) -> CurrentReferenceIdentityReader:
    """Build a side-effect-free reader for one explicit runtime environment."""

    return _CurrentReferenceIdentityReader(runtime_environment=runtime_environment)


def build_current_reference_classification_reader(
    *,
    runtime_environment: str,
) -> CurrentReferenceClassificationReader:
    """Build the opt-in v2 classification reader without activating a profile."""

    return _CurrentReferenceIdentityReader(runtime_environment=runtime_environment)


def _runtime_environment_from_settings_module() -> str:
    """Map the configured settings module to its production or development scope."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    if settings_module.endswith(".production"):
        return "production"
    return "development"


class _ServerUTCClock:
    """Provide the server's aware UTC time to the manual caller and locked UOW."""

    def now(self) -> datetime:
        """Return a fresh aware UTC value without caching a source cutoff."""

        return timezone.now().astimezone(UTC)


class _CalendarConfigurationReader(Protocol):
    """Read catalog selection at the caller's explicit knowledge cutoff."""

    def __call__(self, *, as_of: datetime) -> CalendarCaptureConfiguration:
        """Return current catalog metadata without claiming historical configuration."""


class _ConfiguredExecutionCalendarReader:
    """Bind configured calendar metadata to one exact current publication read."""

    def __init__(
        self,
        *,
        runtime_environment: str,
        read_publication: (
            Callable[
                [ReadCurrentExchangeCalendarPublicationQuery], CurrentPublishedExchangeCalendar
            ]
            | None
        ) = None,
        read_configuration: _CalendarConfigurationReader | None = None,
    ) -> None:
        """Bind one explicit environment without reading metadata or publications."""

        if (
            type(runtime_environment) is not str
            or not runtime_environment
            or runtime_environment.strip() != runtime_environment
            or any(character.isspace() for character in runtime_environment)
        ):
            raise SimulatedTradeExecutionBlocked(
                "manual calendar runtime environment must be an explicit token"
            )
        self._runtime_environment = runtime_environment
        self._read_publication = read_publication
        self._read_configuration = read_configuration

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Read configured metadata and publication at the identical caller cutoff."""

        if type(as_of) is not datetime or as_of.tzinfo is None:
            raise SimulatedTradeExecutionBlocked("manual calendar cutoff must be aware UTC")
        try:
            offset = as_of.utcoffset()
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "manual calendar cutoff must be aware UTC"
            ) from error
        if offset != timedelta(0):
            raise SimulatedTradeExecutionBlocked("manual calendar cutoff must be aware UTC")

        try:
            read_configuration = self._read_configuration or read_calendar_capture_configuration_at
            configuration = read_configuration(as_of=as_of)
        except CalendarCaptureConfigurationError as error:
            raise ExecutionCalendarUnavailable(
                "configured calendar metadata is unavailable"
            ) from error
        if type(configuration) is not CalendarCaptureConfiguration:
            raise SimulatedTradeExecutionBlocked(
                "calendar metadata reader returned an invalid contract"
            )
        try:
            CalendarCaptureConfiguration.__post_init__(configuration)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "calendar metadata failed exact contract validation"
            ) from error
        if configuration.known_at != as_of:
            raise SimulatedTradeExecutionBlocked(
                "calendar metadata differs from the exact caller cutoff"
            )

        if self._read_publication is None:
            reader = build_current_published_execution_calendar_reader(
                dataset_key=configuration.dataset.value,
                runtime_environment=self._runtime_environment,
            )
        else:
            reader = build_current_published_execution_calendar_reader(
                dataset_key=configuration.dataset.value,
                runtime_environment=self._runtime_environment,
                read_publication=self._read_publication,
            )
        return reader.get_effective_execution_calendar(
            exchange=exchange,
            as_of=as_of,
            coverage_start=coverage_start,
        )


def build_configured_execution_calendar_reader(
    *,
    runtime_environment: str,
    read_publication: (
        Callable[[ReadCurrentExchangeCalendarPublicationQuery], CurrentPublishedExchangeCalendar]
        | None
    ) = None,
    read_configuration: _CalendarConfigurationReader | None = None,
) -> PublishedExecutionCalendarReader:
    """Defer catalog selection until the caller's exact calendar cutoff is known."""
    return _ConfiguredExecutionCalendarReader(
        runtime_environment=runtime_environment,
        read_publication=read_publication,
        read_configuration=read_configuration,
    )


@dataclass(frozen=True, slots=True)
class _CurrentReferenceManualExecutionComponents:
    """Keep the manual and automatic callers on the same source and ledger ports."""

    identity_reader: CurrentReferenceIdentityReader
    calendar_reader: PublishedExecutionCalendarReader
    clock: SimulatedTradeExecutionClock
    manual_use_case: ExecuteCurrentReferenceManualTradeUseCase


def _build_current_reference_manual_execution_components() -> (
    _CurrentReferenceManualExecutionComponents
):
    """Compose shared current-reference evidence readers and the manual UoW."""
    runtime_environment = _runtime_environment_from_settings_module()
    clock: SimulatedTradeExecutionClock = _ServerUTCClock()
    identity_reader = build_current_reference_identity_reader(
        runtime_environment=runtime_environment
    )
    calendar_reader: PublishedExecutionCalendarReader = _ConfiguredExecutionCalendarReader(
        runtime_environment=runtime_environment
    )
    rule_reader = build_execution_settlement_v3_rule_reader()
    execution_use_case = build_execute_settlement_bound_simulated_trade_use_case(
        using=DEFAULT_DB_ALIAS,
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=clock,
    )
    repository = DjangoSimulatedTradeExecutionRepository(using=DEFAULT_DB_ALIAS)
    trade_reader = DjangoTradeRepository()
    manual_use_case = ExecuteCurrentReferenceManualTradeUseCase(
        identity_reader=identity_reader,
        repository=repository,
        trade_reader=trade_reader,
        execution_use_case=execution_use_case,
        clock=clock,
    )
    return _CurrentReferenceManualExecutionComponents(
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=clock,
        manual_use_case=manual_use_case,
    )


def build_current_reference_manual_trade_use_case() -> ExecuteCurrentReferenceManualTradeUseCase:
    """Compose the default manual caller without reading current sources at build time.

    Runtime identity, calendar, and Risk evidence are read only during execute.
    The receipt ledger, settlement UOW, and Risk repository are bound to the
    default database alias. The existing trade reader has no alias parameter
    and uses Django's default manager, so this composition is default-database
    only.
    """

    return _build_current_reference_manual_execution_components().manual_use_case


def build_automatic_trade_execution_bridge(
    invocation_id: UUID,
    expected_owner_id: int | None = None,
) -> AutomaticTradeExecutionBridge:
    """Compose automatic-order adapters from one persisted preparing scope.

    Construction reads only the local frozen invocation scope. It does not
    read market sources or write the simulated ledger; source checks and the
    manual settlement UOW run when the Engine invokes an order adapter.
    """

    scope = DjangoAutoTradingInvocationRepository().get_preparing_scope(
        invocation_id=invocation_id,
    )
    components = _build_current_reference_manual_execution_components()
    return AutomaticTradeExecutionBridge(
        run_id=invocation_id,
        execution_date=scope.trade_date,
        account_ids=scope.account_ids,
        expected_owner_id=expected_owner_id,
        owner_reader=DjangoSimulatedAccountRepository(),
        position_repository=DjangoPositionRepository(),
        identity_reader=components.identity_reader,
        calendar_reader=components.calendar_reader,
        manual_use_case=components.manual_use_case,
        clock=components.clock,
        price_lookup=UnifiedPriceService(),
    )


__all__ = [
    "CurrentReferenceIdentityReader",
    "build_automatic_trade_execution_bridge",
    "build_current_reference_identity_reader",
    "build_current_reference_manual_trade_use_case",
]
