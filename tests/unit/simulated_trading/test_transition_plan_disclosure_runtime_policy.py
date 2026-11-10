"""Tests for the active disclosure-coverage runtime policy binding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    DISCLOSURE_COVERAGE_POLICY_KEY,
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    RuntimeDisclosurePolicyEvidence,
)

AS_OF = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
DECISION_ON = date(2026, 11, 11)
EARLIEST_REQUIRED_ON = date(2026, 10, 1)
BODY_STORE_ROOT = Path.cwd() / "agom-data" / "disclosure-body-store"


def _policy_payload() -> dict[str, object]:
    """Build one explicit active policy without defaults or inferred dates."""

    return {
        "schema_version": "simulated-disclosure-coverage-policy.v1",
        "enabled": True,
        "source_id": "szse_official",
        "start_on": "2026-10-01",
        "end_on_mode": "decision_on",
        "body_store_root": str(BODY_STORE_ROOT),
        "policy_version": "szse-window-r1",
        "lease_ttl_seconds": 60,
    }


def _runtime_pair(
    payload: object,
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Create a matching active profile and immutable resolved-value snapshot."""

    values = {DISCLOSURE_COVERAGE_POLICY_KEY: payload}
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    activated_at = AS_OF - timedelta(hours=2)
    profile = RuntimeConfigProfile(
        profile_id="disclosure-policy-profile",
        profile_key="development-profile",
        environment="development",
        version=7,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="a" * 64,
        created_at=activated_at - timedelta(hours=1),
        activated_at=activated_at,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="disclosure-policy-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hashlib.sha256(encoded).hexdigest(),
        resolved_values=values,
        generated_at=activated_at + timedelta(minutes=1),
        effective_from=activated_at,
    )
    return profile, snapshot


def _evidence(
    payload: object,
    *,
    runtime_environment: str = "development",
) -> RuntimeDisclosurePolicyEvidence:
    """Bind a raw policy value to the active profile and snapshot fixture."""

    profile, snapshot = _runtime_pair(payload)
    return RuntimeDisclosurePolicyEvidence(
        runtime_environment=runtime_environment,
        definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
        value=payload,
        profile=profile,
        snapshot=snapshot,
        read_at=AS_OF,
    )


class _EvidenceReader:
    """Return one configured evidence record and retain the exact requested identity."""

    def __init__(self, evidence: RuntimeDisclosurePolicyEvidence | None) -> None:
        self.evidence = evidence
        self.requests: list[tuple[str, str, datetime]] = []

    def read_active_evidence(
        self,
        *,
        runtime_environment: str,
        definition_key: str,
        as_of: datetime,
    ) -> RuntimeDisclosurePolicyEvidence | None:
        """Serve the injected evidence at the caller's exact environment and cutoff."""

        self.requests.append((runtime_environment, definition_key, as_of))
        return self.evidence


def _reader(
    payload: object,
    *,
    evidence: RuntimeDisclosurePolicyEvidence | None = None,
) -> tuple[ConfiguredTransitionPlanDisclosureRuntimePolicyReader, _EvidenceReader]:
    """Bind a typed test evidence reader to the active policy resolver."""

    stub = _EvidenceReader(_evidence(payload) if evidence is None else evidence)
    return (
        ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
            runtime_environment="development",
            evidence_reader=stub,
        ),
        stub,
    )


