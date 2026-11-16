"""Explicit two-response capture contract for a bounded financial E1 slice.

This candidate describes a shared Main response that can be replayed under
separate numeric and NOTICE-date roles, followed by one Balance response. It
does not create a source-time RawAudit, authorize the new v2 capture mode, or
qualify an unverified Balance query. Integrators must verify the one Main
RawAudit and each role independently against the retained exact body.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseBodyScope,
    FinancialResponseScopeBasis,
)

FINANCIAL_FACT_DATASET_KEY = "equity.financial.fact"
FINANCIAL_E1_CAPTURE_SCHEMA = "financial-e1-two-response-capture.v1"
FINANCIAL_SHARED_SOURCE_TIME_SCHEMA = "financial-source-time-shared-main-response.v2"
FINANCIAL_SHARED_SOURCE_TIME_CONTRACT_SCHEMA = (
    "financial-source-time-shared-main-response-contract.v2"
)
_MAX_TEXT_LENGTH = 256
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

JsonScalar = bool | int | str


class FinancialE1ResponseRole(StrEnum):
    """One independently validated use of a captured response body."""

    MAIN_NATIVE_NUMERIC = "main_native_numeric"
    MAIN_NOTICE_DATE = "main_notice_date_source_time"
    BALANCE_NATIVE_NUMERIC = "balance_native_numeric"


@dataclass(frozen=True, slots=True)
class FinancialE1EndpointRequest:
    """One endpoint request slot with retries and follow-up pages forbidden."""

    provider_name: str
    dataset_key: str
    endpoint: str
    roles: tuple[FinancialE1ResponseRole, ...]
    request_asset_code: str
    request_period_end: date
    request_announcement_date: date | None
    max_attempts: int
    pagination_policy: Literal["one_response"]

    def __post_init__(self) -> None:
        """Require one explicit endpoint, role set, physical attempt, and response."""

        for field_name, value in (
            ("provider_name", self.provider_name),
            ("dataset_key", self.dataset_key),
            ("endpoint", self.endpoint),
            ("request_asset_code", self.request_asset_code),
        ):
            _required_text(value, field_name)
        _calendar_date(self.request_period_end, "request_period_end")
        if self.request_announcement_date is not None:
            _calendar_date(self.request_announcement_date, "request_announcement_date")
        if not isinstance(self.roles, tuple) or not self.roles:
            raise ValueError("endpoint roles must be a non-empty tuple")
        if not all(isinstance(role, FinancialE1ResponseRole) for role in self.roles):
            raise ValueError("endpoint roles must be typed")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("endpoint roles must be unique")
        if type(self.max_attempts) is not int or self.max_attempts != 1:
            raise ValueError("E1 endpoint requests must explicitly allow exactly one attempt")
        if self.pagination_policy != "one_response":
            raise ValueError("E1 endpoint requests must forbid follow-up pagination")
        includes_notice_role = FinancialE1ResponseRole.MAIN_NOTICE_DATE in self.roles
        if includes_notice_role != (self.request_announcement_date is not None):
            raise ValueError("only the Main NOTICE role requires an announcement-date request")


@dataclass(frozen=True, slots=True)
class FinancialSharedResponseSourceTimeContractV2:
    """Versioned source-time interpretation for NOTICE_DATE in the Main body.

    This is a contract value only. Its endpoint, field names, parser version,
    and hash must later resolve through the real catalog at the relevant
    source and knowledge clocks; construction does not prove approval.
    """

    provider_name: str
    dataset_key: str
    endpoint: str
    contract_id: str
    contract_version: str
    parser_version: str
    source_timezone: str
    success_key: str
    success_value: JsonScalar
    code_key: str
    success_code: JsonScalar
    result_key: str
    data_key: str
    count_key: str
    asset_field: str
    period_end_field: str
    announcement_date_field: str
    row_identity_prefix: str
    projection_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require explicit same-dataset response parsing with complete row identity."""

        for field_name, value in (
            ("provider_name", self.provider_name),
            ("dataset_key", self.dataset_key),
            ("endpoint", self.endpoint),
            ("contract_id", self.contract_id),
            ("contract_version", self.contract_version),
            ("parser_version", self.parser_version),
            ("source_timezone", self.source_timezone),
            ("success_key", self.success_key),
            ("code_key", self.code_key),
            ("result_key", self.result_key),
            ("data_key", self.data_key),
            ("count_key", self.count_key),
            ("asset_field", self.asset_field),
            ("period_end_field", self.period_end_field),
            ("announcement_date_field", self.announcement_date_field),
            ("row_identity_prefix", self.row_identity_prefix),
        ):
            _required_text(value, field_name)
        if self.dataset_key != FINANCIAL_FACT_DATASET_KEY:
            raise ValueError("shared source-time v2 must reference the Main financial dataset")
        if type(self.success_value) not in {bool, int, str}:
            raise ValueError("success_value must be an explicit JSON scalar")
        if type(self.success_code) not in {bool, int, str}:
            raise ValueError("success_code must be an explicit JSON scalar")
        try:
            ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("source_timezone is unknown") from exc
        row_identity_fields = (
            self.asset_field,
            self.period_end_field,
            self.announcement_date_field,
        )
        if len(set(row_identity_fields)) != len(row_identity_fields):
            raise ValueError("shared source-time row identity fields must be distinct")
        if not isinstance(self.projection_fields, tuple) or not self.projection_fields:
            raise ValueError("projection_fields must be a non-empty tuple")
        for field_name in self.projection_fields:
            _required_text(field_name, "projection_field")
        if len(set(self.projection_fields)) != len(self.projection_fields):
            raise ValueError("projection_fields must be unique")
        if not set(row_identity_fields).issubset(self.projection_fields):
            raise ValueError("projection_fields must preserve all source row identity fields")

    def to_dict(self) -> dict[str, object]:
        """Return the canonical, explicitly versioned contract content."""

        return {
            "schema": FINANCIAL_SHARED_SOURCE_TIME_CONTRACT_SCHEMA,
            "capture_mode": "same_main_response",
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "endpoint": self.endpoint,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "parser_version": self.parser_version,
            "source_timezone": self.source_timezone,
            "success_key": self.success_key,
            "success_value": self.success_value,
            "code_key": self.code_key,
            "success_code": self.success_code,
            "result_key": self.result_key,
            "data_key": self.data_key,
            "count_key": self.count_key,
            "asset_field": self.asset_field,
            "period_end_field": self.period_end_field,
            "announcement_date_field": self.announcement_date_field,
            "row_identity_prefix": self.row_identity_prefix,
            "projection_fields": list(self.projection_fields),
        }

    @property
    def content_hash(self) -> str:
        """Hash the full v2 body-role contract with an independent domain prefix."""

        encoded = _canonical_json(self.to_dict())
        return hashlib.sha256(
            b"agomtradepro:financial-source-time-shared-main-response:v2\0" + encoded
        ).hexdigest()

    @property
    def identity(self) -> str:
        """Return the explicit v2 contract version bound to its content digest."""

        return (
            f"{FINANCIAL_SHARED_SOURCE_TIME_CONTRACT_SCHEMA}:"
            f"{self.contract_version}:{self.content_hash}"
        )


