"""Typed Data Center API adapters for TUI-only task contracts."""

from __future__ import annotations

from itertools import islice
from typing import Any, TypedDict, cast
from uuid import UUID

from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAdminUser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.application.instrument_reference_capture import (
    CaptureExecutionStatus,
    CaptureInvocationMode,
)
from apps.data_center.application.interface_services import (
    make_manage_market_thermometer_config_use_case,
    run_macro_governance_action,
)
from apps.data_center.application.public import load_macro_governance_payload
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotError,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
    InstrumentReferenceSourceContractError,
)
from apps.data_center.instrument_reference_snapshot_composition import (
    capture_instrument_reference_snapshot,
    read_instrument_reference_mapping,
    read_instrument_reference_snapshot,
    save_instrument_reference_mapping,
)
from core.exceptions import DuplicateResourceError, ResourceNotFoundError

from .tui_serializers import (
    InstrumentReferenceCaptureTuiSerializer,
    InstrumentReferenceMappingTuiSerializer,
    InstrumentReferenceSnapshotPageTuiSerializer,
    MacroGovernanceTuiActionSerializer,
    MarketThermometerTuiConfigSerializer,
)

_THRESHOLD_KEYS: tuple[str, ...] = (
    "warm_threshold",
    "hot_threshold",
    "overheat_threshold",
    "extreme_threshold",
)


class _InstrumentReferenceMappingInput(TypedDict):
    """Validated JSON shape for one explicit mapping version."""

    mapping_id: str
    mapping_version: str
    source_crosswalk_id: str
    source_crosswalk_version: str
    exchange_suffix_pairs: list[list[str]]
    exchange_rule_market_pairs: list[list[str]]
    exchange_source_market_board_pairs: list[list[str]]


class _InstrumentReferenceCaptureInput(TypedDict):
    """Validated JSON shape for a source-only capture invocation."""

    capture_id: UUID
    provider_configuration_id: int
    mapping_record_id: UUID
    exchange_scope: list[str]
    list_status_scope: list[str]
    mode: str
    include_currency: bool


def _mapping_content_from_input(
    values: _InstrumentReferenceMappingInput,
) -> InstrumentReferenceMappingContent:
    """Build domain mapping content from validated operator-supplied rows."""

    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id=values["source_crosswalk_id"],
        crosswalk_version=values["source_crosswalk_version"],
        exchange_suffix_pairs=tuple((pair[0], pair[1]) for pair in values["exchange_suffix_pairs"]),
    )
    return InstrumentReferenceMappingContent(
        mapping_id=values["mapping_id"],
        mapping_version=values["mapping_version"],
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=tuple(
            (pair[0], pair[1]) for pair in values["exchange_rule_market_pairs"]
        ),
        exchange_source_market_board_pairs=tuple(
            (triple[0], triple[1], triple[2])
            for triple in values["exchange_source_market_board_pairs"]
        ),
    )


def _mapping_receipt_payload(record: InstrumentReferenceMappingRecord) -> dict[str, object]:
    """Serialize one exact mapping receipt without making an approval claim."""

    return {
        "mapping_record_id": str(record.mapping_record_id),
        "content": record.content.to_payload(),
        "content_hash": record.content_hash,
        "record_digest": record.record_digest,
        "recorded_at": record.recorded_at.isoformat(),
        "operator_supplied_only": True,
        "owner_or_provider_approval_asserted": False,
    }


def _snapshot_receipt_payload(record: InstrumentReferenceSnapshotRecord) -> dict[str, object]:
    """Serialize the exact source-only snapshot receipt and its restrictions."""

    content = record.content
    first_candidate = content.fetch_rounds[0].candidate
    return {
        "snapshot_id": str(record.snapshot_id),
        "run_id": str(content.run_id),
        "mapping_record_id": str(record.mapping_record.mapping_record_id),
        "mapping_content_hash": record.mapping_record.content_hash,
        "mapping_record_digest": record.mapping_record.record_digest,
        "provider_contract": _provider_contract_payload(first_candidate.provider_contract),
        "crosswalk": _crosswalk_payload(first_candidate.crosswalk),
        "content_hash": record.content_hash,
        "record_digest": record.record_digest,
        "recorded_at": record.recorded_at.isoformat(),
        "fetch_round_count": len(content.fetch_rounds),
        "record_count": content.record_count,
        "occurrence_count": content.occurrence_count,
        "empty_occurrence_count": content.empty_occurrence_count,
        "last_response_completed_at": content.last_response_completed_at.isoformat(),
        "source_observed_at": content.source_observed_at,
        "source_available_at": content.source_available_at,
        "must_not_use_for_decision": content.must_not_use_for_decision,
        "must_not_execute": content.must_not_execute,
        "blocked_reason": content.blocked_reason,
    }


