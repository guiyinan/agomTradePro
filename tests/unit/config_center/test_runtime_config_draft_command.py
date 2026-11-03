"""Operator boundary tests for generic draft preview and explicit creation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command

from apps.config_center.application.runtime_config_drafts import (
    RuntimeConfigDraftCreateResult,
    RuntimeConfigDraftPlan,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigValue,
    RuntimeProfileStatus,
)


def _plan() -> RuntimeConfigDraftPlan:
    """Return one complete generic plan without database access."""

    profile_id = str(uuid4())
    value = RuntimeConfigValue(
        profile_id=profile_id,
        definition_key="test.draft.value",
        value_json={"candidate": "data"},
        source="test_fixture",
    )
    profile = RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key="test.draft.profile",
        environment="development",
        version=1,
        status=RuntimeProfileStatus.DRAFT,
        content_hash="0" * 64,
    )
    revision = RuntimeConfigRevision(
        revision_id=str(uuid4()),
        profile_id=profile_id,
        before_hash="",
        after_hash=profile.content_hash,
        changed_keys=(value.definition_key,),
        before_projection={value.definition_key: value.value_json},
        after_projection={value.definition_key: value.value_json},
        actor="operator@example.test",
        reason="command contract",
        changed_at=datetime.now(UTC),
        validation_evidence={
            "draft_only": True,
            "generic_definition_validation": "passed",
            "consumer_schema_validation": "not_performed",
            "snapshot_created": False,
            "active_pointer_changed": False,
        },
    )
    return RuntimeConfigDraftPlan(profile=profile, values=(value,), revision=revision)


def _draft_file(tmp_path, *, extra_field: bool = False) -> str:
    """Write one generic Config Center draft envelope."""

    payload: dict[str, object] = {
        "profile_key": "test.draft.profile",
        "environment": "development",
        "version": 1,
        "values": [
            {
                "definition_key": "test.draft.value",
                "value_json": {"candidate": "data"},
                "source": "test_fixture",
            }
        ],
    }
    if extra_field:
        payload["unexpected"] = True
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_command_is_dry_run_by_default_and_does_not_persist(mocker, tmp_path) -> None:
    plan = _plan()
    preview = mocker.patch(
        "apps.config_center.management.commands.create_runtime_profile_draft."
        "preview_runtime_profile_draft",
        return_value=plan,
    )
    create = mocker.patch(
        "apps.config_center.management.commands.create_runtime_profile_draft."
        "create_runtime_profile_draft"
    )
    stdout = StringIO()

    call_command(
        "create_runtime_profile_draft",
        "--draft-file",
        _draft_file(tmp_path),
        "--actor",
        "operator@example.test",
        "--reason",
        "ASH07 draft, incomplete",
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["status"] == "draft"
    assert payload["draft_only"] is True
    assert payload["consumer_schema_validation"] == "not_performed"
    assert payload["snapshot_created"] is False
    assert payload["active_pointer_changed"] is False
    preview.assert_called_once()
    create.assert_not_called()


def test_command_executes_only_with_explicit_flag_and_reports_no_snapshot(
    mocker,
    tmp_path,
) -> None:
    plan = _plan()
    stored_revision = RuntimeConfigRevision(
        revision_id=str(uuid4()),
        profile_id=plan.revision.profile_id,
        before_hash=plan.revision.before_hash,
        after_hash=plan.revision.after_hash,
        changed_keys=plan.revision.changed_keys,
        before_projection=plan.revision.before_projection,
        after_projection=plan.revision.after_projection,
        actor=plan.revision.actor,
        reason=plan.revision.reason,
        changed_at=plan.revision.changed_at,
        release_ref=plan.revision.release_ref,
        validation_evidence=plan.revision.validation_evidence,
    )
    result = RuntimeConfigDraftCreateResult(
        profile=plan.profile,
        values=plan.values,
        revision=stored_revision,
        created=True,
    )
    preview = mocker.patch(
        "apps.config_center.management.commands.create_runtime_profile_draft."
        "preview_runtime_profile_draft",
        return_value=plan,
    )
    create = mocker.patch(
        "apps.config_center.management.commands.create_runtime_profile_draft."
        "create_runtime_profile_draft",
        return_value=result,
    )
    stdout = StringIO()

    call_command(
        "create_runtime_profile_draft",
        "--draft-file",
        _draft_file(tmp_path),
        "--actor",
        "operator@example.test",
        "--reason",
        "ASH07 draft, incomplete",
        "--execute",
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "execute"
    assert payload["created"] is True
    assert payload["status"] == "draft"
    assert payload["snapshot_created"] is False
    assert payload["active_pointer_changed"] is False
    assert payload["revision_id"] == stored_revision.revision_id
    preview.assert_not_called()
    create.assert_called_once()


def test_command_rejects_unknown_json_fields_before_application_call(
    mocker,
    tmp_path,
) -> None:
    preview = mocker.patch(
        "apps.config_center.management.commands.create_runtime_profile_draft."
        "preview_runtime_profile_draft"
    )

    with pytest.raises(CommandError, match="unknown=unexpected"):
        call_command(
            "create_runtime_profile_draft",
            "--draft-file",
            _draft_file(tmp_path, extra_field=True),
            "--actor",
            "operator@example.test",
            "--reason",
            "strict envelope contract",
            stdout=StringIO(),
        )

    preview.assert_not_called()
