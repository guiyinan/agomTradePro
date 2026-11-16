"""Pure contracts for the canonical E1 shared-Main capture."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.domain import financial_e1_capture_contract as financial_e1
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
    raw_body_sha256,
)

MAIN_ENDPOINT = "datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_MAINFINADATA"
BALANCE_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PROVIDER = "akshare"
ASSET = "000858.SZ"
PERIOD_END = date(2026, 9, 30)
NOTICE_DATE = date(2026, 10, 25)
RESPONSE_COMPLETED_AT = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)
BODY_TEMPLATE = (
    b'{"success":true,"code":0,"result":{"count":1,"data":[{'
    b'"SECUCODE":"000858.SZ","REPORT_DATE":"2026-09-30 00:00:00",'
    b'"NOTICE_DATE":"2026-10-25 00:00:00","TOTALOPERATEREVE":123456789.1234567'
    b"}]}}"
)


def _source_time_contract() -> object:
    """Build an explicit synthetic v2 contract, never a production approval."""

    return financial_e1.FinancialSharedResponseSourceTimeContractV2(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=MAIN_ENDPOINT,
        contract_id="test.shared-main-notice-date",
        contract_version="test-v2",
        parser_version="test-json-row-parser.v2",
        source_timezone="Asia/Shanghai",
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        result_key="result",
        data_key="data",
        count_key="count",
        asset_field="SECUCODE",
        period_end_field="REPORT_DATE",
        announcement_date_field="NOTICE_DATE",
        row_identity_prefix=PROVIDER,
        projection_fields=("SECUCODE", "REPORT_DATE", "NOTICE_DATE"),
    )


def _main_reference(
    body: bytes = BODY_TEMPLATE,
    *,
    capture_id: UUID | None = None,
    asset_code: str = ASSET,
    period_end: date = PERIOD_END,
    row_count: int = 1,
) -> FinancialResponseArtifactRef:
    """Return one synthetic immutable Main response reference."""

    request_scope = FinancialRequestScope(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        asset_code=asset_code,
        period_limit=8,
    )
    evidence = FinancialResponseEvidence(
        body_sha256=raw_body_sha256(body),
        body_size_bytes=len(body),
        response_completed_at=RESPONSE_COMPLETED_AT,
        request_scope=request_scope,
        response_scope=FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(period_end,),
            row_count=row_count,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialResponseArtifactRef(
        capture_id=capture_id or UUID("00000000-0000-4000-8000-000000000001"),
        location="financial-response/2026/10/capture-one.enc",
        evidence=evidence,
        format_version="financial-response-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="test.key",
        encryption_key_version="test-v1",
    )


def _balance_reference(
    body: bytes = b'{"data":[{"ASSET":"000858.SZ","PERIOD":"2026-09-30"}]}',
    *,
    capture_id: UUID | None = None,
    asset_code: str = ASSET,
    dataset_key: str = "equity.financial.fact",
) -> FinancialResponseArtifactRef:
    """Return one Balance response identity without promoting its scope claim."""

    evidence = FinancialResponseEvidence(
        body_sha256=raw_body_sha256(body),
        body_size_bytes=len(body),
        response_completed_at=RESPONSE_COMPLETED_AT,
        request_scope=FinancialRequestScope(
            provider_name=PROVIDER,
            dataset_key=dataset_key,
            asset_code=asset_code,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(PERIOD_END,),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
    )
    return FinancialResponseArtifactRef(
        capture_id=capture_id or UUID("00000000-0000-4000-8000-000000000002"),
        location="financial-response/2026/10/balance-capture.enc",
        evidence=evidence,
        format_version="financial-response-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="test.key",
        encryption_key_version="test-v1",
    )


def _shared_reference(
    body: bytes = BODY_TEMPLATE,
    *,
    announcement_date: date = NOTICE_DATE,
    capture_id: UUID | None = None,
    asset_code: str = ASSET,
    period_end: date = PERIOD_END,
    row_count: int = 1,
) -> object:
    """Build a source-time role reference that aliases one Main artifact."""

    return financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
        response_reference=_main_reference(
            body,
            capture_id=capture_id,
            asset_code=asset_code,
            period_end=period_end,
            row_count=row_count,
        ),
        contract=_source_time_contract(),
        requested_asset_code=asset_code,
        requested_period_end=period_end,
        requested_announcement_date=announcement_date,
    )


def _capture_plan(
    *,
    main_max_attempts: int = 1,
    balance_max_attempts: int = 1,
    main_roles: tuple[object, ...] | None = None,
    balance_endpoint: str = BALANCE_ENDPOINT,
) -> object:
    """Build the E1 two-slot contract with no implicit retries or extra page."""

    roles = main_roles or (
        financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
        financial_e1.FinancialE1ResponseRole.MAIN_NOTICE_DATE,
    )
    main = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=MAIN_ENDPOINT,
        roles=roles,
        request_asset_code=ASSET,
        request_period_end=PERIOD_END,
        request_announcement_date=NOTICE_DATE,
        max_attempts=main_max_attempts,
        pagination_policy="one_response",
    )
    balance = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=balance_endpoint,
        roles=(financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,),
        request_asset_code=ASSET,
        request_period_end=PERIOD_END,
        request_announcement_date=None,
        max_attempts=balance_max_attempts,
        pagination_policy="one_response",
    )
    return financial_e1.FinancialE1CaptureContractV1(
        provider_name=PROVIDER,
        asset_code=ASSET,
        period_end=PERIOD_END,
        announcement_date=NOTICE_DATE,
        main_request=main,
        balance_request=balance,
        source_time_contract=_source_time_contract(),
        maximum_physical_attempts=2,
    )


def _metric_contract(
    *,
    provider: str = PROVIDER,
    dataset_key: str = "equity.financial.fact",
    source_field: str = "TOTALOPERATEREVE",
) -> FinancialMetricSourceContract:
    """Build an explicit synthetic native numeric contract with no unit default."""

    return FinancialMetricSourceContract(
        provider=provider,
        dataset_key=dataset_key,
        metric_code="test.metric.revenue",
        source_field=source_field,
        source_unit="source_unit",
        canonical_unit="canonical_unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="test-v1",
        origin="native",
    )


def _json_body(rows: list[dict[str, object]]) -> bytes:
    """Encode deterministic synthetic response bytes for parser tests."""

    payload = {"success": True, "code": 0, "result": {"count": len(rows), "data": rows}}
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_e1_plan_has_two_one_attempt_slots_and_shares_main_roles() -> None:
    """Numeric and NOTICE roles share one Main slot; Balance is the second slot."""

    plan = _capture_plan()
    projection = plan.to_dict()

    assert plan.request_count == 2
    assert plan.maximum_physical_attempts == 2
    assert projection["evidence_only"] is True
    assert projection["production_ready"] is False
    assert projection["must_not_use_for_decision"] is True
    assert projection["main_request"]["max_attempts"] == 1
    assert projection["balance_request"]["max_attempts"] == 1
    assert projection["main_request"]["roles"] == [
        "main_native_numeric",
        "main_notice_date_source_time",
    ]
    assert projection["balance_request"]["roles"] == ["balance_native_numeric"]
    assert "capture_id" not in projection


@pytest.mark.parametrize(
    ("main_max_attempts", "balance_max_attempts"),
    [(2, 1), (1, 2)],
)
def test_e1_plan_rejects_any_implicit_retry(
    main_max_attempts: int,
    balance_max_attempts: int,
) -> None:
    """The plan cannot silently spend a third request on a retried route."""

    with pytest.raises(ValueError, match="exactly one attempt"):
        _capture_plan(
            main_max_attempts=main_max_attempts,
            balance_max_attempts=balance_max_attempts,
        )


def test_e1_plan_rejects_shared_endpoint_or_wrong_role_assignment() -> None:
    """Two slots must mean one Main endpoint and one distinct Balance endpoint."""

    with pytest.raises(ValueError, match="distinct endpoint"):
        _capture_plan(balance_endpoint=MAIN_ENDPOINT)

    with pytest.raises(ValueError, match="only the Main NOTICE role"):
        _capture_plan(main_roles=(financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,))


def test_e1_plan_binds_same_asset_period_and_main_notice_request() -> None:
    """Both endpoint slots are fixed to one asset/period; only Main gets notice date."""

    contract = _source_time_contract()
    main = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=MAIN_ENDPOINT,
        roles=(
            financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            financial_e1.FinancialE1ResponseRole.MAIN_NOTICE_DATE,
        ),
        request_asset_code="000001.SZ",
        request_period_end=PERIOD_END,
        request_announcement_date=NOTICE_DATE,
        max_attempts=1,
        pagination_policy="one_response",
    )
    balance = financial_e1.FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=BALANCE_ENDPOINT,
        roles=(financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,),
        request_asset_code=ASSET,
        request_period_end=PERIOD_END,
        request_announcement_date=None,
        max_attempts=1,
        pagination_policy="one_response",
    )
    with pytest.raises(ValueError, match="Main request context"):
        financial_e1.FinancialE1CaptureContractV1(
            provider_name=PROVIDER,
            asset_code=ASSET,
            period_end=PERIOD_END,
            announcement_date=NOTICE_DATE,
            main_request=main,
            balance_request=balance,
            source_time_contract=contract,
            maximum_physical_attempts=2,
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"roles": []}, "non-empty tuple"),
        ({"roles": ()}, "non-empty tuple"),
        ({"roles": (object(),)}, "typed"),
        (
            {
                "roles": (
                    financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
                    financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
                )
            },
            "unique",
        ),
        ({"pagination_policy": "multiple_pages"}, "forbid follow-up pagination"),
        ({"request_announcement_date": None}, "Main NOTICE role"),
    ],
)
def test_endpoint_slot_rejects_unbounded_role_and_page_contracts(
    changes: dict[str, object], reason: str
) -> None:
    """Every endpoint slot requires typed, unique roles and one response only."""

    request = _capture_plan().main_request

    with pytest.raises(ValueError, match=reason):
        replace(request, **changes)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"dataset_key": "equity.other"}, "Main financial dataset"),
        ({"success_value": Decimal("1")}, "JSON scalar"),
        ({"success_code": None}, "JSON scalar"),
        ({"source_timezone": "Invalid/Zone"}, "timezone is unknown"),
        ({"period_end_field": "SECUCODE"}, "identity fields must be distinct"),
        ({"projection_fields": []}, "non-empty tuple"),
        ({"projection_fields": ("SECUCODE", "SECUCODE")}, "must be unique"),
        ({"projection_fields": ("NOTICE_DATE",)}, "preserve all source row identity"),
    ],
)
def test_shared_source_time_contract_rejects_incomplete_or_invalid_schema(
    changes: dict[str, object], reason: str
) -> None:
    """Versioned shared-body parsing cannot infer schema or timezone details."""

    with pytest.raises(ValueError, match=reason):
        replace(_source_time_contract(), **changes)


def test_source_time_reference_rejects_provider_record_body_and_empty_body_scope() -> None:
    """Reference scope must bind the exact provider, complete body, and non-empty bytes."""

    valid = _main_reference()
    mismatched_provider_evidence = replace(
        valid.evidence,
        request_scope=replace(valid.evidence.request_scope, provider_name="other-provider"),
    )
    with pytest.raises(ValueError, match="provider does not match"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=replace(valid, evidence=mismatched_provider_evidence),
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )

    record_evidence = replace(
        valid.evidence,
        body_scope=FinancialResponseBodyScope.RECORD,
    )
    with pytest.raises(ValueError, match="complete response body"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=replace(valid, evidence=record_evidence),
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )

    empty_evidence = replace(valid.evidence, body_size_bytes=0)
    with pytest.raises(ValueError, match="must be non-empty"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=replace(valid, evidence=empty_evidence),
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )


def test_notice_binding_rejects_mutated_request_identity_and_projection() -> None:
    """The frozen notice value rechecks every date, row, projection, and digest claim."""

    reference = _shared_reference()
    binding = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=reference,
    )
    assert binding is not None
    mutations = (
        ({"native_asset_code": "000001.SZ"}, "asset does not match"),
        ({"native_period_end": date(2026, 6, 30)}, "period does not match"),
        ({"notice_date": date(2026, 10, 26)}, "NOTICE date does not match"),
        ({"raw_notice_date_text": "2026-10-25 10:00:00"}, "raw NOTICE spelling"),
        ({"native_row_id": "altered-row"}, "row id does not match"),
        ({"row_index": True}, "non-negative integer"),
        ({"row_projection_fields": []}, "immutable tuple"),
        ({"row_projection_fields": (("wrong", "value"),)}, "do not match the contract"),
        ({"row_projection_sha256": "not-a-digest"}, "lowercase SHA-256"),
        ({"row_projection_sha256": "0" * 64}, "does not match the exact row projection"),
    )
    for changes, reason in mutations:
        with pytest.raises(ValueError, match=reason):
            replace(binding, **changes)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("provider", "Main endpoint provider"),
        ("balance_provider", "Balance endpoint provider"),
        ("main_context", "Main request context"),
        ("balance_context", "Balance request context"),
        ("main_dataset", "Main request must use"),
        ("contract_provider", "source-time contract provider"),
        ("contract_endpoint", "must bind the Main endpoint"),
        ("main_roles", "exactly numeric and NOTICE-date roles"),
        ("balance_roles", "only the Balance native-value role"),
        ("same_endpoint", "distinct endpoint"),
    ],
)
def test_e1_capture_contract_rejects_scope_or_endpoint_drift(change: str, reason: str) -> None:
    """Both request slots and the source-time version bind the exact E1 target."""

    plan = _capture_plan()
    main = plan.main_request
    balance = plan.balance_request
    source_contract = plan.source_time_contract
    if change == "provider":
        main = replace(main, provider_name="other-provider")
    elif change == "balance_provider":
        balance = replace(balance, provider_name="other-provider")
    elif change == "main_context":
        main = replace(main, request_period_end=date(2026, 6, 30))
    elif change == "balance_context":
        balance = replace(balance, request_period_end=date(2026, 6, 30))
    elif change == "main_dataset":
        main = replace(main, dataset_key="equity.other")
    elif change == "contract_provider":
        source_contract = replace(source_contract, provider_name="other-provider")
    elif change == "contract_endpoint":
        source_contract = replace(source_contract, endpoint="other-endpoint")
    elif change == "main_roles":
        main = replace(
            main,
            roles=(
                financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
                financial_e1.FinancialE1ResponseRole.MAIN_NOTICE_DATE,
                financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
            ),
        )
    elif change == "balance_roles":
        balance = replace(
            balance,
            roles=(
                financial_e1.FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
                financial_e1.FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,
            ),
        )
    elif change == "same_endpoint":
        balance = replace(balance, endpoint=main.endpoint)
    else:
        raise AssertionError(f"unknown mutation: {change}")

    with pytest.raises(ValueError, match=reason):
        replace(
            plan,
            main_request=main,
            balance_request=balance,
            source_time_contract=source_contract,
        )


def test_shared_response_reference_uses_the_main_identity_without_second_capture() -> None:
    """The source-time role aliases the existing Main ID/body and creates no audit ID."""

    reference = _shared_reference()
    payload = reference.to_dict()

    assert reference.capture_id == reference.response_reference.capture_id
    assert reference.body_sha256 == reference.response_reference.body_sha256
    assert payload["capture_id"] == str(reference.response_reference.capture_id)
    assert payload["body_sha256"] == reference.response_reference.body_sha256
    assert payload["capture_mode"] == "same_main_response"
    assert "source_time_capture_id" not in payload
    assert "source_time_audit_id" not in payload


def test_shared_source_time_reference_rejects_non_main_dataset_and_unverified_scope() -> None:
    """Shared mode cannot disguise a separate source-time dataset or caller claim."""

    wrong_dataset = FinancialResponseArtifactRef(
        capture_id=UUID("00000000-0000-4000-8000-000000000002"),
        location="financial-response/2026/10/other.enc",
        evidence=FinancialResponseEvidence(
            body_sha256=raw_body_sha256(BODY_TEMPLATE),
            body_size_bytes=len(BODY_TEMPLATE),
            response_completed_at=RESPONSE_COMPLETED_AT,
            request_scope=FinancialRequestScope(
                provider_name=PROVIDER,
                dataset_key="equity.financial.source-time",
                asset_code=ASSET,
                period_limit=8,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=(ASSET,), period_ends=(PERIOD_END,), row_count=1
            ),
            response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
        ),
        format_version="financial-response-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="test.key",
        encryption_key_version="test-v1",
    )
    with pytest.raises(ValueError, match="Main request scope"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=wrong_dataset,
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )


def test_shared_source_time_reference_rejects_unverified_main_dataset_scope() -> None:
    """Matching dataset text cannot replace verification of the Main response body."""

    verified = _main_reference()
    unverified_evidence = replace(
        verified.evidence,
        response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
    )
    unverified = replace(verified, evidence=unverified_evidence)

    with pytest.raises(ValueError, match="provider-body-verified scope"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=unverified,
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )


def test_raw_capture_pair_has_two_response_ids_and_does_not_promote_balance_scope() -> None:
    """One Main reference serves two roles; Balance remains a separate raw body."""

    shared = _shared_reference()
    notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
    )
    numeric = financial_e1.build_shared_main_numeric_observation_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
        metric_contract=_metric_contract(),
    )
    assert notice is not None
    assert numeric is not None

    pair = financial_e1.FinancialE1RawCapturePairV1(
        contract=_capture_plan(),
        main_reference=shared.response_reference,
        balance_reference=_balance_reference(),
        source_time_reference=shared,
        source_time_binding=notice,
        main_numeric_observations=(numeric,),
    )
    payload = pair.to_dict()

    assert len(pair.capture_ids) == 2
    assert pair.capture_ids[0] == shared.capture_id
    assert pair.capture_ids[1] != shared.capture_id
    assert payload["capture_ids"] == [str(item) for item in pair.capture_ids]
    assert payload["balance_reference"]["response_scope_basis"] == "caller_declared"
    assert payload["shared_source_time_reference"]["capture_id"] == str(shared.capture_id)
    assert "source_time_capture_id" not in payload
    assert "source_time_audit_id" not in payload


def test_raw_capture_pair_rejects_duplicate_response_identity_and_unplanned_notice_contract() -> (
    None
):
    """The role alias must use the planned v2 contract and a distinct Balance capture."""

    shared = _shared_reference()
    notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
    )
    numeric = financial_e1.build_shared_main_numeric_observation_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
        metric_contract=_metric_contract(),
    )
    assert notice is not None
    assert numeric is not None
    plan = _capture_plan()

    with pytest.raises(ValueError, match="two capture IDs"):
        financial_e1.FinancialE1RawCapturePairV1(
            contract=plan,
            main_reference=shared.response_reference,
            balance_reference=_balance_reference(capture_id=shared.capture_id),
            source_time_reference=shared,
            source_time_binding=notice,
            main_numeric_observations=(numeric,),
        )

    other_contract = replace(_source_time_contract(), parser_version="test-parser.v3")
    other_reference = financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
        response_reference=shared.response_reference,
        contract=other_contract,
        requested_asset_code=ASSET,
        requested_period_end=PERIOD_END,
        requested_announcement_date=NOTICE_DATE,
    )
    other_notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=other_reference,
    )
    assert other_notice is not None
    with pytest.raises(ValueError, match="planned NOTICE contract"):
        financial_e1.FinancialE1RawCapturePairV1(
            contract=plan,
            main_reference=shared.response_reference,
            balance_reference=_balance_reference(),
            source_time_reference=other_reference,
            source_time_binding=other_notice,
            main_numeric_observations=(numeric,),
        )


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (BODY_TEMPLATE + b" ", "body digest mismatch"),
        (
            b'{"success":true,"success":false,"code":0,"result":{"count":1,"data":[]}}',
            "malformed or ambiguous body",
        ),
        (
            b'{"success":true,"code":0,"result":{"count":1,"data":[{"SECUCODE":"000858.SZ","REPORT_DATE":"2026-09-30","NOTICE_DATE":"2026-10-25 10:00:00","TOTALOPERATEREVE":1}]}}',
            "unsupported date spelling",
        ),
    ],
)
def test_notice_role_rejects_body_integrity_duplicates_and_non_date_precision(
    body: bytes,
    reason: str,
) -> None:
    """Malformed retained bytes and intraday NOTICE values cannot bind a role."""

    if reason == "body digest mismatch":
        reference = _shared_reference()
    else:
        reference = _shared_reference(body)

    result = financial_e1.match_shared_main_notice_date_v2(
        body,
        artifact_reference=reference,
    )

    assert result is None


def test_shared_main_roles_independently_replay_one_exact_original() -> None:
    """The numeric and NOTICE validators each replay one identical body identity."""

    reference = _shared_reference()
    metric_contract = _metric_contract()
    decode_calls: list[bytes] = []
    original_decoder = financial_e1._decode_rows

    def recording_decoder(raw_body: bytes, contract: object) -> object:
        decode_calls.append(raw_body)
        return original_decoder(raw_body, contract)

    financial_e1._decode_rows = recording_decoder
    try:
        notice = financial_e1.match_shared_main_notice_date_v2(
            BODY_TEMPLATE,
            artifact_reference=reference,
        )
        numeric = financial_e1.build_shared_main_numeric_observation_v2(
            BODY_TEMPLATE,
            artifact_reference=reference,
            metric_contract=metric_contract,
        )
    finally:
        financial_e1._decode_rows = original_decoder

    assert notice is not None
    assert numeric is not None
    assert decode_calls == [BODY_TEMPLATE, BODY_TEMPLATE]
    assert notice.capture_id == reference.capture_id
    assert numeric.body_sha256 == reference.body_sha256
    assert numeric.native_row_id == notice.native_row_id
    assert numeric.contract.source_field == "TOTALOPERATEREVE"
    assert numeric.source_value == "123456789.1234567"
    assert numeric.canonical_value == "123456789.1234567"
    assert type(numeric.source_value) is str
    assert "announced_at" not in notice.to_dict()
    assert "available_at" not in notice.to_dict()


@pytest.mark.parametrize(
    ("rows", "row_count"),
    [
        (
            [
                {
                    "SECUCODE": ASSET,
                    "REPORT_DATE": "2026-09-30",
                    "NOTICE_DATE": "2026-10-25",
                    "TOTALOPERATEREVE": 1,
                },
                {
                    "SECUCODE": ASSET,
                    "REPORT_DATE": "2026-09-30",
                    "NOTICE_DATE": "2026-10-25",
                    "TOTALOPERATEREVE": 2,
                },
            ],
            2,
        ),
        (
            [
                {
                    "SECUCODE": "000001.SZ",
                    "REPORT_DATE": "2026-09-30",
                    "NOTICE_DATE": "2026-10-25",
                    "TOTALOPERATEREVE": 1,
                }
            ],
            1,
        ),
        (
            [
                {
                    "SECUCODE": ASSET,
                    "REPORT_DATE": "2026-06-30",
                    "NOTICE_DATE": "2026-10-25",
                    "TOTALOPERATEREVE": 1,
                }
            ],
            1,
        ),
        (
            [
                {
                    "SECUCODE": ASSET,
                    "REPORT_DATE": "2026-09-30",
                    "NOTICE_DATE": "2026-10-24",
                    "TOTALOPERATEREVE": 1,
                }
            ],
            1,
        ),
    ],
)
def test_both_main_roles_block_duplicate_or_mismatched_rows(
    rows: list[dict[str, object]],
    row_count: int,
) -> None:
    """Duplicate, wrong-asset, wrong-period, and wrong-notice rows never bind."""

    body = _json_body(rows)
    reference = _shared_reference(body, row_count=row_count)

    assert (
        financial_e1.match_shared_main_notice_date_v2(
            body,
            artifact_reference=reference,
        )
        is None
    )
    assert (
        financial_e1.build_shared_main_numeric_observation_v2(
            body,
            artifact_reference=reference,
            metric_contract=_metric_contract(),
        )
        is None
    )


@pytest.mark.parametrize("value", [None, True, "123.45", "NaN"])
def test_numeric_role_rejects_missing_boolean_string_and_nonfinite_source(
    value: object,
) -> None:
    """Numeric role accepts only finite JSON integer/decimal values."""

    body = _json_body(
        [
            {
                "SECUCODE": ASSET,
                "REPORT_DATE": "2026-09-30",
                "NOTICE_DATE": "2026-10-25",
                "TOTALOPERATEREVE": value,
            }
        ]
    )
    reference = _shared_reference(body)

    assert (
        financial_e1.build_shared_main_numeric_observation_v2(
            body,
            artifact_reference=reference,
            metric_contract=_metric_contract(),
        )
        is None
    )


def test_numeric_role_rejects_contract_identity_drift_and_unknown_fields() -> None:
    """The numeric proof requires the exact provider, dataset, and raw field."""

    reference = _shared_reference()

    assert (
        financial_e1.build_shared_main_numeric_observation_v2(
            BODY_TEMPLATE,
            artifact_reference=reference,
            metric_contract=_metric_contract(provider="other-provider"),
        )
        is None
    )
    assert (
        financial_e1.build_shared_main_numeric_observation_v2(
            BODY_TEMPLATE,
            artifact_reference=reference,
            metric_contract=_metric_contract(dataset_key="another.dataset"),
        )
        is None
    )
    assert (
        financial_e1.build_shared_main_numeric_observation_v2(
            BODY_TEMPLATE,
            artifact_reference=reference,
            metric_contract=_metric_contract(source_field="UNLISTED_ALIAS"),
        )
        is None
    )


def test_notice_binding_projection_is_recomputed_and_contract_identity_is_versioned() -> None:
    """The role hash includes v2 contract/body/raw projection and cannot be self-reported."""

    reference = _shared_reference()
    notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=reference,
    )
    assert notice is not None
    assert notice.artifact_reference.contract.identity.startswith(
        "financial-source-time-shared-main-response-contract.v2:test-v2:"
    )
    assert notice.row_projection_fields == (
        ("SECUCODE", ASSET),
        ("REPORT_DATE", "2026-09-30 00:00:00"),
        ("NOTICE_DATE", "2026-10-25 00:00:00"),
    )

    with pytest.raises(ValueError, match="does not match the exact row projection"):
        replace(notice, row_projection_sha256="0" * 64)


def test_source_time_reference_rejects_main_asset_period_and_body_scope_mismatch() -> None:
    """A shared-role reference must describe the exact provider-verified Main scope."""

    with pytest.raises(ValueError, match="asset does not match Main"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=_main_reference(),
            contract=_source_time_contract(),
            requested_asset_code="000001.SZ",
            requested_period_end=PERIOD_END,
            requested_announcement_date=NOTICE_DATE,
        )

    with pytest.raises(ValueError, match="period is outside verified response scope"):
        financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=_main_reference(),
            contract=_source_time_contract(),
            requested_asset_code=ASSET,
            requested_period_end=date(2026, 6, 30),
            requested_announcement_date=NOTICE_DATE,
        )


def test_shared_contract_hash_changes_when_endpoint_changes() -> None:
    """The v2 identity binds the exact endpoint while retaining the v1 contract."""

    contract = _source_time_contract()
    changed = replace(contract, endpoint=MAIN_ENDPOINT + "&alias=1")

    assert contract.content_hash != changed.content_hash
    assert contract.identity != changed.identity
    assert contract.to_dict()["capture_mode"] == "same_main_response"


def test_source_time_reference_rejects_untyped_artifact_or_contract() -> None:
    """The role reference accepts only exact artifact and v2 contract types."""

    reference = _shared_reference()
    with pytest.raises(ValueError, match="FinancialResponseArtifactRef"):
        replace(reference, response_reference=object())
    with pytest.raises(ValueError, match="FinancialSharedResponseSourceTimeContractV2"):
        replace(reference, contract=object())


def test_e1_plan_requires_typed_slots_and_exactly_two_physical_attempts() -> None:
    """Plan identity is closed and cannot raise the two-send ceiling."""

    plan = _capture_plan()
    with pytest.raises(ValueError, match="main_request must be typed"):
        replace(plan, main_request=object())
    with pytest.raises(ValueError, match="balance_request must be typed"):
        replace(plan, balance_request=object())
    with pytest.raises(ValueError, match="shared-response v2 type"):
        replace(plan, source_time_contract=object())
    with pytest.raises(ValueError, match="exactly two total physical attempts"):
        replace(plan, maximum_physical_attempts=3)
    with pytest.raises(ValueError, match="exactly two total physical attempts"):
        replace(plan, maximum_physical_attempts=True)


def test_pair_rejects_wrong_balance_dataset_and_body_verified_period_mismatch() -> None:
    """The second artifact stays independent and must match the requested period."""

    shared = _shared_reference()
    notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
    )
    numeric = financial_e1.build_shared_main_numeric_observation_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
        metric_contract=_metric_contract(),
    )
    assert notice is not None
    assert numeric is not None
    plan = _capture_plan()

    with pytest.raises(ValueError, match="Balance request scope"):
        financial_e1.FinancialE1RawCapturePairV1(
            contract=plan,
            main_reference=shared.response_reference,
            balance_reference=_balance_reference(dataset_key="equity.other"),
            source_time_reference=shared,
            source_time_binding=notice,
            main_numeric_observations=(numeric,),
        )

    balance = _balance_reference()
    verified_scope = replace(
        balance.evidence,
        response_scope=FinancialResponseScope(
            asset_codes=(ASSET,),
            period_ends=(date(2026, 6, 30),),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    with pytest.raises(ValueError, match="body-verified Balance response misses"):
        financial_e1.FinancialE1RawCapturePairV1(
            contract=plan,
            main_reference=shared.response_reference,
            balance_reference=replace(balance, evidence=verified_scope),
            source_time_reference=shared,
            source_time_binding=notice,
            main_numeric_observations=(numeric,),
        )


def test_pair_rejects_empty_duplicate_or_wrong_body_main_observations() -> None:
    """Main values must be explicit and map to the same response row and body."""

    shared = _shared_reference()
    notice = financial_e1.match_shared_main_notice_date_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
    )
    numeric = financial_e1.build_shared_main_numeric_observation_v2(
        BODY_TEMPLATE,
        artifact_reference=shared,
        metric_contract=_metric_contract(),
    )
    assert notice is not None
    assert numeric is not None
    common = {
        "contract": _capture_plan(),
        "main_reference": shared.response_reference,
        "balance_reference": _balance_reference(),
        "source_time_reference": shared,
        "source_time_binding": notice,
    }

    with pytest.raises(ValueError, match="include explicit native evidence"):
        financial_e1.FinancialE1RawCapturePairV1(
            **common,
            main_numeric_observations=(),
        )
    with pytest.raises(ValueError, match="typed native evidence"):
        financial_e1.FinancialE1RawCapturePairV1(
            **common,
            main_numeric_observations=(object(),),
        )
    with pytest.raises(ValueError, match="shared capture role"):
        financial_e1.FinancialE1RawCapturePairV1(
            **common,
            main_numeric_observations=(replace(numeric, body_sha256="0" * 64),),
        )
    with pytest.raises(ValueError, match="shared capture role"):
        financial_e1.FinancialE1RawCapturePairV1(
            **common,
            main_numeric_observations=(numeric, numeric),
        )


@pytest.mark.parametrize(
    "body",
    [
        b'{"success":1,"code":0,"result":{"count":1,"data":[]}}',
        b'{"success":true,"code":false,"result":{"count":1,"data":[]}}',
        b'{"success":true,"code":0,"result":[]}',
        b'{"success":true,"code":0,"result":{"count":0,"data":[]}}',
        b'{"success":true,"code":0,"result":{"count":1,"data":[1]}}',
        b'{"success":true,"code":0,"result":{"count":1,"data":[{"v":NaN}]}}',
    ],
)
def test_main_notice_replay_rejects_bad_envelopes_and_nonstandard_numbers(body: bytes) -> None:
    """Envelope status, row cardinality, JSON shape, and finite-number rules are strict."""

    reference = _shared_reference(body, row_count=1)

    assert financial_e1.match_shared_main_notice_date_v2(body, artifact_reference=reference) is None


def test_main_notice_replay_rejects_wrong_runtime_inputs_and_projection_types() -> None:
    """Replays require exact bytes, one typed reference, and text projections."""

    reference = _shared_reference()
    assert (
        financial_e1.match_shared_main_notice_date_v2("not-bytes", artifact_reference=reference)
        is None
    )
    assert financial_e1.match_shared_main_notice_date_v2(b"", artifact_reference=reference) is None
    assert (
        financial_e1.match_shared_main_notice_date_v2(BODY_TEMPLATE, artifact_reference=object())
        is None
    )

    contract = replace(
        _source_time_contract(),
        projection_fields=("SECUCODE", "REPORT_DATE", "NOTICE_DATE", "TOTALOPERATEREVE"),
    )
    reference_with_numeric_projection = financial_e1.FinancialSharedResponseSourceTimeReferenceV2(
        response_reference=_main_reference(),
        contract=contract,
        requested_asset_code=ASSET,
        requested_period_end=PERIOD_END,
        requested_announcement_date=NOTICE_DATE,
    )
    assert (
        financial_e1.match_shared_main_notice_date_v2(
            BODY_TEMPLATE,
            artifact_reference=reference_with_numeric_projection,
        )
        is None
    )


def test_private_scalar_and_text_helpers_reject_untyped_or_noncanonical_values() -> None:
    """Boundary helpers preserve exact JSON scalar and date semantics."""

    assert financial_e1._mapping(["not-object"]) is None
    assert financial_e1._mapping({1: "non-string-key"}) is None
    assert financial_e1._same_scalar(True, 1) is False
    assert financial_e1._strict_provider_date(" 2026-10-25") is None
    assert financial_e1._strict_provider_date("2026-02-30") is None
    assert financial_e1._strict_provider_date("2026-10-25 10:00:00") is None
    with pytest.raises(ValueError, match="bounded, unpadded text"):
        financial_e1._required_text("", "test")
    with pytest.raises(ValueError, match="must be a date, not a datetime"):
        financial_e1._calendar_date(datetime(2026, 10, 25, tzinfo=UTC), "test")
