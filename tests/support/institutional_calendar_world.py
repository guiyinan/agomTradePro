"""Explicit CAL test inputs; optional native acceptance uses retained full originals."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apps.data_center.application.institutional_calendar_sources import (
    InstitutionalSourcePolicy,
    RetainedInstitutionalOriginal,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/data_center/institutional_calendar"
SCHEDULE_URL = "https://www.stats.gov.cn/xw/tjxw/tzgg/202512/t20251224_1962137.html"
ACTUAL_URL = "https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html"


def retained_originals() -> tuple[RetainedInstitutionalOriginal, RetainedInstitutionalOriginal]:
    """Use honest captured receipt dates and the current actual persistence clock."""
    now = datetime.now(UTC)
    policy = InstitutionalSourcePolicy(
        source_id="nbs_calendar_qa",
        event_type="nbs_cpi_release",
        rule_version="six-period-v1",
        catalogue_sha256="efc6d373f316e00ab9610c5a1e27aec59a63c3c9cb33739785178d0b7aa50685",
        timezone_name="Asia/Shanghai",
        attribution="国家统计局（NBS）；合理、善意、免费引用，保留来源链接。",
        allowed_urls=(SCHEDULE_URL, ACTUAL_URL),
        valid_until=now + timedelta(days=1),
    )
    schedule_path = Path(
        os.environ.get("CAL02_NBS_SCHEDULE_ORIGINAL", str(FIXTURES / "nbs_2026_schedule_cpi.html"))
    )
    actual_path = Path(
        os.environ.get("CAL02_NBS_ACTUAL_ORIGINAL", str(FIXTURES / "nbs_cpi_20261109.html"))
    )
    schedule_body, actual_body = schedule_path.read_bytes(), actual_path.read_bytes()
    schedule = RetainedInstitutionalOriginal(
        policy,
        SCHEDULE_URL,
        schedule_body,
        hashlib.sha256(schedule_body).hexdigest(),
        datetime(2026, 11, 10, 3, 47, 27, tzinfo=UTC),
        now,
    )
    actual = RetainedInstitutionalOriginal(
        policy,
        ACTUAL_URL,
        actual_body,
        hashlib.sha256(actual_body).hexdigest(),
        datetime(2026, 11, 11, 0, 3, 40, tzinfo=UTC),
        now,
    )
    return schedule, actual
