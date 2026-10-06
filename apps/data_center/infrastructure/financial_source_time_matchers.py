"""Provider-specific matchers recomputing source-time witnesses from retained bodies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeJoinField,
    FinancialSourceTimeJoinSemantic,
    FinancialSourceTimeMatchContract,
    financial_source_time_contract_sha256,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimePrecision,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure.financial_response_capture import decode_json_bytes

AKSHARE_PROVIDER_NAME = "akshare"
AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT = (
    "datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_MAINFINADATA"
)
AKSHARE_NOTICE_DATE_CONTRACT_ID = "akshare.financial-main-data.notice-date"
AKSHARE_NOTICE_DATE_CONTRACT_VERSION = "2026-10-04.v1"
AKSHARE_NOTICE_DATE_PARSER_VERSION = "akshare-eastmoney-main-financial-data.v1"
AKSHARE_SOURCE_TIMEZONE = "Asia/Shanghai"
AKSHARE_ASSET_FIELD = "SECUCODE"
AKSHARE_PERIOD_END_FIELD = "REPORT_DATE"
AKSHARE_ANNOUNCEMENT_DATE_FIELD = "NOTICE_DATE"
# The provider payload has no row-level identifier. Row identity is the
# explicitly declared composite of the three real join fields, and the two
# time values are explicitly declared derivations from the announcement date.
AKSHARE_SOURCE_ROW_ID_FIELD = "composite:SECUCODE+REPORT_DATE+NOTICE_DATE"
AKSHARE_ANNOUNCED_AT_FIELD = "derived:NOTICE_DATE@day_start"
AKSHARE_AVAILABLE_AT_FIELD = "derived:NOTICE_DATE@next_day_start"

_ROW_PROJECTION_HASH_DOMAIN = b"agomtradepro:financial-source-time-row-projection:v1\0"


def akshare_notice_date_match_contract() -> FinancialSourceTimeMatchContract:
    """Build the governed AKShare date-only match contract from declared constants."""

    join_fields = (
        FinancialSourceTimeJoinField(
            FinancialSourceTimeJoinSemantic.ASSET_CODE,
            AKSHARE_ASSET_FIELD,
            AKSHARE_ASSET_FIELD,
        ),
        FinancialSourceTimeJoinField(
            FinancialSourceTimeJoinSemantic.PERIOD_END,
            AKSHARE_PERIOD_END_FIELD,
            AKSHARE_PERIOD_END_FIELD,
        ),
        FinancialSourceTimeJoinField(
            FinancialSourceTimeJoinSemantic.ANNOUNCEMENT_DATE,
            AKSHARE_ANNOUNCEMENT_DATE_FIELD,
            AKSHARE_ANNOUNCEMENT_DATE_FIELD,
        ),
    )
    projection_fields = (
        AKSHARE_ASSET_FIELD,
        AKSHARE_PERIOD_END_FIELD,
        AKSHARE_ANNOUNCEMENT_DATE_FIELD,
        AKSHARE_SOURCE_ROW_ID_FIELD,
        AKSHARE_ANNOUNCED_AT_FIELD,
        AKSHARE_AVAILABLE_AT_FIELD,
    )
    payload: dict[str, object] = {
        "provider_name": AKSHARE_PROVIDER_NAME,
        "financial_dataset_key": "equity.financial.fact",
        "source_time_dataset_key": "equity.financial.source-time",
        "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        "contract_id": AKSHARE_NOTICE_DATE_CONTRACT_ID,
        "contract_version": AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
        "parser_version": AKSHARE_NOTICE_DATE_PARSER_VERSION,
        "source_timezone": AKSHARE_SOURCE_TIMEZONE,
        "join_fields": [item.to_dict() for item in join_fields],
        "source_row_id_field": AKSHARE_SOURCE_ROW_ID_FIELD,
        "announced_at_field": AKSHARE_ANNOUNCED_AT_FIELD,
        "available_at_field": AKSHARE_AVAILABLE_AT_FIELD,
        "projection_fields": list(projection_fields),
    }
    return FinancialSourceTimeMatchContract(
        provider_name=AKSHARE_PROVIDER_NAME,
        financial_dataset_key="equity.financial.fact",
        source_time_dataset_key="equity.financial.source-time",
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        contract_id=AKSHARE_NOTICE_DATE_CONTRACT_ID,
        contract_version=AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
        parser_version=AKSHARE_NOTICE_DATE_PARSER_VERSION,
        source_timezone=AKSHARE_SOURCE_TIMEZONE,
        join_fields=join_fields,
        source_row_id_field=AKSHARE_SOURCE_ROW_ID_FIELD,
        announced_at_field=AKSHARE_ANNOUNCED_AT_FIELD,
        available_at_field=AKSHARE_AVAILABLE_AT_FIELD,
        projection_fields=projection_fields,
        contract_sha256=financial_source_time_contract_sha256(payload),
    )


class AkshareNoticeDateSourceTimeMatcher:
    """Recompute the AKShare date-only witness from both retained response bodies.

    The financial response and the source-time artifact are independent
    captures of the same EastMoney main-financial-data endpoint, whose rows
    carry only calendar-date ``NOTICE_DATE`` values. Availability follows the
    owner-approved date-only rule: the announcement day starts at 00:00
    Asia/Shanghai and the fact becomes available at the next day start.
    """

    def match(
        self,
        *,
        contract: FinancialSourceTimeMatchContract,
        financial_body: bytes,
        source_time_body: bytes,
        decision_evidence: FinancialFactDecisionEvidence,
    ) -> FinancialSourceTimeWitness | None:
        """Return the recomputed unique date-only witness, or ``None``."""

        if contract != akshare_notice_date_match_contract():
            return None
        claimed = decision_evidence.source_time_witness
        if claimed is None:
            return None
        return self.build_witness(
            contract=contract,
            financial_body=financial_body,
            source_time_body=source_time_body,
            decision_evidence=decision_evidence,
            source_time_reference=claimed.artifact_reference,
        )

    def build_witness(
        self,
        *,
        contract: FinancialSourceTimeMatchContract,
        financial_body: bytes,
        source_time_body: bytes,
        decision_evidence: FinancialFactDecisionEvidence,
        source_time_reference: FinancialSourceTimeArtifactRef,
    ) -> FinancialSourceTimeWitness | None:
        """Construct one witness from two exact retained response bodies.

        Producers call this method before a witness exists. Verifiers continue
        to call :meth:`match`, which obtains the claimed artifact reference and
        independently rebuilds the same value for exact equality comparison.
        """

        if contract != akshare_notice_date_match_contract():
            return None
        if not isinstance(decision_evidence, FinancialFactDecisionEvidence) or not isinstance(
            source_time_reference, FinancialSourceTimeArtifactRef
        ):
            return None
        financial_reference = decision_evidence.artifact_reference
        financial_evidence = financial_reference.evidence
        if (
            financial_reference.capture_id == source_time_reference.capture_id
            or financial_evidence.request_scope.provider_name != contract.provider_name
            or financial_evidence.request_scope.dataset_key != contract.financial_dataset_key
            or source_time_reference.provider_name != contract.provider_name
            or source_time_reference.dataset_key != contract.source_time_dataset_key
            or source_time_reference.requested_asset_code != decision_evidence.native_asset_code
            or not _body_matches_reference(
                financial_body,
                expected_sha256=financial_reference.body_sha256,
                expected_size=financial_reference.body_size_bytes,
            )
            or not _body_matches_reference(
                source_time_body,
                expected_sha256=source_time_reference.body_sha256,
                expected_size=source_time_reference.body_size_bytes,
            )
        ):
            return None
        financial_rows = _main_financial_data_rows(financial_body)
        source_rows = _main_financial_data_rows(source_time_body)
        if financial_rows is None or source_rows is None:
            return None
        financial_candidates = [
            row
            for row in financial_rows
            if _row_asset(row) == decision_evidence.native_asset_code
            and _row_period_end(row) == decision_evidence.native_period_end
            and _composite_row_id(row) == decision_evidence.native_row_id
        ]
        if len(financial_candidates) != 1:
            return None
        source_matches = [
            row for row in source_rows if _composite_row_id(row) == decision_evidence.native_row_id
        ]
        if len(source_matches) != 1:
            return None
        source_row = source_matches[0]
        announcement_date = _row_announcement_date(source_row)
        if (
            announcement_date is None
            or source_time_reference.requested_announcement_date != announcement_date
        ):
            return None
        source_zone = ZoneInfo(AKSHARE_SOURCE_TIMEZONE)
        announced_at = datetime.combine(announcement_date, time.min, tzinfo=source_zone).astimezone(
            UTC
        )
        available_at = datetime.combine(
            announcement_date + timedelta(days=1), time.min, tzinfo=source_zone
        ).astimezone(UTC)
        projection_sha256 = _row_projection_sha256(
            source_row,
            announced_at=announced_at,
            available_at=available_at,
        )
        if projection_sha256 is None:
            return None
        try:
            return FinancialSourceTimeWitness(
                artifact_reference=source_time_reference,
                native_asset_code=decision_evidence.native_asset_code,
                native_period_end=decision_evidence.native_period_end,
                financial_native_row_id=decision_evidence.native_row_id,
                financial_announced_date=announcement_date,
                source_native_row_id=str(_composite_row_id(source_row)),
                source_timezone=AKSHARE_SOURCE_TIMEZONE,
                announced_at=announced_at,
                available_at=available_at,
                row_projection_sha256=projection_sha256,
                governed_match_contract_id=contract.contract_id,
                governed_match_contract_version=contract.contract_version,
                governed_match_contract_sha256=contract.contract_sha256,
                matched_row_count=1,
                availability_basis=FinancialAvailabilityBasis.PROVIDER_DATE_NEXT_SESSION,
                source_time_precision=FinancialSourceTimePrecision.DATE,
            )
        except (TypeError, ValueError):
            return None


def _body_matches_reference(
    body: bytes,
    *,
    expected_sha256: str,
    expected_size: int,
) -> bool:
    """Return whether exact provider bytes match one retained reference."""

    return (
        type(body) is bytes
        and len(body) == expected_size
        and hashlib.sha256(body).hexdigest() == expected_sha256
    )


def _main_financial_data_rows(body: bytes) -> tuple[Mapping[str, object], ...] | None:
    """Return the data rows of one successful main-financial-data response."""

    try:
        payload = decode_json_bytes(body)
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("success") is not True or payload.get("code") != 0:
        return None
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return None
    data = result.get("data")
    if not isinstance(data, list) or any(not isinstance(row, Mapping) for row in data):
        return None
    count = result.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(data):
        return None
    return tuple(data)


def _strict_provider_date(value: object) -> date | None:
    """Parse one provider calendar date; any intraday or padded text fails."""

    if not isinstance(value, str) or value != value.strip():
        return None
    if len(value) == 10:
        text = value
    elif len(value) == 19 and value.endswith(" 00:00:00"):
        text = value[:10]
    else:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _row_asset(row: Mapping[str, object]) -> str | None:
    """Return the row asset code without normalization or guessing."""

    value = row.get(AKSHARE_ASSET_FIELD)
    return value if isinstance(value, str) and value else None


def _row_period_end(row: Mapping[str, object]) -> date | None:
    """Return the row fiscal period end as a strict calendar date."""

    return _strict_provider_date(row.get(AKSHARE_PERIOD_END_FIELD))


def _row_announcement_date(row: Mapping[str, object]) -> date | None:
    """Return the row announcement date as a strict calendar date."""

    return _strict_provider_date(row.get(AKSHARE_ANNOUNCEMENT_DATE_FIELD))


def _composite_row_id(row: Mapping[str, object]) -> str | None:
    """Return the declared composite row identity, or ``None`` when incomplete."""

    asset = _row_asset(row)
    period_end = _row_period_end(row)
    announcement = _row_announcement_date(row)
    if asset is None or period_end is None or announcement is None:
        return None
    return f"akshare:{asset}:{period_end.isoformat()}:{announcement.isoformat()}"


def _row_projection_sha256(
    row: Mapping[str, object],
    *,
    announced_at: datetime,
    available_at: datetime,
) -> str | None:
    """Hash the canonical projection of one matched source-time row."""

    row_id = _composite_row_id(row)
    raw_values = (
        row.get(AKSHARE_ASSET_FIELD),
        row.get(AKSHARE_PERIOD_END_FIELD),
        row.get(AKSHARE_ANNOUNCEMENT_DATE_FIELD),
    )
    if row_id is None or any(not isinstance(value, str) for value in raw_values):
        return None
    projection = {
        AKSHARE_ASSET_FIELD: raw_values[0],
        AKSHARE_PERIOD_END_FIELD: raw_values[1],
        AKSHARE_ANNOUNCEMENT_DATE_FIELD: raw_values[2],
        AKSHARE_SOURCE_ROW_ID_FIELD: row_id,
        AKSHARE_ANNOUNCED_AT_FIELD: announced_at.isoformat(),
        AKSHARE_AVAILABLE_AT_FIELD: available_at.isoformat(),
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_ROW_PROJECTION_HASH_DOMAIN + encoded).hexdigest()


__all__ = [
    "AKSHARE_ANNOUNCEMENT_DATE_FIELD",
    "AKSHARE_ANNOUNCED_AT_FIELD",
    "AKSHARE_ASSET_FIELD",
    "AKSHARE_AVAILABLE_AT_FIELD",
    "AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT",
    "AKSHARE_NOTICE_DATE_CONTRACT_ID",
    "AKSHARE_NOTICE_DATE_CONTRACT_VERSION",
    "AKSHARE_NOTICE_DATE_PARSER_VERSION",
    "AKSHARE_PERIOD_END_FIELD",
    "AKSHARE_PROVIDER_NAME",
    "AKSHARE_SOURCE_ROW_ID_FIELD",
    "AKSHARE_SOURCE_TIMEZONE",
    "AkshareNoticeDateSourceTimeMatcher",
    "akshare_notice_date_match_contract",
]