@dataclass(frozen=True, slots=True)
class FinancialSharedResponseSourceTimeReferenceV2:
    """A source-time role reference to the exact same Main response artifact.

    No second capture UUID, location, body copy, or RawAudit is created. The
    endpoint claim is bound by ``contract`` and must be checked against the
    existing financial RawAudit by an infrastructure verifier.
    """

    response_reference: FinancialResponseArtifactRef
    contract: FinancialSharedResponseSourceTimeContractV2
    requested_asset_code: str
    requested_period_end: date
    requested_announcement_date: date

    def __post_init__(self) -> None:
        """Bind the source-time role to one body-verified Main artifact identity."""

        if not isinstance(self.response_reference, FinancialResponseArtifactRef):
            raise ValueError("response_reference must be a FinancialResponseArtifactRef")
        if not isinstance(self.contract, FinancialSharedResponseSourceTimeContractV2):
            raise ValueError("contract must be FinancialSharedResponseSourceTimeContractV2")
        _required_text(self.requested_asset_code, "requested_asset_code")
        _calendar_date(self.requested_period_end, "requested_period_end")
        _calendar_date(self.requested_announcement_date, "requested_announcement_date")
        evidence = self.response_reference.evidence
        scope = evidence.request_scope
        response = evidence.response_scope
        if scope.provider_name != self.contract.provider_name:
            raise ValueError("shared source-time provider does not match Main request scope")
        if scope.dataset_key != self.contract.dataset_key:
            raise ValueError("shared source-time dataset does not match Main request scope")
        if scope.asset_code != self.requested_asset_code:
            raise ValueError("shared source-time asset does not match Main request scope")
        if evidence.response_scope_basis is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED:
            raise ValueError("shared source-time reference requires provider-body-verified scope")
        if evidence.body_scope is not FinancialResponseBodyScope.BATCH:
            raise ValueError("shared source-time reference requires the complete response body")
        if evidence.body_size_bytes <= 0:
            raise ValueError("shared source-time response body must be non-empty")
        if self.requested_asset_code not in response.asset_codes:
            raise ValueError("shared source-time asset is outside verified response scope")
        if self.requested_period_end not in response.period_ends:
            raise ValueError("shared source-time period is outside verified response scope")

    @property
    def capture_id(self) -> UUID:
        """Return the one Main capture UUID; this type owns no separate identity."""

        return self.response_reference.capture_id

    @property
    def body_sha256(self) -> str:
        """Return the digest from the one retained Main body reference."""

        return self.response_reference.body_sha256

    @property
    def body_size_bytes(self) -> int:
        """Return the byte size from the one retained Main body reference."""

        return self.response_reference.body_size_bytes

    def to_dict(self) -> dict[str, object]:
        """Return a role projection while retaining the same underlying capture ID."""

        return {
            "schema": FINANCIAL_SHARED_SOURCE_TIME_SCHEMA,
            "capture_mode": "same_main_response",
            "response_reference": self.response_reference.to_dict(),
            "capture_id": str(self.capture_id),
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "requested_asset_code": self.requested_asset_code,
            "requested_period_end": self.requested_period_end.isoformat(),
            "requested_announcement_date": self.requested_announcement_date.isoformat(),
            "contract_identity": self.contract.identity,
            "contract_hash": self.contract.content_hash,
        }


