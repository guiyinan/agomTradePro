"""Synthetic adapter boundaries; actual PostgreSQL/source qualification is tested separately."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading import corporate_action_tax_cash_coverage_composition as composition
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageStatus,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading import (
    test_execution_instrument_classification as classification_fixtures,
)
from tests.unit.simulated_trading.test_simulated_account_row_source_v2 import _at, _raw, _source


def _classification(
    *,
    as_of: datetime,
    code: str = "001211.SZ",
    source_at: datetime | None = None,
    source_exchange: str = "SZSE",
    rule_market: str = "SZ",
    profile_content_hash: str = "e" * 64,
) -> SimulatedInstrumentClassificationEvidenceV1:
    """Build actual V2 selector and source evidence for the exact SZ asset fixture."""

    selector_template = classification_fixtures._selector()
    selector_item = replace(
        selector_template.items[0],
        security_id=code,
        asset_code=code,
        source_code=code,
    )
    selector = replace(selector_template, items=(selector_item,))
    identity_template = classification_fixtures._identity(selector_template)
    source_clock = source_at or as_of - timedelta(minutes=10)
    snapshot_at = source_clock + timedelta(minutes=5)
    mapping_at = source_clock + timedelta(minutes=4)
    activated_at = source_clock - timedelta(hours=1)
    selection = replace(
        identity_template.selection,
        selector_content_hash=selector.content_hash,
        profile_content_hash=profile_content_hash,
        profile_activated_at=activated_at,
        runtime_snapshot_generated_at=source_clock + timedelta(minutes=3),
        selected_at=as_of,
    )
    source = replace(
        identity_template.source_evidence,
        security_id=code,
        asset_code=code,
        source_code=code,
        source_exchange=source_exchange,
        source_market=source_exchange,
        rule_market=rule_market,
        board="MAIN",
        first_seen_at=source_clock,
        snapshot_recorded_at=snapshot_at,
        mapping_recorded_at=mapping_at,
        response_completed_at=source_clock,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(activated_at, snapshot_at, mapping_at),
        identity_valid_until=source_clock
        + timedelta(seconds=selection.max_local_reference_age_seconds),
        must_not_use_for_decision=False,
        must_not_execute=False,
    )
    identity = replace(
        identity_template,
        source_evidence=source,
        selection=selection,
        reference_response_completed_at=source_clock,
    )
    return SimulatedInstrumentClassificationEvidenceV1(
        selector=selector,
        identity_evidence=identity,
        read_at=as_of,
    )


@pytest.fixture
def context(monkeypatch):
    source = _source(raw=_raw(row_user_id=29, raw_account_type="simulated"))
    account = SimpleNamespace(
        pk=7, user_id=29, created_at=source.row_created_at, updated_at=source.row_updated_at
    )
    clock = [_at(5)]
    monkeypatch.setattr(composition.timezone, "now", lambda: clock[0])

    class SyntheticRetainedMapping:
        def __init__(self, **kwargs):
            pass

        def lock_current_sources_for_read(self):
            pass

        def get_physical_account_heads(self, **kwargs):
            return (SimpleNamespace(source=source),)

    monkeypatch.setattr(
        composition, "DjangoSimulatedAccountRowSourceV2Repository", SyntheticRetainedMapping
    )
    monkeypatch.setattr(
        composition, "read_locked_corporate_action_tax_payable", lambda **kwargs: Decimal("0")
    )
    monkeypatch.setattr(
        composition,
        "read_locked_owner_corporate_action_posting_state",
        lambda **kwargs: SimpleNamespace(audit_receipts=()),
    )
    origin_at = _at(1)
    origin = SimpleNamespace(
        origin_at=origin_at,
        origin_on=_at(1).date(),
        decision_on=_at(5).date(),
        timezone_policy=SimpleNamespace(policy_id="synthetic-only", policy_sha256="a" * 64),
    )

    class SyntheticOwnershipReader:
        def read_verified_zero_origin_calendar(self, **kwargs):
            return origin

        def read_verified_zero_origin_at(self, **kwargs):
            return origin_at

    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        lambda **kwargs: SyntheticOwnershipReader(),
    )
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: _classification(
                as_of=kwargs["as_of"], source_at=_at(5) - timedelta(minutes=10)
            )
        ),
        raising=False,
    )
    reader = composition.DjangoCorporateActionTaxCashCoverageReader(runtime_environment="test")
    monkeypatch.setattr(reader, "_account", lambda **kwargs: account)
    monkeypatch.setattr(reader, "_asset_codes", lambda account: ("001211.SZ",))
    monkeypatch.setattr(reader, "_cover_asset", lambda **kwargs: ("b" * 64, _at(4), _at(6)))
    return reader, account, clock


def test_zero_accepted_debt_requires_independent_event_history_coverage(context, monkeypatch):
    reader, account, _ = context

    def missing(**kwargs):
        raise BusinessLogicError("missing independent history")

    monkeypatch.setattr(reader, "_cover_asset", missing)
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.accepted_unpaid_tax == Decimal("0")
    assert result.coverage_status is TaxCashCoverageStatus.UNKNOWN
    assert result.tax_cash_unavailable is None
    assert not reader._witnesses


def test_covered_current_inputs_keep_original_deadline_and_canonical_identity(context):
    reader, _, clock = context
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.query.canonical_account_id == "0007"
    assert result.valid_until == _at(5) + timedelta(minutes=50)
    assert result.tax_cash_unavailable == Decimal("0")
    clock[0] += timedelta(seconds=1)
    reader.assert_still_current(result, using="default")
    assert result.valid_until == _at(5) + timedelta(minutes=50)


def test_final_source_epoch_change_blocks_even_with_same_debt(context, monkeypatch):
    reader, _, _ = context
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    monkeypatch.setattr(reader, "_cover_asset", lambda **kwargs: ("c" * 64, _at(4), _at(6)))
    with pytest.raises(BusinessLogicError):
        reader.assert_still_current(result, using="default")


def test_source_io_expiry_cannot_renew_original_coverage(context):
    reader, _, clock = context
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    clock[0] = result.valid_until
    with pytest.raises(BusinessLogicError):
        reader.assert_still_current(result, using="default")


def test_empty_asset_universe_still_requires_verified_zero_origin(context, monkeypatch):
    reader, _, _ = context
    monkeypatch.setattr(reader, "_asset_codes", lambda account: ())

    def missing(**kwargs):
        raise BusinessLogicError("no immutable zero origin")

    monkeypatch.setattr(composition, "build_corporate_action_ownership_history_repository", missing)
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.tax_cash_unavailable is None


def test_empty_asset_universe_uses_anchor_without_exchange_calendar(context, monkeypatch):
    reader, _, _ = context
    monkeypatch.setattr(reader, "_asset_codes", lambda account: ())

    class CalendarIndependentOrigin:
        def read_verified_zero_origin_at(self, **kwargs):
            return _at(1)

        def read_verified_zero_origin_calendar(self, **kwargs):
            raise AssertionError("empty ownership must not require an exchange calendar")

    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        lambda **kwargs: CalendarIndependentOrigin(),
    )
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: pytest.fail("an empty asset set has no classification scope"),
        raising=False,
    )
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.coverage_status is TaxCashCoverageStatus.COMPLETE
    assert result.tax_cash_unavailable == Decimal("0")


def test_nonempty_coverage_requires_explicit_szse_classification(context, monkeypatch):
    reader, _, _ = context
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: None
        ),
    )
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.coverage_status is TaxCashCoverageStatus.UNKNOWN
    assert result.tax_cash_unavailable is None


@pytest.mark.parametrize("changes", [{"source_exchange": "SSE"}, {"rule_market": "SH"}])
def test_non_szse_or_wrong_rule_market_classification_is_unknown(context, monkeypatch, changes):
    reader, _, _ = context
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: _classification(
                as_of=kwargs["as_of"], **changes
            )
        ),
    )
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.coverage_status is TaxCashCoverageStatus.UNKNOWN
    assert result.tax_cash_unavailable is None


def test_wrong_security_or_asset_classification_is_unknown(context, monkeypatch):
    reader, _, _ = context
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: _classification(
                as_of=kwargs["as_of"], code="001212.SZ"
            )
        ),
    )
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert result.coverage_status is TaxCashCoverageStatus.UNKNOWN
    assert result.tax_cash_unavailable is None


def test_explicit_szse_empty_window_can_complete_synthetically(context, monkeypatch):
    """A typed SZSE/SZ class may bind a fully read empty source-window fixture."""

    reader, _, _ = context
    empty_window_sha = composition._digest({"exchange": "SZSE", "events": ()})
    monkeypatch.setattr(
        reader,
        "_cover_asset",
        lambda **kwargs: (empty_window_sha, _at(4), _at(6)),
    )

    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")

    assert result.coverage_status is TaxCashCoverageStatus.COMPLETE
    assert result.coverage_sha256 is not None


def test_final_classification_change_invalidates_the_original_epoch(context, monkeypatch):
    reader, _, _ = context
    classifications = iter(
        (
            _classification(as_of=_at(5)),
            _classification(as_of=_at(5), profile_content_hash="f" * 64),
        )
    )
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: next(classifications)
        ),
    )
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    with pytest.raises(BusinessLogicError):
        reader.assert_still_current(proof, using="default")


def test_local_classification_reread_clocks_do_not_change_original_source_epoch(
    context, monkeypatch
):
    reader, _, clock = context
    source_at = _at(5) - timedelta(minutes=10)

    class AdvancingClassificationReader:
        def resolve_simulated_instrument_classification(self, **kwargs):
            return _classification(as_of=kwargs["as_of"], source_at=source_at)

    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: AdvancingClassificationReader(),
    )
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    clock[0] += timedelta(seconds=1)
    reader.assert_still_current(proof, using="default")
    assert proof.valid_until == source_at + timedelta(seconds=3600)


def test_a_different_reader_cannot_accept_an_unread_witness(context):
    reader, _, _ = context
    result = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    other = composition.DjangoCorporateActionTaxCashCoverageReader(runtime_environment="test")
    with pytest.raises(BusinessLogicError):
        other.assert_still_current(result, using="default")


def test_initial_coverage_cannot_clear_a_changed_physical_row(context):
    reader, account, _ = context
    account.updated_at += timedelta(seconds=1)
    with pytest.raises(BusinessLogicError):
        reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")


def test_final_reread_accepts_only_the_exact_explicit_same_transaction_write(context):
    reader, account, _ = context
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    account.updated_at += timedelta(seconds=1)
    with pytest.raises(BusinessLogicError):
        reader.assert_still_current(proof, using="default")
    reader.assert_still_current(
        proof, using="default", expected_account_updated_at=account.updated_at
    )
    with pytest.raises(BusinessLogicError):
        reader.assert_still_current(
            proof,
            using="default",
            expected_account_updated_at=account.updated_at + timedelta(seconds=1),
        )


def test_tax_complete_without_independent_entitlement_witness_cannot_publish_rights(context):
    reader, _, _ = context
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert proof.coverage_status is TaxCashCoverageStatus.COMPLETE
    with pytest.raises(BusinessLogicError):
        reader.read_current_entitlement_coverage(proof, using="default")


def test_genuine_empty_asset_universe_returns_only_empty_rights_with_original_finite_lease(
    context, monkeypatch
):
    reader, _, clock = context
    monkeypatch.setattr(reader, "_asset_codes", lambda account: ())
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    assert proof.coverage_status is TaxCashCoverageStatus.COMPLETE
    assert reader.read_current_entitlement_coverage(proof, using="default") == ()
    original_deadline = proof.valid_until
    clock[0] = original_deadline
    with pytest.raises(BusinessLogicError):
        reader.read_current_entitlement_coverage(proof, using="default")
    assert proof.valid_until == original_deadline


def test_entitlement_getter_rejects_physical_row_version_changed_after_coverage(
    context, monkeypatch
):
    reader, account, _ = context
    monkeypatch.setattr(reader, "_asset_codes", lambda account: ())
    proof = reader.read_locked(physical_account_id=7, owner_user_id=29, using="default")
    account.updated_at += timedelta(seconds=1)
    with pytest.raises(BusinessLogicError):
        reader.read_current_entitlement_coverage(proof, using="default")


def test_coverage_logs_only_stable_failure_metadata(context, monkeypatch, caplog):
    reader, account, _ = context

    def fail(**kwargs):
        raise BusinessLogicError("OPAQUE_SECRET_DO_NOT_LOG", code="TAX_TEST_UNVERIFIED")

    monkeypatch.setattr(composition, "read_locked_corporate_action_tax_payable", fail)
    result, _ = reader._read(account=account, codes=())
    assert result.coverage_status is TaxCashCoverageStatus.UNKNOWN
    assert "accepted_tax_payable" in caplog.text
    assert "TAX_TEST_UNVERIFIED" in caplog.text
    assert "OPAQUE_SECRET" not in caplog.text
