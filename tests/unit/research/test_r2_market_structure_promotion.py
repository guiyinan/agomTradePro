"""Domain and strict-codec coverage for R2 promotion."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta, timezone

import pytest

from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureEvidenceSeal,
    R2MarketStructureLifecycleAction,
    R2MarketStructurePromotionDecisionOutcome,
    create_r2_market_structure_lifecycle_event,
    create_r2_market_structure_promotion_decision,
    derive_r2_market_structure_active_stack,
)
from apps.research.infrastructure.r2_market_structure_promotion_codec import (
    R2MarketStructurePromotionCodecError,
    decode_r2_market_structure_decision,
    decode_r2_market_structure_lifecycle_event,
    decode_r2_market_structure_policy,
    encode_r2_market_structure_decision,
    encode_r2_market_structure_lifecycle_event,
    encode_r2_market_structure_policy,
)
from apps.research.r2_market_structure_promotion_composition import (
    DjangoExactR2MarketStructureEvidenceProvider,
)
from tests.unit.data_center.test_market_structure import AS_OF
from tests.unit.research.r2_market_structure_promotion_factories import (
    HASH,
    make_r2_decision,
    make_r2_evidence,
    make_r2_lifecycle_authorization,
    make_r2_policy,
)


def test_promotion_approves_only_exact_published_descriptive_evidence() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    decision, _authorization = make_r2_decision(evidence, policy)

    assert decision.outcome is R2MarketStructurePromotionDecisionOutcome.APPROVED
    assert decision.research_only is True
    assert decision.structure_description_only is True
    assert decision.must_not_use_for_decision is True
    assert decision.must_not_execute is True
    assert decision.evidence.publication_datasets == policy.required_publication_datasets


def test_lifecycle_replays_promote_and_retire_without_exposing_a_signal() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    decision, _authorization = make_r2_decision(evidence, policy)
    promote = create_r2_market_structure_lifecycle_event(
        history=(),
        decision=decision,
        authorization=make_r2_lifecycle_authorization(decision),
        rollback_target=None,
    )
    retire = create_r2_market_structure_lifecycle_event(
        history=(promote,),
        decision=decision,
        authorization=make_r2_lifecycle_authorization(
            decision,
            action=R2MarketStructureLifecycleAction.RETIRE,
            offset_hours=4,
        ),
        rollback_target=None,
    )

    assert derive_r2_market_structure_active_stack((promote,)) == (decision.reference,)
    assert derive_r2_market_structure_active_stack((promote, retire)) == ()
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r2_market_structure_active_stack(
            (replace(promote, sequence=2, previous_event_hash="1" * 64),)
        )


def test_codec_round_trips_non_utc_clocks_and_rejects_extra_fields() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    non_utc_seal = replace(
        R2MarketStructureEvidenceSeal.from_evidence(evidence),
        as_of_time=evidence.as_of_time.astimezone(timezone(timedelta(hours=8))),
    )
    decided_at = AS_OF + timedelta(hours=2)
    authorization = R2MarketStructureDecisionAuthorization.create(
        authorization_version="r2-decision-auth.v1",
        policy=policy,
        evidence=non_utc_seal,
        issued_at=decided_at - timedelta(minutes=5),
        decided_at=decided_at,
        decision_recorded_at=decided_at + timedelta(minutes=5),
        valid_until=AS_OF + timedelta(days=20),
        owner_receipt_hash=HASH,
    )
    decision = create_r2_market_structure_promotion_decision(
        policy=policy,
        evidence=non_utc_seal,
        authorization=authorization,
    )
    event = create_r2_market_structure_lifecycle_event(
        history=(),
        decision=decision,
        authorization=make_r2_lifecycle_authorization(decision),
        rollback_target=None,
    )

    assert decode_r2_market_structure_policy(encode_r2_market_structure_policy(policy)) == policy
    assert (
        decode_r2_market_structure_decision(encode_r2_market_structure_decision(decision))
        == decision
    )
    assert (
        decode_r2_market_structure_lifecycle_event(
            encode_r2_market_structure_lifecycle_event(event)
        )
        == event
    )
    payload = json.loads(encode_r2_market_structure_decision(decision))
    payload["unsupported"] = True
    with pytest.raises(R2MarketStructurePromotionCodecError, match="unsupported"):
        decode_r2_market_structure_decision(json.dumps(payload))


def test_default_data_center_provider_rejects_cross_database_label() -> None:
    with pytest.raises(ValueError, match="default database"):
        DjangoExactR2MarketStructureEvidenceProvider(using="replica")
