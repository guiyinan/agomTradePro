"""Contract tests for the bounded current-reference reader composition."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

_MODULE = "apps.simulated_trading.execution_current_reference_composition"
_CONFIG_KEY = "config_center.market.simulated_current_reference_selection"
_CONFIG_SCHEMA = "normal-simulated-current-reference-selection.v1"
_PURPOSE = "normal_simulated_current_reference"
_ENVIRONMENT = "simulated-test"
_SECURITY_ID = "risk-security-fixture-001"
_ASSET_CODE = "600000.SH"
_SOURCE_CODE = "600000.SH"
_BASE = datetime(2026, 10, 18, 2, 0, tzinfo=UTC)


def _load_composition() -> Any:
    """Turn an absent production seam into a focused assertion, not collection error."""

    spec = importlib.util.find_spec(_MODULE)
    assert spec is not None, "current-reference reader composition is not implemented"
    module = importlib.import_module(_MODULE)
    factory = getattr(module, "build_current_reference_identity_reader", None)
    assert callable(factory), "current-reference reader factory is not exported"
    return module


def _selector_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _synthetic_snapshot(
    *,
    mapping_recorded_at: datetime | None = None,
    board_market: str = "fixture-main",
) -> Any:
    """Build complete synthetic source evidence with unrelated later responses."""

    from apps.data_center.domain.entities import RawAuditReference
    from apps.data_center.domain.instrument_reference_snapshot import (
        InstrumentReferenceFetchRound,
        InstrumentReferenceMappingContent,
        InstrumentReferenceSnapshotContent,
        make_instrument_reference_mapping_record,
        make_instrument_reference_snapshot_record,
    )
    from apps.data_center.domain.instrument_reference_source import (
        InstrumentReferenceCandidate,
        InstrumentReferenceExchangeSuffixCrosswalk,
        InstrumentReferenceOccurrence,
        InstrumentReferenceProviderContract,
        InstrumentReferenceRecord,
    )

    run_id = uuid4()
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture-crosswalk",
        crosswalk_version="v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.stock-basic",
        contract_version="v1",
        provider_name="fixture-provider",
        dataset_key="fixture.instrument-reference.stock-basic",
        api_name="stock_basic",
        fields=(
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
        ),
        exchange_scope=("SSE",),
        list_status_scope=("L",),
    )
    mapping_content = InstrumentReferenceMappingContent(
        mapping_id="fixture-instrument-map",
        mapping_version="v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
        exchange_source_market_board_pairs=(("SSE", board_market, "FIXTURE_MAIN"),),
    )
    mapping_time = mapping_recorded_at or (_BASE - timedelta(minutes=1))
    mapping = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=uuid4(),
        recorded_at=mapping_time,
    )

    audit_id_sequence = iter(range(1, 5))

    def make_round(
        *,
        response_time: datetime,
        codes: tuple[tuple[str, str], ...],
    ) -> InstrumentReferenceFetchRound:
        occurrence_id = uuid4()
        payload_id = str(uuid4())
        raw_ref = RawAuditReference(
            raw_audit_id=str(next(audit_id_sequence)),
            version="fixture-v1",
            content_hash="a" * 64,
            run_id=str(run_id),
            ingested_run_id=str(uuid4()),
        )
        occurrence = InstrumentReferenceOccurrence(
            occurrence_id=occurrence_id,
            exchange="SSE",
            list_status="L",
            raw_audit_reference=raw_ref,
            raw_payload_id=payload_id,
            raw_payload_hash="sha256:" + "b" * 64,
            response_body_sha256="c" * 64,
            response_completed_at=response_time,
            row_count=len(codes),
        )
        records = tuple(
            InstrumentReferenceRecord(
                ts_code=code,
                name=name,
                source_exchange="SSE",
                source_market="fixture-main",
                source_list_status="L",
                list_date_raw=None,
                list_date=None,
                delist_date_raw=None,
                delist_date=None,
                exchange_suffix="SH",
                occurrence_id=occurrence_id,
                raw_audit_reference=raw_ref,
                raw_payload_id=payload_id,
                raw_payload_hash="sha256:" + "b" * 64,
            )
            for code, name in codes
        )
        candidate = InstrumentReferenceCandidate(
            provider_contract=contract,
            crosswalk=crosswalk,
            occurrences=(occurrence,),
            records=records,
        )
        return InstrumentReferenceFetchRound(
            fetch_round_id=uuid4(),
            candidate=candidate,
        )

    content = InstrumentReferenceSnapshotContent(
        run_id=run_id,
        mapping_record=mapping,
        fetch_rounds=(
            make_round(
                response_time=_BASE + timedelta(seconds=10),
                codes=((_SOURCE_CODE, "Fixture bank"),),
            ),
            make_round(
                response_time=_BASE + timedelta(seconds=20),
                codes=((_SOURCE_CODE, "Fixture bank"),),
            ),
            make_round(
                response_time=_BASE + timedelta(seconds=90),
                codes=(("600001.SH", "Other bank"),),
            ),
            make_round(response_time=_BASE + timedelta(seconds=120), codes=()),
        ),
    )
    recorded_at = max(
        _BASE + timedelta(seconds=130),
        mapping.recorded_at + timedelta(seconds=1),
    )
    snapshot = make_instrument_reference_snapshot_record(
        content,
        snapshot_id=uuid4(),
        recorded_at=recorded_at,
    )
    return snapshot


def _selector(
    snapshot: Any,
    *,
    age_seconds: int = 600,
    asset_code: str = _ASSET_CODE,
) -> dict[str, object]:
    mapping = snapshot.mapping_record
    return {
        "schema": _CONFIG_SCHEMA,
        "purpose": _PURPOSE,
        "max_local_reference_age_seconds": age_seconds,
        "items": [
            {
                "security_id": _SECURITY_ID,
                "asset_code": asset_code,
                "source_code": _SOURCE_CODE,
                "snapshot_id": str(snapshot.snapshot_id),
                "snapshot_content_hash": snapshot.content_hash,
                "snapshot_record_digest": snapshot.record_digest,
                "mapping_record_id": str(mapping.mapping_record_id),
                "mapping_id": mapping.content.mapping_id,
                "mapping_version": mapping.content.mapping_version,
                "mapping_content_hash": mapping.content_hash,
                "mapping_record_digest": mapping.record_digest,
            }
        ],
    }


def _runtime_metadata(
    selector: object,
    *,
    profile_id: str = "fixture-profile-id",
    profile_activated_at: datetime = _BASE + timedelta(seconds=140),
    snapshot_generated_at: datetime = _BASE + timedelta(seconds=160),
) -> tuple[Any, Any]:
    """Create valid Config Center domain value objects without persistence."""

    from apps.config_center.domain.runtime_config import (
        RuntimeConfigProfile,
        RuntimeConfigSnapshot,
        RuntimeProfileStatus,
        hash_public_runtime_projection,
        hash_runtime_profile_values,
    )

    values: dict[str, object] = {} if selector is None else {_CONFIG_KEY: selector}
    profile = RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key="fixture.market-profile",
        environment=_ENVIRONMENT,
        version=1,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(values),
        created_at=profile_activated_at - timedelta(seconds=10),
        activated_at=profile_activated_at,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="fixture-runtime-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(values),
        resolved_values=values,
        generated_at=snapshot_generated_at,
        effective_from=profile_activated_at,
    )
    return profile, snapshot


def _install_ports(
    monkeypatch: pytest.MonkeyPatch,
    composition: Any,
    *,
    source_snapshot: Any,
    source_mapping: Any,
    selector: object,
    profile_id: str = "fixture-profile-id",
    profile_sequence: list[Any] | None = None,
    snapshot_sequence: list[Any] | None = None,
    runtime_value: object | None = None,
) -> dict[str, list[Any]]:
    profile, runtime_snapshot = _runtime_metadata(selector, profile_id=profile_id)
    profiles = profile_sequence or [profile]
    snapshots = snapshot_sequence or [runtime_snapshot]
    calls: dict[str, list[Any]] = {
        "profiles": [],
        "runtime_snapshots": [],
        "values": [],
        "source_snapshots": [],
        "source_mappings": [],
    }

    def take(sequence: list[Any], index: int) -> Any:
        return sequence[min(index, len(sequence) - 1)]

    def active_profile(environment: str) -> Any:
        calls["profiles"].append(environment)
        return take(profiles, len(calls["profiles"]) - 1)

    def latest_snapshot(profile_key: str) -> Any:
        calls["runtime_snapshots"].append(profile_key)
        return take(snapshots, len(calls["runtime_snapshots"]) - 1)

    def active_value(
        *,
        environment: str,
        definition_key: str,
        as_of: datetime,
    ) -> object | None:
        calls["values"].append((environment, definition_key, as_of))
        if runtime_value is not None:
            return runtime_value
        return selector

    def get_source_snapshot(*, snapshot_id: UUID) -> Any:
        calls["source_snapshots"].append(snapshot_id)
        return source_snapshot

    def get_source_mapping(*, mapping_record_id: UUID) -> Any:
        calls["source_mappings"].append(mapping_record_id)
        return source_mapping

    monkeypatch.setattr(composition, "get_active_runtime_profile", active_profile)
    monkeypatch.setattr(composition, "get_latest_runtime_snapshot", latest_snapshot)
    monkeypatch.setattr(composition, "get_active_runtime_value", active_value)
    monkeypatch.setattr(
        composition,
        "read_instrument_reference_snapshot",
        get_source_snapshot,
    )
    monkeypatch.setattr(
        composition,
        "read_instrument_reference_mapping",
        get_source_mapping,
    )
    return calls


def test_factory_is_explicit_and_has_no_read_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public reader requires an environment and performs no I/O at construction."""

    composition = _load_composition()
    factory = composition.build_current_reference_identity_reader
    parameter = inspect.signature(factory).parameters["runtime_environment"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty

    calls: list[str] = []
    for name in (
        "get_active_runtime_profile",
        "get_latest_runtime_snapshot",
        "get_active_runtime_value",
        "read_instrument_reference_snapshot",
        "read_instrument_reference_mapping",
    ):
        monkeypatch.setattr(
            composition,
            name,
            lambda *args, _name=name, **kwargs: calls.append(_name),
        )

    reader = factory(runtime_environment=_ENVIRONMENT)
    assert callable(getattr(reader, "get_execution_instrument_identity", None))
    assert callable(getattr(reader, "resolve_current_reference_identity", None))
    assert calls == []


def test_exact_selection_preserves_source_evidence_and_uses_selected_security_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later unrelated/empty response cannot refresh the selected security's age."""

    composition = _load_composition()
    snapshot = _synthetic_snapshot()
    selector = _selector(snapshot)
    cutoff = _BASE + timedelta(seconds=180)
    calls = _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    resolved = reader.resolve_current_reference_identity(
        asset_code=_ASSET_CODE,
        as_of=cutoff,
    )
    direct = reader.get_execution_instrument_identity(
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        as_of=cutoff,
    )

    assert resolved == direct
    assert resolved is not None
    source = resolved.source_evidence
    assert source.snapshot_id == snapshot.snapshot_id
    assert source.snapshot_content_hash == snapshot.content_hash
    assert source.snapshot_record_digest == snapshot.record_digest
    assert source.mapping_record_id == snapshot.mapping_record.mapping_record_id
    assert source.mapping_id == snapshot.mapping_record.content.mapping_id
    assert source.mapping_version == snapshot.mapping_record.content.mapping_version
    assert source.mapping_content_hash == snapshot.mapping_record.content_hash
    assert source.mapping_record_digest == snapshot.mapping_record.record_digest
    assert source.source_exchange == "SSE"
    assert source.source_market == "fixture-main"
    assert source.rule_market == "FIXTURE_SSE"
    assert source.board == "FIXTURE_MAIN"
    assert source.source_observed_at is None
    assert source.source_available_at is None
    assert source.must_not_use_for_decision is True
    assert source.must_not_execute is True
    assert source.first_seen_at == snapshot.content.last_response_completed_at
    assert source.response_completed_at == snapshot.content.last_response_completed_at

    matching_occurrences = [
        occurrence
        for fetch_round in snapshot.content.fetch_rounds
        for occurrence in fetch_round.candidate.occurrences
        if any(
            record.ts_code == _SOURCE_CODE and record.occurrence_id == occurrence.occurrence_id
            for record in fetch_round.candidate.records
        )
    ]
    expected_occurrence = max(
        matching_occurrences,
        key=lambda occurrence: (
            occurrence.response_completed_at,
            str(occurrence.occurrence_id),
        ),
    )
    assert resolved.source_occurrence_id == expected_occurrence.occurrence_id
    assert resolved.reference_response_completed_at == expected_occurrence.response_completed_at
    assert resolved.reference_response_completed_at < source.response_completed_at
    expected_profile, expected_runtime_snapshot = _runtime_metadata(selector)
    assert resolved.selection.purpose == _PURPOSE
    assert resolved.selection.profile_id == expected_profile.profile_id
    assert resolved.selection.profile_key == expected_profile.profile_key
    assert resolved.selection.environment == _ENVIRONMENT
    assert resolved.selection.profile_version == expected_profile.version
    assert resolved.selection.profile_content_hash == expected_profile.content_hash
    assert resolved.selection.runtime_snapshot_id == expected_runtime_snapshot.snapshot_id
    assert resolved.selection.runtime_snapshot_hash == expected_runtime_snapshot.snapshot_hash
    assert resolved.selection.selector_content_hash == _selector_digest(selector)
    assert resolved.selection.profile_activated_at == expected_profile.activated_at
    assert (
        resolved.selection.runtime_snapshot_generated_at == expected_runtime_snapshot.generated_at
    )
    assert resolved.selection.selected_at == cutoff
    assert resolved.selection.max_local_reference_age_seconds == 600
    assert source.identity_valid_from == max(
        resolved.selection.profile_activated_at,
        source.snapshot_recorded_at,
        source.mapping_recorded_at,
    )
    assert source.identity_valid_until == (
        expected_occurrence.response_completed_at + timedelta(seconds=600)
    )
    assert source.identity_valid_until > cutoff

    payload = resolved.to_payload()
    assert set(payload) == {
        "schema",
        "source_evidence",
        "selection",
        "source_occurrence_id",
        "reference_response_completed_at",
    }
    assert payload["schema"] == "simulated-execution-instrument-identity.v2"
    assert payload["source_evidence"]["source_observed_at"] is None
    assert payload["source_evidence"]["source_available_at"] is None
    assert payload["source_evidence"]["must_not_use_for_decision"] is True
    assert payload["source_evidence"]["must_not_execute"] is True
    assert type(resolved).from_payload(payload) == resolved
    assert calls["values"] == [(_ENVIRONMENT, _CONFIG_KEY, cutoff)] * 2
    assert calls["source_snapshots"] == [snapshot.snapshot_id] * 2
    assert calls["source_mappings"] == [snapshot.mapping_record.mapping_record_id] * 2
    assert len(calls["profiles"]) >= 4
    assert len(calls["runtime_snapshots"]) >= 4


@pytest.mark.parametrize(
    "missing",
    ["profile", "selector", "item", "snapshot", "mapping"],
)
def test_absent_selection_inputs_return_no_identity(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    """Absence stays distinct from a malformed or contradictory identity binding."""

    composition = _load_composition()
    snapshot = _synthetic_snapshot()
    selector: object = _selector(snapshot)
    profiles: list[Any] | None = None
    source_snapshot: Any = snapshot
    source_mapping: Any = snapshot.mapping_record
    runtime_value: object | None = None
    if missing == "profile":
        profiles = [None]
    elif missing == "selector":
        runtime_value = None
        selector = None
    elif missing == "item":
        selector = _selector(snapshot, asset_code="600009.SH")
    elif missing == "snapshot":
        source_snapshot = None
    else:
        source_mapping = None
    _install_ports(
        monkeypatch,
        composition,
        source_snapshot=source_snapshot,
        source_mapping=source_mapping,
        selector=selector,
        profile_sequence=profiles,
        runtime_value=runtime_value,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    result = reader.resolve_current_reference_identity(
        asset_code=_ASSET_CODE,
        as_of=_BASE + timedelta(seconds=180),
    )
    assert result is None


@pytest.mark.parametrize(
    "fault",
    [
        "security_id",
        "source_snapshot_hash",
        "runtime_snapshot_hash",
        "snapshot_projection",
        "source_code",
        "profile_switch",
        "future_profile",
        "raw_error",
        "unknown_board",
    ],
)
def test_contradictory_or_unverifiable_bindings_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    """Never downgrade a matching asset with contradictory evidence to a quiet miss."""

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    composition = _load_composition()
    snapshot = _synthetic_snapshot(
        board_market="unmatched-market" if fault == "unknown_board" else "fixture-main"
    )
    selector = _selector(snapshot)
    profile_sequence: list[Any] | None = None
    snapshot_sequence: list[Any] | None = None
    source_snapshot: Any = snapshot
    if fault == "source_snapshot_hash":
        item = selector["items"][0]
        item["snapshot_content_hash"] = "sha256:" + "f" * 64
        selector["items"] = [item]
    if fault == "source_code":
        item = selector["items"][0]
        item["source_code"] = "600009.SH"
        selector["items"] = [item]
    if fault == "runtime_snapshot_hash":
        from dataclasses import replace

        profile, runtime_snapshot = _runtime_metadata(selector)
        snapshot_sequence = [replace(runtime_snapshot, snapshot_hash="0" * 64)]
        profile_sequence = [profile]
    if fault == "snapshot_projection":
        from dataclasses import replace

        profile, runtime_snapshot = _runtime_metadata(selector)
        snapshot_sequence = [
            replace(runtime_snapshot, resolved_values={_CONFIG_KEY: {"tampered": True}})
        ]
        profile_sequence = [profile]
    if fault == "profile_switch":
        before, before_snapshot = _runtime_metadata(selector)
        after, after_snapshot = _runtime_metadata(
            selector,
            profile_id="switched-profile-id",
        )
        profile_sequence = [before, after]
        snapshot_sequence = [before_snapshot, after_snapshot]
    if fault == "future_profile":
        future, future_snapshot = _runtime_metadata(
            selector,
            profile_activated_at=_BASE + timedelta(seconds=200),
            snapshot_generated_at=_BASE + timedelta(seconds=220),
        )
        profile_sequence = [future]
        snapshot_sequence = [future_snapshot]
    calls = _install_ports(
        monkeypatch,
        composition,
        source_snapshot=source_snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
        profile_sequence=profile_sequence,
        snapshot_sequence=snapshot_sequence,
    )
    if fault == "raw_error":

        def fail_source_read(*, snapshot_id: UUID) -> Any:
            calls["source_snapshots"].append(snapshot_id)
            raise ValueError("exact raw evidence was tampered")

        monkeypatch.setattr(
            composition,
            "read_instrument_reference_snapshot",
            fail_source_read,
        )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    with pytest.raises(SimulatedTradeExecutionBlocked) as exc_info:
        if fault == "security_id":
            reader.get_execution_instrument_identity(
                security_id="risk-other-security",
                asset_code=_ASSET_CODE,
                as_of=_BASE + timedelta(seconds=180),
            )
        else:
            reader.resolve_current_reference_identity(
                asset_code=_ASSET_CODE,
                as_of=_BASE + timedelta(seconds=180),
            )
    if fault == "raw_error":
        assert calls["source_snapshots"] == [snapshot.snapshot_id]
        assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.parametrize(
    "mode",
    ["expiry_boundary", "mapping_cannot_refresh_old_occurrence"],
)
def test_local_reference_window_is_half_open_and_source_occurrence_anchored(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """A later mapping or batch response cannot extend this security's local-age end."""

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    if mode == "expiry_boundary":
        snapshot = _synthetic_snapshot()
        cutoff = _BASE + timedelta(seconds=620)
        selector = _selector(snapshot, age_seconds=600)
        metadata_times = (
            _BASE + timedelta(seconds=140),
            _BASE + timedelta(seconds=160),
        )
    else:
        snapshot = _synthetic_snapshot(mapping_recorded_at=_BASE + timedelta(seconds=400))
        cutoff = _BASE + timedelta(seconds=430)
        selector = _selector(snapshot, age_seconds=60)
        metadata_times = (
            _BASE + timedelta(seconds=410),
            _BASE + timedelta(seconds=420),
        )
    composition = _load_composition()
    profile, runtime_snapshot = _runtime_metadata(
        selector,
        profile_activated_at=metadata_times[0],
        snapshot_generated_at=metadata_times[1],
    )
    calls = _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
        profile_sequence=[profile],
        snapshot_sequence=[runtime_snapshot],
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.resolve_current_reference_identity(asset_code=_ASSET_CODE, as_of=cutoff)
    assert calls["values"] == [(_ENVIRONMENT, _CONFIG_KEY, cutoff)]


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_schema",
        "wrong_purpose",
        "extra_selector_key",
        "missing_selector_key",
        "schema_bool",
        "purpose_int",
        "age_bool",
        "age_float",
        "age_list",
        "items_int",
        "items_dict",
        "item_not_object",
        "extra_item_key",
        "missing_item_key",
        "security_id_bool",
        "asset_code_int",
        "source_code_list",
        "snapshot_id_bool",
        "snapshot_content_hash_list",
        "snapshot_record_digest_int",
        "mapping_record_id_list",
        "mapping_id_bool",
        "mapping_version_int",
        "mapping_content_hash_list",
        "mapping_record_digest_int",
    ),
)
def test_selector_schema_keys_and_exact_types_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject malformed selector envelopes and typed item pins without guessing."""

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    composition = _load_composition()
    snapshot = _synthetic_snapshot()
    selector = _selector(snapshot)
    item = selector["items"][0]
    if mutation == "wrong_schema":
        selector["schema"] = "normal-simulated-current-reference-selection.v2"
    elif mutation == "wrong_purpose":
        selector["purpose"] = "historical_backtest"
    elif mutation == "extra_selector_key":
        selector["unexpected"] = "must-be-rejected"
    elif mutation == "missing_selector_key":
        del selector["max_local_reference_age_seconds"]
    elif mutation == "schema_bool":
        selector["schema"] = True
    elif mutation == "purpose_int":
        selector["purpose"] = 1
    elif mutation == "age_bool":
        selector["max_local_reference_age_seconds"] = True
    elif mutation == "age_float":
        selector["max_local_reference_age_seconds"] = 600.0
    elif mutation == "age_list":
        selector["max_local_reference_age_seconds"] = []
    elif mutation == "items_int":
        selector["items"] = 1
    elif mutation == "items_dict":
        selector["items"] = {}
    elif mutation == "item_not_object":
        selector["items"] = [None]
    else:
        assert type(item) is dict
        if mutation == "extra_item_key":
            item["unexpected"] = "must-be-rejected"
        elif mutation == "missing_item_key":
            del item["source_code"]
        elif mutation == "security_id_bool":
            item["security_id"] = True
        elif mutation == "asset_code_int":
            item["asset_code"] = 600000
        elif mutation == "source_code_list":
            item["source_code"] = [_SOURCE_CODE]
        elif mutation == "snapshot_id_bool":
            item["snapshot_id"] = True
        elif mutation == "snapshot_content_hash_list":
            item["snapshot_content_hash"] = [snapshot.content_hash]
        elif mutation == "snapshot_record_digest_int":
            item["snapshot_record_digest"] = 1
        elif mutation == "mapping_record_id_list":
            item["mapping_record_id"] = [str(snapshot.mapping_record.mapping_record_id)]
        elif mutation == "mapping_id_bool":
            item["mapping_id"] = True
        elif mutation == "mapping_version_int":
            item["mapping_version"] = 1
        elif mutation == "mapping_content_hash_list":
            item["mapping_content_hash"] = [snapshot.mapping_record.content_hash]
        else:
            assert mutation == "mapping_record_digest_int"
            item["mapping_record_digest"] = 1

    cutoff = _BASE + timedelta(seconds=180)
    _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.resolve_current_reference_identity(asset_code=_ASSET_CODE, as_of=cutoff)


@pytest.mark.parametrize("duplicate", ("security_id", "asset_code", "source_code"))
def test_selector_rejects_duplicate_security_asset_or_source_ids(
    monkeypatch: pytest.MonkeyPatch,
    duplicate: str,
) -> None:
    """A duplicated selector key is contradictory even if only one item matches."""

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    composition = _load_composition()
    snapshot = _synthetic_snapshot()
    selector = _selector(snapshot)
    first = selector["items"][0]
    assert type(first) is dict
    second = dict(first)
    second["security_id"] = "risk-security-fixture-002"
    second["asset_code"] = "600001.SH"
    second["source_code"] = "600001.SH"
    second[duplicate] = first[duplicate]
    selector["items"] = [first, second]
    _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.resolve_current_reference_identity(
            asset_code=_ASSET_CODE,
            as_of=_BASE + timedelta(seconds=180),
        )


@pytest.mark.parametrize(
    "pin",
    (
        "mapping_record_id",
        "mapping_id",
        "mapping_version",
        "mapping_content_hash",
        "mapping_record_digest",
    ),
)
def test_selector_rejects_each_mismatched_mapping_pin(
    monkeypatch: pytest.MonkeyPatch,
    pin: str,
) -> None:
    """Every mapping pin is checked against a present, exact source mapping record."""

    from apps.data_center.domain.instrument_reference_snapshot import (
        make_instrument_reference_mapping_record,
    )
    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    composition = _load_composition()
    snapshot = _synthetic_snapshot()
    selector = _selector(snapshot)
    item = selector["items"][0]
    assert type(item) is dict
    selected_mapping = snapshot.mapping_record
    if pin == "mapping_record_id":
        old_id = snapshot.mapping_record.mapping_record_id
        next_value = (old_id.int + 1) % (1 << 128)
        alternate_id = UUID(int=next_value or 1)
        selected_mapping = make_instrument_reference_mapping_record(
            snapshot.mapping_record.content,
            mapping_record_id=alternate_id,
            recorded_at=snapshot.mapping_record.recorded_at,
        )
        item["mapping_record_id"] = str(selected_mapping.mapping_record_id)
        item["mapping_id"] = selected_mapping.content.mapping_id
        item["mapping_version"] = selected_mapping.content.mapping_version
        item["mapping_content_hash"] = selected_mapping.content_hash
        item["mapping_record_digest"] = selected_mapping.record_digest
    elif pin == "mapping_id":
        item[pin] = "different-mapping-id"
    elif pin == "mapping_version":
        item[pin] = "different-mapping-version"
    else:
        item[pin] = "sha256:" + "0" * 64

    _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=selected_mapping,
        selector=selector,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.resolve_current_reference_identity(
            asset_code=_ASSET_CODE,
            as_of=_BASE + timedelta(seconds=180),
        )


def test_equal_latest_occurrence_times_use_lexicographically_larger_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break equal response-clock ties deterministically by canonical UUID text."""

    from dataclasses import replace

    from apps.data_center.domain.instrument_reference_snapshot import (
        InstrumentReferenceSnapshotContent,
        make_instrument_reference_snapshot_record,
    )

    composition = _load_composition()
    original = _synthetic_snapshot()
    content = original.content
    occurrence_ids = (
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
    )
    tied_at = _BASE + timedelta(seconds=20)
    fetch_rounds = []
    for index, fetch_round in enumerate(content.fetch_rounds):
        if index >= 2:
            fetch_rounds.append(fetch_round)
            continue
        candidate = fetch_round.candidate
        occurrence = candidate.occurrences[0]
        tied_occurrence = replace(
            occurrence,
            occurrence_id=occurrence_ids[index],
            response_completed_at=tied_at,
        )
        tied_records = tuple(
            replace(record, occurrence_id=occurrence_ids[index]) for record in candidate.records
        )
        tied_candidate = replace(
            candidate,
            occurrences=(tied_occurrence,),
            records=tied_records,
        )
        fetch_rounds.append(replace(fetch_round, candidate=tied_candidate))
    tied_content = InstrumentReferenceSnapshotContent(
        run_id=content.run_id,
        mapping_record=content.mapping_record,
        fetch_rounds=tuple(fetch_rounds),
    )
    snapshot = make_instrument_reference_snapshot_record(
        tied_content,
        snapshot_id=original.snapshot_id,
        recorded_at=original.recorded_at,
    )
    selector = _selector(snapshot)
    _install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=snapshot.mapping_record,
        selector=selector,
    )
    reader = composition.build_current_reference_identity_reader(runtime_environment=_ENVIRONMENT)

    resolved = reader.resolve_current_reference_identity(
        asset_code=_ASSET_CODE,
        as_of=_BASE + timedelta(seconds=180),
    )

    assert str(occurrence_ids[0]) < str(occurrence_ids[1])
    assert tied_content.fetch_rounds[0].candidate.occurrences[0].response_completed_at == tied_at
    assert tied_content.fetch_rounds[1].candidate.occurrences[0].response_completed_at == tied_at
    assert resolved is not None
    assert resolved.source_occurrence_id == occurrence_ids[1]
    assert resolved.reference_response_completed_at == tied_at
