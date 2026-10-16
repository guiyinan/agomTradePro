"""Check the published v2 detail schema against the actual canonical builder."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from apps.audit.application.data_publication_rollback_audit import (
    build_data_publication_rollback_audit_event,
)
from tests.unit.audit.test_data_publication_rollback_audit import SCOPE, _observation

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "docs/api/data-publication-rolled-back-v2-detail.schema.json"
    ).read_text(encoding="utf-8")
)


def _detail() -> dict[str, object]:
    observation = replace(
        _observation(scope=SCOPE),
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
        previous_pointer_activation_id="b4bf22c3-3e4e-46ac-993d-318c8f0d342e",
    )
    event = build_data_publication_rollback_audit_event(
        observation, sequence_no=1, predecessor_hash=None
    )
    assert event.detail_schema == "data.publication.rolled_back.v2"
    return dict(event.to_payload()["detail"])


def test_actual_pointer_rollback_detail_matches_published_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(_detail())


@pytest.mark.parametrize("change", ("missing_epoch", "noncanonical_epoch", "extra", "bad_hash"))
def test_pointer_rollback_detail_rejects_incomplete_or_changed_shape(change: str) -> None:
    detail = _detail()
    if change == "missing_epoch":
        del detail["previous_pointer_activation_id"]
    elif change == "noncanonical_epoch":
        detail["previous_pointer_activation_id"] = "B4BF22C3-3E4E-46AC-993D-318C8F0D342E"
    elif change == "extra":
        detail["unexpected"] = True
    else:
        detail["publication_hash"] = "sha256:" + "a" * 64
    assert list(Draft202012Validator(SCHEMA).iter_errors(detail))
