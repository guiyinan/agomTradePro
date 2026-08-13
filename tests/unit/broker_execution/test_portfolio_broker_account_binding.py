"""Pure contract coverage for inactive cross-namespace account bindings."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.domain.portfolio_broker_account_binding import (
    BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION,
    PORTFOLIO_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    PORTFOLIO_ACCOUNT_BINDING_SOURCE_OWNER,
    BrokerPortfolioAccountBindingActor,
    BrokerPortfolioAccountNamespaceBinding,
    validate_broker_portfolio_account_binding_successor,
)

NOW = datetime(2026, 8, 13, 6, tzinfo=UTC)


def _actor(**changes: object) -> BrokerPortfolioAccountBindingActor:
    values: dict[str, object] = {
        "actor_id": "user:19",
        "user_id": 19,
        "role": "broker_account_binding_approver",
    }
    values.update(changes)
    return BrokerPortfolioAccountBindingActor(**values)  # type: ignore[arg-type]


def _binding(**changes: object) -> BrokerPortfolioAccountNamespaceBinding:
    values: dict[str, object] = {
        "binding_id": "broker-portfolio-account-binding-1",
        "broker_account_namespace": "broker_execution.system_account",
        "broker_account_id": 7,
        "portfolio_account_namespace": "portfolio.transition_plan_account",
        "portfolio_account_id": "portfolio-account-7",
        "broker_source_owner": BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
        "broker_source_artifact_type": BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
        "broker_source_id": "broker-account-source-7",
        "broker_source_version": "broker-account-source.v1",
        "broker_source_content_hash": "a" * 64,
        "portfolio_source_owner": PORTFOLIO_ACCOUNT_BINDING_SOURCE_OWNER,
        "portfolio_source_artifact_type": PORTFOLIO_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
        "portfolio_source_id": "portfolio-account-source-7",
        "portfolio_source_version": "portfolio-account-source.v1",
        "portfolio_source_content_hash": "b" * 64,
        "asserted_by": _actor(),
        "issued_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return BrokerPortfolioAccountNamespaceBinding(**values)  # type: ignore[arg-type]


def test_binding_preserves_both_namespaces_without_equating_identifier_types() -> None:
    binding = _binding()

    assert binding.broker_account_namespace == "broker_execution.system_account"
    assert type(binding.broker_account_id) is int
    assert binding.portfolio_account_namespace == "portfolio.transition_plan_account"
    assert type(binding.portfolio_account_id) is str
    assert binding.broker_account_id == 7
    assert binding.portfolio_account_id == "portfolio-account-7"
    assert binding.owner == BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER
    assert binding.binding_version == BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION
    assert binding.permission == BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION
    assert binding.blocker_codes == BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS
    assert binding.activation_available is False
    assert binding.must_not_execute is True
    assert len(binding.identity_hash) == 64
    assert len(binding.content_hash) == 64
    assert binding.is_knowable_at(NOW)
    assert not binding.is_knowable_at(binding.valid_until)


def test_payload_keeps_owner_source_seals_and_explicit_inactive_flags() -> None:
    payload = _binding().to_payload()

    assert payload["broker_source_id"] == "broker-account-source-7"
    assert payload["broker_source_owner"] == "broker_execution"
    assert payload["broker_source_artifact_type"] == "broker_account_identity_snapshot"
    assert payload["broker_source_version"] == "broker-account-source.v1"
    assert payload["broker_source_content_hash"] == "a" * 64
    assert payload["portfolio_source_id"] == "portfolio-account-source-7"
    assert payload["portfolio_source_owner"] == "portfolio"
    assert payload["portfolio_source_artifact_type"] == "portfolio_account_identity_snapshot"
    assert payload["portfolio_source_version"] == "portfolio-account-source.v1"
    assert payload["portfolio_source_content_hash"] == "b" * 64
    assert payload["asserted_by"] == {
        "actor_id": "user:19",
        "user_id": 19,
        "role": "broker_account_binding_approver",
        "kind": "human",
        "is_staff": True,
    }
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("broker_account_namespace", "broker_execution.other_namespace"),
        ("broker_account_id", 8),
        ("portfolio_account_namespace", "portfolio.other_namespace"),
        ("portfolio_account_id", "7"),
        ("broker_source_id", "broker-account-source-8"),
        ("broker_source_version", "broker-account-source.v2"),
        ("broker_source_content_hash", "c" * 64),
        ("portfolio_source_id", "portfolio-account-source-8"),
        ("portfolio_source_version", "portfolio-account-source.v2"),
        ("portfolio_source_content_hash", "d" * 64),
        ("asserted_by", _actor(actor_id="user:20", user_id=20)),
        ("issued_at", NOW - timedelta(minutes=2)),
        ("supersedes_binding_hash", "e" * 64),
    ],
)
def test_every_material_assertion_participates_in_canonical_hash(
    field_name: str, replacement: object
) -> None:
    original = _binding()
    changed = _binding(**{field_name: replacement})

    assert changed.content_hash != original.content_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"broker_account_id": "7"},
        {"broker_account_id": True},
        {"portfolio_account_id": 7},
        {"portfolio_account_id": " 7"},
        {"broker_source_content_hash": "A" * 64},
        {"portfolio_source_content_hash": "short"},
        {"recorded_at": datetime(2026, 8, 13, 6)},
        {"issued_at": NOW + timedelta(seconds=1)},
        {"valid_until": NOW},
        {"permission": "active"},
        {"blocker_codes": ()},
        {"owner": "portfolio"},
    ],
)
def test_binding_rejects_casts_noncanonical_seals_and_authority_upgrade(
    changes: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _binding(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"broker_source_owner": ""},
        {"broker_source_owner": "portfolio"},
        {"broker_source_artifact_type": "broker account"},
        {"broker_source_artifact_type": "other_snapshot"},
        {"portfolio_source_owner": ""},
        {"portfolio_source_owner": "broker_execution"},
        {"portfolio_source_artifact_type": "portfolio account"},
        {"portfolio_source_artifact_type": "other_snapshot"},
    ],
)
def test_source_authority_and_artifact_types_are_fixed_tokens(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _binding(**changes)


def test_identity_hash_is_canonical_and_rejects_caller_substitution() -> None:
    binding = _binding()

    assert _binding(identity_hash=binding.identity_hash) == binding
    assert _binding(binding_id="binding-2").identity_hash != binding.identity_hash
    with pytest.raises(ValueError, match="identity_hash"):
        _binding(identity_hash="9" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": True},
        {"user_id": 0},
        {"actor_id": "user 19"},
        {"kind": "service"},
        {"is_staff": False},
    ],
)
def test_actor_requires_exact_human_staff_dual_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _actor(**changes)


def test_successor_binds_exact_predecessor_and_same_broker_namespace_identity() -> None:
    previous = _binding()
    successor = _binding(
        binding_id="broker-portfolio-account-binding-2",
        portfolio_account_id="portfolio-account-8",
        recorded_at=NOW + timedelta(minutes=1),
        issued_at=NOW + timedelta(seconds=30),
        supersedes_binding_hash=previous.content_hash,
    )

    validate_broker_portfolio_account_binding_successor(previous, successor)


@pytest.mark.parametrize(
    "changes",
    [
        {"supersedes_binding_hash": "0" * 64},
        {"broker_account_namespace": "broker_execution.other_namespace"},
        {"broker_account_id": 8},
        {"recorded_at": NOW, "issued_at": NOW - timedelta(minutes=1)},
    ],
)
def test_successor_rejects_fork_identity_or_nonadvancing_clock(changes: dict[str, object]) -> None:
    previous = _binding()
    values: dict[str, object] = {
        "binding_id": "broker-portfolio-account-binding-2",
        "recorded_at": NOW + timedelta(minutes=1),
        "issued_at": NOW + timedelta(seconds=30),
        "supersedes_binding_hash": previous.content_hash,
    }
    values.update(changes)
    successor = _binding(**values)

    with pytest.raises(ValueError):
        validate_broker_portfolio_account_binding_successor(previous, successor)


def test_domain_contract_has_no_cross_app_or_external_dependency() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "broker_execution"
        / "domain"
        / "portfolio_broker_account_binding.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith("apps.") for name in imported)
    assert imported <= {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