@dataclass(frozen=True, slots=True)
class FinancialSharedResponseNoticeBindingV2:
    """Date-precision NOTICE row binding from one exact Main response body.

    This object binds source date evidence only. It intentionally does not
    derive ``announced_at`` or ``available_at``; a separate approved temporal
    witness must establish availability.
    """

    artifact_reference: FinancialSharedResponseSourceTimeReferenceV2
    native_asset_code: str
    native_period_end: date
    native_row_id: str
    notice_date: date
    raw_notice_date_text: str
    row_index: int
    row_projection_fields: tuple[tuple[str, str], ...]
    row_projection_sha256: str

    def __post_init__(self) -> None:
        """Require exact request dimensions, body identity, and source-date shape."""

        if not isinstance(self.artifact_reference, FinancialSharedResponseSourceTimeReferenceV2):
            raise ValueError("artifact_reference must be the shared-response v2 reference")
        _required_text(self.native_asset_code, "native_asset_code")
        _required_text(self.native_row_id, "native_row_id")
        _calendar_date(self.native_period_end, "native_period_end")
        _calendar_date(self.notice_date, "notice_date")
        if self.native_asset_code != self.artifact_reference.requested_asset_code:
            raise ValueError("NOTICE row asset does not match request")
        if self.native_period_end != self.artifact_reference.requested_period_end:
            raise ValueError("NOTICE row period does not match request")
        if self.notice_date != self.artifact_reference.requested_announcement_date:
            raise ValueError("NOTICE date does not match request")
        if _strict_provider_date(self.raw_notice_date_text) != self.notice_date:
            raise ValueError("raw NOTICE spelling does not encode the declared date")
        expected_row_id = _row_id(
            self.artifact_reference.contract,
            self.native_asset_code,
            self.native_period_end,
            self.notice_date,
        )
        if self.native_row_id != expected_row_id:
            raise ValueError("NOTICE row id does not match its native dimensions")
        if type(self.row_index) is not int or self.row_index < 0:
            raise ValueError("row_index must be a non-negative integer")
        if not isinstance(self.row_projection_fields, tuple):
            raise ValueError("row_projection_fields must be an immutable tuple")
        if not all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
            for item in self.row_projection_fields
        ):
            raise ValueError("row_projection_fields must contain text pairs")
        contract = self.artifact_reference.contract
        field_names = tuple(item[0] for item in self.row_projection_fields)
        if field_names != contract.projection_fields:
            raise ValueError("row_projection_fields do not match the contract projection")
        projection_values = dict(self.row_projection_fields)
        if (
            projection_values.get(contract.asset_field) != self.native_asset_code
            or _strict_provider_date(projection_values.get(contract.period_end_field))
            != self.native_period_end
            or projection_values.get(contract.announcement_date_field) != self.raw_notice_date_text
        ):
            raise ValueError("row projection fields do not match the declared native row")
        expected_projection_hash = _row_projection_sha256(
            contract_identity=contract.identity,
            body_sha256=self.body_sha256,
            row_index=self.row_index,
            fields=self.row_projection_fields,
        )
        if not isinstance(self.row_projection_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.row_projection_sha256
        ):
            raise ValueError("row_projection_sha256 must be lowercase SHA-256")
        if self.row_projection_sha256 != expected_projection_hash:
            raise ValueError("row_projection_sha256 does not match the exact row projection")

    @property
    def capture_id(self) -> UUID:
        """Return the single Main response capture ID used by both roles."""

        return self.artifact_reference.capture_id

    @property
    def body_sha256(self) -> str:
        """Return the exact Main response digest used by the independent role replay."""

        return self.artifact_reference.body_sha256

    def to_dict(self) -> dict[str, object]:
        """Serialize source-date evidence without claiming a timestamp or availability."""

        return {
            "schema": FINANCIAL_SHARED_SOURCE_TIME_SCHEMA,
            "capture_id": str(self.capture_id),
            "body_sha256": self.body_sha256,
            "contract_identity": self.artifact_reference.contract.identity,
            "native_asset_code": self.native_asset_code,
            "native_period_end": self.native_period_end.isoformat(),
            "native_row_id": self.native_row_id,
            "notice_date": self.notice_date.isoformat(),
            "raw_notice_date_text": self.raw_notice_date_text,
            "row_index": self.row_index,
            "row_projection_fields": [list(item) for item in self.row_projection_fields],
            "row_projection_sha256": self.row_projection_sha256,
            "source_time_precision": "date",
        }


