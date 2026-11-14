"""Root regressions for semantic classification and actual completion-time policy fences."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.config_center.domain.runtime_config import (
    RuntimeConfigSnapshot,
    hash_public_runtime_projection,
)
from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventReviewState
from apps.simulated_trading import transition_plan_event_review_composition as composition
from tests.unit.simulated_trading.test_transition_plan_event_review_composition import (
    _NOW,
    _classification,
    _PolicyEvidenceReader,
    _revision,
    _validator,
)


def test_configured_stock_type_label_does_not_become_an_unsupported_exchange():
    as_of = _NOW + timedelta(seconds=10)
    classification = _classification(
        as_of=as_of, source_exchange="SZSE", rule_market="SZ", simulated_asset_type="stock"
    )
    result = _validator(as_of=as_of, enabled=True, classification=classification).assess(
        _revision(asset_type="stock", classification_hash=classification.content_hash), as_of=as_of
    )
    assert result.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
    assert result.reason_code == "EVENT_COVERAGE_PIN_MISSING"


def test_unrelated_us_repeated_read_clock_alone_does_not_invalidate_original_plan():
    old_at = _NOW + timedelta(seconds=5)
    as_of = _NOW + timedelta(seconds=10)
    original = _classification(as_of=old_at, source_exchange="NASDAQ", rule_market="US")
    identity = replace(
        original.identity_evidence,
        selection=replace(original.identity_evidence.selection, selected_at=as_of),
    )
    current = replace(original, identity_evidence=identity, read_at=as_of)
    result = _validator(as_of=as_of, enabled=True, classification=current).assess(
        _revision(classification_hash=original.content_hash), as_of=as_of
    )
    assert result.state is TransitionPlanEventReviewState.UNCHANGED


def test_disabled_policy_is_reread_after_io_and_same_value_profile_swap_blocks():
    as_of = _NOW + timedelta(seconds=10)
    inner = _PolicyEvidenceReader(False, as_of=as_of)
    calls = []

    def read(**kwargs):
        calls.append(kwargs)
        first = inner.read_active_evidence(**{**kwargs, "as_of": as_of})
        if len(calls) > 1:
            profile = replace(first.profile, profile_id="new-profile")
            snapshot = replace(first.snapshot, profile_id="new-profile", snapshot_id="new-snapshot")
            return replace(first, profile=profile, snapshot=snapshot, read_at=kwargs["as_of"])
        return first

    validator = _validator(as_of=as_of, enabled=False, classification=None)
    validator._policy_evidence_reader = SimpleNamespace(read_active_evidence=read)
    result = validator.assess(_revision(), as_of=as_of)
    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert len(calls) >= 2


def test_runtime_snapshot_post_init_does_not_verify_its_actual_value_hash():
    as_of = _NOW + timedelta(seconds=10)
    validator = _validator(as_of=as_of, enabled=False, classification=None)
    evidence = validator._policy_evidence_reader.read_active_evidence(
        runtime_environment="development",
        definition_key="config_center.market.simulated_disclosure_coverage_policy",
        as_of=as_of,
    )
    old = evidence.snapshot
    snapshot = RuntimeConfigSnapshot(
        old.snapshot_id,
        old.profile_id,
        old.profile_key,
        old.profile_version,
        "f" * 64,
        dict(old.resolved_values),
        old.generated_at,
        old.effective_from,
    )
    snapshot.__post_init__()  # This checks shape, not the complete stored-value digest.
    validator._policy_evidence_reader = SimpleNamespace(
        read_active_evidence=lambda **kwargs: replace(evidence, snapshot=snapshot)
    )
    assert (
        validator.assess(_revision(), as_of=as_of).state is TransitionPlanEventReviewState.BLOCKED
    )


def test_disabled_plan_still_checks_actual_finish_clock_and_revision_expiry(monkeypatch):
    as_of = _NOW + timedelta(seconds=10)
    revision = _revision()
    monkeypatch.setattr(timezone, "now", lambda: revision.identity.valid_until)
    validator = _validator(as_of=as_of, enabled=False, classification=None)
    validator._clock = SimpleNamespace(now=timezone.now)
    result = validator.assess(revision, as_of=as_of)
    assert result.state is TransitionPlanEventReviewState.BLOCKED


def test_current_unrelated_scope_preserves_originals_while_completion_clocks_advance():
    as_of = _NOW + timedelta(seconds=10)
    original = _classification(as_of=as_of, source_exchange="NASDAQ", rule_market="US")
    validator = _validator(as_of=as_of, enabled=True, classification=original)
    evidence = validator._policy_evidence_reader.read_active_evidence(
        runtime_environment="development",
        definition_key="config_center.market.simulated_disclosure_coverage_policy",
        as_of=as_of,
    )
    validator._policy_evidence_reader = SimpleNamespace(
        read_active_evidence=lambda **kwargs: replace(evidence, read_at=kwargs["as_of"])
    )

    def classification(**kwargs):
        clock = kwargs["as_of"]
        return replace(
            original,
            identity_evidence=replace(
                original.identity_evidence,
                selection=replace(original.identity_evidence.selection, selected_at=clock),
            ),
            read_at=clock,
        )

    validator._classification_reader = SimpleNamespace(
        resolve_simulated_instrument_classification=classification
    )
    clocks = iter(
        (as_of + timedelta(seconds=1), as_of + timedelta(seconds=2), as_of + timedelta(seconds=3))
    )
    validator._clock = SimpleNamespace(now=lambda: next(clocks))
    result = validator.assess(_revision(classification_hash=original.content_hash), as_of=as_of)
    assert result.state is TransitionPlanEventReviewState.UNCHANGED
    assert original.read_at == as_of


def test_classification_source_profile_change_during_final_io_blocks():
    as_of = _NOW + timedelta(seconds=10)
    original = _classification(as_of=as_of, source_exchange="NASDAQ", rule_market="US")
    validator = _validator(as_of=as_of, enabled=True, classification=original)
    calls = []

    def classification(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return original
        identity = replace(
            original.identity_evidence,
            selection=replace(original.identity_evidence.selection, profile_content_hash="d" * 64),
        )
        return replace(original, identity_evidence=identity)

    validator._classification_reader = SimpleNamespace(
        resolve_simulated_instrument_classification=classification
    )
    result = validator.assess(_revision(classification_hash=original.content_hash), as_of=as_of)
    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_CLASSIFICATION_CHANGED_DURING_READ"


def test_classification_expiry_during_last_io_blocks_even_without_new_event():
    as_of = _NOW + timedelta(seconds=10)
    original = _classification(as_of=as_of, source_exchange="NASDAQ", rule_market="US")
    selector = replace(original.selector, max_local_reference_age_seconds=601)
    selection = replace(
        original.identity_evidence.selection,
        max_local_reference_age_seconds=601,
        selector_content_hash=selector.content_hash,
    )
    identity = replace(
        original.identity_evidence,
        selection=selection,
        source_evidence=replace(
            original.identity_evidence.source_evidence,
            identity_valid_until=as_of + timedelta(seconds=1),
        ),
    )
    current = replace(original, selector=selector, identity_evidence=identity)
    validator = _validator(as_of=as_of, enabled=True, classification=current)
    clocks = iter((as_of, as_of, as_of + timedelta(seconds=2)))
    validator._clock = SimpleNamespace(now=lambda: next(clocks))
    assert (
        validator.assess(_revision(classification_hash=current.content_hash), as_of=as_of).state
        is TransitionPlanEventReviewState.BLOCKED
    )


def _install_optional_snapshot(
    monkeypatch, *, present=False, bad_hash=False, missing_profile=False
):
    as_of = _NOW + timedelta(seconds=10)
    validator = _validator(as_of=as_of, enabled=False, classification=None)
    evidence = validator._policy_evidence_reader.read_active_evidence(
        runtime_environment="development",
        definition_key="config_center.market.simulated_disclosure_coverage_policy",
        as_of=as_of,
    )
    values = {evidence.definition_key: None} if present else {}
    snapshot = replace(
        evidence.snapshot,
        resolved_values=values,
        snapshot_hash="f" * 64 if bad_hash else hash_public_runtime_projection(values),
    )
    monkeypatch.setattr(
        composition,
        "ConfigCenterDisclosurePolicyEvidenceReader",
        lambda: SimpleNamespace(read_active_evidence=lambda **kwargs: None),
    )
    monkeypatch.setattr(
        composition,
        "get_active_runtime_profile",
        lambda environment: None if missing_profile else evidence.profile,
    )
    monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: snapshot)
    monkeypatch.setattr(composition, "get_active_runtime_value", lambda **kwargs: None)
    validator._policy_evidence_reader = composition._CurrentOptionalPolicyEvidenceReader()
    return validator, as_of


def test_complete_current_snapshot_proves_optional_m1_key_absent_without_fabricating_disabled_value(
    monkeypatch,
):
    validator, as_of = _install_optional_snapshot(monkeypatch)
    result = validator.assess(_revision(), as_of=as_of)
    assert result.state is TransitionPlanEventReviewState.UNCHANGED
    evidence = validator._policy_evidence_reader.read_active_evidence(
        runtime_environment="development",
        definition_key="config_center.market.simulated_disclosure_coverage_policy",
        as_of=as_of,
    )
    assert evidence.value is None
    assert evidence.definition_key not in evidence.snapshot.resolved_values


def test_missing_metadata_is_not_a_proved_absent_optional_feature(monkeypatch):
    validator, as_of = _install_optional_snapshot(monkeypatch, missing_profile=True)
    assert (
        validator.assess(_revision(), as_of=as_of).state is TransitionPlanEventReviewState.BLOCKED
    )


def test_invalid_complete_snapshot_hash_cannot_prove_optional_feature_absence(monkeypatch):
    validator, as_of = _install_optional_snapshot(monkeypatch, bad_hash=True)
    assert (
        validator.assess(_revision(), as_of=as_of).state is TransitionPlanEventReviewState.BLOCKED
    )


def test_present_null_value_is_malformed_configuration_not_proved_absence(monkeypatch):
    validator, as_of = _install_optional_snapshot(monkeypatch, present=True)
    assert (
        validator.assess(_revision(), as_of=as_of).state is TransitionPlanEventReviewState.BLOCKED
    )
