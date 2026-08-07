"""Unit coverage for R7 sample policy approval and canonical sealing."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.research.application.r7_sample_policy import R7SamplePolicyRegistrationDraft
from apps.research.domain.r7_sample_policy import PersistedR7SamplePolicy
from apps.research.infrastructure.r7_sample_policy_codec import (
    R7SamplePolicyCodecError,
    decode_persisted_r7_sample_policy,
    decode_r7_sample_policy_authorization,
    encode_persisted_r7_sample_policy,
    encode_r7_sample_policy_authorization,
)
from tests.unit.research.r7_sample_policy_factories import (
    RECORDED_AT,
    make_authorization,
    make_draft,
    make_policy_definition,
    make_scope,
)


def _record() -> PersistedR7SamplePolicy:
    draft = make_draft()
    return PersistedR7SamplePolicy.create(
        policy_id=draft.policy_id,
        policy_version=draft.policy_version,
        scope=draft.scope,
        policy_definition=draft.policy_definition,
        authorization=make_authorization(draft),
        recorded_at=RECORDED_AT,
    )


def test_external_authorization_replaces_self_attested_approver_and_seals_all_fields() -> None:
    record = _record()

    assert record.policy.approved_by == "research-governance-owner"
    assert record.policy.approved_by != make_draft().policy_definition.approved_by
    assert record.research_only is True
    assert record.must_not_use_for_decision is True
    assert record.must_not_execute is True
    assert decode_persisted_r7_sample_policy(encode_persisted_r7_sample_policy(record)) == record
    assert (
        decode_r7_sample_policy_authorization(
            encode_r7_sample_policy_authorization(record.authorization)
        )
        == record.authorization
    )


def test_definition_or_owner_receipt_substitution_fails_closed() -> None:
    draft = make_draft()
    changed = replace(
        draft,
        policy_definition=make_policy_definition(minimum_historical_analogies=99),
    )
    with pytest.raises(ValueError, match="authorization substitution"):
        PersistedR7SamplePolicy.create(
            policy_id=changed.policy_id,
            policy_version=changed.policy_version,
            scope=changed.scope,
            policy_definition=changed.policy_definition,
            authorization=make_authorization(draft),
            recorded_at=RECORDED_AT,
        )


def test_codec_rejects_unknown_keys_wrong_types_and_forged_hashes() -> None:
    record = _record()
    payload = encode_persisted_r7_sample_policy(record)
    body = payload["body"]
    assert isinstance(body, dict)
    body["unknown"] = True
    with pytest.raises(R7SamplePolicyCodecError, match="keys are not canonical"):
        decode_persisted_r7_sample_policy(payload)

    payload = encode_persisted_r7_sample_policy(record)
    body = payload["body"]
    assert isinstance(body, dict)
    body["research_only"] = 1
    with pytest.raises(R7SamplePolicyCodecError, match="must be a boolean"):
        decode_persisted_r7_sample_policy(payload)

    payload = encode_r7_sample_policy_authorization(record.authorization)
    body = payload["body"]
    assert isinstance(body, dict)
    body["content_hash"] = "0" * 64
    with pytest.raises(R7SamplePolicyCodecError, match="content_hash mismatch"):
        decode_r7_sample_policy_authorization(payload)


def test_codec_rejects_noncanonical_uuid_spellings() -> None:
    record = _record()
    payload = encode_persisted_r7_sample_policy(record)
    body = payload["body"]
    assert isinstance(body, dict)
    scope = body["scope"]
    assert isinstance(scope, dict)
    scope["scenario_set_revision_id"] = "{" + str(record.scope.scenario_set_revision_id) + "}"
    with pytest.raises(R7SamplePolicyCodecError, match="canonical lowercase UUID"):
        decode_persisted_r7_sample_policy(payload)

    payload = encode_persisted_r7_sample_policy(record)
    body = payload["body"]
    assert isinstance(body, dict)
    scope = body["scope"]
    assert isinstance(scope, dict)
    revisions = scope["scenario_revision_ids"]
    assert isinstance(revisions, list)
    revisions[0] = revisions[0].replace("-", "")
    with pytest.raises(R7SamplePolicyCodecError, match="canonical lowercase UUID"):
        decode_persisted_r7_sample_policy(payload)


@pytest.mark.parametrize(
    ("scope_kwargs", "policy_kwargs", "message"),
    [
        (
            {},
            {"forecast_horizon": timedelta(days=91)},
            "forecast_horizon mismatch",
        ),
        (
            {},
            {"censoring_rule_version": "scenario-censoring.v2"},
            "censoring_rule_version mismatch",
        ),
        (
            {},
            {"path_horizon_periods": 4},
            "path_horizon_periods mismatch",
        ),
    ],
)
def test_scope_and_policy_semantics_must_be_coherent(
    scope_kwargs: dict[str, object],
    policy_kwargs: dict[str, object],
    message: str,
) -> None:
    draft = make_draft()
    scope = make_scope(**scope_kwargs)
    policy = make_policy_definition(**policy_kwargs)
    with pytest.raises(ValueError, match=message):
        R7SamplePolicyRegistrationDraft(
            policy_id=draft.policy_id,
            policy_version=draft.policy_version,
            scope=scope,
            policy_definition=policy,
        )


def test_policy_requiring_all_path_initial_states_rejects_partial_scope() -> None:
    draft = make_draft()
    with pytest.raises(ValueError, match="every scope revision"):
        R7SamplePolicyRegistrationDraft(
            policy_id=draft.policy_id,
            policy_version=draft.policy_version,
            scope=make_scope(
                path_initial_state_revision_ids=(draft.scope.scenario_revision_ids[0],)
            ),
            policy_definition=make_policy_definition(),
        )
