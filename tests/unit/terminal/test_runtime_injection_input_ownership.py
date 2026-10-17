"""Normalization must not change reusable runtime metadata declarations."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository
from apps.terminal.infrastructure.tui_metadata_runtime_injection_registry import (
    RUNTIME_METADATA_INJECTIONS,
    RuntimeMetadataInjectionBundle,
)
from tests.unit.test_tui_workbench import _metadata_payload


@pytest.mark.parametrize("replace_existing", [False, True])
@pytest.mark.parametrize("field_owner", ["bundle", "ia"])
def test_normalization_preserves_injection_input_fields(
    replace_existing: bool,
    field_owner: Literal["bundle", "ia"],
) -> None:
    """Inserted and replaced actions normalize their own fields, from either owner."""
    action = _metadata_payload()["actions"][0]
    field = {"key": "exchange", "label": "交易所", "binding": "query", "required": True}
    owned_copy: dict[str, dict[str, Any]] = {}
    if field_owner == "bundle":
        action["fields"] = [field]
    else:
        owned_copy[action["key"]] = {"fields": [field]}
    bundle = RuntimeMetadataInjectionBundle(
        coverage_key="test_owned_fields",
        actions=(action,),
        replace_existing=replace_existing,
    )
    before_bundle = deepcopy(bundle)
    before_owned = deepcopy(owned_copy)
    old_action = deepcopy(action) | {"label": "Old label"}
    payload = _metadata_payload(actions=[old_action] if replace_existing else [])
    payload["screens"][0]["default_action_key"] = action["key"]

    injected = PublishedTuiMetadataRepository._inject_runtime_bundle(
        bundle=bundle,
        groups=payload["groups"],
        modules=payload["modules"],
        screens=payload["screens"],
        actions=payload["actions"],
        ia_owned_action_copy=owned_copy,
    )
    result = validate_tui_metadata(payload)

    assert injected == 1
    assert result["actions"][0]["fields"][0]["default"] == ""
    assert bundle == before_bundle
    assert owned_copy == before_owned


def test_published_normalization_preserves_runtime_declarations() -> None:
    """The real published graph cannot add derived keys to shared runtime bundles."""
    before = deepcopy(RUNTIME_METADATA_INJECTIONS)
    path = (
        Path(__file__).resolve().parents[3]
        / "config/tui/published/tui_operation_graph.published.json"
    )
    repository = PublishedTuiMetadataRepository(published_path=path)

    result = repository.validate_and_normalize_runtime_payload(
        json.loads(path.read_text(encoding="utf-8"))
    )

    assert result["actions"]
    assert RUNTIME_METADATA_INJECTIONS == before