def test_reader_returns_explicit_policy_and_exact_runtime_provenance() -> None:
    payload = _policy_payload()
    evidence = _evidence(payload)
    reader, stub = _reader(payload, evidence=evidence)

    result = reader.read_policy(
        decision_on=DECISION_ON,
        earliest_required_on=EARLIEST_REQUIRED_ON,
        as_of=AS_OF,
    )

    assert result is not None
    assert result.source_id == "szse_official"
    assert result.start_on == EARLIEST_REQUIRED_ON
    assert result.end_on == DECISION_ON
    assert result.body_store_root == BODY_STORE_ROOT
    assert result.policy_version == "szse-window-r1"
    assert result.lease_policy.policy_version == result.policy_version
    assert result.lease_policy.ttl == timedelta(seconds=60)
    assert result.lease_policy.maximum_ttl == timedelta(seconds=60)
    assert result.runtime_environment == "development"
    assert result.profile_id == evidence.profile.profile_id
    assert result.profile_key == evidence.profile.profile_key
    assert result.profile_version == evidence.profile.version
    assert result.profile_content_hash == evidence.profile.content_hash
    assert result.snapshot_id == evidence.snapshot.snapshot_id
    assert result.snapshot_content_hash == evidence.snapshot.snapshot_hash
    assert result.known_at == evidence.profile.created_at
    assert result.effective_at == evidence.snapshot.effective_from
    assert result.read_at == AS_OF
    assert len(result.policy_content_hash) == 64
    assert stub.requests == [("development", DISCLOSURE_COVERAGE_POLICY_KEY, AS_OF)]


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "disabled",
        "schema",
        "source",
        "end_mode",
        "unknown_field",
        "ttl_zero",
        "ttl_over_owner_limit",
        "ttl_boolean",
        "missing_ttl",
        "relative_body_store_root",
        "parent_body_store_root",
        "empty_body_store_root",
        "start_after_earliest",
        "earliest_after_decision",
    ],
)
def test_reader_fails_closed_for_missing_or_invalid_policy(
    defect: str,
) -> None:
    payload = _policy_payload()
    evidence = _evidence(payload)
    decision_on = DECISION_ON
    earliest_required_on = EARLIEST_REQUIRED_ON
    if defect == "missing":
        evidence = replace(evidence, value=None)
    elif defect == "disabled":
        payload["enabled"] = False
        evidence = _evidence(payload)
    elif defect == "schema":
        payload["schema_version"] = "simulated-disclosure-coverage-policy.v2"
        evidence = _evidence(payload)
    elif defect == "source":
        payload["source_id"] = "sse_official"
        evidence = _evidence(payload)
    elif defect == "end_mode":
        payload["end_on_mode"] = "fixed"
        evidence = _evidence(payload)
    elif defect == "unknown_field":
        payload["fallback"] = True
        evidence = _evidence(payload)
    elif defect == "ttl_zero":
        payload["lease_ttl_seconds"] = 0
        evidence = _evidence(payload)
    elif defect == "ttl_over_owner_limit":
        payload["lease_ttl_seconds"] = 61
        evidence = _evidence(payload)
    elif defect == "ttl_boolean":
        payload["lease_ttl_seconds"] = True
        evidence = _evidence(payload)
    elif defect == "missing_ttl":
        payload.pop("lease_ttl_seconds")
        evidence = _evidence(payload)
    elif defect == "relative_body_store_root":
        payload["body_store_root"] = "var/disclosure-body-store"
        evidence = _evidence(payload)
    elif defect == "parent_body_store_root":
        payload["body_store_root"] = str(BODY_STORE_ROOT.parent / ".." / "body-store")
        evidence = _evidence(payload)
    elif defect == "empty_body_store_root":
        payload["body_store_root"] = " "
        evidence = _evidence(payload)
    elif defect == "start_after_earliest":
        payload["start_on"] = "2026-10-02"
        evidence = _evidence(payload)
    elif defect == "earliest_after_decision":
        earliest_required_on = DECISION_ON + timedelta(days=1)

    reader, _ = _reader(payload, evidence=evidence)

    assert (
        reader.read_policy(
            decision_on=decision_on,
            earliest_required_on=earliest_required_on,
            as_of=AS_OF,
        )
        is None
    )


