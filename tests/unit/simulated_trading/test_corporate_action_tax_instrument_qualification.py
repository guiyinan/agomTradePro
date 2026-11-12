"""Simulation scope must bind an exact source snapshot, currency and listing dates."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from apps.data_center.domain.instrument_reference_snapshot import (
    make_instrument_reference_mapping_record,
    make_instrument_reference_snapshot_record,
)
from apps.simulated_trading.corporate_action_tax_instrument_qualification import (
    qualify_simulated_dividend_tax_instrument,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading import test_execution_current_reference_reader as source
from tests.unit.simulated_trading.test_simulated_dividend_tax_policy_scope import _scope


def _inputs(monkeypatch: pytest.MonkeyPatch, **changes: object):
    """Build actual sealed source objects through the existing classification reader."""
    original = source._synthetic_snapshot()
    mapping = make_instrument_reference_mapping_record(
        replace(original.mapping_record.content, exchange_rule_market_pairs=(("SSE", "SH"),)),
        mapping_record_id=original.mapping_record.mapping_record_id,
        recorded_at=original.mapping_record.recorded_at,
    )
    rounds = tuple(
        replace(
            row,
            candidate=replace(
                row.candidate,
                provider_contract=replace(
                    row.candidate.provider_contract,
                    fields=(*row.candidate.provider_contract.fields, "curr_type"),
                ),
                records=tuple(
                    replace(
                        record,
                        source_currency=changes.get("currency", "CNY"),
                        list_date=date(2020, 1, 1),
                        list_date_raw="20200101",
                    )
                    for record in row.candidate.records
                ),
            ),
        )
        for row in original.content.fetch_rounds
    )
    snapshot = make_instrument_reference_snapshot_record(
        replace(original.content, mapping_record=mapping, fetch_rounds=rounds),
        snapshot_id=original.snapshot_id,
        recorded_at=original.recorded_at,
    )
    selector = source._selector(snapshot)
    selector["schema"] = "normal-simulated-current-reference-selection.v2"
    selector["items"][0]["simulated_asset_type"] = "explicit-synthetic-equity"
    composition = source._load_composition()
    source._install_ports(
        monkeypatch,
        composition,
        source_snapshot=snapshot,
        source_mapping=mapping,
        selector=selector,
    )
    cutoff = source._BASE + timedelta(seconds=180)
    classification = composition.build_current_reference_classification_reader(
        runtime_environment=source._ENVIRONMENT,
    ).resolve_simulated_instrument_classification(
        security_id=source._SECURITY_ID,
        asset_code=source._ASSET_CODE,
        as_of=cutoff,
    )
    assert classification is not None
    scope = replace(
        _scope(),
        security_id=source._SECURITY_ID,
        asset_code=source._ASSET_CODE,
        known_at=source._BASE - timedelta(days=3),
        valid_from=source._BASE - timedelta(days=2),
        valid_until=source._BASE + timedelta(days=2),
    )
    return scope, classification, snapshot, cutoff


def test_exact_native_classification_keeps_source_restrictions(monkeypatch):
    scope, classification, snapshot, cutoff = _inputs(monkeypatch)
    result = qualify_simulated_dividend_tax_instrument(
        scope=scope,
        classification=classification,
        snapshot=snapshot,
        record_date=date(2025, 5, 1),
        as_of=cutoff,
    )
    assert (
        result.valid_until == classification.identity_evidence.source_evidence.identity_valid_until
    )
    assert result.must_not_use_as_real_tax_proof is True
    assert snapshot.content.must_not_use_for_decision is True
    assert classification.identity_evidence.source_evidence.must_not_execute is True
    later_identity = replace(
        classification.identity_evidence,
        selection=replace(
            classification.identity_evidence.selection, selected_at=cutoff + timedelta(seconds=1)
        ),
    )
    later = replace(
        classification, identity_evidence=later_identity, read_at=cutoff + timedelta(seconds=1)
    )
    refreshed = qualify_simulated_dividend_tax_instrument(
        scope=scope,
        classification=later,
        snapshot=snapshot,
        record_date=date(2025, 5, 1),
        as_of=cutoff + timedelta(seconds=1),
    )
    assert result.semantic_sha256 == refreshed.semantic_sha256


@pytest.mark.parametrize("currency", [None, "USD", "HKD"])
def test_missing_or_non_cny_source_currency_blocks(monkeypatch, currency):
    scope, classification, snapshot, cutoff = _inputs(monkeypatch, currency=currency)
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_instrument(
            scope=scope,
            classification=classification,
            snapshot=snapshot,
            record_date=date(2025, 5, 1),
            as_of=cutoff,
        )


@pytest.mark.parametrize(
    "fault", ["security", "exchange", "snapshot", "future", "expired", "not_listed"]
)
def test_scope_source_and_clock_mismatches_block(monkeypatch, fault):
    scope, classification, snapshot, cutoff = _inputs(monkeypatch)
    record_date = date(2025, 5, 1)
    if fault == "security":
        scope = replace(scope, security_id="different-security")
    elif fault == "exchange":
        scope = replace(scope, exchange=type(scope.exchange)("SZ"))
    elif fault == "snapshot":
        snapshot = source._synthetic_snapshot()
    elif fault == "future":
        cutoff -= timedelta(seconds=1)
    elif fault == "expired":
        cutoff = classification.identity_evidence.source_evidence.identity_valid_until
    elif fault == "not_listed":
        record_date = date(2019, 12, 31)
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_instrument(
            scope=scope,
            classification=classification,
            snapshot=snapshot,
            record_date=record_date,
            as_of=cutoff,
        )
