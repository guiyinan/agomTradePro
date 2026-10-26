"""Pure Domain cases for source identity, explicit validity, limits, and falsification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskObservation,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RiskApplicability,
    RiskConditionOutcome,
    RiskQualificationState,
    evaluate_falsification,
    qualify_revision,
    validate_publish_command,
)

KNOWN_AT = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
EFFECTIVE_FROM = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
EFFECTIVE_UNTIL = datetime(2026, 12, 31, 0, 0, tzinfo=UTC)


def _source_snapshot(
    *, account_stop_loss_pct: Decimal | None = Decimal("8")
) -> M1RiskSourceSnapshot:
    """Build an exact manual-account source with no Strategy selected."""

    return M1RiskSourceSnapshot(
        account_id=701,
        account_owner_user_id=77,
        account_type="simulated",
        account_is_active=True,
        account_max_single_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=account_stop_loss_pct,
        strategy_selection_state="confirmed_unconfigured",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )


def _revision(
    *,
    source: M1RiskSourceSnapshot | None = None,
    revoked_at: datetime | None = None,
    revoked_by_user_id: int | None = None,
    revocation_reason: str | None = None,
) -> M1RiskPolicyRevision:
    """Create an explicit version independent of strategy_version and timestamps."""

    selected_source = source or _source_snapshot()
    return M1RiskPolicyRevision(
        risk_policy_version="1b83f7a7-2182-41f8-a741-7edcd0d993ec",
        account_id=selected_source.account_id,
        actor_user_id=77,
        effective_from=EFFECTIVE_FROM,
        effective_until=EFFECTIVE_UNTIL,
        known_at=KNOWN_AT,
        reason="Owner approved an M1-only preview policy.",
        max_single_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("7")),
        source_snapshot=selected_source,
        revocation_state=(
            "unknown"
            if revoked_at is not None and revoked_by_user_id is None
            else "revoked" if revoked_at is not None else "not_revoked"
        ),
        revoked_at=revoked_at,
        revoked_by_user_id=revoked_by_user_id,
        revocation_reason=revocation_reason,
    )


def _publish_command(
    *,
    source: M1RiskSourceSnapshot | None = None,
    max_single_position: M1RiskCondition | None = None,
) -> M1RiskPolicyPublishCommand:
    """Build an owner command whose limits do not widen current numeric caps."""

    selected_source = source or _source_snapshot()
    return M1RiskPolicyPublishCommand(
        account_id=selected_source.account_id,
        actor_user_id=77,
        effective_from=EFFECTIVE_FROM,
        effective_until=EFFECTIVE_UNTIL,
        reason="Owner approved an M1-only preview policy.",
        max_single_position=max_single_position
        or M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("7")),
        source_snapshot=selected_source,
    )


def test_owner_m1_revision_qualifies_only_inside_explicit_aware_window() -> None:
    """The stored risk version and effective window are independent of old rule fields."""

    source = _source_snapshot()
    revision = _revision(source=source)
    at_start = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )
    at_end = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=EFFECTIVE_UNTIL,
        current_source=source,
    )

    assert revision.risk_policy_version != str(source.strategy_version)
    assert at_start.state is RiskQualificationState.QUALIFIED
    assert at_start.ready_for_buy is True
    assert at_end.state is RiskQualificationState.NOT_EFFECTIVE
    assert at_end.ready_for_buy is False


def test_source_content_change_invalidates_the_published_revision() -> None:
    """A changed account risk value invalidates this exact owner-reviewed snapshot."""

    qualification = qualify_revision(
        revision=_revision(),
        account_id=701,
        as_of=EFFECTIVE_FROM + timedelta(days=1),
        current_source=replace(
            _source_snapshot(),
            account_max_total_position_pct=Decimal("94"),
        ),
    )

    assert qualification.state is RiskQualificationState.SOURCE_CHANGED
    assert qualification.reason_codes == ("M1_RISK_POLICY_SOURCE_CHANGED",)
    assert qualification.ready_for_buy is False


def test_account_owner_change_invalidates_the_previous_owner_revision() -> None:
    """A transfer cannot make an old actor's owner decision valid for a new owner."""

    qualification = qualify_revision(
        revision=_revision(),
        account_id=701,
        as_of=EFFECTIVE_FROM + timedelta(days=1),
        current_source=replace(_source_snapshot(), account_owner_user_id=78),
    )

    assert qualification.state is RiskQualificationState.SOURCE_CHANGED
    assert qualification.reason_codes == ("M1_RISK_POLICY_OWNER_SOURCE_CHANGED",)
    assert qualification.ready_for_buy is False