def _raw_audit_reference_payload(reference: RawAuditReference) -> dict[str, str]:
    """Serialize all identity fields of one exact source RawAudit reference."""

    return {
        "raw_audit_id": reference.raw_audit_id,
        "version": reference.version,
        "content_hash": reference.content_hash,
        "run_id": reference.run_id,
        "ingested_run_id": reference.ingested_run_id,
    }


def _provider_contract_payload(
    contract: InstrumentReferenceProviderContract,
) -> dict[str, object]:
    """Serialize the exact provider request contract and its content identity."""

    return {
        "contract_id": contract.contract_id,
        "contract_version": contract.contract_version,
        "provider_name": contract.provider_name,
        "dataset_key": contract.dataset_key,
        "api_name": contract.api_name,
        "fields": list(contract.fields),
        "exchange_scope_count": len(contract.exchange_scope),
        "list_status_scope_count": len(contract.list_status_scope),
        "content_hash": contract.content_hash,
    }


def _crosswalk_payload(
    crosswalk: InstrumentReferenceExchangeSuffixCrosswalk,
) -> dict[str, object]:
    """Serialize the exact source-exchange suffix mapping used by the snapshot."""

    return {
        "crosswalk_id": crosswalk.crosswalk_id,
        "crosswalk_version": crosswalk.crosswalk_version,
        "content_hash": crosswalk.content_hash,
    }


def _source_occurrence_payload(
    fetch_round: InstrumentReferenceFetchRound,
    occurrence: InstrumentReferenceOccurrence,
    content: InstrumentReferenceSnapshotContent,
) -> dict[str, object]:
    """Serialize one bounded source occurrence with full response and audit identity."""

    contract = fetch_round.candidate.provider_contract
    crosswalk = fetch_round.candidate.crosswalk
    raw_audit_reference = _raw_audit_reference_payload(occurrence.raw_audit_reference)
    return {
        "fetch_round_id": str(fetch_round.fetch_round_id),
        "provider_contract_id": contract.contract_id,
        "provider_contract_version": contract.contract_version,
        "provider_contract_content_hash": contract.content_hash,
        "crosswalk_id": crosswalk.crosswalk_id,
        "crosswalk_version": crosswalk.crosswalk_version,
        "crosswalk_content_hash": crosswalk.content_hash,
        "occurrence_id": str(occurrence.occurrence_id),
        "exchange": occurrence.exchange,
        "list_status": occurrence.list_status,
        "raw_audit_id": occurrence.raw_audit_reference.raw_audit_id,
        "raw_audit_reference": raw_audit_reference,
        "raw_audit_version": occurrence.raw_audit_reference.version,
        "raw_audit_content_hash": occurrence.raw_audit_reference.content_hash,
        "raw_audit_run_id": occurrence.raw_audit_reference.run_id,
        "raw_audit_ingested_run_id": occurrence.raw_audit_reference.ingested_run_id,
        "raw_payload_id": occurrence.raw_payload_id,
        "raw_payload_hash": occurrence.raw_payload_hash,
        "response_body_sha256": occurrence.response_body_sha256,
        "response_completed_at": occurrence.response_completed_at.isoformat(),
        "row_count": occurrence.row_count,
        "source_observed_at": None,
        "source_available_at": None,
        "upstream_time_unknown": True,
        "must_not_use_for_decision": content.must_not_use_for_decision,
        "must_not_execute": content.must_not_execute,
        "blocked_reason": content.blocked_reason,
    }