@dataclass(frozen=True, slots=True)
class FinancialE1CaptureContractV1:
    """Describe exactly two one-attempt requests and three response roles.

    The Main endpoint has two roles on the same body: native financial values
    and NOTICE-date source-time evidence. The Balance endpoint has one role
    for its native values. This plan does not permit retry or pagination and
    does not claim that either endpoint's business qualification is approved.
    """

    provider_name: str
    asset_code: str
    period_end: date
    announcement_date: date
    main_request: FinancialE1EndpointRequest
    balance_request: FinancialE1EndpointRequest
    source_time_contract: FinancialSharedResponseSourceTimeContractV2
    maximum_physical_attempts: int

    def __post_init__(self) -> None:
        """Require Main+NOTICE role sharing and one exact Balance request slot."""

        _required_text(self.provider_name, "provider_name")
        _required_text(self.asset_code, "asset_code")
        _calendar_date(self.period_end, "period_end")
        _calendar_date(self.announcement_date, "announcement_date")
        if not isinstance(self.main_request, FinancialE1EndpointRequest):
            raise ValueError("main_request must be typed")
        if not isinstance(self.balance_request, FinancialE1EndpointRequest):
            raise ValueError("balance_request must be typed")
        if not isinstance(self.source_time_contract, FinancialSharedResponseSourceTimeContractV2):
            raise ValueError("source_time_contract must be the explicit shared-response v2 type")
        if self.main_request.provider_name != self.provider_name:
            raise ValueError("Main endpoint provider does not match capture contract")
        if self.balance_request.provider_name != self.provider_name:
            raise ValueError("Balance endpoint provider does not match capture contract")
        if (
            self.main_request.request_asset_code != self.asset_code
            or self.main_request.request_period_end != self.period_end
            or self.main_request.request_announcement_date != self.announcement_date
        ):
            raise ValueError("Main request context does not match the capture target")
        if (
            self.balance_request.request_asset_code != self.asset_code
            or self.balance_request.request_period_end != self.period_end
            or self.balance_request.request_announcement_date is not None
        ):
            raise ValueError("Balance request context does not match the capture target")
        if self.main_request.dataset_key != FINANCIAL_FACT_DATASET_KEY:
            raise ValueError("Main request must use the financial fact dataset")
        if self.source_time_contract.provider_name != self.provider_name:
            raise ValueError("source-time contract provider does not match Main request")
        if self.source_time_contract.dataset_key != self.main_request.dataset_key:
            raise ValueError("source-time v2 contract must reuse the Main request dataset")
        if self.source_time_contract.endpoint != self.main_request.endpoint:
            raise ValueError("source-time v2 contract must bind the Main endpoint")
        if set(self.main_request.roles) != {
            FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            FinancialE1ResponseRole.MAIN_NOTICE_DATE,
        }:
            raise ValueError("Main response must serve exactly numeric and NOTICE-date roles")
        if self.balance_request.roles != (FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,):
            raise ValueError("Balance response must serve only the Balance native-value role")
        if self.main_request.endpoint == self.balance_request.endpoint:
            raise ValueError("Balance must be one distinct endpoint request")
        if self.maximum_physical_attempts != 2 or type(self.maximum_physical_attempts) is not int:
            raise ValueError("E1 must reserve exactly two total physical attempts")

    @property
    def request_count(self) -> int:
        """Return the number of endpoint request slots in this E1 plan."""

        return 2

    def to_dict(self) -> dict[str, object]:
        """Serialize the bounded request plan without any approval claim."""

        return {
            "schema": FINANCIAL_E1_CAPTURE_SCHEMA,
            "provider_name": self.provider_name,
            "asset_code": self.asset_code,
            "period_end": self.period_end.isoformat(),
            "announcement_date": self.announcement_date.isoformat(),
            "request_count": self.request_count,
            "maximum_physical_attempts": self.maximum_physical_attempts,
            "source_time_contract_identity": self.source_time_contract.identity,
            "main_request": _request_to_dict(self.main_request),
            "balance_request": _request_to_dict(self.balance_request),
            "evidence_only": True,
            "production_ready": False,
            "must_not_use_for_decision": True,
        }


