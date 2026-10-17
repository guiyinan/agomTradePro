"""Application contract tests for exact instrument mapping reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.application.instrument_reference_snapshot import (
    GetInstrumentReferenceMappingUseCase,
    InstrumentReferenceSnapshotRepositoryPort,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
    make_instrument_reference_mapping_record,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
)
from core.exceptions import DataValidationError, InvalidInputError

_MAPPING_RECORD_ID = UUID("b560c9a7-e489-4a6c-9cef-7d1ccfd865fb")
_OTHER_MAPPING_RECORD_ID = UUID("bca38cd4-cab8-4f2e-b8cb-a38d0e812e41")
_RECORDED_AT = datetime(2026, 10, 17, 1, 2, 3, tzinfo=UTC)


def _mapping_record(
    mapping_record_id: UUID = _MAPPING_RECORD_ID,
) -> InstrumentReferenceMappingRecord:
    """Build a sealed test mapping without production defaults or persistence."""

    content = InstrumentReferenceMappingContent(
        mapping_id="fixture.instrument-reference",
        mapping_version="fixture-v1",
        source_crosswalk=InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="fixture.crosswalk",
            crosswalk_version="fixture-v1",
            exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
        ),
        exchange_rule_market_pairs=(("SSE", "FIXTURE_RULE_SSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-source-market", "FIXTURE_BOARD"),),
    )
    return make_instrument_reference_mapping_record(
        content,
        mapping_record_id=mapping_record_id,
        recorded_at=_RECORDED_AT,
    )


class _MappingRepository:
    """A typed exact-read port fake that records only requested identities."""

    def __init__(self, result: InstrumentReferenceMappingRecord | None) -> None:
        self.result = result
        self.requested_ids: list[UUID] = []

    def save_mapping(
        self,
        content: InstrumentReferenceMappingContent,
    ) -> InstrumentReferenceMappingRecord:
        raise AssertionError("mapping query must not write")

    def save_snapshot(
        self,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        raise AssertionError("mapping query must not write snapshots")

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        raise AssertionError("mapping query must not read snapshots")

    def get_mapping(self, mapping_record_id: UUID) -> InstrumentReferenceMappingRecord | None:
        self.requested_ids.append(mapping_record_id)
        return self.result


def test_mapping_query_returns_exact_immutable_receipt_without_inverting_mapping() -> None:
    """The public query preserves the selected row's identity and one-way mappings."""

    record = _mapping_record()
    repository = _MappingRepository(record)
    query = GetInstrumentReferenceMappingUseCase(
        cast(InstrumentReferenceSnapshotRepositoryPort, repository)
    )

    result = query.execute(_MAPPING_RECORD_ID)

    assert result is record
    assert repository.requested_ids == [_MAPPING_RECORD_ID]
    assert result.mapping_record_id == _MAPPING_RECORD_ID
    assert result.content.mapping_version == "fixture-v1"
    assert result.content_hash == record.content_hash
    assert result.record_digest == record.record_digest
    assert result.content.rule_market_for("SSE") == "FIXTURE_RULE_SSE"
    assert result.content.rule_market_for("FIXTURE_RULE_SSE") is None


def test_mapping_query_returns_none_for_the_exact_missing_uuid() -> None:
    """A missing explicit UUID stays missing instead of selecting another version."""

    missing_id = UUID("6d9cf90f-2f22-4b18-a95b-2278a7f1f00b")
    repository = _MappingRepository(None)
    query = GetInstrumentReferenceMappingUseCase(
        cast(InstrumentReferenceSnapshotRepositoryPort, repository)
    )

    assert query.execute(missing_id) is None
    assert repository.requested_ids == [missing_id]


@pytest.mark.parametrize("invalid_id", [None, "b560c9a7-e489-4a6c-9cef-7d1ccfd865fb", 17])
def test_mapping_query_rejects_non_uuid_before_repository_access(invalid_id: object) -> None:
    """Invalid runtime values are rejected before reaching persistence."""

    repository = _MappingRepository(_mapping_record())
    query = GetInstrumentReferenceMappingUseCase(
        cast(InstrumentReferenceSnapshotRepositoryPort, repository)
    )

    with pytest.raises(InvalidInputError) as error:
        query.execute(cast(UUID, invalid_id))

    assert error.value.code == "INSTRUMENT_REFERENCE_MAPPING_ID_INVALID"
    assert repository.requested_ids == []


def test_mapping_query_rejects_an_adapter_result_that_is_not_a_domain_record() -> None:
    """A broken adapter cannot make an untyped object look like mapping evidence."""

    repository = _MappingRepository(cast(InstrumentReferenceMappingRecord, object()))
    query = GetInstrumentReferenceMappingUseCase(
        cast(InstrumentReferenceSnapshotRepositoryPort, repository)
    )

    with pytest.raises(DataValidationError) as error:
        query.execute(_MAPPING_RECORD_ID)

    assert error.value.code == "INSTRUMENT_REFERENCE_MAPPING_RESULT_INVALID"
    assert repository.requested_ids == [_MAPPING_RECORD_ID]


def test_mapping_query_rejects_a_different_record_returned_for_the_requested_uuid() -> None:
    """A port cannot substitute another immutable mapping version or identity."""

    repository = _MappingRepository(_mapping_record(_OTHER_MAPPING_RECORD_ID))
    query = GetInstrumentReferenceMappingUseCase(
        cast(InstrumentReferenceSnapshotRepositoryPort, repository)
    )

    with pytest.raises(DataValidationError) as error:
        query.execute(_MAPPING_RECORD_ID)

    assert error.value.code == "INSTRUMENT_REFERENCE_MAPPING_RESULT_INVALID"
    assert repository.requested_ids == [_MAPPING_RECORD_ID]
