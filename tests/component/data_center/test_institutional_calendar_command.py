"""Operator import verifies exact inputs and preserves clocks on an identical retry."""

import hashlib
import io
import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from apps.data_center.infrastructure.models import RawPayloadModel
from tests.support.institutional_calendar_world import FIXTURES, retained_originals

pytestmark = pytest.mark.django_db


def command_inputs(tmp_path: Path) -> dict[str, str]:
    schedule, actual = retained_originals()
    policy = asdict(schedule.policy)
    policy["valid_until"] = schedule.policy.valid_until.isoformat()
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_bytes(b'{"scope":"synthetic command mechanics"}')
    policy["catalogue_sha256"] = hashlib.sha256(catalogue.read_bytes()).hexdigest()
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    return {
        "policy": str(policy_path),
        "catalogue": str(catalogue),
        "schedule": os.environ.get(
            "CAL02_NBS_SCHEDULE_ORIGINAL", str(FIXTURES / "nbs_2026_schedule_cpi.html")
        ),
        "actual": os.environ.get(
            "CAL02_NBS_ACTUAL_ORIGINAL", str(FIXTURES / "nbs_cpi_20261109.html")
        ),
        "schedule_sha256": schedule.sha256,
        "actual_sha256": actual.sha256,
        "schedule_url": schedule.url,
        "actual_url": actual.url,
        "schedule_first_seen": schedule.first_seen_at.isoformat(),
        "actual_first_seen": actual.first_seen_at.isoformat(),
        "content_title": "居民消费价格指数月度报告",
        "event_id_prefix": "nbs-cpi-command",
    }


def test_operator_retry_keeps_exact_first_seen_and_original_recording_clock(tmp_path: Path) -> None:
    options = command_inputs(tmp_path)
    call_command("import_institutional_calendar", **options, stdout=io.StringIO())
    before = DjangoInstitutionalCalendarRepository().list_versions()
    assert len(before) == 13 and RawPayloadModel.objects.count() == 2
    call_command("import_institutional_calendar", **options, stdout=io.StringIO())
    assert DjangoInstitutionalCalendarRepository().list_versions() == before
    assert RawPayloadModel.objects.count() == 2


@pytest.mark.parametrize("field", ("catalogue", "actual_sha256"))
def test_input_digest_mismatch_prevents_all_original_and_event_writes(
    tmp_path: Path, field: str
) -> None:
    options = command_inputs(tmp_path)
    if field == "catalogue":
        Path(options["catalogue"]).write_bytes(b"changed catalogue")
    else:
        options[field] = "0" * 64
    with pytest.raises(CommandError):
        call_command("import_institutional_calendar", **options, stdout=io.StringIO())
    assert DjangoInstitutionalCalendarRepository().list_versions() == ()
    assert RawPayloadModel.objects.count() == 0