@dataclass(frozen=True, slots=True)
class FinancialE1RawCapturePairV1:
    """Retain two real response identities while aliasing Main's NOTICE role.

    The pair contains only two immutable response references: Main and Balance.
    Its NOTICE binding reuses Main's exact response reference; no extra capture
    or RawAudit is represented. This value does not assert that either RawAudit
    exists exactly once, and it does not promote a caller-declared Balance scope.
    """

    contract: FinancialE1CaptureContractV1
    main_reference: FinancialResponseArtifactRef
    balance_reference: FinancialResponseArtifactRef
    source_time_reference: FinancialSharedResponseSourceTimeReferenceV2
    source_time_binding: FinancialSharedResponseNoticeBindingV2
    main_numeric_observations: tuple[NativeFinancialMetricObservation, ...]

    def __post_init__(self) -> None:
        """Bind Main numeric/time evidence and the second Balance body to one target."""

        if not isinstance(self.contract, FinancialE1CaptureContractV1):
            raise ValueError("contract must be the typed E1 capture contract")
        if not isinstance(self.main_reference, FinancialResponseArtifactRef):
            raise ValueError("main_reference must be a FinancialResponseArtifactRef")
        if not isinstance(self.balance_reference, FinancialResponseArtifactRef):
            raise ValueError("balance_reference must be a FinancialResponseArtifactRef")
        if not isinstance(self.source_time_reference, FinancialSharedResponseSourceTimeReferenceV2):
            raise ValueError("source_time_reference must be the shared-response v2 reference")
        if not isinstance(self.source_time_binding, FinancialSharedResponseNoticeBindingV2):
            raise ValueError("source_time_binding must be the independently parsed NOTICE role")
        if (
            not isinstance(self.main_numeric_observations, tuple)
            or not self.main_numeric_observations
        ):
            raise ValueError("main_numeric_observations must include explicit native evidence")
        if not all(
            type(item) is NativeFinancialMetricObservation
            for item in self.main_numeric_observations
        ):
            raise ValueError("main_numeric_observations must be typed native evidence")

        main_scope = self.main_reference.evidence.request_scope
        main_response = self.main_reference.evidence.response_scope
        balance_scope = self.balance_reference.evidence.request_scope
        balance_evidence = self.balance_reference.evidence
        target = self.contract
        if (
            self.main_reference.capture_id == self.balance_reference.capture_id
            or self.source_time_reference.response_reference != self.main_reference
            or self.source_time_binding.artifact_reference != self.source_time_reference
            or self.source_time_reference.contract.identity != target.source_time_contract.identity
        ):
            raise ValueError(
                "E1 must have two capture IDs and the planned NOTICE contract must reuse Main"
            )
        if (
            main_scope.provider_name != target.provider_name
            or main_scope.dataset_key != target.main_request.dataset_key
            or main_scope.asset_code != target.asset_code
            or self.main_reference.evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or target.asset_code not in main_response.asset_codes
            or target.period_end not in main_response.period_ends
        ):
            raise ValueError("Main response scope does not match the E1 target")
        if (
            balance_scope.provider_name != target.provider_name
            or balance_scope.dataset_key != target.balance_request.dataset_key
            or balance_scope.asset_code != target.asset_code
        ):
            raise ValueError("Balance request scope does not match the E1 target")
        if (
            balance_evidence.response_scope_basis
            is FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
        ):
            balance_response = balance_evidence.response_scope
            if (
                target.asset_code not in balance_response.asset_codes
                or target.period_end not in balance_response.period_ends
            ):
                raise ValueError("body-verified Balance response misses the E1 asset/period")
        expected_row_id = self.source_time_binding.native_row_id
        metric_codes: set[str] = set()
        for observation in self.main_numeric_observations:
            if (
                observation.body_sha256 != self.main_reference.body_sha256
                or observation.native_row_id != expected_row_id
                or observation.contract.provider != target.provider_name
                or observation.contract.dataset_key != target.main_request.dataset_key
                or observation.contract.metric_code in metric_codes
            ):
                raise ValueError("Main numeric evidence does not match its shared capture role")
            metric_codes.add(observation.contract.metric_code)

    @property
    def capture_ids(self) -> tuple[UUID, UUID]:
        """Return exactly the two provider response identities in the pair."""

        return (self.main_reference.capture_id, self.balance_reference.capture_id)

    def to_dict(self) -> dict[str, object]:
        """Serialize both retained bodies and the shared Main source-time role."""

        return {
            "schema": FINANCIAL_E1_CAPTURE_SCHEMA,
            "main_reference": self.main_reference.to_dict(),
            "balance_reference": self.balance_reference.to_dict(),
            "capture_ids": [str(capture_id) for capture_id in self.capture_ids],
            "shared_source_time_reference": self.source_time_reference.to_dict(),
            "source_time_binding": self.source_time_binding.to_dict(),
            "main_numeric_metric_codes": [
                item.contract.metric_code for item in self.main_numeric_observations
            ],
            "evidence_only": True,
            "production_ready": False,
            "must_not_use_for_decision": True,
        }