def test_null_stop_loss_remains_unknown_even_when_policy_has_an_explicit_value() -> None:
    """A new M1 rule never rewrites a legacy SQL NULL into zero or disabled."""

    source = _source_snapshot(account_stop_loss_pct=None)
    qualification = qualify_revision(
        revision=_revision(source=source),
        account_id=701,
        as_of=EFFECTIVE_FROM + timedelta(days=1),
        current_source=source,
    )

    assert qualification.state is RiskQualificationState.UNKNOWN
    assert "ACCOUNT_STOP_LOSS_SOURCE_UNKNOWN" in qualification.reason_codes
    assert qualification.ready_for_buy is False


def test_explicit_owner_not_applicable_is_distinct_from_unknown() -> None:
    """A reasoned owner declaration is retained as N/A, not inferred from NULL."""

    explicit_na = M1RiskCondition(
        applicability=RiskApplicability.NOT_APPLICABLE,
        limit_pct=None,
        not_applicable_reason="The owner excludes this dimension from this M1 policy.",
    )
    explicit_unknown = M1RiskCondition(
        applicability=RiskApplicability.UNKNOWN,
        limit_pct=None,
    )
    assert explicit_na.applicability is RiskApplicability.NOT_APPLICABLE
    assert explicit_unknown.applicability is RiskApplicability.UNKNOWN
    assert explicit_na != explicit_unknown


def test_unconfigured_legacy_stop_loss_is_not_required_for_an_empty_plan() -> None:
    """A true N/A stop-loss state preserves legacy NULL without inventing a limit."""

    source = _source_snapshot(account_stop_loss_pct=None)
    revision = replace(
        _revision(source=source),
        max_stop_loss=M1RiskCondition(
            applicability=RiskApplicability.NOT_APPLICABLE,
            limit_pct=None,
            not_applicable_reason="No existing holdings are in scope for stop-loss measurement.",
        ),
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )
    result = evaluate_falsification(
        qualification=qualification,
        observations=(
            M1RiskObservation(
                dimension="max_single_position",
                applicability=RiskApplicability.NOT_APPLICABLE,
                observed_pct=None,
            ),
            M1RiskObservation(
                dimension="max_total_position",
                applicability=RiskApplicability.NOT_APPLICABLE,
                observed_pct=None,
            ),
            M1RiskObservation(
                dimension="max_stop_loss",
                applicability=RiskApplicability.NOT_APPLICABLE,
                observed_pct=None,
            ),
        ),
    )

    assert source.account_stop_loss_pct is None
    assert qualification.state is RiskQualificationState.QUALIFIED
    assert result.status == "not_applicable"
    assert result.conditions[2].policy_applicability is RiskApplicability.NOT_APPLICABLE
    assert result.conditions[2].observation_applicability is RiskApplicability.NOT_APPLICABLE
    assert result.conditions[2].outcome is RiskConditionOutcome.NOT_APPLICABLE


def test_explicit_n_a_keeps_its_status_when_runtime_has_a_buy_observation() -> None:
    """N/A is valid only for a dimension with no configured legacy limit."""

    source = replace(_source_snapshot(), account_max_single_position_pct=None)
    revision = replace(
        _revision(source=source),
        max_single_position=M1RiskCondition(
            applicability=RiskApplicability.NOT_APPLICABLE,
            limit_pct=None,
            not_applicable_reason="This dimension was left unconfigured at publication.",
        ),
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )
    result = evaluate_falsification(
        qualification=qualification,
        observations=(
            M1RiskObservation(
                dimension="max_single_position",
                applicability=RiskApplicability.APPLICABLE,
                observed_pct=Decimal("10"),
            ),
            M1RiskObservation(
                dimension="max_total_position",
                applicability=RiskApplicability.APPLICABLE,
                observed_pct=Decimal("80"),
            ),
            M1RiskObservation(
                dimension="max_stop_loss",
                applicability=RiskApplicability.NOT_APPLICABLE,
                observed_pct=None,
            ),
        ),
    )

    assert qualification.state is RiskQualificationState.QUALIFIED
    assert result.status == "not_falsified"
    assert result.conditions[0].policy_applicability is RiskApplicability.NOT_APPLICABLE
    assert result.conditions[0].observation_applicability is RiskApplicability.APPLICABLE
    assert result.conditions[0].threshold_pct is None
    assert result.conditions[0].outcome is RiskConditionOutcome.NOT_APPLICABLE


