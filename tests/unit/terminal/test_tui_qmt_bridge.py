"""User-visible pairing tasks are registered and schema-valid."""

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository


@pytest.mark.django_db
def test_qmt_pairing_and_approval_are_published_to_separate_audiences():
    metadata = PublishedTuiMetadataRepository().load_published()
    validate_tui_metadata(metadata)
    actions = {a["key"]: a for a in metadata["actions"]}
    create = actions["qmt-bridge.create"]
    assert create["audience"] == "authenticated"
    assert "copyable_secret" in create["result_semantics"]
    assert actions["qmt-bridge.approve"]["audience"] == "admin"
    assert actions["qmt-bridge.list"]["view_model"]["rows_path"] == "data"
    assert {f["key"] for f in create["fields"]} == {"agent_id", "assets"}
