"""Pure tests for Account-owned raw identity source evidence."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.domain.account_identity_raw_source import (
    ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS,
    ACCOUNT_IDENTITY_RAW_SOURCE_OWNER,
    ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION,
    ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA,
    ACCOUNT_IDENTITY_RAW_SOURCE_STATUS,
    AccountIdentityRawSource,
    resolve_account_identity_raw_source_head,
    validate_account_identity_raw_source_successor,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def _source(**changes: object) -> AccountIdentityRawSource:
    values: dict[str, object] = {
        "source_id": "account-identity-source-7",
        "source_version": "account-identity-source.v1",
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "owner_user_id": 19,
        "assignment_state": "authoritative",
        "assignment_evidence_owner": "account",
        "assignment_evidence_artifact_type": "account_owner_assignment_evidence",
        "assignment_evidence_id": "owner-assignment-7",
        "assignment_evidence_version": "owner-assignment.v1",
        "assignment_evidence_content_hash": "a" * 64,
        "row_source_owner": "simulated_trading",
        "row_source_artifact_type": "unified_account_row_observation",
        "row_source_id": "simulated-account-row-7",
        "row_source_version": "row-observation.v3",
        "row_source_content_hash": "b" * 64,
        "observed_at": NOW,
        "recorded_at": NOW + timedelta(seconds=1),
        "row_source_valid_until": NOW + timedelta(minutes=10),
        "ttl_valid_until": NOW + timedelta(minutes=5),
        "valid_until": NOW + timedelta(minutes=5),
        "is_active": True,
    }
    values.update(changes)
    return AccountIdentityRawSource(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountIdentityRawSource,
    **changes: object,
) -> AccountIdentityRawSource:
    values: dict[str, object] = {
        "source_id": previous.source_id,
        "source_version": "account-identity-source.v2",
        "account_namespace": previous.account_namespace,
        "account_id": previous.account_id,
        "underlying_unified_account_namespace": (previous.underlying_unified_account_namespace),
        "underlying_unified_account_id": previous.underlying_unified_account_id,
        "owner_user_id": previous.owner_user_id,
        "assignment_state": previous.assignment_state,
        "assignment_evidence_owner": previous.assignment_evidence_owner,
        "assignment_evidence_artifact_type": (previous.assignment_evidence_artifact_type),
        "assignment_evidence_id": previous.assignment_evidence_id,
        "assignment_evidence_version": previous.assignment_evidence_version,
        "assignment_evidence_content_hash": (previous.assignment_evidence_content_hash),
        "row_source_owner": previous.row_source_owner,
        "row_source_artifact_type": previous.row_source_artifact_type,
        "row_source_id": previous.row_source_id,
        "row_source_version": "row-observation.v4",
        "row_source_content_hash": "c" * 64,
        "observed_at": NOW + timedelta(minutes=1),
        "recorded_at": NOW + timedelta(minutes=1, seconds=1),
        "row_source_valid_until": NOW + timedelta(minutes=11),
        "ttl_valid_until": NOW + timedelta(minutes=6),
        "valid_until": NOW + timedelta(minutes=6),
        "is_active": previous.is_active,
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return AccountIdentityRawSource(**values)  # type: ignore[arg-type]


def test_authoritative_source_is_fixed_inactive_evidence_only() -> None:
    source = _source()

    assert source.owner == ACCOUNT_IDENTITY_RAW_SOURCE_OWNER == "account"
    assert source.artifact_type == ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE
    assert source.schema == ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA
    assert source.permission == ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION == "source_evidence_only"
    assert source.status == ACCOUNT_IDENTITY_RAW_SOURCE_STATUS == "inactive"
    assert source.blocker_codes == ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS
    assert source.activation_available is False
    assert source.must_not_execute is True
    assert source.account_type == "real"


def test_account_string_identity_is_not_cast_from_underlying_integer() -> None:
    source = _source(account_id="7", underlying_unified_account_id=7)

    assert source.account_id == "7"
    assert type(source.account_id) is str
    assert type(source.underlying_unified_account_id) is int

    with pytest.raises(TypeError, match="account_id"):
        _source(account_id=7)
    with pytest.raises(TypeError, match="underlying_unified_account_id"):
        _source(underlying_unified_account_id="7")


def test_authoritative_assignment_requires_exact_owner_evidence() -> None:
    source = _source()

    assert source.owner_user_id == 19
    assert source.assignment_state == "authoritative"

    for field_name in (
        "assignment_evidence_owner",
        "assignment_evidence_artifact_type",
        "assignment_evidence_id",
        "assignment_evidence_version",
        "assignment_evidence_content_hash",
    ):
        with pytest.raises(ValueError, match="authoritative assignment"):
            _source(**{field_name: None})


def test_legacy_default_assignment_requires_formal_evidence_but_no_owner_claim() -> None:
    source = _source(
        owner_user_id=None,
        assignment_state="legacy_default",
        assignment_evidence_artifact_type="account_owner_assignment_evidence",
    )

    assert source.owner_user_id is None
    assert source.assignment_state == "legacy_default"

    with pytest.raises(ValueError, match="legacy_default assignment"):
        replace(source, assignment_evidence_id=None, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="cannot claim an owner"):
        replace(source, owner_user_id=19, identity_hash="", content_hash="")


def test_unknown_assignment_has_no_owner_or_evidence_and_cannot_be_upgraded() -> None:
    source = _source(
        owner_user_id=None,
        assignment_state="unknown",
        assignment_evidence_owner=None,
        assignment_evidence_artifact_type=None,
        assignment_evidence_id=None,
        assignment_evidence_version=None,
        assignment_evidence_content_hash=None,
    )

    assert source.owner_user_id is None
    assert source.assignment_state == "unknown"
    assert source.is_issuable_at(NOW + timedelta(seconds=2)) is False

    with pytest.raises(ValueError, match="unknown assignment"):
        replace(source, owner_user_id=19, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="unknown assignment"):
        replace(
            source,
            assignment_evidence_owner="account",
            identity_hash="",
            content_hash="",
        )


@pytest.mark.parametrize("assignment_state", ["", "trusted", "manual_reclaim", 1])
def test_assignment_state_is_closed(assignment_state: object) -> None:
    with pytest.raises((TypeError, ValueError), match="assignment_state"):
        _source(assignment_state=assignment_state)


def test_owner_evidence_owner_and_type_are_state_specific() -> None:
    with pytest.raises(ValueError, match="authoritative assignment"):
        _source(assignment_evidence_owner="simulated_trading")
    with pytest.raises(ValueError, match="authoritative assignment"):
        _source(assignment_evidence_artifact_type="account_legacy_default_assignment_evidence")
    with pytest.raises(ValueError, match="legacy_default assignment"):
        _source(
            owner_user_id=None,
            assignment_state="legacy_default",
            assignment_evidence_artifact_type="account_legacy_default_assignment_evidence",
        )


def test_validity_is_the_exact_minimum_of_row_source_and_ttl() -> None:
    row_limited = _source(
        row_source_valid_until=NOW + timedelta(minutes=3),
        ttl_valid_until=NOW + timedelta(minutes=8),
        valid_until=NOW + timedelta(minutes=3),
    )
    ttl_limited = _source()

    assert row_limited.valid_until == row_limited.row_source_valid_until
    assert ttl_limited.valid_until == ttl_limited.ttl_valid_until

    with pytest.raises(ValueError, match="minimum"):
        _source(valid_until=NOW + timedelta(minutes=4))
    with pytest.raises(ValueError, match="minimum"):
        _source(valid_until=NOW + timedelta(minutes=6))


def test_all_clocks_are_aware_and_strictly_ordered() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _source(observed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="clock sequence"):
        _source(recorded_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="clock sequence"):
        _source(ttl_valid_until=NOW, valid_until=NOW)


def test_identity_and_content_hashes_are_canonical_and_caller_checked() -> None:
    source = _source()

    assert len(source.identity_hash) == 64
    assert len(source.content_hash) == 64
    assert source.identity_hash != source.content_hash
    assert replace(source) == source

    with pytest.raises(ValueError, match="identity_hash"):
        replace(source, identity_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(source, content_hash="0" * 64)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("account_id", "real-account-8"),
        ("underlying_unified_account_id", 8),
        ("owner_user_id", 20),
        ("assignment_evidence_content_hash", "d" * 64),
        ("row_source_content_hash", "e" * 64),
        ("is_active", False),
        ("valid_until", NOW + timedelta(minutes=4)),
    ],
)
def test_semantic_field_changes_are_sealed_by_content_hash(
    field_name: str,
    replacement: object,
) -> None:
    source = _source()
    changes = {field_name: replacement, "identity_hash": "", "content_hash": ""}

    if field_name == "valid_until":
        changes["ttl_valid_until"] = replacement
    changed = replace(source, **changes)

    assert changed.identity_hash == source.identity_hash
    assert changed.content_hash != source.content_hash


def test_bad_hash_and_exact_boolean_substitutions_fail() -> None:
    with pytest.raises(ValueError, match="row_source_content_hash"):
        _source(row_source_content_hash="A" * 64)
    with pytest.raises(TypeError, match="is_active"):
        _source(is_active=1)


def test_successor_preserves_logical_identity_and_binds_predecessor() -> None:
    first = _source()
    successor = _successor(first)

    validate_account_identity_raw_source_successor(first, successor)

    with pytest.raises(ValueError, match="previous"):
        validate_account_identity_raw_source_successor(
            first,
            _successor(first, supersedes_content_hash="f" * 64),
        )
    with pytest.raises(ValueError, match="account_id"):
        validate_account_identity_raw_source_successor(
            first,
            _successor(first, account_id="real-account-8"),
        )
    with pytest.raises(ValueError, match="source_version"):
        validate_account_identity_raw_source_successor(
            first,
            _successor(first, source_version=first.source_version),
        )


def test_assignment_can_advance_only_with_a_new_exact_evidence_reference() -> None:
    unknown = _source(
        owner_user_id=None,
        assignment_state="unknown",
        assignment_evidence_owner=None,
        assignment_evidence_artifact_type=None,
        assignment_evidence_id=None,
        assignment_evidence_version=None,
        assignment_evidence_content_hash=None,
    )
    authoritative = _successor(
        unknown,
        owner_user_id=19,
        assignment_state="authoritative",
        assignment_evidence_owner="account",
        assignment_evidence_artifact_type="account_owner_assignment_evidence",
        assignment_evidence_id="owner-assignment-7",
        assignment_evidence_version="owner-assignment.v1",
        assignment_evidence_content_hash="a" * 64,
    )

    validate_account_identity_raw_source_successor(unknown, authoritative)

    with pytest.raises(ValueError, match="new exact assignment evidence"):
        validate_account_identity_raw_source_successor(
            _source(),
            _successor(_source(), owner_user_id=20),
        )


def test_inactive_successor_remains_logical_head() -> None:
    first = _source()
    inactive = _successor(first, is_active=False)

    head = resolve_account_identity_raw_source_head(
        (first, inactive),
        as_of=NOW + timedelta(minutes=2),
    )

    assert head == inactive
    assert head.is_active is False
    assert head.is_issuable_at(NOW + timedelta(minutes=2)) is False


def test_expired_successor_does_not_resurrect_predecessor() -> None:
    first = _source(
        row_source_valid_until=NOW + timedelta(minutes=20),
        ttl_valid_until=NOW + timedelta(minutes=20),
        valid_until=NOW + timedelta(minutes=20),
    )
    expired = _successor(
        first,
        row_source_valid_until=NOW + timedelta(minutes=2),
        ttl_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
    )

    head = resolve_account_identity_raw_source_head(
        (first, expired),
        as_of=NOW + timedelta(minutes=3),
    )

    assert head == expired
    assert head.is_knowable_at(NOW + timedelta(minutes=3)) is False


def test_head_resolution_is_point_in_time_by_recorded_clock() -> None:
    first = _source()
    successor = _successor(first)

    assert (
        resolve_account_identity_raw_source_head(
            (first, successor),
            as_of=NOW + timedelta(seconds=30),
        )
        == first
    )
    assert resolve_account_identity_raw_source_head((), as_of=NOW) is None


def test_public_contract_has_no_execution_grant_field() -> None:
    field_names = {field.name for field in fields(AccountIdentityRawSource)}

    assert not field_names & {
        "can_execute",
        "execution_allowed",
        "activation_token",
        "broker_account_id",
    }
