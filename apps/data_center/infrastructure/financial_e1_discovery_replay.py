"""Strict endpoint scope and native-row replay for the isolated E1 runner.

Main NOTICE is discovered from one Main response and verified again by the
existing shared-response contract parser. Balance rows are parsed only by the
strict one-row Balance boundary and retain that endpoint's own NOTICE and full
raw context. These adapters do not make a candidate qualification production
eligible; the database resolver and v3 writer must independently recheck it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Literal, cast

from apps.data_center.application.financial_e1_capture_use_case import (
    FinancialE1NativeRowIdentity,
    FinancialE1RetainedResponse,
)
from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1EndpointReplay,
)
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
    FinancialSharedResponseNoticeBindingV2,
    FinancialSharedResponseSourceTimeContractV2,
    FinancialSharedResponseSourceTimeReferenceV2,
    build_shared_main_numeric_observation_v2,
    match_shared_main_notice_date_v2,
)
from apps.data_center.domain.financial_numeric_evidence import NativeFinancialMetricObservation
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseEvidence,
    FinancialResponseScope,
    with_provider_verified_response_scope,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.infrastructure._provider_adapter_base import _period_type_from_period_end
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    BalanceValueBinding,
    build_balance_candidate_query,
    parse_balance_candidate_body,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_BALANCE_REPORT_NAME,
    _balance_native_row_id,
    _validate_balance_parser_contract,
)
from apps.data_center.infrastructure.financial_response_capture import decode_json_bytes
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_ANNOUNCEMENT_DATE_FIELD,
    AKSHARE_ASSET_FIELD,
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_NOTICE_DATE_CONTRACT_ID,
    AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
    AKSHARE_NOTICE_DATE_PARSER_VERSION,
    AKSHARE_PERIOD_END_FIELD,
    AKSHARE_PROVIDER_NAME,
    AKSHARE_SOURCE_TIMEZONE,
)

_CONFIG_SUBTREE = "financial_e1_capture_v2"
_CONFIG_SCHEMA = "financial-e1-provider-capture-config.v2"
_CONFIG_FIELDS = frozenset(
    {
        "schema",
        "balance_contract_id",
        "evidence_state",
        "endpoint_url",
        "report_name",
        "base_filter_terms",
        "security_filter_key",
        "report_date_filter_key",
        "result_key",
        "success_key",
        "success_value",
        "code_key",
        "success_code",
        "count_key",
        "pages_key",
        "data_key",
        "row_security_code_key",
        "row_report_date_key",
        "row_notice_date_key",
    }
)
_MAIN_SUCCESS_VALUE: bool = True
_MAIN_SUCCESS_CODE: int = 0
_MAIN_REPORT_TYPE = "RPT_F10_FINANCE_MAINFINADATA"
_MAIN_FIELDS = "SECUCODE,REPORT_DATE,NOTICE_DATE"
_MAIN_FILTER_REPORT_FIELD = "REPORT_DATE"
_MAIN_FILTER_ASSET_FIELD = "SECUCODE"
_MAIN_ROW_LIMIT = 200
_STRICT_DATE_LENGTHS = {10, 19}


class FinancialE1ReplayError(ValueError):
    """Stable failure for unsupported endpoint configuration or raw-row replay."""


@dataclass(frozen=True, slots=True)
class FinancialE1BalanceCaptureConfigV2:
    """Explicit provider-configured Balance parser shape for this one endpoint.

    No metric, unit, scale, currency, classification, or row-context business
    rule is stored here. The three native value bindings are composed only
    from the selected persisted numeric qualifications.
    """

    base_filter_terms: tuple[str, ...]
    contract_id: str
    evidence_state: str
    endpoint_url: str
    report_name: str
    security_filter_key: str
    report_date_filter_key: str
    result_key: str
    success_key: str
    success_value: bool | int | str
    code_key: str
    success_code: bool | int | str
    count_key: str
    pages_key: str
    data_key: str
    row_security_code_key: str
    row_report_date_key: str
    row_notice_date_key: str

    def __post_init__(self) -> None:
        """Require explicit exact vendor schema fields and no substituted endpoint."""

        if type(self.base_filter_terms) is not tuple or not self.base_filter_terms:
            raise ValueError("Balance base_filter_terms must be an explicit non-empty tuple")
        if any(
            type(term) is not str or not term or term != term.strip()
            for term in self.base_filter_terms
        ):
            raise ValueError("Balance base_filter_terms must contain exact non-empty text")
        for field_name in (
            "contract_id",
            "evidence_state",
            "endpoint_url",
            "report_name",
            "security_filter_key",
            "report_date_filter_key",
            "result_key",
            "success_key",
            "code_key",
            "count_key",
            "pages_key",
            "data_key",
            "row_security_code_key",
            "row_report_date_key",
            "row_notice_date_key",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"Balance {field_name} must be exact non-empty text")
        if (
            self.contract_id != "akshare.stock_zcfz_em.raw.v1"
            or self.evidence_state != "static_candidate_unverified"
            or self.endpoint_url != AKSHARE_BALANCE_API_URL
            or self.report_name != AKSHARE_BALANCE_REPORT_NAME
            or self.success_value is not True
            or type(self.success_code) is not int
            or self.success_code != 0
        ):
            raise ValueError("Balance config differs from the one supported vendor response schema")
        if len(self.base_filter_terms) > 16 or any(
            len(term) > 256 for term in self.base_filter_terms
        ):
            raise ValueError("Balance base_filter_terms exceed bounded parser limits")

    @classmethod
    def from_provider_extra_config(cls, extra_config: object) -> FinancialE1BalanceCaptureConfigV2:
        """Decode only the strict v2 Balance subtree from persisted ProviderConfig JSON."""

        if not isinstance(extra_config, Mapping) or any(
            type(key) is not str for key in extra_config
        ):
            raise ValueError("Provider extra_config must be a string-keyed object")
        raw = extra_config.get(_CONFIG_SUBTREE)
        if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
            raise ValueError("Provider financial E1 v2 config is missing or malformed")
        if frozenset(raw) != _CONFIG_FIELDS or raw.get("schema") != _CONFIG_SCHEMA:
            raise ValueError("Provider financial E1 v2 config has missing or unknown fields")
        raw_terms = raw.get("base_filter_terms")
        if (
            type(raw_terms) is not list
            or not raw_terms
            or any(type(term) is not str for term in raw_terms)
        ):
            raise ValueError("Provider Balance filter terms must be an explicit JSON array")
        success_value = raw.get("success_value")
        success_code = raw.get("success_code")
        if type(success_value) not in {bool, int, str} or type(success_code) not in {
            bool,
            int,
            str,
        }:
            raise ValueError("Provider Balance response markers must be explicit JSON scalars")
        return cls(
            base_filter_terms=tuple(cast(list[str], raw_terms)),
            contract_id=_text(raw, "balance_contract_id"),
            evidence_state=_text(raw, "evidence_state"),
            endpoint_url=_text(raw, "endpoint_url"),
            report_name=_text(raw, "report_name"),
            security_filter_key=_text(raw, "security_filter_key"),
            report_date_filter_key=_text(raw, "report_date_filter_key"),
            result_key=_text(raw, "result_key"),
            success_key=_text(raw, "success_key"),
            success_value=cast(bool | int | str, success_value),
            code_key=_text(raw, "code_key"),
            success_code=cast(bool | int | str, success_code),
            count_key=_text(raw, "count_key"),
            pages_key=_text(raw, "pages_key"),
            data_key=_text(raw, "data_key"),
            row_security_code_key=_text(raw, "row_security_code_key"),
            row_report_date_key=_text(raw, "row_report_date_key"),
            row_notice_date_key=_text(raw, "row_notice_date_key"),
        )

    def build_parser_contract(
        self,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
    ) -> BalanceCandidateContract:
        """Bind the exact selected Balance metric contracts to this parser schema."""

        selected = tuple(
            qualification
            for qualification in qualifications
            if qualification.endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        )
        if len(selected) != 3:
            raise ValueError(
                "Balance parser needs exactly three explicitly selected qualifications"
            )
        if any(
            qualification.contract.origin != "native"
            or qualification.contract.provider != AKSHARE_PROVIDER_NAME
            or qualification.contract.dataset_key != FINANCIAL_FACT_DATASET_KEY
            for qualification in selected
        ):
            raise ValueError("Balance parser qualifications do not share the exact native source")
        bindings = tuple(
            BalanceValueBinding(
                metric_code=qualification.contract.metric_code,
                raw_key=qualification.contract.source_field,
                unit_code=qualification.contract.source_unit,
            )
            for qualification in sorted(
                selected,
                key=lambda item: item.contract.source_field,
            )
        )
        contract = BalanceCandidateContract(
            contract_id=self.contract_id,
            evidence_state=cast(Literal["static_candidate_unverified"], self.evidence_state),
            endpoint_url=self.endpoint_url,
            report_name=self.report_name,
            base_filter_terms=self.base_filter_terms,
            security_filter_key=self.security_filter_key,
            report_date_filter_key=self.report_date_filter_key,
            result_key=self.result_key,
            success_key=self.success_key,
            success_value=self.success_value,
            code_key=self.code_key,
            success_code=self.success_code,
            count_key=self.count_key,
            pages_key=self.pages_key,
            data_key=self.data_key,
            row_security_code_key=self.row_security_code_key,
            row_report_date_key=self.row_report_date_key,
            row_notice_date_key=self.row_notice_date_key,
            value_bindings=cast(
                tuple[BalanceValueBinding, BalanceValueBinding, BalanceValueBinding],
                bindings,
            ),
        )
        _validate_balance_parser_contract(contract)
        for qualification in selected:
            matches = tuple(
                binding
                for binding in contract.value_bindings
                if binding.metric_code == qualification.contract.metric_code
            )
            if (
                len(matches) != 1
                or matches[0].raw_key != qualification.contract.source_field
                or matches[0].unit_code != qualification.contract.source_unit
            ):
                raise ValueError("Balance parser value binding differs from exact catalog contract")
        return contract


def build_main_shared_response_contract() -> FinancialSharedResponseSourceTimeContractV2:
    """Return the existing exact Main NOTICE parser contract for body discovery."""

    return FinancialSharedResponseSourceTimeContractV2(
        provider_name=AKSHARE_PROVIDER_NAME,
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        contract_id=AKSHARE_NOTICE_DATE_CONTRACT_ID,
        contract_version=AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
        parser_version=AKSHARE_NOTICE_DATE_PARSER_VERSION,
        source_timezone=AKSHARE_SOURCE_TIMEZONE,
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        result_key="result",
        data_key="data",
        count_key="count",
        asset_field=AKSHARE_ASSET_FIELD,
        period_end_field=AKSHARE_PERIOD_END_FIELD,
        announcement_date_field=AKSHARE_ANNOUNCEMENT_DATE_FIELD,
        row_identity_prefix=AKSHARE_PROVIDER_NAME,
        projection_fields=(
            AKSHARE_ASSET_FIELD,
            AKSHARE_PERIOD_END_FIELD,
            AKSHARE_ANNOUNCEMENT_DATE_FIELD,
        ),
    )


class FinancialE1DiscoveryResponseScopeVerifier:
    """Verify the exact one-row Main or Balance response before body retention."""

    def __init__(
        self,
        *,
        main_notice_contract: FinancialSharedResponseSourceTimeContractV2,
        balance_parser_contract: BalanceCandidateContract,
    ) -> None:
        """Bind both exact endpoint parsers; no fallback route is installed."""

        if type(main_notice_contract) is not FinancialSharedResponseSourceTimeContractV2:
            raise TypeError("an exact Main NOTICE contract is required")
        _validate_balance_parser_contract(balance_parser_contract)
        self._main_contract = main_notice_contract
        self._balance_contract = balance_parser_contract

    def verify(
        self,
        request: FinancialE1EndpointRequest,
        *,
        raw_body: bytes,
        payload: object,
        evidence: FinancialResponseEvidence,
    ) -> FinancialResponseEvidence:
        """Return provider-body-verified scope only for one exact requested row."""

        del payload
        if (
            type(request) is not FinancialE1EndpointRequest
            or type(raw_body) is not bytes
            or not raw_body
            or type(evidence) is not FinancialResponseEvidence
            or request.provider_name != AKSHARE_PROVIDER_NAME
            or request.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request.request_announcement_date is not None
            or request.max_attempts != 1
            or request.pagination_policy != "one_response"
        ):
            raise FinancialE1ReplayError("E1 response scope request is invalid")
        if request.endpoint == self._main_contract.endpoint:
            row = _one_main_row(raw_body, self._main_contract)
            asset = row.get(self._main_contract.asset_field)
            period = _strict_provider_date(row.get(self._main_contract.period_end_field))
            if asset != request.request_asset_code or period != request.request_period_end:
                raise FinancialE1ReplayError("Main body does not contain the exact requested row")
        elif request.endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT:
            parsed = parse_balance_candidate_body(
                raw_body,
                request=_balance_request(request),
                contract=self._balance_contract,
            )
            if (
                parsed.outcome != "candidate_parsed"
                or parsed.source_row_identity is None
                or parsed.source_row_identity.symbol != request.request_asset_code
                or parsed.source_row_identity.report_date != request.request_period_end
            ):
                raise FinancialE1ReplayError(
                    "Balance body does not contain the exact requested row"
                )
        else:
            raise FinancialE1ReplayError("E1 endpoint is not an exact Main or Balance endpoint")
        scope = FinancialResponseScope(
            asset_codes=(request.request_asset_code,),
            period_ends=(request.request_period_end,),
            row_count=1,
        )
        return with_provider_verified_response_scope(evidence, scope)


class FinancialE1DiscoveryRoleReplayer:
    """Independently replay Main/Balance numeric roles from their retained bytes."""

    def __init__(
        self,
        *,
        main_notice_contract: FinancialSharedResponseSourceTimeContractV2,
        balance_parser_contract: BalanceCandidateContract,
    ) -> None:
        """Bind strict provider parsers and no metric or unit defaults."""

        if type(main_notice_contract) is not FinancialSharedResponseSourceTimeContractV2:
            raise TypeError("an exact Main NOTICE contract is required")
        _validate_balance_parser_contract(balance_parser_contract)
        self._main_contract = main_notice_contract
        self._balance_contract = balance_parser_contract

    def replay_main(
        self,
        plan: object,
        response: FinancialE1RetainedResponse,
        *,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
    ) -> FinancialE1EndpointReplay:
        """Discover NOTICE and replay every selected Main value from one body."""

        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("Main role replay requires the explicit E1 discovery plan")
        if type(response) is not FinancialE1RetainedResponse:
            raise TypeError("Main role replay requires one retained response")
        row_values = _one_main_row(response.raw_body, self._main_contract)
        if (
            row_values.get(self._main_contract.asset_field) != plan.asset_code
            or _strict_provider_date(row_values.get(self._main_contract.period_end_field))
            != plan.period_end
        ):
            raise FinancialE1ReplayError("Main response does not match the requested asset/period")
        notice_text = row_values.get(self._main_contract.announcement_date_field)
        notice_date = _strict_provider_date(notice_text)
        if notice_date is None or type(notice_text) is not str:
            raise FinancialE1ReplayError("Main raw row has no strict native NOTICE_DATE")
        response_reference = response.retention.reference
        shared_reference = FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=response_reference,
            contract=self._main_contract,
            requested_asset_code=plan.asset_code,
            requested_period_end=plan.period_end,
            requested_announcement_date=notice_date,
        )
        notice_binding = match_shared_main_notice_date_v2(
            response.raw_body,
            artifact_reference=shared_reference,
        )
        if type(notice_binding) is not FinancialSharedResponseNoticeBindingV2:
            raise FinancialE1ReplayError(
                "Main NOTICE role did not independently replay exact bytes"
            )
        selected = _exact_qualifications(
            qualifications,
            endpoint=plan.main_request.endpoint,
        )
        observations: list[NativeFinancialMetricObservation] = []
        for qualification in selected:
            observation = build_shared_main_numeric_observation_v2(
                response.raw_body,
                artifact_reference=shared_reference,
                metric_contract=qualification.contract,
            )
            if type(observation) is not NativeFinancialMetricObservation:
                raise FinancialE1ReplayError(
                    "Main native metric did not replay from its exact body"
                )
            observations.append(observation)
        row = FinancialE1NativeRowIdentity(
            artifact_reference=response_reference,
            provider_name=plan.provider_name,
            dataset_key=plan.main_request.dataset_key,
            endpoint=plan.main_request.endpoint,
            asset_code=plan.asset_code,
            period_end=plan.period_end,
            period_type=_period_type_from_period_end(plan.period_end),
            notice_date=notice_binding.notice_date,
            native_row_id=notice_binding.native_row_id,
            row_projection_sha256=notice_binding.row_projection_sha256,
            matched_row_count=1,
        )
        context = MappingProxyType(dict(row_values))
        return FinancialE1EndpointReplay(
            role=FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            row=row,
            observations=tuple(observations),
            source_context=context,
            notice_binding=notice_binding,
        )

    def replay_balance(
        self,
        plan: object,
        response: FinancialE1RetainedResponse,
        *,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
    ) -> FinancialE1EndpointReplay:
        """Replay Balance native values and its own raw NOTICE from its body."""

        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("Balance role replay requires the explicit E1 discovery plan")
        if type(response) is not FinancialE1RetainedResponse:
            raise TypeError("Balance role replay requires one retained response")
        request = _balance_request(plan.balance_request)
        parsed = parse_balance_candidate_body(
            response.raw_body,
            request=request,
            contract=self._balance_contract,
        )
        if (
            parsed.outcome != "candidate_parsed"
            or parsed.source_row_identity is None
            or parsed.row_projection_sha256 is None
            or parsed.row_index != 0
            or parsed.source_row_identity.symbol != plan.asset_code
            or parsed.source_row_identity.report_date != plan.period_end
        ):
            raise FinancialE1ReplayError("Balance raw row did not strictly replay")
        expected_parameters = dict(
            build_balance_candidate_query(request, self._balance_contract).parameters
        )
        expected_parameters["endpoint"] = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        actual_params = response.retention.audit.request_params
        if not _exact_mapping(actual_params, expected_parameters):
            raise FinancialE1ReplayError(
                "Balance RawAudit query differs from exact request contract"
            )
        selected = _exact_qualifications(
            qualifications,
            endpoint=plan.balance_request.endpoint,
        )
        observations: list[NativeFinancialMetricObservation] = []
        for qualification in selected:
            matches = tuple(
                value
                for value in parsed.values
                if value.metric_code == qualification.contract.metric_code
            )
            if (
                len(matches) != 1
                or matches[0].raw_key != qualification.contract.source_field
                or matches[0].unit_code != qualification.contract.source_unit
            ):
                raise FinancialE1ReplayError("Balance native field binding differs from catalog")
            observations.append(
                NativeFinancialMetricObservation.from_raw_value(
                    contract=qualification.contract,
                    raw_value=matches[0].value,
                    source_field=qualification.contract.source_field,
                    body_sha256=parsed.body_sha256,
                    native_row_id=_balance_native_row_id(parsed.source_row_identity),
                )
            )
        row = FinancialE1NativeRowIdentity(
            artifact_reference=response.retention.reference,
            provider_name=plan.provider_name,
            dataset_key=plan.balance_request.dataset_key,
            endpoint=plan.balance_request.endpoint,
            asset_code=plan.asset_code,
            period_end=plan.period_end,
            period_type=_period_type_from_period_end(plan.period_end),
            notice_date=parsed.source_row_identity.notice_date,
            native_row_id=_balance_native_row_id(parsed.source_row_identity),
            row_projection_sha256=parsed.row_projection_sha256,
            matched_row_count=1,
        )
        return FinancialE1EndpointReplay(
            role=FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
            row=row,
            observations=tuple(observations),
            source_context=MappingProxyType(dict(parsed.raw_row_context)),
        )


def _one_main_row(
    raw_body: bytes,
    contract: FinancialSharedResponseSourceTimeContractV2,
) -> Mapping[str, object]:
    """Decode the exact Main body and require exactly one full target row."""

    if type(raw_body) is not bytes or not raw_body:
        raise FinancialE1ReplayError("Main response body is empty")
    payload = decode_json_bytes(raw_body)
    if not isinstance(payload, Mapping):
        raise FinancialE1ReplayError("Main response root must be a JSON object")
    if (
        type(payload.get(contract.success_key)) is not type(contract.success_value)
        or payload.get(contract.success_key) != contract.success_value
        or type(payload.get(contract.code_key)) is not type(contract.success_code)
        or payload.get(contract.code_key) != contract.success_code
    ):
        raise FinancialE1ReplayError("Main provider success markers do not match the contract")
    result = payload.get(contract.result_key)
    if not isinstance(result, Mapping):
        raise FinancialE1ReplayError("Main response has no result object")
    raw_rows = result.get(contract.data_key)
    count = result.get(contract.count_key)
    if type(count) is not int or not isinstance(raw_rows, list) or count != len(raw_rows):
        raise FinancialE1ReplayError("Main response row count is ambiguous")
    if count != 1 or not isinstance(raw_rows[0], Mapping):
        raise FinancialE1ReplayError("E1 Main response must contain exactly one raw row")
    row = raw_rows[0]
    if any(type(key) is not str for key in row):
        raise FinancialE1ReplayError("Main response row keys must be text")
    for field_name in (
        contract.asset_field,
        contract.period_end_field,
        contract.announcement_date_field,
    ):
        if field_name not in row:
            raise FinancialE1ReplayError("Main response row is missing its native identity")
    return cast(Mapping[str, object], row)


def _strict_provider_date(value: object) -> date | None:
    """Parse only the source matcher's explicit date-only spellings."""

    if type(value) is not str or len(value) not in _STRICT_DATE_LENGTHS or value != value.strip():
        return None
    text = value if len(value) == 10 else value[:10]
    if len(value) == 19 and not value.endswith(" 00:00:00"):
        return None
    if text[4:5] != "-" or text[7:8] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _balance_request(request: FinancialE1EndpointRequest) -> BalanceCandidateRequest:
    """Build a Balance parser request from an explicit six-digit-suffix symbol."""

    if (
        type(request) is not FinancialE1EndpointRequest
        or request.endpoint != AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        or request.provider_name != AKSHARE_PROVIDER_NAME
        or request.dataset_key != FINANCIAL_FACT_DATASET_KEY
        or len(request.request_asset_code) != 9
        or request.request_asset_code[6] != "."
        or request.request_asset_code[7:] not in {"SH", "SZ"}
        or not request.request_asset_code[:6].isascii()
        or not request.request_asset_code[:6].isdigit()
    ):
        raise FinancialE1ReplayError("Balance request has no exact supported security identity")
    return BalanceCandidateRequest(
        symbol=request.request_asset_code,
        security_code=request.request_asset_code[:6],
        report_date=request.request_period_end,
    )


