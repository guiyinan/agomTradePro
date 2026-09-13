"""Field-shape completeness keeps partial financial evidence explicit."""

from datetime import UTC, datetime
from typing import cast

import pytest

from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence


@pytest.mark.parametrize(
    ("announced_at", "source_record_id", "raw_payload_hash", "complete"),
    [
        (None, "record-1", "a" * 64, False),
        (datetime(2026, 9, 14, tzinfo=UTC), None, "a" * 64, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "", "a" * 64, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", None, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", "", False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", "a" * 63, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", "A" * 64, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", "g" * 64, False),
        (datetime(2026, 9, 14, tzinfo=UTC), "record-1", "a" * 64, True),
    ],
)
def test_financial_source_completeness_requires_all_valid_field_shapes(
    announced_at: datetime | None,
    source_record_id: str | None,
    raw_payload_hash: str | None,
    complete: bool,
) -> None:
    """Missing or malformed source fields cannot become complete evidence."""
    evidence = FinancialFactSourceEvidence(announced_at, source_record_id, raw_payload_hash)

    assert evidence.is_complete is complete
    assert evidence.to_dict() == {
        "announced_at": announced_at.isoformat() if announced_at is not None else None,
        "source_record_id": source_record_id,
        "raw_payload_hash": raw_payload_hash,
    }


@pytest.mark.parametrize("field_name", ["source_record_id", "raw_payload_hash"])
@pytest.mark.parametrize("invalid_value", [" padded", "padded ", 17])
def test_financial_source_identifiers_reject_padded_or_non_text_values(
    field_name: str, invalid_value: str | int
) -> None:
    """Source identifiers must survive the typed boundary without coercion."""
    values: dict[str, str | None] = {field_name: cast(str, invalid_value)}

    with pytest.raises(ValueError, match=field_name):
        FinancialFactSourceEvidence(**values)
