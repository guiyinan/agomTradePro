"""Pure tests for the Broker-owned order approval artifact ID reader."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.broker_execution.application.order_approval_artifact_owner_reader import (
    BrokerOrderApprovalArtifactIdentityWinner,
    BrokerOrderApprovalArtifactOwnerReader,
    BrokerOrderApprovalArtifactOwnerReaderCorruption,
    GetBrokerOrderApprovalArtifactByIdentity,
)

ORDER_ID = "75df9306-cb1d-47de-8588-3bfce22a7931"
APPROVED_AT = datetime(2026, 8, 13, 5, 55, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 8, 13, 6, 30, tzinfo=UTC)


def _winner(**changes: object) -> BrokerOrderApprovalArtifactIdentityWinner:
    values: dict[str, object] = {
        "artifact_id": ORDER_ID,
        "artifact_version": "broker-live-order-approval-artifact.v1.3",
        "identity_hash": "a" * 64,
        "content_hash": "b" * 64,
        "account_id": 7,
        "order_version": 3,
        "approval_digest": "c" * 64,
        "risk_policy_version": "risk-policy-v4",
        "approved_at": APPROVED_AT,
        "recorded_at": RECORDED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return BrokerOrderApprovalArtifactIdentityWinner(**values)  # type: ignore[arg-type]


class _Repository:
    def __init__(
        self,
        value: BrokerOrderApprovalArtifactIdentityWinner | None,
    ) -> None:
        self.value = value
        self.calls: list[tuple[str, str, datetime]] = []

    def get_identity_winner(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> BrokerOrderApprovalArtifactIdentityWinner | None:
        self.calls.append((artifact_id, artifact_version, as_of))
        return self.value


def test_query_is_id_only_without_hash_or_semantic_fields() -> None:
    assert {field.name for field in fields(GetBrokerOrderApprovalArtifactByIdentity)} == {
        "artifact_id",
        "artifact_version",
        "as_of",
    }


def test_reader_returns_exact_inactive_owner_winner() -> None:
    winner = _winner()
    repository = _Repository(winner)
    reader = BrokerOrderApprovalArtifactOwnerReader(repository)
    as_of = RECORDED_AT + timedelta(minutes=1)

    assert (
        reader.execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version=winner.artifact_version,
                as_of=as_of,
            )
        )
        == winner
    )
    assert repository.calls == [(ORDER_ID, winner.artifact_version, as_of)]
    assert winner.owner == "broker_execution"
    assert winner.artifact_type == "live_order_approval_snapshot"
    assert winner.schema == "broker-live-order-approval-artifact.v1"
    assert winner.activation_available is False
    assert winner.must_not_execute is True
    assert winner.permission == "approval_evidence_only"
    assert winner.status == "inactive"


def test_recorded_clock_is_distinct_from_approved_clock_and_controls_pit() -> None:
    winner = _winner()
    assert winner.approved_at < winner.recorded_at

    assert (
        BrokerOrderApprovalArtifactOwnerReader(_Repository(winner)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version=winner.artifact_version,
                as_of=winner.approved_at + timedelta(minutes=1),
            )
        )
        is None
    )
    assert (
        BrokerOrderApprovalArtifactOwnerReader(_Repository(winner)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version=winner.artifact_version,
                as_of=winner.recorded_at,
            )
        )
        == winner
    )
    assert (
        BrokerOrderApprovalArtifactOwnerReader(_Repository(winner)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version=winner.artifact_version,
                as_of=winner.valid_until,
            )
        )
        is None
    )


def test_missing_identity_winner_returns_none() -> None:
    assert (
        BrokerOrderApprovalArtifactOwnerReader(_Repository(None)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version="broker-live-order-approval-artifact.v1.3",
                as_of=RECORDED_AT,
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_id": "75df9306-cb1d-47de-8588-3bfce22a7930"},
        {
            "artifact_version": "broker-live-order-approval-artifact.v1.4",
            "order_version": 4,
        },
    ],
)
def test_repository_identity_substitution_fails_closed(changes: dict[str, object]) -> None:
    winner = _winner(**changes)
    reader = BrokerOrderApprovalArtifactOwnerReader(_Repository(winner))

    with pytest.raises(BrokerOrderApprovalArtifactOwnerReaderCorruption, match="identity"):
        reader.execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version="broker-live-order-approval-artifact.v1.3",
                as_of=RECORDED_AT,
            )
        )


class _Substituted:
    pass


def test_repository_type_substitution_fails_closed() -> None:
    repository = _Repository(None)
    repository.value = _Substituted()  # type: ignore[assignment]

    with pytest.raises(BrokerOrderApprovalArtifactOwnerReaderCorruption, match="type"):
        BrokerOrderApprovalArtifactOwnerReader(repository).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=ORDER_ID,
                artifact_version="broker-live-order-approval-artifact.v1.3",
                as_of=RECORDED_AT,
            )
        )


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("identity_hash", "A" * 64, "identity_hash"),
        ("content_hash", "0" * 63, "content_hash"),
        ("approval_digest", "x" * 64, "approval_digest"),
        ("account_id", True, "account_id"),
        ("order_version", 0, "order_version"),
        ("risk_policy_version", "", "risk_policy_version"),
        ("owner", "portfolio", "owner"),
        ("schema", "broker-live-order-approval-artifact.v2", "schema"),
        ("activation_available", True, "inactive"),
        ("must_not_execute", False, "inactive"),
    ],
)
def test_dto_rejects_malformed_or_upgraded_owner_projection(
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _winner(**{field_name: replacement})


def test_clock_sequence_and_aware_cutoff_are_strict() -> None:
    with pytest.raises(ValueError, match="clock"):
        _winner(recorded_at=APPROVED_AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="clock"):
        _winner(recorded_at=VALID_UNTIL)
    with pytest.raises(ValueError, match="timezone-aware"):
        GetBrokerOrderApprovalArtifactByIdentity(
            artifact_id=ORDER_ID,
            artifact_version="broker-live-order-approval-artifact.v1.3",
            as_of=RECORDED_AT.replace(tzinfo=None),
        )


def test_artifact_version_must_bind_order_version() -> None:
    with pytest.raises(ValueError, match="order_version"):
        _winner(order_version=4)


def test_reader_revalidates_mutated_frozen_instance() -> None:
    winner = _winner()
    object.__setattr__(winner, "content_hash", "f" * 64)
    # A valid different hash remains structurally legal, so identity/hash content is owner-repo trust.
    assert (
        BrokerOrderApprovalArtifactOwnerReader(_Repository(winner)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=winner.artifact_id,
                artifact_version=winner.artifact_version,
                as_of=winner.recorded_at,
            )
        )
        == winner
    )

    object.__setattr__(winner, "status", "active")
    with pytest.raises(ValueError, match="inactive"):
        replace(winner)
    with pytest.raises((ValueError, BrokerOrderApprovalArtifactOwnerReaderCorruption)):
        BrokerOrderApprovalArtifactOwnerReader(_Repository(winner)).execute(
            GetBrokerOrderApprovalArtifactByIdentity(
                artifact_id=winner.artifact_id,
                artifact_version=winner.artifact_version,
                as_of=winner.recorded_at,
            )
        )
