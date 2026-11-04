"""Opt-in isolated Owner GET for the real 510050 partial look-through case.

Set ``AGOM_RUN_ASH07_REAL_SOURCE_ETF_PARTIAL_ACCEPTANCE=1`` only when the
current-date bank candidate, separately captured 510050 quote and explicit ETF
identity/policy context are available. The identity row below is a local test
fixture read from Root's exact crosswalk, never derived from a ticker prefix.
Close policy and rule rows are the same test-only simulation fixtures as the
bank-only Owner test; they are not official market restrictions or execution
authorization. The test creates one new simulated account in a transaction,
does a public owner-scoped risk GET, and does not place, preview, or settle an
order.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_runtime_profile,
)
from apps.config_center.domain.runtime_config import RuntimeProfileStatus
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceMappingUseCase,
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.interface_services import save_provider_settings_payload
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceSnapshotContent,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    TushareInstrumentReferenceSource,
    TushareStockBasicClientPort,
)
from apps.risk_center.domain.portfolio_exposure_types import PortfolioAssetKind
from apps.risk_center.domain.portfolio_risk_snapshot import exact_decimal_product
from apps.risk_center.source_admission_composition import (
    build_portfolio_risk_source_admission_use_case,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_identity_reader,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    FIELDS as _REFERENCE_FIELDS,
)
from tests.component.simulated_trading import test_auto_trading_current_reference_t1 as auto_fixture
from tests.component.simulated_trading import test_owner_real_public_risk_sources as bank_case
from tests.support import ash07_public_risk_sources as admission_builder
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_native_runtime_role import isolated_ash07_runtime_role
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    create_owner_account_seed,
)
from tests.support.ash07_owner_etf_partial_case import (
    add_isolated_etf_position,
    assert_public_etf_partial_risk_report,
    build_q3_report_admission_request,
    build_supplemental_etf_quote_admission_requests,
    load_q3_report_facts,
    load_supplemental_sina_capture,
)
from tests.support.ash07_owner_risk_policy_binding import bind_audited_balanced_v2_policy
from tests.support.ash07_owner_session import (
    create_simulated_account_for_approved_owner,
    ordinary_owner_session_client,
)
from tests.support.ash07_real_calendar_publication import publish_real_calendar_for_acceptance
from tests.support.runtime_config import configure_critical_runtime
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_RISK_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"
_CURRENT_REFERENCE_SELECTION_KEY = "config_center.market.simulated_current_reference_selection"
_CLOSE_POLICIES_KEY = "config_center.market.simulated_sina_close_snapshot_policies"
_ETF_ASSET_CODE = "510050.SH"
_REPORT_KIND = "etf_report"
_DISCLOSED_REPORT_MODE = "policy_bounded_disclosed_report"
_CTX_SCHEMA = "ash07.owner-etf-partial-test-context.v1"


def _required_path(name: str, *, root: Path) -> Path:
    """Read one explicit external input path and refuse implicit fallbacks."""

    raw_path = os.environ.get(name, "")
    if not raw_path or raw_path.strip() != raw_path:
        raise AssertionError(f"set {name} to the exact retained input file")
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise AssertionError(f"the required opt-in input is absent: {path}")
    return path.resolve()


def _load_context(*, root: Path, business_date: date) -> dict[str, Any]:
    """Load the owner-supplied exact ETF crosswalk and source-policy facts."""

    path = _required_path("ASH07_REAL_ETF_PARTIAL_CONTEXT_PATH", root=root)
    expected_hash = os.environ.get("ASH07_REAL_ETF_PARTIAL_CONTEXT_SHA256", "")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        raise AssertionError("ETF crosswalk/context SHA-256 is missing or differs")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(value) is not dict or value.get("schema") != _CTX_SCHEMA:
        raise AssertionError("ETF partial context has the wrong exact schema")
    context = cast(dict[str, Any], value)
    if context.get("business_date") != business_date.isoformat():
        raise AssertionError("ETF crosswalk is not bound to the bank candidate business date")
    identity = _mapping(context.get("identity_crosswalk"), "identity_crosswalk")
    expected_identity = {
        "asset_code": _ETF_ASSET_CODE,
        "ts_code": _ETF_ASSET_CODE,
        "source_exchange": "SSE",
        "source_list_status": "L",
        "exchange_suffix": "SH",
    }
    for key, expected in expected_identity.items():
        if identity.get(key) != expected:
            raise AssertionError(f"ETF explicit identity crosswalk must provide {key}={expected}")
    for key in (
        "security_id",
        "source_name",
        "source_market",
        "rule_market",
        "board",
    ):
        _token(identity.get(key), f"identity_crosswalk.{key}")
    for key in ("source_list_date_raw", "source_delist_date_raw"):
        if key not in identity or not _optional_provider_date(identity[key]):
            raise AssertionError(f"identity_crosswalk.{key} must preserve its exact source value")
    if identity["source_market"] == "fixture-main":
        raise AssertionError("ETF local source-market key must be distinct from bank fixture rows")
    policy = _mapping(context.get("etf_report_policy"), "etf_report_policy")
    _token(policy.get("source_id"), "etf_report_policy.source_id")
    _token(policy.get("source_purpose"), "etf_report_policy.source_purpose")
    allowed = _string_list(policy.get("allowed_purposes"), "allowed_purposes")
    restrictions = _string_list(policy.get("restrictions"), "restrictions")
    if not allowed:
        raise AssertionError("ETF report must retain explicit permitted consumer purposes")
    if any(
        token.startswith("must_not_") or token in {"research_only", "observation_only"}
        for token in restrictions
    ):
        raise AssertionError("ETF source restrictions prohibit decision use and cannot be waived")
    quantity = _decimal(policy.get("test_position_quantity"), "test_position_quantity")
    if quantity <= 0:
        raise AssertionError("test-only ETF position quantity must be explicitly positive")
    return context


def _report_facts_reference(
    *,
    context: dict[str, Any],
    root: Path,
) -> tuple[Path, str]:
    """Resolve the facts path and digest carried by the SHA-bound test context."""

    reference = _mapping(context.get("report_facts"), "report_facts")
    path_text = _token(reference.get("path"), "report_facts.path")
    expected_sha256 = _token(reference.get("sha256"), "report_facts.sha256")
    path = Path(path_text)
    resolved_path = path if path.is_absolute() else root / path
    resolved_path = resolved_path.resolve()
    if not resolved_path.is_file():
        raise AssertionError("the SHA-bound report facts file is unavailable")
    return resolved_path, expected_sha256


def _load_audited_policy_seed(*, root: Path) -> dict[str, Any]:
    """Read balanced-v2 policy values only from the operator-selected JSON."""

    path = _required_path("ASH07_REAL_RISK_POLICY_V2_PATH", root=root)
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        type(document) is not dict
        or document.get("profile_key") != "risk_center.simulated_portfolio_risk.draft.balanced"
        or document.get("version") != 2
    ):
        raise AssertionError("selected values are not the audited balanced-v2 Risk draft")
    values = document.get("values")
    if type(values) is not list or len(values) != 1 or type(values[0]) is not dict:
        raise AssertionError("balanced-v2 input must contain exactly one Risk value")
    entry = cast(dict[str, Any], values[0])
    if entry.get("definition_key") != _RISK_DEFINITION_KEY:
        raise AssertionError("balanced-v2 value is bound to a different runtime key")
    policy = entry.get("value_json")
    if type(policy) is not dict:
        raise AssertionError("balanced-v2 Risk value is malformed")
    industry = policy.get("industry")
    etf_report = policy.get("etf_report")
    if type(industry) is not dict or type(etf_report) is not dict:
        raise AssertionError("balanced-v2 policy is missing industry or ETF report rules")
    if (
        etf_report.get("age_basis") != "report_period_end"
        or type(etf_report.get("max_report_age_days")) is not int
        or etf_report.get("max_report_age_days", 0) < 1
    ):
        raise AssertionError("balanced-v2 ETF report-age policy is not explicit")
    return cast(dict[str, Any], policy)


class _BankPlusETFStockBasicSession(_Session):
    """Return the existing bank fixture plus only Root's exact ETF crosswalk row."""

    def __init__(self, response: _Response, *, identity: dict[str, Any]) -> None:
        """Bind one externally selected ETF identity to the local test response."""

        super().__init__(response)
        self._identity = identity

    def post(self, url: str, **kwargs: object) -> _Response:
        """Add the exact external ETF row without making a network call."""

        response = super().post(url, **kwargs)
        request = kwargs.get("json")
        assert isinstance(request, dict)
        params = request.get("params")
        assert isinstance(params, dict)
        if params.get("list_status") != "L":
            return response
        payload = json.loads(response.body.decode("utf-8"))
        rows = payload["data"]["items"]
        rows.append(
            [
                self._identity["ts_code"],
                self._identity["source_name"],
                self._identity["source_exchange"],
                self._identity["source_market"],
                self._identity["source_list_status"],
                self._identity["source_list_date_raw"],
                self._identity["source_delist_date_raw"],
            ]
        )
        self.response = _Response(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        return cast(_Response, self.response)


def _persisted_reference_snapshot_with_etf(
    *,
    monkeypatch: pytest.MonkeyPatch,
    identity: dict[str, Any],
) -> tuple[Any, Any]:
    """Publish exact local identity rows through the existing DataCenter use cases."""

    session = _BankPlusETFStockBasicSession(_Response(b"{}"), identity=identity)
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    payloads = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payloads)
    dataset_key = "fixture.ash07.owner-etf-current-reference"
    client = tushare_client.create_tushare_pro_client(
        token="ash07-test-only-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.ash07.owner-etf-current-reference",
        contract_version="test-only-exact-crosswalk",
        provider_name="tushare",
        dataset_key=dataset_key,
        api_name="stock_basic",
        fields=_REFERENCE_FIELDS,
        exchange_scope=(identity["source_exchange"],),
        list_status_scope=("L", "D"),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.ash07.owner-etf-crosswalk",
        crosswalk_version="test-only-explicit-input",
        exchange_suffix_pairs=((identity["source_exchange"], identity["exchange_suffix"]),),
    )
    audits = RawAuditRepository()
    source = TushareInstrumentReferenceSource(
        cast(TushareStockBasicClientPort, client),
        payloads,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(audits),
        provider_contract=contract,
        exchange_suffix_crosswalk=crosswalk,
    )
    candidate = source.fetch_candidate(run_id=uuid4(), ingested_run_id=uuid4())
    repository = DjangoInstrumentReferenceSnapshotRepository(
        cast(RawAuditRepositoryProtocol, audits),
        payloads,
        clock=lambda: timezone.now().astimezone(UTC),
    )
    board_mappings = (
        ("SSE", "fixture-main", "MAIN"),
        (
            identity["source_exchange"],
            identity["source_market"],
            identity["board"],
        ),
    )
    if len({(exchange, market) for exchange, market, _board in board_mappings}) != 2:
        raise AssertionError("ETF crosswalk conflicts with the existing bank fixture mapping")
    mapping = InstrumentReferenceMappingContent(
        mapping_id=f"fixture.ash07.owner-etf-map-{uuid4().hex[:12]}",
        mapping_version="test-only-explicit-crosswalk",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=((identity["source_exchange"], identity["rule_market"]),),
        exchange_source_market_board_pairs=board_mappings,
    )
    mapping_record = SaveInstrumentReferenceMappingUseCase(repository).execute(mapping)
    content = InstrumentReferenceSnapshotContent(
        run_id=uuid4(),
        mapping_record=mapping_record,
        fetch_rounds=(InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidate),),
    )
    snapshot = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    for asset_code in ("600036.SH", "601398.SH", identity["asset_code"]):
        classification = snapshot.content.classify_security(asset_code)
        if classification is None or classification.blocked_reason is not None:
            raise AssertionError(f"explicit test identity mapping is unavailable: {asset_code}")
        if classification.source_exchange != identity["source_exchange"]:
            raise AssertionError(f"identity exchange differs for {asset_code}")
        if classification.rule_market is None or classification.board is None:
            raise AssertionError(f"explicit market/board mapping is missing for {asset_code}")
    etf_classification = snapshot.content.classify_security(identity["ts_code"])
    if (
        etf_classification is None
        or etf_classification.rule_market != identity["rule_market"]
        or etf_classification.board != identity["board"]
    ):
        raise AssertionError("Root ETF crosswalk and exact published local mapping differ")
    return repository, snapshot


