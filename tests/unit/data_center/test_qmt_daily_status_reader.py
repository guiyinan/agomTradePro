"""Daily state selection preserves unknowns, conflicts, and local knowledge clocks."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from apps.data_center.application.qmt_daily_status import (
    QmtDailyStatusReadSnapshot,
    QmtDailyStatusRecord,
    ReadQmtDailyStatus,
)
from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
    QmtDailyStatusState,
    QmtDailyStatusValidationError,
)

DAY = date(2026, 10, 26)
KNOWN = datetime(2026, 10, 27, 1, tzinfo=UTC)
AS_OF = KNOWN + timedelta(hours=2)
BINDING = str(UUID(int=8))


def record(flag=1, *, number=1, collected_at=KNOWN, asset="510300.SH", day=DAY):
    batch = BridgeDailyStatusBatch(
        batch_id=str(UUID(int=number)),
        kind="daily_status",
        collected_at=collected_at,
        request_start=day,
        request_end=day,
        samples=(BridgeDailyStatusSample(asset, day, flag),),
        schema_version="qmt-native-daily-status.v1",
    )
    return QmtDailyStatusRecord(batch, collected_at + timedelta(seconds=1), batch.content_hash)


class Port:
    def __init__(self, *records, reason=None):
        self.snapshot = QmtDailyStatusReadSnapshot(tuple(records), reason)
        self.calls = []

    def read_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return self.snapshot


def read(port, **kwargs):
    return ReadQmtDailyStatus(port).execute(
        **(
            {
                "owner_id": 1,
                "binding_id": BINDING,
                "asset_code": "510300.SH",
                "bar_date": DAY,
                "as_of": AS_OF,
            }
            | kwargs
        )
    )


@pytest.mark.parametrize("flag,state", [(0, "normal"), (1, "suspended"), (-1, "resumed")])
def test_daily_status_returns_native_state_without_decision_qualification(flag, state):
    source = record(flag)
    result = read(Port(source))
    assert result.state.value == state
    assert result.suspend_flag == flag
    assert result.local_known_at == KNOWN
    assert result.recorded_at == source.recorded_at
    assert result.source_observed_at is None and result.source_available_at is None
    assert result.freshness == "unknown" and result.reliability == "unverified"
    assert result.must_not_use_for_decision and result.must_not_execute
    assert result.blocked_reason == "qmt_daily_status_requires_publication_validation"
    assert result.evidence[0].batch_id == source.batch.batch_id
    assert result.evidence[0].content_hash == source.digest


@pytest.mark.parametrize("records", [(), (record(None),), (record(asset="600000.SH"),)])
def test_daily_status_missing_or_unknown_never_means_normal(records):
    result = read(Port(*records))
    assert result.state is QmtDailyStatusState.UNKNOWN
    assert result.suspend_flag is None
    assert result.must_not_use_for_decision and result.must_not_execute


def test_daily_status_cannot_silently_clear_a_prior_restriction():
    older = record(1)
    newer = record(0, number=2, collected_at=KNOWN + timedelta(minutes=1))
    for records in ((older, newer), (newer, older)):
        result = read(Port(*records))
        assert result.state is QmtDailyStatusState.UNKNOWN
        assert result.blocked_reason == "qmt_daily_status_conflicting_observations"


def test_daily_status_latest_unknown_does_not_fall_back_to_older_normal():
    result = read(
        Port(record(0), record(None, number=2, collected_at=KNOWN + timedelta(minutes=1)))
    )
    assert result.state is QmtDailyStatusState.UNKNOWN
    assert result.blocked_reason == "qmt_daily_status_missing_suspend_flag"


def test_daily_status_new_explicit_observation_can_replace_an_earlier_unknown():
    later = KNOWN + timedelta(minutes=1)
    result = read(Port(record(None), record(1, number=2, collected_at=later)))
    assert result.state is QmtDailyStatusState.SUSPENDED
    assert result.local_known_at == later
    assert len(result.evidence) == 2


@pytest.mark.parametrize("mutation", ["digest", "future_record", "before_collection"])
def test_daily_status_reader_rejects_broken_retained_proof(mutation):
    source = record()
    if mutation == "digest":
        source = replace(source, digest="0" * 64)
    elif mutation == "future_record":
        source = replace(source, recorded_at=AS_OF + timedelta(seconds=1))
    else:
        source = replace(source, recorded_at=KNOWN - timedelta(seconds=1))
    result = read(Port(source))
    assert result.state is QmtDailyStatusState.UNKNOWN
    assert result.blocked_reason == "qmt_daily_status_invalid_retained_evidence"


def test_daily_status_blocked_scope_is_not_recovered_from_supplied_rows():
    port = Port(record(), reason="qmt_daily_status_scope_unavailable")
    result = read(port)
    assert result.state is QmtDailyStatusState.UNKNOWN
    assert result.blocked_reason == "qmt_daily_status_scope_unavailable"
    assert result.evidence == ()
    assert port.calls == [
        {
            "owner_id": 1,
            "binding_id": BINDING,
            "asset_code": "510300.SH",
            "bar_date": DAY,
            "as_of": AS_OF,
        }
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", True),
        ("owner_id", 0),
        ("binding_id", "bad"),
        ("asset_code", " x "),
        ("bar_date", AS_OF),
        ("as_of", AS_OF.replace(tzinfo=None)),
    ],
)
def test_daily_status_invalid_queries_do_not_read_storage(field, value):
    port = Port()
    kwargs = {
        "owner_id": 1,
        "binding_id": BINDING,
        "asset_code": "510300.SH",
        "bar_date": DAY,
        "as_of": AS_OF,
    }
    kwargs[field] = value
    with pytest.raises(QmtDailyStatusValidationError):
        ReadQmtDailyStatus(port).execute(**kwargs)
    assert not port.calls