def test_owner_cannot_declare_configured_account_cap_not_applicable() -> None:
    """A configured hard cap must be represented in the new revision contract."""

    command = _publish_command(
        max_single_position=M1RiskCondition(
            applicability=RiskApplicability.NOT_APPLICABLE,
            limit_pct=None,
            not_applicable_reason="Owner says this dimension is outside M1.",
        )
    )

    assert validate_publish_command(command) == (
        "M1_POLICY_OMITS_CONFIGURED_MAX_SINGLE_POSITION_LIMIT",
    )


def test_all_not_applicable_policy_is_not_a_qualified_buy_policy() -> None:
    """Three N/A assertions cannot produce an empty version that passes BUY."""

    source = replace(
        _source_snapshot(account_stop_loss_pct=None),
        account_max_single_position_pct=None,
        account_max_total_position_pct=None,
    )
    na = M1RiskCondition(
        applicability=RiskApplicability.NOT_APPLICABLE,
        limit_pct=None,
        not_applicable_reason="Owner confirms this limit is not configured.",
    )
    command = replace(
        _publish_command(source=source),
        max_single_position=na,
        max_total_position=na,
        max_stop_loss=na,
    )
    revision = replace(
        _revision(source=source),
        max_single_position=na,
        max_total_position=na,
        max_stop_loss=na,
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=source.account_id,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )

    assert "M1_POLICY_HAS_NO_APPLICABLE_LIMITS" in validate_publish_command(command)
    assert qualification.state is RiskQualificationState.UNKNOWN
    assert qualification.ready_for_buy is False
    assert "M1_RISK_POLICY_HAS_NO_APPLICABLE_LIMITS" in qualification.reason_codes


def test_qualification_and_falsification_reject_persisted_n_a_over_known_cap() -> None:
    """Persisted or forged N/A cannot hide an existing numeric account cap."""

    source = _source_snapshot()
    revision = replace(
        _revision(source=source),
        max_single_position=M1RiskCondition(
            applicability=RiskApplicability.NOT_APPLICABLE,
            limit_pct=None,
            not_applicable_reason="Forged N/A must not cover the account cap.",
        ),
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=source.account_id,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )
    falsification = evaluate_falsification(
        qualification=qualification,
        observations=(
            M1RiskObservation(
                "max_single_position",
                RiskApplicability.APPLICABLE,
                Decimal("10"),
            ),
            M1RiskObservation(
                "max_total_position",
                RiskApplicability.APPLICABLE,
                Decimal("80"),
            ),
            M1RiskObservation(
                "max_stop_loss",
                RiskApplicability.APPLICABLE,
                Decimal("2"),
            ),
        ),
    )

    assert qualification.state is RiskQualificationState.UNKNOWN
    assert "M1_POLICY_OMITS_CONFIGURED_MAX_SINGLE_POSITION_LIMIT" in qualification.reason_codes
    assert falsification.status == "unknown"
    assert falsification.conditions[0].outcome is RiskConditionOutcome.UNKNOWN
    assert falsification.conditions[0].predicate == (
        "configured_legacy_limit_must_be_covered_by_m1_policy"
    )


def test_publish_validation_rejects_widening_a_known_account_cap() -> None:
    """The additive M1 policy cannot set a looser cap than any known baseline."""

    command = _publish_command(
        max_single_position=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            Decimal("20.001"),
        )
    )

    assert validate_publish_command(command) == ("M1_POLICY_WIDENS_MAX_SINGLE_POSITION_LIMIT",)


