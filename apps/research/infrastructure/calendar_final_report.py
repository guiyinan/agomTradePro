"""Immutable JSON artifacts keyed by a CAL-03 final-use receipt."""

import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from apps.research.application.calendar_validation import FinalCalendarReport
from apps.research.domain.event_study_control import EventStudyControlError


def _encode(value: object) -> str | list[str]:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, frozenset) and all(isinstance(v, str) for v in value):
        return sorted(value)
    raise TypeError(f"Cannot encode final report field of type {type(value).__name__}")


def publish_final_calendar_report(directory: Path, report: FinalCalendarReport) -> None:
    """Publish a complete report atomically and refuse conflicting bytes for the same receipt."""
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"cal03-final-{report.claim.claim_id}.json"
    content = (
        json.dumps(
            asdict(report),
            default=_encode,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    with TemporaryDirectory(dir=directory) as staging:
        source = Path(staging) / "report.json"
        with source.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(source, dest)
        except FileExistsError:
            if dest.read_bytes() != content:
                raise EventStudyControlError("FINAL_REPORT_RECEIPT_CONFLICT") from None