def match_shared_main_notice_date_v2(
    raw_body: bytes,
    *,
    artifact_reference: FinancialSharedResponseSourceTimeReferenceV2,
) -> FinancialSharedResponseNoticeBindingV2 | None:
    """Independently parse NOTICE_DATE from the same Main response used for numerics.

    Return ``None`` for malformed bodies, out-of-scope rows, ambiguous matches,
    or byte/reference mismatches. This parser does not create an audit, assert
    an endpoint, or establish an availability timestamp.
    """

    if type(raw_body) is not bytes or not raw_body:
        return None
    if not isinstance(artifact_reference, FinancialSharedResponseSourceTimeReferenceV2):
        return None
    response = artifact_reference.response_reference
    if (
        len(raw_body) != response.body_size_bytes
        or hashlib.sha256(raw_body).hexdigest() != response.body_sha256
    ):
        return None
    rows = _decode_rows(raw_body, artifact_reference.contract)
    if rows is None or len(rows) != response.evidence.response_scope.row_count:
        return None
    selected = _select_target_row(rows, artifact_reference)
    if selected is None:
        return None
    row_index, row, notice_date, raw_notice_text = selected
    contract = artifact_reference.contract
    projection: list[tuple[str, str]] = []
    for field_name in contract.projection_fields:
        value = row.get(field_name)
        if not isinstance(value, str):
            return None
        projection.append((field_name, value))
    projection_hash = _row_projection_sha256(
        contract_identity=contract.identity,
        body_sha256=response.body_sha256,
        row_index=row_index,
        fields=tuple(projection),
    )
    try:
        return FinancialSharedResponseNoticeBindingV2(
            artifact_reference=artifact_reference,
            native_asset_code=artifact_reference.requested_asset_code,
            native_period_end=artifact_reference.requested_period_end,
            native_row_id=_row_id(
                contract,
                artifact_reference.requested_asset_code,
                artifact_reference.requested_period_end,
                notice_date,
            ),
            notice_date=notice_date,
            raw_notice_date_text=raw_notice_text,
            row_index=row_index,
            row_projection_fields=tuple(projection),
            row_projection_sha256=projection_hash,
        )
    except (TypeError, ValueError):
        return None


