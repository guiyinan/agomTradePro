"""Evidence boundaries preserve exact identity, sample accounting, and authority."""

from dataclasses import replace
from decimal import Decimal

import pytest

from apps.research.domain.evidence_contracts import (
    DecisionPermission,
    EvidenceBlockerCode,
    GovernanceState,
)
from tests.unit.research.test_evidence_contracts import (
    NOW,
    _artifact,
    _grant,
    _input,
    _resolve,
    _spec,
    _track_record,
)


@pytest.mark.parametrize(
    ("field", "value", "exception", "reason"),
    [
        ("operator_id", "operator with spaces", ValueError, "bounded non-blank token"),
        ("required_input_roles", ["features"], TypeError, "must be a tuple"),
        ("dependency_flags", set(), TypeError, "must be a frozenset"),
        ("valid_until", NOW, ValueError, "validity window is invalid"),
        ("content_hash", "A" * 64, ValueError, "sha256 hex digest"),
    ],
)
def test_operator_spec_rejects_noncanonical_or_expired_definition(
    field: str, value: object, exception: type[Exception], reason: str
) -> None:
    spec = _spec()
    if field == "valid_until":
        value = spec.activated_at
    with pytest.raises(exception, match=reason):
        replace(spec, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("artifact", object(), "exact ArtifactRef"),
        ("reliability", object(), "exact ReliabilityContract"),
        ("dependency_flags", set(), "must be a frozenset"),
        ("pit_verified", 1, "must be a bool"),
    ],
)
def test_input_binding_requires_exact_identity_and_explicit_pit_verdict(
    field: str, value: object, reason: str
) -> None:
    with pytest.raises(TypeError, match=reason):
        replace(_input("features", "features-1"), **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("eligible", True, "non-negative integers"),
        ("unresolved", 1, "conserve eligible samples"),
        ("n_eff", Decimal("11"), "cannot exceed resolved samples"),
        ("coverage", Decimal("0.9"), "resolved divided by eligible"),
        ("market_regimes", ("growth", "growth"), "ordered and unique"),
        ("confidence_interval_low", Decimal("1"), "confidence interval is inverted"),
        ("primary_metric_code", None, "complete metric evidence"),
        ("primary_metric_value", Decimal("NaN"), "finite Decimal"),
    ],
)
def test_track_record_enforces_sample_accounting_and_metric_completeness(
    field: str, value: object, reason: str
) -> None:
    snapshot = _track_record(_artifact("forecast"))
    with pytest.raises(ValueError, match=reason):
        replace(snapshot, **{field: value})


def test_track_record_expiry_and_empty_sample_metadata_are_rejected() -> None:
    snapshot = _track_record(_artifact("forecast"))
    with pytest.raises(ValueError, match="validity window is invalid"):
        replace(snapshot, valid_until=snapshot.evaluated_at)
    empty = _track_record(_artifact("forecast"), eligible=0)
    with pytest.raises(ValueError, match="cannot publish metric metadata"):
        replace(empty, primary_metric_code="brier")
    assert empty.coverage == Decimal(0)
    assert empty.primary_metric_value is None


@pytest.mark.parametrize(
    ("field", "value", "exception", "reason"),
    [
        ("output_artifact", object(), TypeError, "exact ArtifactRef"),
        ("lineage", (), ValueError, "non-empty tuple"),
        ("dependency_flags", set(), TypeError, "must be a frozenset"),
        ("track_record_ref", object(), TypeError, "exact ArtifactRef"),
        (
            "blockers",
            (EvidenceBlockerCode.INPUT_UNRELIABLE,) * 2,
            ValueError,
            "blockers must be ordered and unique",
        ),
    ],
)
def test_envelope_rejects_substituted_or_noncanonical_evidence(
    field: str, value: object, exception: type[Exception], reason: str
) -> None:
    envelope = _resolve(_artifact("forecast"))
    with pytest.raises(exception, match=reason):
        replace(envelope, **{field: value})


def test_envelope_rejects_duplicate_lineage_and_preserves_valid_seal() -> None:
    envelope = _resolve(_artifact("forecast"))
    with pytest.raises(ValueError, match="lineage must be ordered and unique"):
        replace(envelope, lineage=envelope.lineage * 2)
    assert replace(envelope) == envelope
    snapshot = _track_record(_artifact("forecast"))
    assert replace(snapshot) == snapshot


def test_resolver_rejects_wrong_output_and_duplicate_input_identity() -> None:
    output = _artifact("forecast")
    with pytest.raises(ValueError, match="output artifact type differs"):
        _resolve(replace(output, artifact_type="other"))
    first = _input("features", "same-source")
    with pytest.raises(TypeError, match="inputs must be a tuple"):
        _resolve(output, inputs=[first])
    with pytest.raises(ValueError, match="input roles must be unique"):
        _resolve(output, inputs=(first, first))
    with pytest.raises(ValueError, match="artifact identities must be unique"):
        _resolve(output, inputs=(first, replace(first, role="regime")))


def test_cross_output_grant_and_track_record_cannot_authorize_execution() -> None:
    output = _artifact("forecast")
    other = _artifact("other-forecast", digest="f")
    envelope = _resolve(output, governance_grant=_grant(other), track_record=_track_record(other))
    assert set(envelope.blockers) == {
        EvidenceBlockerCode.INPUT_HASH_CONFLICT,
        EvidenceBlockerCode.TRACK_RECORD_MISMATCH,
    }
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY
    assert envelope.must_not_use_for_decision and envelope.must_not_execute
    with pytest.raises(ValueError, match="must represent an active promotion"):
        replace(_grant(output), governance_state=GovernanceState.RETIRED)


def test_operator_without_track_record_requirement_uses_remaining_authority() -> None:
    envelope = _resolve(
        _artifact("forecast"), operator_spec=_spec(requires_track_record=False), track_record=None
    )
    assert envelope.blockers == ()
    assert envelope.track_record_ref is None
    assert envelope.permission is DecisionPermission.EXECUTION_ELIGIBLE
