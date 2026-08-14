from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
    AccountActorAuthorityRawSourceV3Unavailable,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)
DIGEST = "a" * 64


def test_selector_is_frozen_scalar_exact_and_point_in_time_aware() -> None:
    selector = AccountActorAuthorityRawSourceV3Selector(
        source_id="django-user:41",
        source_version="v1",
        expected_content_hash=DIGEST,
        as_of=NOW,
    )

    assert selector == AccountActorAuthorityRawSourceV3Selector("django-user:41", "v1", DIGEST, NOW)
    with pytest.raises(FrozenInstanceError):
        selector.source_version = "v2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", ""),
        ("source_id", " django-user:41"),
        ("source_id", 41),
        ("source_version", "v 1"),
        ("source_version", True),
        ("expected_content_hash", "A" * 64),
        ("expected_content_hash", "a" * 63),
        ("expected_content_hash", False),
        ("as_of", datetime(2026, 8, 14, 12)),
        ("as_of", "2026-08-14T12:00:00Z"),
    ],
)
def test_selector_rejects_nonexact_or_noncanonical_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "source_id": "django-user:41",
        "source_version": "v1",
        "expected_content_hash": DIGEST,
        "as_of": NOW,
    }
    values[field] = value

    with pytest.raises(ValueError):
        AccountActorAuthorityRawSourceV3Selector(**values)  # type: ignore[arg-type]


def test_recorder_has_fixed_frozen_service_semantics() -> None:
    recorder = AccountActorAuthorityRawSourceV3Recorder("account-authority-recorder-v3")

    assert (
        recorder.service_id,
        recorder.role,
        recorder.kind,
        recorder.is_automated,
    ) == (
        "account-authority-recorder-v3",
        "account_actor_authority_raw_recorder",
        "service",
        True,
    )
    with pytest.raises(FrozenInstanceError):
        recorder.service_id = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"service_id": ""},
        {"service_id": 3},
        {"role": "account_actor_authority_recorder"},
        {"role": True},
        {"kind": "human"},
        {"kind": 1},
        {"is_automated": False},
        {"is_automated": 1},
    ],
)
def test_recorder_rejects_nonexact_or_nonfixed_values(changes: dict[str, object]) -> None:
    values: dict[str, object] = {"service_id": "account-authority-recorder-v3"}
    values.update(changes)

    with pytest.raises(ValueError):
        AccountActorAuthorityRawSourceV3Recorder(**values)  # type: ignore[arg-type]


def test_common_exceptions_are_narrow_value_errors() -> None:
    for error_type in (
        AccountActorAuthorityRawSourceV3Unavailable,
        AccountActorAuthorityRawSourceV3Conflict,
        AccountActorAuthorityRawSourceV3Corruption,
    ):
        error = error_type("bounded")
        assert type(error) is error_type
        assert isinstance(error, ValueError)


def test_application_primitives_have_no_orm_or_concrete_artifact_dependency() -> None:
    path = Path("apps/account/application/account_actor_authority_raw_source_primitives_v3.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    source = path.read_text(encoding="utf-8")

    assert all(not name.startswith(("django", "apps.account.infrastructure")) for name in imports)
    assert ".objects" not in source
    assert "AccountAuthenticationContextSourceV3" not in source
    assert "AccountUserAuthoritySourceV3" not in source
    assert "AccountRbacAuthoritySourceV3" not in source
