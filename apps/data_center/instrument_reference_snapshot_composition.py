"""Public exact-read composition for immutable instrument-reference receipts."""

from __future__ import annotations

from uuid import UUID

from apps.data_center.application.instrument_reference_capture import (
    CaptureExecutionStatus,
    CaptureInvocationMode,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureResult,
)
from apps.data_center.application.instrument_reference_capture_use_case import (
    CaptureInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.instrument_reference_snapshot import (
    GetInstrumentReferenceMappingUseCase,
    GetInstrumentReferenceSnapshotUseCase,
    SaveInstrumentReferenceMappingUseCase,
)
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceProviderContract,
)
from apps.data_center.infrastructure.instrument_reference_capture_composition import (
    create_instrument_reference_capture_use_case,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    InstrumentReferenceSnapshotPersistenceError,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_runtime import (
    create_instrument_reference_snapshot_repository,
)
from core.exceptions import (
    DataValidationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)

_STOCK_BASIC_FIELDS: tuple[str, ...] = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)


def read_instrument_reference_snapshot(
    *,
    snapshot_id: UUID,
) -> InstrumentReferenceSnapshotRecord | None:
    """Read and fully revalidate one exact persisted source snapshot."""

    repository = create_instrument_reference_snapshot_repository()
    return GetInstrumentReferenceSnapshotUseCase(repository).execute(snapshot_id)


def read_instrument_reference_mapping(
    *,
    mapping_record_id: UUID,
) -> InstrumentReferenceMappingRecord | None:
    """Read and fully revalidate one exact persisted mapping receipt."""

    repository = create_instrument_reference_snapshot_repository()
    return GetInstrumentReferenceMappingUseCase(repository).execute(mapping_record_id)


def save_instrument_reference_mapping(
    content: InstrumentReferenceMappingContent,
) -> InstrumentReferenceMappingRecord:
    """Append an explicit mapping version and return only its exact readback."""

    repository = create_instrument_reference_snapshot_repository()
    try:
        saved = SaveInstrumentReferenceMappingUseCase(repository).execute(content)
    except InstrumentReferenceSnapshotPersistenceError as exc:
        if exc.code == "INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE":
            raise DuplicateResourceError(
                "This mapping identifier and version are already sealed with different content.",
                code=exc.code,
            ) from exc
        raise DataValidationError(
            "The instrument-reference mapping could not be persisted.",
            code=exc.code,
        ) from exc
    readback = GetInstrumentReferenceMappingUseCase(repository).execute(saved.mapping_record_id)
    if readback is None or readback != saved:
        raise DataValidationError(
            "The saved instrument-reference mapping did not match its exact readback.",
            code="INSTRUMENT_REFERENCE_MAPPING_READBACK_INVALID",
        )
    return readback


def capture_instrument_reference_snapshot(
    *,
    capture_id: UUID,
    provider_configuration_id: int,
    mapping_record_id: UUID,
    exchange_scope: tuple[str, ...],
    list_status_scope: tuple[str, ...],
    actor_provenance: str,
    mode: CaptureInvocationMode,
    include_currency: bool = False,
) -> InstrumentReferenceCaptureResult:
    """Capture exact source facts, optionally requesting the provider's currency field.

    The default preserves existing seven-field request identities. Changing
    this choice on a retry changes the contract and must fail the existing
    capture request-digest check rather than reuse a differently scoped result.
    """

    if type(include_currency) is not bool:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CURRENCY_CHOICE_INVALID"
        )

    mapping_record = read_instrument_reference_mapping(mapping_record_id=mapping_record_id)
    if mapping_record is None:
        raise ResourceNotFoundError(
            "The exact instrument-reference mapping receipt does not exist.",
            code="INSTRUMENT_REFERENCE_MAPPING_NOT_FOUND",
        )
    provider_contract = InstrumentReferenceProviderContract(
        contract_id="tushare.stock_basic",
        contract_version="v2" if include_currency else "v1",
        provider_name="tushare",
        dataset_key="tushare.stock_basic.reference",
        api_name="stock_basic",
        fields=(*_STOCK_BASIC_FIELDS, "curr_type") if include_currency else _STOCK_BASIC_FIELDS,
        exchange_scope=exchange_scope,
        list_status_scope=list_status_scope,
    )
    request = InstrumentReferenceCaptureRequest(
        capture_id=capture_id,
        provider_contract=provider_contract,
        provider_route_id="tushare.stock_basic",
        provider_route_revision="v1",
        provider_configuration_id=provider_configuration_id,
        mapping_record=mapping_record,
        actor_provenance=actor_provenance,
        source_only=True,
        repository_alias="default",
    )
    capture_use_case: CaptureInstrumentReferenceSnapshotUseCase = (
        create_instrument_reference_capture_use_case()
    )
    result = capture_use_case.execute(
        InstrumentReferenceCaptureInvocation(request=request, mode=mode)
    )
    if result.status is not CaptureExecutionStatus.COMPLETED or result.snapshot is None:
        return result
    readback = read_instrument_reference_snapshot(snapshot_id=result.snapshot.snapshot_id)
    if readback != result.snapshot:
        return InstrumentReferenceCaptureResult(
            status=CaptureExecutionStatus.BLOCKED,
            identity=request.identity,
            request_sha256=request.request_sha256,
            reason_code="INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_READBACK_INVALID",
        )
    return result


__all__ = [
    "capture_instrument_reference_snapshot",
    "read_instrument_reference_mapping",
    "read_instrument_reference_snapshot",
    "save_instrument_reference_mapping",
]
