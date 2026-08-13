"""Pure tests for Portfolio planning-policy two-person activation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
    validate_planning_policy_activation_successor,
)
from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition

NOW = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)


def _definition(**changes: object) -> PlanningPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "portfolio-policy-standard",
        "policy_version": "v1",
        "buy_lot_size": 100,
        "fee_rate": Decimal("0.0003"),
        "slippage_rate": Decimal("0.001"),
        "min_rebalance_value": Decimal("1000"),
        "max_asset_weight": Decimal("0.2"),
        "max_volume_participation": Decimal("0.1"),
        "recorded_at": NOW - timedelta(hours=2),
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return PlanningPolicyDefinition(**values)


def _actor(number: int) -> PlanningPolicyActivationActor:
    return PlanningPolicyActivationActor(
        actor_id=f"portfolio-staff-{number}",
        user_id=number,
        role="portfolio_policy_approver",
    )


def _subject(**changes: object) -> PlanningPolicyActivationSubject:
    values: dict[str, object] = {
        "subject_id": "planning-policy-activation-request-1",
        "subject_version": "v1",
        "definition": _definition(),
        "requested_by": _actor(11),
        "requested_at": NOW,
        "supersedes_activation_hash": None,
    }
    values.update(changes)
    return PlanningPolicyActivationSubject.create(**values)  # type: ignore[arg-type]


def _activation(**changes: object) -> PlanningPolicyActivation:
    values: dict[str, object] = {
        "activation_id": "planning-policy-activation-1",
        "activation_version": "v1",
        "subject": _subject(),
        "approved_by": _actor(12),
        "issued_at": NOW + timedelta(minutes=1),
    }
    values.update(changes)
    return PlanningPolicyActivation.create(**values)  # type: ignore[arg-type]


def test_subject_binds_exact_definition_and_requester() -> None:
    definition = _definition()
    subject = _subject(definition=definition)

    assert subject.policy_id == definition.policy_id
    assert subject.policy_version == definition.policy_version
    assert subject.definition_identity_hash == definition.identity_hash
    assert subject.definition_content_hash == definition.content_hash
    assert subject.valid_until == definition.valid_until
    assert subject.is_valid_at(NOW)
    assert len(subject.content_hash) == 64


def test_subject_rejects_definition_not_knowable_at_request() -> None:
    with pytest.raises(ValueError, match="not active"):
        _subject(definition=_definition(recorded_at=NOW + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="not active"):
        _subject(definition=_definition(valid_until=NOW))


def test_activation_requires_distinct_actor_and_user_identity() -> None:
    subject = _subject()
    with pytest.raises(ValueError, match="self approval"):
        _activation(subject=subject, approved_by=_actor(11))
    with pytest.raises(ValueError, match="self approval"):
        _activation(
            subject=subject,
            approved_by=PlanningPolicyActivationActor(
                actor_id="different-actor",
                user_id=11,
                role="portfolio_policy_approver",
            ),
        )


def test_activation_is_configuration_authority_not_execution_authority() -> None:
    activation = _activation()
    payload = activation.to_payload()

    assert activation.owner == "portfolio"
    assert activation.capability == "planning_policy_activation"
    assert activation.permission == "policy_configuration_only"
    assert activation.must_not_execute is True
    assert payload["must_not_execute"] is True
    assert activation.is_valid_at(activation.issued_at)
    assert not activation.is_valid_at(activation.valid_until)


def test_activation_hash_binds_subject_actor_and_clock() -> None:
    activation = _activation()
    changed_subject = _subject(subject_id="request-2")
    changed = _activation(subject=changed_subject)

    assert changed.content_hash != activation.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(activation, issued_at=activation.issued_at + timedelta(seconds=1))


def test_activation_rejects_invalid_or_extended_validity() -> None:
    activation = _activation()
    with pytest.raises(ValueError, match="validity"):
        replace(activation, valid_until=activation.valid_until - timedelta(seconds=1))
    with pytest.raises(ValueError, match="outside"):
        _activation(issued_at=activation.valid_until)


def test_successor_requires_same_policy_predecessor_and_forward_clock() -> None:
    previous = _activation()
    next_definition = _definition(policy_version="v2", fee_rate=Decimal("0.0004"))
    successor_subject = _subject(
        subject_id="request-2",
        subject_version="v2",
        definition=next_definition,
        requested_at=NOW + timedelta(hours=1),
        supersedes_activation_hash=previous.content_hash,
    )
    successor = _activation(
        activation_id="activation-2",
        activation_version="v2",
        subject=successor_subject,
        issued_at=NOW + timedelta(hours=1, minutes=1),
    )

    validate_planning_policy_activation_successor(previous, successor)
    with pytest.raises(ValueError, match="predecessor"):
        validate_planning_policy_activation_successor(
            previous,
            replace(
                successor,
                subject=replace(
                    successor.subject,
                    supersedes_activation_hash="a" * 64,
                    content_hash="",
                ),
                content_hash="",
            ),
        )


def test_domain_has_no_framework_or_cross_app_imports() -> None:
    source = Path("apps/portfolio/domain/planning_policy_activation.py").read_text(encoding="utf-8")

    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