def test_publish_validation_requires_the_authenticated_owner_source() -> None:
    """A typed command cannot bind one user's authorization to another account owner."""

    command = replace(
        _publish_command(),
        source_snapshot=replace(_source_snapshot(), account_owner_user_id=78),
    )

    assert validate_publish_command(command) == ("RISK_SOURCE_ACTOR_MISMATCH",)


def test_falsification_reports_real_threshold_observations_and_blocking_event() -> None:
    """The bound predicate exposes its threshold, measured percentage, and result."""

    source = _source_snapshot()
    qualification = qualify_revision(
        revision=_revision(source=source),
        account_id=701,
        as_of=EFFECTIVE_FROM + timedelta(days=1),
        current_source=source,
    )
    result = evaluate_falsification(
        qualification=qualification,
        observations=(
            M1RiskObservation(
                "max_single_position",
                RiskApplicability.APPLICABLE,
                Decimal("21"),
            ),
            M1RiskObservation(
                "max_total_position",
                RiskApplicability.APPLICABLE,
                Decimal("80"),
            ),
            M1RiskObservation(
                "max_stop_loss",
                RiskApplicability.APPLICABLE,
                Decimal("2"),
            ),
        ),
    )

    assert result.status == "falsified"
    assert result.conditions[0].predicate == "target_single_position_pct <= limit_pct"
    assert result.conditions[0].threshold_pct == Decimal("19")
    assert result.conditions[0].observed_pct == Decimal("21")
    assert result.conditions[0].outcome is RiskConditionOutcome.FALSIFIED
    assert "M1_RISK_FALSIFICATION_TRIGGERED" in result.reason_codes


def test_missing_runtime_observation_keeps_falsification_unknown() -> None:
    """A known policy version with missing measurements cannot make a BUY ready."""

    source = _source_snapshot()
    qualification = qualify_revision(
        revision=_revision(source=source),
        account_id=701,
        as_of=EFFECTIVE_FROM + timedelta(days=1),
        current_source=source,
    )
    result = evaluate_falsification(qualification=qualification, observations=())

    assert result.status == "unknown"
    assert all(item.outcome is RiskConditionOutcome.UNKNOWN for item in result.conditions)


def test_revocation_is_an_audit_event_and_never_mutates_revision_content() -> None:
    """An appended revocation event invalidates the version from its audit time."""

    revoked_at = EFFECTIVE_FROM + timedelta(days=2)
    revision = _revision(
        revoked_at=revoked_at,
        revoked_by_user_id=88,
        revocation_reason="The owner replaced this policy after reviewing new inputs.",
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=revoked_at,
        current_source=revision.source_snapshot,
    )
    before_revocation = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=revoked_at - timedelta(microseconds=1),
        current_source=revision.source_snapshot,
    )

    assert qualification.state is RiskQualificationState.REVOKED
    assert qualification.ready_for_buy is False
    assert before_revocation.state is RiskQualificationState.QUALIFIED
    assert revision.risk_policy_version == "1b83f7a7-2182-41f8-a741-7edcd0d993ec"


def test_revocation_audit_with_lost_actor_fails_closed() -> None:
    """SET_NULL audit cleanup cannot turn a revoked version back into a live one."""

    revoked_at = EFFECTIVE_FROM + timedelta(days=2)
    revision = _revision(
        revoked_at=revoked_at,
        revoked_by_user_id=None,
        revocation_reason="The event remains but its actor FK was removed.",
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=701,
        as_of=revoked_at,
        current_source=revision.source_snapshot,
    )

    assert qualification.state is RiskQualificationState.UNKNOWN
    assert qualification.reason_codes == ("M1_RISK_POLICY_REVOCATION_SOURCE_UNKNOWN",)
    assert qualification.ready_for_buy is False


def test_naive_policy_clock_is_rejected() -> None:
    """Every persisted and observed policy timestamp remains timezone-aware."""

    with pytest.raises(ValueError, match="effective_from must be timezone-aware"):
        replace(_revision(), effective_from=datetime(2026, 10, 26, 0, 0))