def build_shared_main_numeric_observation_v2(
    raw_body: bytes,
    *,
    artifact_reference: FinancialSharedResponseSourceTimeReferenceV2,
    metric_contract: FinancialMetricSourceContract,
) -> NativeFinancialMetricObservation | None:
    """Replay one explicit native numeric contract from the shared Main body.

    This re-decodes and re-matches the retained bytes independently of the
    NOTICE-date parser. No float conversion, field alias, unit inference, or
    derived formula is applied.
    """

    if type(raw_body) is not bytes or not raw_body:
        return None
    if not isinstance(artifact_reference, FinancialSharedResponseSourceTimeReferenceV2):
        return None
    if type(metric_contract) is not FinancialMetricSourceContract:
        return None
    response = artifact_reference.response_reference
    request_scope = response.evidence.request_scope
    if (
        metric_contract.provider != request_scope.provider_name
        or metric_contract.dataset_key != request_scope.dataset_key
        or len(raw_body) != response.body_size_bytes
        or hashlib.sha256(raw_body).hexdigest() != response.body_sha256
    ):
        return None
    rows = _decode_rows(raw_body, artifact_reference.contract)
    if rows is None or len(rows) != response.evidence.response_scope.row_count:
        return None
    selected = _select_target_row(rows, artifact_reference)
    if selected is None:
        return None
    _row_index, row, notice_date, _raw_notice_text = selected
    raw_value = row.get(metric_contract.source_field)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (Decimal, int)):
        return None
    try:
        return NativeFinancialMetricObservation.from_raw_value(
            contract=metric_contract,
            raw_value=raw_value,
            source_field=metric_contract.source_field,
            body_sha256=response.body_sha256,
            native_row_id=_row_id(
                artifact_reference.contract,
                artifact_reference.requested_asset_code,
                artifact_reference.requested_period_end,
                notice_date,
            ),
        )
    except (TypeError, ValueError):
        return None


