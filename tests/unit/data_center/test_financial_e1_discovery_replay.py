"""Synthetic raw-boundary tests for the canonical E1 Main/Balance replayers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from apps.data_center.application import financial_e1_discovery_runner as _app_module
from apps.data_center.application.egress_service import FinancialResponseAttemptBudget
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactRetention,
)
from apps.data_center.domain import financial_e1_discovery_plan as _plan_module
from apps.data_center.domain.control_plane import SyncRun
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
)
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
)
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.infrastructure import financial_e1_discovery_replay as _replay_module
from apps.data_center.infrastructure import (
    financial_e1_execution_plan_file as _execution_plan_file_module,
)
from apps.data_center.infrastructure.control_plane_repositories import SyncRunRepository
from apps.data_center.infrastructure.financial_e1_governed_execution import (
    finish_django_financial_e1_non_success_run,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateRequest,
    build_balance_candidate_query,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_BALANCE_REPORT_NAME,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)
from core.exceptions import DataFetchError, DataValidationError

PROVIDER = "akshare"
ASSET = "000858.SZ"
PERIOD = date(2026, 9, 30)
RESPONSE_AT = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)


def _main_contract() -> object:
    """Build the existing source-time contract for raw Main NOTICE discovery."""

    return _replay_module.build_main_shared_response_contract()


def _plan() -> object:
    """Create an explicit finite two-endpoint plan without a caller NOTICE date."""

    main = FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        roles=(FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC,),
        request_asset_code=ASSET,
        request_period_end=PERIOD,
        request_announcement_date=None,
        max_attempts=1,
        pagination_policy="one_response",
    )
    balance = FinancialE1EndpointRequest(
        provider_name=PROVIDER,
        dataset_key="equity.financial.fact",
        endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
        roles=(FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,),
        request_asset_code=ASSET,
        request_period_end=PERIOD,
        request_announcement_date=None,
        max_attempts=1,
        pagination_policy="one_response",
    )
    return _plan_module.FinancialE1DiscoveryPlanV2(
        provider_id=77,
        provider_name=PROVIDER,
        asset_code=ASSET,
        period_end=PERIOD,
        exchange="SZ",
        calendar_dataset_key="equity.trading_calendar",
        qualification_identities=(
            "main-qualified",
            "balance-qualified-1",
            "balance-qualified-2",
            "balance-qualified-3",
        ),
        main_request=main,
        balance_request=balance,
        main_notice_contract=_main_contract(),
        maximum_physical_attempts=2,
    )


def _run(plan: object) -> SyncRun:
    """Build one synthetic persisted-run value for application-only tests."""

    return SyncRun(
        run_id=str(uuid4()),
        dataset_key=plan.main_request.dataset_key,
        trigger="financial_e1_discovery",
        requested=len(plan.qualification_identities),
        provider_name=plan.provider_name,
        contract_version="financial-e1-discovery.v2",
        config_snapshot_hash="a" * 64,
    )


class _AllowAuthorityGuard:
    """Count exact authority rechecks without accessing SystemAudit."""

    def __init__(self) -> None:
        self.calls = 0

    def assert_current(self) -> None:
        """Allow the synthetic boundary after recording the call."""

        self.calls += 1


def _qualification(
    *,
    metric_code: str,
    source_field: str,
    endpoint: str,
) -> FinancialNumericSourceQualification:
    """Build one synthetic qualification with explicit units and capture identity."""

    contract = FinancialMetricSourceContract(
        provider=PROVIDER,
        dataset_key="equity.financial.fact",
        metric_code=metric_code,
        source_field=source_field,
        source_unit="synthetic-source-unit",
        canonical_unit="synthetic-canonical-unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="test-e1-v1",
        origin="native",
    )
    from apps.data_center.domain.financial_numeric_source_qualification import (
        FinancialNumericSourceContextRequirement,
        FinancialNumericSourceDocumentCaptureReference,
    )

    return FinancialNumericSourceQualification(
        contract=contract,
        endpoint=endpoint,
        source_applicability="synthetic-row-context-v1",
        document_capture=FinancialNumericSourceDocumentCaptureReference(
            capture_id=uuid4(),
            document_id=f"doc-{metric_code}",
            issuer="Synthetic test source",
            canonical_url="https://example.test/financial",
            body_sha256="a" * 64,
            body_size_bytes=32,
            captured_at=datetime(2026, 10, 1, tzinfo=UTC),
            content_type="text/html; charset=utf-8",
        ),
        context_requirements=(
            FinancialNumericSourceContextRequirement(
                field_name="REPORT_DATE",
                expected_value="2026-09-30 00:00:00",
            ),
        ),
        effective_from=datetime(2026, 10, 1, tzinfo=UTC),
        effective_until=None,
    )


def _balance_config() -> object:
    """Build an explicit synthetic config with no assumed classification filters."""

    return _replay_module.FinancialE1BalanceCaptureConfigV2(
        base_filter_terms=("(REPORT_SCOPE='documented-test')",),
        contract_id="akshare.stock_zcfz_em.raw.v1",
        evidence_state="static_candidate_unverified",
        endpoint_url=AKSHARE_BALANCE_API_URL,
        report_name=AKSHARE_BALANCE_REPORT_NAME,
        security_filter_key="SECURITY_CODE",
        report_date_filter_key="REPORT_DATE",
        result_key="result",
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        count_key="count",
        pages_key="pages",
        data_key="data",
        row_security_code_key="SECURITY_CODE",
        row_report_date_key="REPORT_DATE",
        row_notice_date_key="NOTICE_DATE",
    )


def _balance_qualifications() -> tuple[FinancialNumericSourceQualification, ...]:
    """Bind synthetic metrics to the exact three Balance native fields."""

    endpoint = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
    return (
        _qualification(metric_code="asset_metric", source_field="TOTAL_ASSETS", endpoint=endpoint),
        _qualification(
            metric_code="liability_metric", source_field="TOTAL_LIABILITIES", endpoint=endpoint
        ),
        _qualification(metric_code="equity_metric", source_field="TOTAL_EQUITY", endpoint=endpoint),
    )


def _retained_response(
    *,
    request: FinancialE1EndpointRequest,
    raw_body: bytes,
    request_params: dict[str, object],
    capture_id: UUID | None = None,
) -> object:
    """Build an exact typed retained response and RawAudit for pure replay tests."""

    from apps.data_center.application.financial_e1_capture_use_case import (
        FinancialE1RetainedResponse,
    )

    capture_id = capture_id or uuid4()
    body_sha = hashlib.sha256(raw_body).hexdigest()
    evidence = FinancialResponseEvidence(
        body_sha256=body_sha,
        body_size_bytes=len(raw_body),
        response_completed_at=RESPONSE_AT,
        request_scope=FinancialRequestScope(
            provider_name=PROVIDER,
            dataset_key=request.dataset_key,
            asset_code=request.request_asset_code,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(request.request_asset_code,),
            period_ends=(PERIOD,),
            row_count=1,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    reference = FinancialResponseArtifactRef(
        capture_id=capture_id,
        location=f"financial-response:///v1/{capture_id}.frb",
        evidence=evidence,
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="synthetic.e1.key",
        encryption_key_version="test-v1",
    )
    audit = RawAudit(
        provider_name=PROVIDER,
        capability="financial",
        request_params={"endpoint": request.endpoint, **request_params},
        status="ok",
        row_count=1,
        fetched_at=RESPONSE_AT,
        extra={
            "financial_response_artifact": {
                "schema": "financial-response-artifact-link.v1",
                **reference.to_dict(),
                "provider_id": 77,
            }
        },
        response_payload_hash=body_sha,
        redacted=True,
        parser_version="financial-response-artifact.v1",
        payload_size_bytes=len(raw_body),
    )
    audit = replace(
        audit,
        raw_audit_id=str(uuid4()),
        content_hash=raw_audit_content_hash(audit),
    )
    return FinancialE1RetainedResponse(
        request=request,
        retention=FinancialResponseArtifactRetention(reference=reference, audit=audit),
        raw_body=raw_body,
        provider_id=77,
        provider_payload=json.loads(raw_body, parse_float=Decimal),
        observed_attempts=1,
    )


def _main_body(notice: str = "2026-10-25 00:00:00") -> bytes:
    """Return one strict synthetic Main row with precise native numeric text."""

    return (
        '{"success":true,"code":0,"result":{"count":1,"data":[{'
        '"SECUCODE":"000858.SZ","REPORT_DATE":"2026-09-30 00:00:00",'
        f'"NOTICE_DATE":"{notice}","MAIN_RAW":123456789.1234567'
        "}]}}"
    ).encode()


def _balance_body(notice: str = "2026-10-27 00:00:00") -> bytes:
    """Return one strict synthetic Balance row, separate from Main NOTICE."""

    return (
        '{"success":true,"code":0,"result":{"count":1,"pages":1,"data":[{'
        '"SECURITY_CODE":"000858","REPORT_DATE":"2026-09-30 00:00:00",'
        f'"NOTICE_DATE":"{notice}","TOTAL_ASSETS":987654321.1234567,'
        '"TOTAL_LIABILITIES":456789.1234567,"TOTAL_EQUITY":987197532.0'
        "}]}}"
    ).encode()


def test_provider_config_decoder_rejects_missing_and_unknown_fields() -> None:
    """The versioned Balance provider subtree is required and closed to extras."""

    config = _balance_config()
    raw = {
        "schema": "financial-e1-provider-capture-config.v2",
        "balance_contract_id": config.contract_id,
        "evidence_state": config.evidence_state,
        "endpoint_url": config.endpoint_url,
        "report_name": config.report_name,
        "base_filter_terms": list(config.base_filter_terms),
        "security_filter_key": config.security_filter_key,
        "report_date_filter_key": config.report_date_filter_key,
        "result_key": config.result_key,
        "success_key": config.success_key,
        "success_value": config.success_value,
        "code_key": config.code_key,
        "success_code": config.success_code,
        "count_key": config.count_key,
        "pages_key": config.pages_key,
        "data_key": config.data_key,
        "row_security_code_key": config.row_security_code_key,
        "row_report_date_key": config.row_report_date_key,
        "row_notice_date_key": config.row_notice_date_key,
    }

    restored = _replay_module.FinancialE1BalanceCaptureConfigV2.from_provider_extra_config(
        {"financial_e1_capture_v2": raw}
    )
    assert restored == config
    with pytest.raises(ValueError):
        _replay_module.FinancialE1BalanceCaptureConfigV2.from_provider_extra_config({})
    with pytest.raises(ValueError):
        _replay_module.FinancialE1BalanceCaptureConfigV2.from_provider_extra_config(
            {"financial_e1_capture_v2": {**raw, "currency": "CNY"}}
        )


def test_balance_parser_contract_uses_only_selected_native_bindings() -> None:
    """Metric/raw field/unit labels are derived from each supplied qualification."""

    config = _balance_config()
    qualifications = _balance_qualifications()
    contract = config.build_parser_contract(qualifications)

    assert {
        (item.metric_code, item.raw_key, item.unit_code) for item in contract.value_bindings
    } == {
        (
            item.contract.metric_code,
            item.contract.source_field,
            item.contract.source_unit,
        )
        for item in qualifications
    }
    with pytest.raises(ValueError):
        config.build_parser_contract(qualifications[:2])


def test_main_role_discovers_notice_and_replays_numeric_from_one_artifact() -> None:
    """The body-derived Main NOTICE and exact Decimal replay share one capture."""

    plan = _plan()
    request = plan.main_request
    body = _main_body()
    qualification = _qualification(
        metric_code="main_metric",
        source_field="MAIN_RAW",
        endpoint=request.endpoint,
    )
    retained = _retained_response(request=request, raw_body=body, request_params={"filter": "raw"})
    replayer = _replay_module.FinancialE1DiscoveryRoleReplayer(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=_balance_config().build_parser_contract(_balance_qualifications()),
    )

    replay = replayer.replay_main(
        plan,
        retained,
        qualifications=(qualification,),
    )

    assert replay.notice_binding.notice_date == date(2026, 10, 25)
    assert replay.row.notice_date == date(2026, 10, 25)
    assert replay.notice_binding.native_row_id == replay.row.native_row_id
    assert replay.notice_binding.row_projection_sha256 == replay.row.row_projection_sha256
    assert replay.observations[0].source_value == "123456789.1234567"
    assert replay.row.artifact_reference.capture_id == retained.retention.reference.capture_id
    assert replay.source_context["MAIN_RAW"] == Decimal("123456789.1234567")


def test_balance_role_keeps_its_own_notice_and_body_bound_projection() -> None:
    """Balance values/context use their own RawAudit, row ID, hash, and NOTICE."""

    plan = _plan()
    contract = _balance_config().build_parser_contract(_balance_qualifications())
    query = build_balance_candidate_query(
        BalanceCandidateRequest(ASSET, ASSET[:6], PERIOD),
        contract,
    )
    params = dict(query.parameters)
    qualifications = _balance_qualifications()
    retained = _retained_response(
        request=plan.balance_request,
        raw_body=_balance_body(),
        request_params={**params, "endpoint": AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT},
    )
    replayer = _replay_module.FinancialE1DiscoveryRoleReplayer(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=contract,
    )

    replay = replayer.replay_balance(plan, retained, qualifications=qualifications)

    assert replay.row.notice_date == date(2026, 10, 27)
    assert replay.notice_binding is None
    assert replay.row.native_row_id.startswith("balance-row-projection.v1:")
    assert replay.source_context["SECURITY_CODE"] == "000858"
    assert len(replay.observations) == 3
    assert all(
        item.body_sha256 == retained.retention.reference.body_sha256 for item in replay.observations
    )


def test_balance_role_rejects_nested_audit_params_and_endpoint_substitution() -> None:
    """A nested request map or a different endpoint cannot pass exact replay."""

    plan = _plan()
    contract = _balance_config().build_parser_contract(_balance_qualifications())
    query = build_balance_candidate_query(
        BalanceCandidateRequest(ASSET, ASSET[:6], PERIOD),
        contract,
    )
    raw_body = _balance_body()
    nested = _retained_response(
        request=plan.balance_request,
        raw_body=raw_body,
        request_params={"params": dict(query.parameters)},
    )
    replayer = _replay_module.FinancialE1DiscoveryRoleReplayer(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=contract,
    )

    with pytest.raises(_replay_module.FinancialE1ReplayError):
        replayer.replay_balance(plan, nested, qualifications=_balance_qualifications())

    wrong_request = replace(plan.balance_request, endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT)
    wrong_endpoint_response = _retained_response(
        request=wrong_request,
        raw_body=raw_body,
        request_params={
            **dict(query.parameters),
            "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        },
    )
    with pytest.raises(_replay_module.FinancialE1ReplayError):
        replayer.replay_balance(
            plan,
            wrong_endpoint_response,
            qualifications=_balance_qualifications(),
        )


def test_discovery_use_case_blocks_before_capture_when_preflight_fails() -> None:
    """No gateway call is possible when current Owner/body preflight blocks."""

    class BrokenPreflight:
        def load_exact_current_selection(
            self, selected_plan: object, *, known_at: datetime
        ) -> object:
            del selected_plan, known_at
            raise DataValidationError("catalog selection unavailable")

    class CountingGateway:
        def __init__(self) -> None:
            self.calls = 0

        def capture_one(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            self.calls += 1
            raise AssertionError("gateway must not run before preflight")

    class NeverWriter:
        def write_and_read_back(self, *args: object, **kwargs: object) -> tuple[object, ...]:
            del args, kwargs
            raise AssertionError("writer must not run when preflight blocks")

    gateway = CountingGateway()
    clock = type("Clock", (), {"now_utc": lambda self: RESPONSE_AT})()
    guard = _AllowAuthorityGuard()
    use_case = _app_module.CaptureFinancialE1DiscoveryUseCase(
        preflight=BrokenPreflight(),
        capture_gateway=gateway,
        role_replayer=object(),
        qualification_resolver=object(),
        fact_writer=NeverWriter(),
        clock=clock,
        authority_guard=guard,
    )

    plan = _plan()
    result = use_case.execute(plan, run=_run(plan))

    assert result.outcome == "blocked"
    assert result.physical_attempts == 0
    assert result.retained_capture_ids == ()
    assert gateway.calls == 0
    assert guard.calls == 0


def test_discovery_use_case_stops_after_two_sends_when_balance_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful Main response plus Balance failure never reaches fact DML."""

    main = _qualification(
        metric_code="main_metric",
        source_field="MAIN_RAW",
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    )
    balance = _balance_qualifications()
    qualifications = (main, *balance)
    plan = replace(
        _plan(),
        qualification_identities=tuple(item.identity for item in qualifications),
    )
    cutoff = datetime(2026, 11, 16, 3, 0, tzinfo=UTC)
    entries: list[FinancialNumericCatalogEntry] = []
    for qualification in qualifications:
        entry_id = uuid4()
        recorded_at = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)
        event = FinancialNumericCatalogOwnerEvent(
            event_id=uuid4(),
            entry_id=entry_id,
            action="apply",
            qualification_identity=qualification.identity,
            qualification_sha256=qualification.content_hash,
            actor_id=7,
            actor_username="owner",
            event_at=recorded_at,
            recorded_at=recorded_at,
        )
        entries.append(
            FinancialNumericCatalogEntry(
                entry_id=entry_id,
                qualification=qualification,
                recorded_at=recorded_at,
                capture_recorded_at=recorded_at,
                owner_events=(event,),
            )
        )
    snapshot = _app_module.FinancialE1PreflightSnapshot(
        known_at=cutoff,
        entries=tuple(entries),
    )

    class Preflight:
        def load_exact_current_selection(
            self, selected_plan: object, *, known_at: datetime
        ) -> object:
            assert selected_plan == plan
            assert known_at == cutoff
            return snapshot

    class Clock:
        def now_utc(self) -> datetime:
            return cutoff

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def capture_one(
            self,
            request: FinancialE1EndpointRequest,
            *,
            request_id: UUID,
            attempt_budget: FinancialResponseAttemptBudget,
            run_id: UUID | None,
        ) -> object:
            del run_id
            self.calls.append(request.endpoint)
            assert attempt_budget.reserve()
            if request.endpoint == plan.main_request.endpoint:
                return _retained_response(
                    request=request,
                    raw_body=_main_body(),
                    request_params={"filter": "explicit-plan"},
                    capture_id=request_id,
                )
            raise DataFetchError("Balance request failed", code="BALANCE_CAPTURE_FAILED")

    class Resolver:
        def resolve_exact(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("the partial capture cannot resolve all selections")

    class Writer:
        def __init__(self) -> None:
            self.calls = 0

        def write_and_read_back(self, *args: object, **kwargs: object) -> tuple[object, ...]:
            del args, kwargs
            self.calls += 1
            raise AssertionError("partial capture must never reach the fact writer")

    role_replayer = _replay_module.FinancialE1DiscoveryRoleReplayer(
        main_notice_contract=plan.main_notice_contract,
        balance_parser_contract=_balance_config().build_parser_contract(balance),
    )
    gateway = Gateway()
    writer = Writer()
    guard = _AllowAuthorityGuard()
    use_case = _app_module.CaptureFinancialE1DiscoveryUseCase(
        preflight=Preflight(),
        capture_gateway=gateway,
        role_replayer=role_replayer,
        qualification_resolver=Resolver(),
        fact_writer=writer,
        clock=Clock(),
        authority_guard=guard,
    )

    run = _run(plan)
    result = use_case.execute(plan, run=run)

    assert result.outcome == "partial"
    assert result.requested == 4
    assert result.succeeded == 0
    assert result.failed == 4
    assert result.stored == 0
    assert result.physical_attempts == 2
    assert gateway.calls == [plan.main_request.endpoint, plan.balance_request.endpoint]
    assert guard.calls == 2
    assert len(result.retained_capture_ids) == 1
    assert writer.calls == 0

    monkeypatch.setattr(SyncRunRepository, "save", lambda self, record: record)
    terminal = finish_django_financial_e1_non_success_run(run, result, authority_guard=guard)
    assert (terminal.outcome, terminal.fetched, terminal.stored) == ("partial", 1, 0)


def test_pinned_plan_file_requires_the_independent_raw_file_digest(tmp_path: Path) -> None:
    """An externally supplied digest must match the closed plan file bytes."""

    document: dict[str, object] = {
        "schema": "financial-e1-execution-plan.v3",
        "simulated_account_id": 631,
        "provider_id": 3,
        "provider_name": PROVIDER,
        "dataset_key": "equity.financial.fact",
        "asset_code": ASSET,
        "period_end": PERIOD.isoformat(),
        "exchange": "SZ",
        "calendar_dataset_key": "equity.trading_calendar",
        "main_endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        "balance_endpoint": AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
        "qualification_identities": [f"qualified-{index}" for index in range(10)],
        "official_source_profile_pin": {
            "profile_id": "official-source-e1",
            "profile_version": "1",
            "publisher_code": "official-publisher",
            "publisher_class": "regulator",
            "profile_content_sha256": "a" * 64,
        },
    }
    path = tmp_path / "plan.json"
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()

    pinned = _execution_plan_file_module.load_pinned_financial_e1_plan(
        path,
        expected_sha256=digest,
    )

    assert pinned.simulated_account_id == 631
    assert pinned.plan_file_sha256 == digest
    assert pinned.discovery_plan.provider_id == 3
    assert pinned.discovery_plan.asset_code == ASSET
    assert pinned.discovery_plan.period_end == PERIOD
    assert len(pinned.discovery_plan.qualification_identities) == 10
    assert pinned.official_source_profile_pin.profile_id == "official-source-e1"
    assert pinned.official_source_profile_pin.profile_content_sha256 == "a" * 64
    with pytest.raises(ValueError, match="external SHA-256 pin"):
        _execution_plan_file_module.load_pinned_financial_e1_plan(
            path,
            expected_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        {"schema": "financial-e1-execution-plan.v2"},
        {"main_endpoint": "https://example.test/nearby"},
        {"unexpected": "not allowed"},
        {"period_end": "20260930"},
        {
            "official_source_profile_pin": {
                "profile_id": "official-source-e1",
                "profile_version": "1",
                "publisher_code": "official-publisher",
                "publisher_class": "regulator",
                "profile_content_sha256": "a" * 64,
                "unexpected": "not bound by the reviewed pin",
            }
        },
        {
            "official_source_profile_pin": {
                "profile_id": "official-source-e1",
                "profile_version": "1",
                "publisher_code": "official-publisher",
                "publisher_class": "regulator",
                "profile_content_sha256": "not-a-digest",
            }
        },
    ),
)
def test_pinned_plan_file_rejects_unsupported_shape_even_with_matching_hash(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    """A matching hash does not permit aliases, extra fields, or date coercion."""

    document: dict[str, object] = {
        "schema": "financial-e1-execution-plan.v3",
        "simulated_account_id": 631,
        "provider_id": 3,
        "provider_name": PROVIDER,
        "dataset_key": "equity.financial.fact",
        "asset_code": ASSET,
        "period_end": PERIOD.isoformat(),
        "exchange": "SZ",
        "calendar_dataset_key": "equity.trading_calendar",
        "main_endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        "balance_endpoint": AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
        "qualification_identities": [f"qualified-{index}" for index in range(10)],
        "official_source_profile_pin": {
            "profile_id": "official-source-e1",
            "profile_version": "1",
            "publisher_code": "official-publisher",
            "publisher_class": "regulator",
            "profile_content_sha256": "a" * 64,
        },
    }
    document.update(mutation)
    path = tmp_path / "bad-plan.json"
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(body)
    with pytest.raises(ValueError):
        _execution_plan_file_module.load_pinned_financial_e1_plan(
            path,
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )


def test_pinned_plan_file_rejects_duplicate_json_names(tmp_path: Path) -> None:
    """Duplicate request scope fields cannot be resolved by JSON parser order."""

    profile_digest = "a" * 64
    document = (
        '{"schema":"financial-e1-execution-plan.v3","simulated_account_id":631,'
        '"provider_id":3,"provider_id":4,"provider_name":"akshare",'
        '"dataset_key":"equity.financial.fact","asset_code":"000858.SZ",'
        '"period_end":"2026-09-30","exchange":"SZ",'
        '"calendar_dataset_key":"equity.trading_calendar",'
        f'"main_endpoint":"{AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT}",'
        f'"balance_endpoint":"{AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT}",'
        '"qualification_identities":["one"],'
        '"official_source_profile_pin":{"profile_id":"p","profile_version":"1",'
        '"publisher_code":"pub","publisher_class":"reg",'
        f'"profile_content_sha256":"{profile_digest}"}}'
    ).encode()
    path = tmp_path / "duplicate-plan.json"
    path.write_bytes(document)

    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        _execution_plan_file_module.load_pinned_financial_e1_plan(
            path,
            expected_sha256=hashlib.sha256(document).hexdigest(),
        )