@pytest.mark.parametrize(
    "defect",
    [
        "environment",
        "definition_key",
        "inactive_profile",
        "snapshot_profile_id",
        "snapshot_profile_key",
        "snapshot_profile_version",
        "profile_hash",
        "snapshot_hash",
        "snapshot_value",
        "future_known_at",
        "future_activation",
        "future_effective_at",
        "future_generated_at",
        "naive_effective_at",
        "read_at_mismatch",
    ],
)
def test_reader_fails_closed_for_untrusted_config_center_evidence(
    defect: str,
) -> None:
    payload = _policy_payload()
    evidence = _evidence(payload)
    if defect == "environment":
        evidence = replace(evidence, runtime_environment="production")
    elif defect == "definition_key":
        evidence = replace(evidence, definition_key="config_center.market.other")
    elif defect == "inactive_profile":
        evidence = replace(
            evidence,
            profile=replace(evidence.profile, status=RuntimeProfileStatus.SUPERSEDED),
        )
    elif defect == "snapshot_profile_id":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, profile_id="other-profile"),
        )
    elif defect == "snapshot_profile_key":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, profile_key="other-profile-key"),
        )
    elif defect == "snapshot_profile_version":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, profile_version=evidence.profile.version + 1),
        )
    elif defect == "profile_hash":
        evidence = replace(evidence, profile=replace(evidence.profile, content_hash="invalid"))
    elif defect == "snapshot_hash":
        evidence = replace(evidence, snapshot=replace(evidence.snapshot, snapshot_hash="b" * 64))
    elif defect == "snapshot_value":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, resolved_values={}),
        )
    elif defect == "future_known_at":
        evidence = replace(
            evidence,
            profile=replace(evidence.profile, created_at=AS_OF + timedelta(seconds=1)),
        )
    elif defect == "future_activation":
        future = AS_OF + timedelta(seconds=1)
        evidence = replace(
            evidence,
            profile=replace(evidence.profile, activated_at=future),
            snapshot=replace(
                evidence.snapshot,
                effective_from=future,
                generated_at=future,
            ),
        )
    elif defect == "future_effective_at":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, effective_from=AS_OF + timedelta(seconds=1)),
        )
    elif defect == "future_generated_at":
        evidence = replace(
            evidence,
            snapshot=replace(evidence.snapshot, generated_at=AS_OF + timedelta(seconds=1)),
        )
    elif defect == "naive_effective_at":
        evidence = replace(
            evidence,
            snapshot=replace(
                evidence.snapshot,
                effective_from=datetime(2026, 11, 11, 8),
            ),
        )
    else:
        evidence = replace(evidence, read_at=AS_OF - timedelta(seconds=1))

    reader, _ = _reader(payload, evidence=evidence)

    assert (
        reader.read_policy(
            decision_on=DECISION_ON,
            earliest_required_on=EARLIEST_REQUIRED_ON,
            as_of=AS_OF,
        )
        is None
    )


@pytest.mark.parametrize("environment", ["", "two words", "production "])
def test_reader_rejects_invalid_environment(environment: str) -> None:
    with pytest.raises(ValueError):
        ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
            runtime_environment=environment,
            evidence_reader=_EvidenceReader(None),
        )


def test_reader_requires_explicit_aware_dates_and_cutoff() -> None:
    reader, _ = _reader(_policy_payload())

    assert (
        reader.read_policy(
            decision_on=DECISION_ON,
            earliest_required_on=EARLIEST_REQUIRED_ON,
            as_of=datetime(2026, 11, 11, 12),
        )
        is None
    )
    assert (
        reader.read_policy(
            decision_on=datetime(2026, 11, 11, 12),  # type: ignore[arg-type]
            earliest_required_on=EARLIEST_REQUIRED_ON,
            as_of=AS_OF,
        )
        is None
    )


def test_policy_reader_construction_does_not_read_config_center() -> None:
    stub = _EvidenceReader(None)

    reader = ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
        runtime_environment="development",
        evidence_reader=stub,
    )

    assert reader
    assert stub.requests == []