def _current_reference_items_with_etf(
    snapshot: Any, identity: dict[str, Any]
) -> list[dict[str, str]]:
    """Extend the main bank selector with Root's exact ETF identity pair."""

    result = bank_case._current_reference_items(snapshot)
    result.append(
        {
            "security_id": identity["security_id"],
            "asset_code": identity["asset_code"],
            "source_code": identity["ts_code"],
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_content_hash": snapshot.content_hash,
            "snapshot_record_digest": snapshot.record_digest,
            "mapping_record_id": str(snapshot.mapping_record.mapping_record_id),
            "mapping_id": snapshot.mapping_record.content.mapping_id,
            "mapping_version": snapshot.mapping_record.content.mapping_version,
            "mapping_content_hash": snapshot.mapping_record.content_hash,
            "mapping_record_digest": snapshot.mapping_record.record_digest,
        }
    )
    return result


def _quote_evidence_templates(
    candidate: dict[str, Any],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """Reuse the current bank candidate's Sina purpose/restriction contract."""

    quote = candidate["sina_quotes"][0]
    close_state = quote.get("close_state_candidate")
    if type(close_state) is not dict:
        raise AssertionError("Sina close-state candidate must be explicit")
    templates: dict[str, dict[str, object]] = {}
    for kind in ("valuation", "capacity_window"):
        template_key = (
            "capacity_source_evidence_template"
            if kind == "capacity_window"
            else f"{kind}_source_evidence_template"
        )
        value = quote.get(template_key)
        if type(value) is not dict:
            raise AssertionError(f"current candidate lacks its {kind} source-evidence template")
        templates[kind] = cast(dict[str, object], value)
    templates["execution_session_state"] = {
        "source_purpose": close_state["purpose"],
        "allowed_purposes": [close_state["purpose"]],
        "restrictions": close_state["restrictions"],
        "must_not_use_for_decision": False,
        "coverage": {
            "status": "complete",
            "precision_basis": "one_security_quote_response",
            "expected_item_count": 1,
            "observed_item_count": 1,
        },
    }
    capacity = quote.get("capacity_facts")
    if type(capacity) is not dict:
        raise AssertionError(
            "current bank candidate must provide the exact cumulative capacity template"
        )
    return templates, cast(dict[str, object], capacity)


def _admit_requests(
    requests: tuple[Any, ...],
) -> dict[tuple[str, str, str, str], str]:
    """Persist each exact original through the existing admission use case."""

    use_case = build_portfolio_risk_source_admission_use_case()
    hashes: dict[tuple[str, str, str, str], str] = {}
    for request in requests:
        receipt = request.capture_receipt
        if receipt is None or not request.original_body or request.original_url is None:
            raise AssertionError("every source needs its retained bytes, URL and receipt")
        body_hash = hashlib.sha256(request.original_body).hexdigest()
        if request.source_evidence.original_payload_sha256 != body_hash:
            raise AssertionError("admission request differs from its retained vendor body")
        result = use_case.execute(request, persist=True)
        if not result.stored or result.payload.fetched_at != receipt.response_completed_at:
            raise AssertionError("RawPayload did not keep the real response receipt clock")
        if result.payload.payload_hash == f"sha256:{body_hash}":
            raise AssertionError("local manifest hash must differ from original vendor-body hash")
        key = (request.kind, request.asset_code, request.security_id, request.source_record_id)
        if key in hashes:
            raise AssertionError("source admission contains a duplicate exact identity")
        hashes[key] = result.payload.payload_hash
    return hashes


def _source_clock_mode(kind: str) -> str:
    """Select the already defined per-kind proof mode, including ETF report DATE."""

    if kind == _REPORT_KIND:
        return _DISCLOSED_REPORT_MODE
    return bank_case._source_reference_clock_mode(kind)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TypeError(f"{label} must be an exact JSON object")
    return cast(dict[str, Any], value)


def _token(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact nonempty token")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError(f"{label} must be a list of strings")
    return cast(list[str], value)


def _decimal(value: object, label: str) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{label} must be exact decimal text")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _optional_provider_date(value: object) -> bool:
    """Accept only a retained YYYYMMDD date, null or empty provider field."""

    if value is None or value == "":
        return True
    if type(value) is not str or len(value) != 8 or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


@pytest.fixture(name="runtime_role")
def _ash07_runtime_role(
    transactional_db: None,
    tmp_path: Path,
) -> Iterator[dict[str, object]]:
    """Restore the test DB runtime identity before transactional cleanup."""

    del transactional_db
    with isolated_ash07_runtime_role(tmp_path / "runtime-role") as report:
        yield report


@pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_ASH07_REAL_SOURCE_ETF_PARTIAL_ACCEPTANCE") != "1",
    reason="opt in only after Root supplies current source captures and exact ETF context",
)
@override_settings(ROOT_URLCONF="tests.support.ash07_owner_acceptance_test_urls")
def test_owner_get_real_q3_etf_partial_source_report(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    runtime_role: dict[str, object],
) -> None:
    """Show real Q3 overlaps and conservative residuals in a new simulated account."""

    bank_case._assert_native_test_database()
    if runtime_role.get("runtime_acl_verified") is not True:
        raise AssertionError("the isolated runtime role was not verified")

    root = bank_case._REPOSITORY_ROOT
    candidate_path = bank_case._candidate_path()
    candidate = bank_case._load_candidate(candidate_path)
    business_date = date.fromisoformat(candidate["business_date"])
    context = _load_context(root=root, business_date=business_date)
    identity = _mapping(context.get("identity_crosswalk"), "identity_crosswalk")
    report_policy = _mapping(context.get("etf_report_policy"), "etf_report_policy")
    balanced_v2 = _load_audited_policy_seed(root=root)
    industry_policy = _mapping(balanced_v2.get("industry"), "balanced_v2.industry")
    report_basis = _token(
        industry_policy.get("coverage_precision_basis"),
        "balanced_v2.industry.coverage_precision_basis",
    )
    if report_policy.get("coverage_precision_basis") != report_basis:
        raise AssertionError("ETF report facts do not use the selected balanced-v2 coverage basis")

    bank_requests = admission_builder.build_real_source_admission_requests(candidate_path)
    if len(bank_requests) != 8:
        raise AssertionError("the retained two-bank case must still provide its eight source refs")
    bank_industry_requests = tuple(
        item for item in bank_requests if item.kind == "industry_membership"
    )
    if len(bank_industry_requests) != 2:
        raise AssertionError("two same-day typed bank memberships are required for overlaps")

    supplemental = load_supplemental_sina_capture(
        supplemental_manifest_path=candidate_path.parent / "supplemental-quotes.json",
        repository_root=root,
        expected_provider_asset_code="510050.SH",
        source_id=candidate["sina_quotes"][0]["source_id"],
        source_record_namespace="sina-public-quote",
        business_date=business_date,
    )
    templates, capacity_template = _quote_evidence_templates(candidate)
    unit_mapping = admission_builder.verify_source_unit_mapping(candidate)
    if (
        unit_mapping["canonical_quantity_unit"] != "share"
        or unit_mapping["canonical_money_unit"] != "CNY"
        or unit_mapping["numeric_scale"] != "1"
    ):
        raise AssertionError(
            "current Sina unit mapping differs from the existing canonical contract"
        )
    etf_quote_requests = build_supplemental_etf_quote_admission_requests(
        retained_capture=supplemental,
        asset_code=identity["asset_code"],
        security_id=identity["security_id"],
        asset_kind=PortfolioAssetKind.ETF,
        quantity_unit=str(unit_mapping["canonical_quantity_unit"]),
        price_unit=str(unit_mapping["canonical_money_unit"]),
        source_evidence_templates=templates,
        capacity_window_template=capacity_template,
    )
    facts_path, expected_facts_sha256 = _report_facts_reference(context=context, root=root)
    facts = load_q3_report_facts(
        facts_path=facts_path,
        expected_facts_sha256=expected_facts_sha256,
        repository_root=root,
    )
    source_code_to_asset_code = {
        item["sse_company_code"]: item["asset_code"]
        for item in candidate["identity_resolution"]["records"]
    }
    report_request = build_q3_report_admission_request(
        facts=facts,
        repository_root=root,
        asset_code=identity["asset_code"],
        security_id=identity["security_id"],
        source_id=_token(report_policy.get("source_id"), "ETF report source id"),
        source_purpose=_token(report_policy.get("source_purpose"), "ETF report purpose"),
        allowed_purposes=tuple(_string_list(report_policy.get("allowed_purposes"), "allowed")),
        restrictions=tuple(_string_list(report_policy.get("restrictions"), "restrictions")),
        coverage_precision_basis=report_basis,
        business_date=business_date,
        same_day_bank_industry_requests=bank_industry_requests,
        source_code_to_asset_code=source_code_to_asset_code,
    )
    requests = (*bank_requests, *etf_quote_requests, report_request)
    if len(requests) != 12:
        raise AssertionError("expected 8 bank refs and 4 ETF refs in the new successor")

    configure_critical_runtime()
    provider_settings = save_provider_settings_payload(
        default_source="tushare",
        enable_failover=False,
        failover_tolerance=0.01,
        actor="ash07-owner-etf-partial-test",
    )
    if (
        provider_settings.get("status") != "active"
        or provider_settings.get("default_source") != "tushare"
        or provider_settings.get("enable_failover") is not False
        or provider_settings.get("failover_tolerance") != 0.01
    ):
        raise AssertionError("provider-backed close readers need explicit Tushare runtime settings")
    publisher_seed = create_owner_account_seed()
    approver_profile = AccountProfileModel.objects.get(user_id=publisher_seed.owner.pk)
    if (
        not publisher_seed.owner.is_staff
        or publisher_seed.owner.is_superuser
        or approver_profile.rbac_role != "admin"
        or publisher_seed.account.user_id != publisher_seed.owner.pk
    ):
        raise AssertionError("ETF test approver must remain a separate staff/admin identity")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    from tests.component.data_center.test_calendar_workbench_tui_browser import (
        _create_browser_regular_user as create_approved_regular_user,
    )

    # The existing fixture records an approved isolated test profile, not real human approval.
    ordinary_owner = create_approved_regular_user(approved_by=publisher_seed.owner)
    account = create_simulated_account_for_approved_owner(ordinary_owner)
    account_id = cast(int, account.pk)
    owner_id = cast(int, account.user_id)
    owner_profile = AccountProfileModel.objects.get(user_id=owner_id)
    if (
        account.user_id != ordinary_owner.pk
        or account.user.is_staff
        or account.user.is_superuser
        or owner_profile.rbac_role != "owner"
        or owner_profile.approval_status != "approved"
        or not owner_profile.user_agreement_accepted
        or not owner_profile.risk_warning_acknowledged
        or owner_profile.approved_by_id != publisher_seed.owner.pk
        or publisher_seed.owner.pk == owner_id
        or not publisher_seed.owner.is_staff
        or publisher_seed.owner.is_superuser
    ):
        raise AssertionError("ETF Risk account must use a separately approved ordinary test Owner")
    bank_case._seed_baseline(account_id)
    raw_payload_hashes = _admit_requests(requests)

    names: dict[str, str] = {}
    for bank_identity in candidate["identity_resolution"]["records"]:
        source_path = Path(bank_identity["sse_record_path"])
        if not source_path.is_absolute():
            source_path = root / source_path
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != bank_identity["sse_record_sha256"]:
            raise AssertionError("retained SSE bank identity bytes differ from their source hash")
        source_document = json.loads(source_bytes.decode("utf-8-sig"))
        rows = source_document.get("result")
        if type(rows) is not list or len(rows) != 1:
            raise AssertionError("SSE bank identity source row is not unique")
        names[bank_identity["asset_code"]] = rows[0]["COMPANY_ABBR"]
    positions = bank_case._seed_positions(
        account,
        candidate=candidate,
        names=names,
        business_date=business_date,
    )
    if len(positions) != 2:
        raise AssertionError("the two bank direct holdings must remain present for ETF overlap")
    quantity = _decimal(report_policy.get("test_position_quantity"), "test_position_quantity")
    quote = supplemental.capture.quote
    if quote is None or quote.last_price is None:
        raise AssertionError("the exact supplemental 510050 quote has no current price")
    etf_position = add_isolated_etf_position(
        account=account,
        asset_code=identity["asset_code"],
        asset_name=_token(identity.get("display_name"), "ETF display_name"),
        quantity=quantity,
        price=quote.last_price,
        business_date=business_date,
        first_buy_date=business_date,
    )
    position_snapshot = PositionModel.objects.filter(account=account).order_by("asset_code")
    if position_snapshot.count() != 3 or etf_position.asset_type != "fund":
        raise AssertionError("test account must contain two banks and one typed ETF holding")
    ledger_before = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        tuple(
            (position.asset_code, position.quantity, position.available_quantity)
            for position in position_snapshot
        ),
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
    )

    _repository, source_snapshot = _persisted_reference_snapshot_with_etf(
        monkeypatch=monkeypatch,
        identity=identity,
    )
    calendar_lease = publish_real_calendar_for_acceptance(
        business_date=business_date,
        coverage_start=business_date - timedelta(days=7),
        coverage_end=business_date + timedelta(days=14),
    )
    request.addfinalizer(calendar_lease.close)
    if calendar_lease.market_session != business_date:
        raise AssertionError("published SSE calendar session differs from the actual source date")
    selector = {
        "schema": "normal-simulated-current-reference-selection.v1",
        "purpose": "normal_simulated_current_reference",
        "max_local_reference_age_seconds": 600,
        "items": _current_reference_items_with_etf(source_snapshot, identity),
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={_CURRENT_REFERENCE_SELECTION_KEY: selector},
        actor="ash07-owner-etf-partial-test",
        reason="bind bank sources and Root's exact 510050 identity crosswalk for isolated report GET",
    )
    identity_reader = build_current_reference_identity_reader(runtime_environment="development")
    rule_market_by_asset: dict[str, str] = {}
    board_by_asset: dict[str, str] = {}
    for asset_code, security_id in (
        (item["asset_code"], item["security_id"])
        for item in (
            *candidate["identity_resolution"]["records"],
            identity,
        )
    ):
        current_identity = identity_reader.resolve_current_reference_identity(
            asset_code=asset_code,
            as_of=timezone.now().astimezone(UTC),
        )
        if (
            current_identity is None
            or current_identity.asset_code != asset_code
            or current_identity.security_id != security_id
            or current_identity.source_exchange != "SSE"
        ):
            raise AssertionError(
                f"public CurrentReference did not resolve the exact pair: {asset_code}"
            )
        classification = source_snapshot.content.classify_security(asset_code)
        if classification is None or classification.blocked_reason is not None:
            raise AssertionError(
                f"explicit source-market classification is unavailable: {asset_code}"
            )
        if classification.rule_market is None or classification.board is None:
            raise AssertionError(f"exact Rule market/board is missing for {asset_code}")
        rule_market_by_asset[asset_code] = classification.rule_market
        board_by_asset[asset_code] = classification.board
        monkeypatch.setattr(auto_fixture, "AS_OF", timezone.now().astimezone(UTC))
        monkeypatch.setattr(
            auto_fixture,
            "KNOWLEDGE_AT",
            timezone.now().astimezone(UTC) - timedelta(seconds=1),
        )
        # This is the existing isolated-test Rule fixture only. It is not an
        # official limit source and no order or execution is attempted here.
        auto_fixture._seed_rule_bundle(
            security_id=security_id,
            market=classification.rule_market,
            board=classification.board,
        )

    etf_quote_row = {
        "provider_asset_code": supplemental.provider_asset_code,
        "risk_asset_code": identity["asset_code"],
        "security_id": identity["security_id"],
        "source_id": supplemental.receipt.source_id,
        "response_completed_at": supplemental.receipt.response_completed_at.isoformat(),
    }
    close_candidate = {**candidate, "sina_quotes": [*candidate["sina_quotes"], etf_quote_row]}
    close_policies = bank_case._close_policy_payloads(
        candidate=close_candidate,
        account_id=account_id,
        rule_market_by_asset=rule_market_by_asset,
        board_by_asset=board_by_asset,
    )
    source_references: list[dict[str, object]] = []
    for source_request in requests:
        key = (
            source_request.kind,
            source_request.asset_code,
            source_request.security_id,
            source_request.source_record_id,
        )
        source_references.append(
            {
                "kind": source_request.kind,
                "asset_code": source_request.asset_code,
                "security_id": source_request.security_id,
                "raw_payload_hash": raw_payload_hashes[key],
                "source_record_id": source_request.source_record_id,
                "clock_evidence_mode": _source_clock_mode(source_request.kind),
            }
        )
    risk_policy = bind_audited_balanced_v2_policy(
        account_id=account_id,
        source_references=source_references,
        admitted_requests=requests,
        admitted_manifest_hashes=raw_payload_hashes,
        repository_root=root,
        unit_mapping=unit_mapping,
    )
    if risk_policy["industry"]["coverage_precision_basis"] != report_basis:
        raise AssertionError("bound Risk profile changed the selected balanced-v2 coverage basis")
    if risk_policy.get("account_ids") != [account_id]:
        raise AssertionError("ETF Risk v2 policy is not bound to this ordinary Owner account")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            _RISK_DEFINITION_KEY: risk_policy,
            _CLOSE_POLICIES_KEY: {"policies": close_policies},
        },
        actor="ash07-owner-etf-partial-test",
        reason=(
            "successor of audited balanced v2 bound to exact bank and ETF captures; "
            "all other active profile values are retained"
        ),
    )

    active_profile = get_active_runtime_profile("development")
    if active_profile is None or active_profile.status is not RuntimeProfileStatus.ACTIVE:
        raise AssertionError("ETF Owner flow must read the actual active ConfigCenter profile")
    client, csrf_token = ordinary_owner_session_client(owner_id)
    assert csrf_token
    assert client.cookies.get(settings.CSRF_COOKIE_NAME) is not None
    report_url = reverse(
        "api_simulated_trading:portfolio-risk-report",
        kwargs={"account_id": account_id},
    )
    response = client.get(report_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert response.status_code == 200, response.content
    report = response.json()
    assert report["account_id"] == account_id
    assert report["scope"] == "simulation_only"
    assert report["must_not_execute"] is True
    assert report["outcome"] == "blocked"
    assert len(report["sources"]) == 12
    input_scope = next(item for item in report["checks"] if item["dimension"] == "input_scope")
    assert input_scope["details"]["policy_profile_key"] == active_profile.profile_key
    assert input_scope["details"]["policy_profile_version"] == active_profile.version
    assert input_scope["details"]["policy_profile_content_hash"] == active_profile.content_hash
    reference_fields = (
        "kind",
        "asset_code",
        "security_id",
        "source_record_id",
        "raw_payload_hash",
    )
    configured_pins = {
        tuple(reference[field] for field in reference_fields) for reference in source_references
    }
    reported_pins = {
        (
            binding["kind"],
            binding["asset_code"],
            binding["security_id"],
            binding["source_record_id"],
            binding["manifest_sha256"],
        )
        for binding in input_scope["details"]["source_reference_bindings"]
    }
    assert reported_pins == configured_pins
    reference_hashes = {
        item["manifest_sha256"] for item in input_scope["details"]["source_reference_bindings"]
    }
    assert reference_hashes == set(raw_payload_hashes.values())
    report_source = next(
        item
        for item in report["sources"]
        if item["source_record_id"] == report_request.source_record_id
    )
    assert report_source["observed_on"] == facts.publication_on.isoformat()
    assert report_source["available_at"] is None
    assert report_source["valid_until"] is None

    exact_etf_value = exact_decimal_product(quote.last_price, quantity)
    direct_values = {
        position.asset_code: exact_decimal_product(position.current_price, position.quantity)
        for position in positions
        if position.current_price is not None
    }
    assert_public_etf_partial_risk_report(
        report,
        etf_asset_code=identity["asset_code"],
        etf_market_value=exact_etf_value,
        minimum_lookthrough_coverage=Decimal(
            str(risk_policy["industry"]["minimum_etf_lookthrough_coverage"])
        ),
        facts=facts,
        source_code_to_asset_code=source_code_to_asset_code,
        direct_holding_market_values=direct_values,
    )

    account.refresh_from_db()
    final_positions = PositionModel.objects.filter(account=account).order_by("asset_code")
    for position in final_positions:
        position.refresh_from_db()
    ledger_after = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        tuple(
            (position.asset_code, position.quantity, position.available_quantity)
            for position in final_positions
        ),
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
    )
    assert ledger_after == ledger_before