def _decode_rows(
    raw_body: bytes,
    contract: FinancialSharedResponseSourceTimeContractV2,
) -> tuple[Mapping[str, object], ...] | None:
    """Decode one strict JSON response without float or duplicate-key coercion."""

    try:
        payload: object = json.loads(
            raw_body.decode("utf-8"),
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    root = _mapping(payload)
    if root is None or not _same_scalar(root.get(contract.success_key), contract.success_value):
        return None
    if not _same_scalar(root.get(contract.code_key), contract.success_code):
        return None
    result = _mapping(root.get(contract.result_key))
    if result is None:
        return None
    count = result.get(contract.count_key)
    rows_value = result.get(contract.data_key)
    if (
        type(count) is not int
        or not isinstance(rows_value, list)
        or count != len(rows_value)
        or count <= 0
    ):
        return None
    rows = tuple(_mapping(row) for row in rows_value)
    if any(row is None for row in rows):
        return None
    return cast(tuple[Mapping[str, object], ...], rows)


def _select_target_row(
    rows: tuple[Mapping[str, object], ...],
    reference: FinancialSharedResponseSourceTimeReferenceV2,
) -> tuple[int, Mapping[str, object], date, str] | None:
    """Require in-scope rows and exactly one asset/period/NOTICE row match."""

    contract = reference.contract
    matches: list[tuple[int, Mapping[str, object], date, str]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        asset = row.get(contract.asset_field)
        period_text = row.get(contract.period_end_field)
        notice_text = row.get(contract.announcement_date_field)
        if not isinstance(asset, str) or asset != reference.requested_asset_code:
            return None
        period = _strict_provider_date(period_text)
        notice = _strict_provider_date(notice_text)
        if period is None or notice is None or notice != reference.requested_announcement_date:
            return None
        native_id = _row_id(contract, asset, period, notice)
        if native_id in seen_ids:
            return None
        seen_ids.add(native_id)
        if period == reference.requested_period_end:
            if not isinstance(notice_text, str):
                return None
            matches.append((index, row, notice, notice_text))
    return matches[0] if len(matches) == 1 else None


def _row_id(
    contract: FinancialSharedResponseSourceTimeContractV2,
    asset_code: str,
    period_end: date,
    notice_date: date,
) -> str:
    """Build the explicit v2 composite identity from the three matched dimensions."""

    return (
        f"{contract.row_identity_prefix}:{asset_code}:"
        f"{period_end.isoformat()}:{notice_date.isoformat()}"
    )


def _row_projection_sha256(
    *,
    contract_identity: str,
    body_sha256: str,
    row_index: int,
    fields: tuple[tuple[str, str], ...],
) -> str:
    """Hash the raw identity projection and exact body without invented times."""

    encoded = _canonical_json(
        {
            "schema": FINANCIAL_SHARED_SOURCE_TIME_SCHEMA,
            "contract_identity": contract_identity,
            "body_sha256": body_sha256,
            "row_index": row_index,
            "fields": [[key, value] for key, value in fields],
        }
    )
    return hashlib.sha256(encoded).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys rather than accepting last-write wins."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Reject JavaScript NaN and infinity tokens in source JSON."""

    raise ValueError(f"non-standard JSON constant: {value}")


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one decoded object without coercing its values."""

    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _strict_provider_date(value: object) -> date | None:
    """Accept a calendar date or the provider's exact zero-time date spelling."""

    if not isinstance(value, str) or value != value.strip():
        return None
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        text = value
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} 00:00:00", value):
        text = value[:10]
    else:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _same_scalar(actual: object, expected: JsonScalar) -> bool:
    """Compare JSON success fields without bool/integer equality coercion."""

    return type(actual) is type(expected) and actual == expected


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    """Encode one canonical JSON object used only for content identities."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _request_to_dict(request: FinancialE1EndpointRequest) -> dict[str, object]:
    """Return the bounded request slot without any secret or approval fields."""

    return {
        "provider_name": request.provider_name,
        "dataset_key": request.dataset_key,
        "endpoint": request.endpoint,
        "roles": [role.value for role in request.roles],
        "request_asset_code": request.request_asset_code,
        "request_period_end": request.request_period_end.isoformat(),
        "request_announcement_date": (
            request.request_announcement_date.isoformat()
            if request.request_announcement_date is not None
            else None
        ),
        "max_attempts": request.max_attempts,
        "pagination_policy": request.pagination_policy,
    }


def _required_text(value: object, field_name: str) -> str:
    """Require bounded unpadded source and contract text without normalization."""

    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT_LENGTH
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be bounded, unpadded text")
    return value


def _calendar_date(value: object, field_name: str) -> date:
    """Reject datetime values at date-precision source boundaries."""

    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{field_name} must be a date, not a datetime")
    return value


__all__ = [
    "FINANCIAL_E1_CAPTURE_SCHEMA",
    "FINANCIAL_FACT_DATASET_KEY",
    "FINANCIAL_SHARED_SOURCE_TIME_CONTRACT_SCHEMA",
    "FINANCIAL_SHARED_SOURCE_TIME_SCHEMA",
    "FinancialE1CaptureContractV1",
    "FinancialE1EndpointRequest",
    "FinancialE1RawCapturePairV1",
    "FinancialE1ResponseRole",
    "FinancialSharedResponseNoticeBindingV2",
    "FinancialSharedResponseSourceTimeContractV2",
    "FinancialSharedResponseSourceTimeReferenceV2",
    "build_shared_main_numeric_observation_v2",
    "match_shared_main_notice_date_v2",
]