def _source_row_payload(record: InstrumentReferenceRecord) -> dict[str, object]:
    """Serialize the exact captured source identity and evidence pointers."""

    raw_audit_reference = _raw_audit_reference_payload(record.raw_audit_reference)
    return {
        "ts_code": record.ts_code,
        "name": record.name,
        "source_exchange": record.source_exchange,
        "source_market": record.source_market,
        "source_list_status": record.source_list_status,
        "list_date_raw": record.list_date_raw,
        "list_date": record.list_date.isoformat() if record.list_date is not None else None,
        "delist_date_raw": record.delist_date_raw,
        "delist_date": record.delist_date.isoformat() if record.delist_date is not None else None,
        "exchange_suffix": record.exchange_suffix,
        "occurrence_id": str(record.occurrence_id),
        "raw_audit_id": record.raw_audit_reference.raw_audit_id,
        "raw_audit_reference": raw_audit_reference,
        "raw_audit_version": record.raw_audit_reference.version,
        "raw_audit_content_hash": record.raw_audit_reference.content_hash,
        "raw_audit_run_id": record.raw_audit_reference.run_id,
        "raw_audit_ingested_run_id": record.raw_audit_reference.ingested_run_id,
        "raw_payload_id": record.raw_payload_id,
        "raw_payload_hash": record.raw_payload_hash,
        "source_currency": record.source_currency,
        "source_observed_at": record.source_observed_at,
        "source_available_at": record.source_available_at,
        "upstream_time_unknown": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


class MacroGovernanceTuiView(APIView):
    """Expose the staff-only governance snapshot and confirmed repair actions."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return the current bounded governance evidence snapshot."""

        del request
        return Response({"success": True, "snapshot": load_macro_governance_payload()})

    def post(self, request: Request) -> Response:
        """Run one allow-listed governance action through the Application service."""

        serializer = MacroGovernanceTuiActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "参数验证失败",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        action = str(serializer.validated_data["action"])
        return Response(run_macro_governance_action(action))


class MarketThermometerTuiConfigView(APIView):
    """Read and patch global thermometer config through flat scalar fields."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return the current global thermometer configuration."""

        del request
        config = make_manage_market_thermometer_config_use_case().get()
        return Response(config.to_dict())

    def patch(self, request: Request) -> Response:
        """Merge flat threshold fields into the owner's nested config contract."""

        serializer = MarketThermometerTuiConfigSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "参数验证失败",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        values = dict(serializer.validated_data)
        update_values: dict[str, Any] = {
            key: value for key, value in values.items() if key not in _THRESHOLD_KEYS
        }
        threshold_patch = {key: values[key] for key in _THRESHOLD_KEYS if key in values}
        if threshold_patch:
            current = make_manage_market_thermometer_config_use_case().get().to_dict()
            current_thresholds = dict(current.get("thresholds") or {})
            current_thresholds.update(threshold_patch)
            update_values["thresholds"] = current_thresholds

        updated = make_manage_market_thermometer_config_use_case().update(**update_values)
        return Response(updated.to_dict())


class InstrumentReferenceMappingTuiView(APIView):
    """Register operator-supplied mapping versions."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def post(self, request: Request) -> Response:
        """Append one explicit mapping version or return its exact replay receipt."""

        serializer = InstrumentReferenceMappingTuiSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": "参数验证失败", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        values = cast(_InstrumentReferenceMappingInput, serializer.validated_data)
        try:
            content = _mapping_content_from_input(values)
        except (InstrumentReferenceSnapshotError, InstrumentReferenceSourceContractError) as exc:
            return Response(
                {"success": False, "error": "映射材料无效", "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            record = save_instrument_reference_mapping(content)
        except DuplicateResourceError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "success": True,
                "status": "recorded_or_exact_replay",
                "mapping": _mapping_receipt_payload(record),
            },
            status=status.HTTP_200_OK,
        )


class InstrumentReferenceMappingDetailTuiView(APIView):
    """Read one exact operator-supplied mapping receipt."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request, mapping_record_id: UUID) -> Response:
        """Return only the exact requested immutable mapping receipt."""

        del request
        record = read_instrument_reference_mapping(mapping_record_id=mapping_record_id)
        if record is None:
            return Response(
                {
                    "success": False,
                    "error": "未找到指定版本的映射凭证",
                    "code": "INSTRUMENT_REFERENCE_MAPPING_NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"success": True, "mapping": _mapping_receipt_payload(record)},
            status=status.HTTP_200_OK,
        )


class InstrumentReferenceCaptureTuiView(APIView):
    """Run or resume the existing source-only instrument-reference capture."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def post(self, request: Request) -> Response:
        """Execute the exact provider-config/mapping/scope request and expose its real state."""

        serializer = InstrumentReferenceCaptureTuiSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": "参数验证失败", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        values = cast(_InstrumentReferenceCaptureInput, serializer.validated_data)
        try:
            result = capture_instrument_reference_snapshot(
                capture_id=values["capture_id"],
                provider_configuration_id=values["provider_configuration_id"],
                mapping_record_id=values["mapping_record_id"],
                exchange_scope=tuple(values["exchange_scope"]),
                list_status_scope=tuple(values["list_status_scope"]),
                include_currency=values["include_currency"],
                actor_provenance=f"tui-admin:{request.user.pk}",
                mode=CaptureInvocationMode(values["mode"]),
            )
        except ResourceNotFoundError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (
            InstrumentReferenceCaptureContractError,
            InstrumentReferenceSnapshotError,
            InstrumentReferenceSourceContractError,
        ) as exc:
            return Response(
                {"success": False, "error": "采集请求无效", "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if result.status is CaptureExecutionStatus.COMPLETED:
            response_status: int = status.HTTP_200_OK
            outcome = "success"
            message = "来源快照采集已完成并可按精确编号回读。"
        elif result.status is CaptureExecutionStatus.IN_PROGRESS:
            response_status = status.HTTP_202_ACCEPTED
            outcome = "noop"
            message = "来源采集仍在处理中；当前请求尚未形成完成回执。"
        elif result.status is CaptureExecutionStatus.RESUME_REQUIRED:
            response_status = status.HTTP_202_ACCEPTED
            outcome = "blocked"
            message = "此捕获需要明确恢复；当前请求尚未完成。"
        elif result.status is CaptureExecutionStatus.BLOCKED:
            response_status = status.HTTP_409_CONFLICT
            outcome = "blocked"
            message = "来源捕获已阻断，当前没有完成快照。"
        else:
            response_status = status.HTTP_409_CONFLICT
            outcome = "blocked"
            message = "来源捕获状态无法确认，当前没有完成快照。"
        return Response(
            {
                "outcome": outcome,
                "message": message,
                "success": result.status is CaptureExecutionStatus.COMPLETED,
                "status": result.status.value,
                "capture_id": str(values["capture_id"]),
                "provider_configuration_id": values["provider_configuration_id"],
                "mapping_record_id": str(values["mapping_record_id"]),
                "exchange_scope": values["exchange_scope"],
                "list_status_scope": values["list_status_scope"],
                "mode": values["mode"],
                "include_currency": values["include_currency"],
                "request_sha256": result.request_sha256,
                "reason_code": result.reason_code,
                "snapshot": (
                    _snapshot_receipt_payload(result.snapshot)
                    if result.snapshot is not None
                    else None
                ),
                "decision_ready": False,
                "execution_authorized": False,
            },
            status=response_status,
        )


class InstrumentReferenceSnapshotTuiView(APIView):
    """Read one exact source-only snapshot receipt and a bounded raw-row page."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request, snapshot_id: UUID) -> Response:
        """Return one exact snapshot and a stable page of its captured source rows."""

        serializer = InstrumentReferenceSnapshotPageTuiSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": "参数验证失败", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record = read_instrument_reference_snapshot(snapshot_id=snapshot_id)
        if record is None:
            return Response(
                {
                    "success": False,
                    "error": "未找到指定来源快照",
                    "code": "INSTRUMENT_REFERENCE_SNAPSHOT_NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        values = cast(dict[str, int], serializer.validated_data)
        rows = tuple(
            source_record
            for fetch_round in record.content.fetch_rounds
            for source_record in fetch_round.candidate.records
        )
        occurrences = (
            (fetch_round, occurrence)
            for fetch_round in record.content.fetch_rounds
            for occurrence in fetch_round.candidate.occurrences
        )
        offset = values["offset"]
        limit = values["limit"]
        page = rows[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(rows) else None
        occurrence_page = tuple(islice(occurrences, offset, offset + limit))
        occurrence_total = record.content.occurrence_count
        occurrence_next_offset = (
            offset + len(occurrence_page)
            if offset + len(occurrence_page) < occurrence_total
            else None
        )
        return Response(
            {
                "success": True,
                "snapshot": _snapshot_receipt_payload(record),
                "offset": offset,
                "limit": limit,
                "total": len(rows),
                "next_offset": next_offset,
                "rows": [_source_row_payload(row) for row in page],
                "occurrence_offset": offset,
                "occurrence_limit": limit,
                "occurrence_total": occurrence_total,
                "occurrence_next_offset": occurrence_next_offset,
                "occurrences": [
                    _source_occurrence_payload(fetch_round, occurrence, record.content)
                    for fetch_round, occurrence in occurrence_page
                ],
            },
            status=status.HTTP_200_OK,
        )