def _exact_qualifications(
    qualifications: tuple[FinancialNumericSourceQualification, ...],
    *,
    endpoint: str,
) -> tuple[FinancialNumericSourceQualification, ...]:
    """Require a typed unique non-empty endpoint-specific qualification tuple."""

    if type(qualifications) is not tuple or not qualifications:
        raise FinancialE1ReplayError("Endpoint has no explicitly selected metric qualifications")
    if any(type(item) is not FinancialNumericSourceQualification for item in qualifications):
        raise FinancialE1ReplayError("Endpoint qualification input is not fully typed")
    if any(item.endpoint != endpoint for item in qualifications):
        raise FinancialE1ReplayError("Endpoint qualification tuple contains another endpoint")
    identities = tuple(item.identity for item in qualifications)
    metrics = tuple(item.contract.metric_code for item in qualifications)
    if len(set(identities)) != len(identities) or len(set(metrics)) != len(metrics):
        raise FinancialE1ReplayError("Endpoint qualification tuple contains duplicates")
    return qualifications


def _exact_mapping(actual: object, expected: Mapping[str, object]) -> bool:
    """Compare audit query keys and scalar types without string coercion."""

    return (
        isinstance(actual, Mapping)
        and dict(actual) == dict(expected)
        and all(type(actual[key]) is type(value) for key, value in expected.items())
    )


def _text(payload: Mapping[str, object], key: str) -> str:
    """Read one exact, bounded v2 provider-config string."""

    value = payload.get(key)
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise ValueError(f"provider config field {key} is invalid")
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"provider config field {key} contains a control character")
    return value


__all__ = [
    "FinancialE1BalanceCaptureConfigV2",
    "FinancialE1DiscoveryResponseScopeVerifier",
    "FinancialE1DiscoveryRoleReplayer",
    "FinancialE1ReplayError",
    "build_main_shared_response_contract",
]
