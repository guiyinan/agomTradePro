"""Opt-in Native PostgreSQL Owner TUI flow over retained public risk sources.

The risk inputs must be independently captured after the market close for the
current Shanghai business date and admitted through the real RawPayload path.
Scenario historical returns, local stock-reference rows, the published
calendar fixture, holdings, and baseline rows are isolated test fixtures; the
industry, valuation, capacity, and close-quote bytes must remain retained public
sources. This test never turns the older 2026-11-03 evidence into a current
source and never writes to a developer/default ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_runtime_profile,
)
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceMappingUseCase,
    SaveInstrumentReferenceSnapshotUseCase,
)
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
from apps.risk_center import portfolio_risk_composition as risk_composition
from apps.risk_center.domain.close_snapshot_simulation import CloseSnapshotSimulationPolicy
from apps.risk_center.domain.execution_trading_constraints import PriceBoundaryMode
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskTemplateModel,
    ScenarioRunEvidenceModel,
    StressScenarioRevisionModel,
)
from apps.risk_center.source_admission_composition import (
    build_portfolio_risk_source_admission_use_case,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_identity_reader,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    FIELDS as _REFERENCE_FIELDS,
)
from tests.component.simulated_trading import test_auto_trading_current_reference_t1 as auto_fixture
from tests.component.simulated_trading import test_owner_order_submission_tui_browser as tui_flow
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _owner_session_client,
)
from tests.support import ash07_public_risk_sources as admission_builder
from tests.support.ash03_auto_calendar_fixture import persist_auto_uow_formal_calendar
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(transaction=True)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RISK_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"
_CURRENT_REFERENCE_SELECTION_KEY = "config_center.market.simulated_current_reference_selection"
_EXCHANGE_TIMEZONE_MAP_KEY = "config_center.market.exchange_timezone_map"
_CLOSE_POLICIES_KEY = "config_center.market.simulated_sina_close_snapshot_policies"
_CAPACITY_PURPOSE = "close_snapshot_simulation"
_INDUSTRY_PURPOSE = "simulation_portfolio_risk_industry_exposure"
_CAPACITY_MODE = "policy_bounded_timestamp_snapshot"
_INDUSTRY_MODE = "policy_bounded_date_snapshot"
_VALUATION_MODE = "policy_bounded_timestamp_snapshot"
_SESSION_MODE = "policy_bounded_close_snapshot_state"


def _repository_root() -> Path:
    """Find the checkout root for either this overlay or its formal test copy."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "manage.py").is_file() and (parent / "apps").is_dir():
            return parent
    raise AssertionError("repository root could not be resolved from the acceptance test")


_REPOSITORY_ROOT = _repository_root()
_RETAINED_2026_11_03_CANDIDATE = (
    _REPOSITORY_ROOT
    / ".tmp"
    / "ash07-risk-20261103"
    / "a-real-source-e2e"
    / "real-source-owner-risk-candidate.json"
)


class _TwoBankStockBasicSession(_Session):
    """Return fixture-owned exact stock-basic rows for two SSE listings."""

    def post(self, url: str, **kwargs: object) -> _Response:
        """Capture stock-basic calls without performing any network request."""

        del url
        self.calls.append(kwargs)
        request = kwargs.get("json")
        assert isinstance(request, dict)
        params = request.get("params")
        assert isinstance(params, dict)
        rows: list[list[object]] = []
        if params.get("list_status") == "L":
            rows = [
                ["600036.SH", "招商银行", "SSE", "fixture-main", "L", "20020409", ""],
                ["601398.SH", "工商银行", "SSE", "fixture-main", "L", "20061027", ""],
            ]
        body = json.dumps(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": list(_REFERENCE_FIELDS), "items": rows},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.response = _Response(body)
        return cast(_Response, self.response)


def _candidate_path() -> Path:
    """Resolve a root-supplied current-date candidate without inventing a source."""

    configured = os.environ.get("ASH07_REAL_SOURCE_CANDIDATE_PATH", "").strip()
    if not configured:
        raise AssertionError(
            "set ASH07_REAL_SOURCE_CANDIDATE_PATH to Root's retained same-day candidate"
        )
    path = Path(configured)
    return path if path.is_absolute() else _REPOSITORY_ROOT / path


def _evidence_root(candidate_path: Path) -> Path:
    """Resolve the operator-supplied retained source-artifact directory."""

    configured = os.environ.get("ASH07_REAL_SOURCE_EVIDENCE_ROOT", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else _REPOSITORY_ROOT / path
    derived = candidate_path.parent.parent / "evidence"
    if not derived.is_dir():
        raise AssertionError(
            "set ASH07_REAL_SOURCE_EVIDENCE_ROOT for taxonomy documents retained with the candidate"
        )
    return derived


def _load_candidate(path: Path) -> dict[str, Any]:
    """Read the facts index and refuse anything except exact current-date bytes."""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(value) is not dict:
        raise AssertionError("retained source candidate must be a JSON object")
    candidate = cast(dict[str, Any], value)
    if candidate.get("candidate_status") != "raw_capture_facts_only_not_admitted_or_policy_pinned":
        raise AssertionError("source candidate must remain pre-admission source facts")
    business_date = date.fromisoformat(candidate["business_date"])
    current_date = timezone.now().astimezone(_SHANGHAI).date()
    if business_date != current_date:
        raise AssertionError(
            f"current-source acceptance requires {current_date}, candidate is {business_date}; "
            "historical evidence must remain expired/unknown"
        )
    if candidate.get("scope") != "simulation_only; test-only holdings; no real-account assertion":
        raise AssertionError("source candidate must retain simulation-only scope")
    industry = candidate["industry_capture"]
    if (
        industry["provider_version"] != "2019-revision"
        or industry["source_clock_fields"]["observed_on"] != business_date.isoformat()
        or industry["source_clock_fields"]["observed_at"] is not None
    ):
        raise AssertionError("industry version/date fields must remain exact source facts")
    evidence_root = _evidence_root(path)
    for taxonomy_source in industry["taxonomy_sources"]:
        local_source_path: Path | None = None
        if taxonomy_source.get("local_path") is not None:
            local_source_path = Path(taxonomy_source["local_path"])
            if not local_source_path.is_absolute():
                local_source_path = _REPOSITORY_ROOT / local_source_path
        if taxonomy_source["role"] == "classification standard":
            source_path = local_source_path or (
                evidence_root
                / "source-followup-2"
                / "a"
                / "cnindex-2019-industry-classification-standard.pdf"
            )
        elif taxonomy_source["role"] == "classification update notice; not a member expiry":
            source_path = local_source_path or (
                evidence_root
                / "source-followup-2"
                / "a"
                / "cnindex-2026-industry-classification-update-notice.pdf"
            )
        else:
            raise AssertionError("industry source candidate has an unrecognized taxonomy artifact")
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != taxonomy_source["sha256"]:
            raise AssertionError("industry taxonomy artifact bytes differ from their retained hash")
    for quote in candidate["sina_quotes"]:
        observed_at = datetime.fromisoformat(quote["quote"]["observed_at"])
        received_at = datetime.fromisoformat(quote["response_completed_at"])
        if (
            observed_at.astimezone(_SHANGHAI).date() != business_date
            or observed_at.astimezone(_SHANGHAI).timetz().replace(tzinfo=None) < time(15, 0)
            or received_at.astimezone(_SHANGHAI).date() != business_date
            or received_at > timezone.now().astimezone(UTC)
            or observed_at.astimezone(UTC) > received_at.astimezone(UTC)
            or quote["quote"]["vendor_status_code"] != "00"
            or quote["source_clock_fields"]["available_at"] is not None
            or quote["source_clock_fields"]["valid_until"] is not None
        ):
            raise AssertionError("Sina input is not a current, bounded after-close source")
    return candidate


def _persisted_reference_snapshot(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Publish explicit local identity rows through the real DataCenter snapshot path."""

    # This local stock_basic response only exercises the persisted identity path.
    # It is synthetic test data and is not counted as a public-source capture.
    session = _TwoBankStockBasicSession(_Response(b"{}"))
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    payloads = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payloads)
    dataset_key = "fixture.ash07.sse-current-reference"
    client = tushare_client.create_tushare_pro_client(
        token="ash07-test-only-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.ash07.sse-current-reference",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key=dataset_key,
        api_name="stock_basic",
        fields=_REFERENCE_FIELDS,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.ash07.sse-suffix-crosswalk",
        crosswalk_version="explicit-local-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
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
    mapping = InstrumentReferenceMappingContent(
        mapping_id="fixture.ash07.explicit-sse-map",
        mapping_version="local-crosswalk-v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=(("SSE", "SSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-main", "MAIN"),),
    )
    mapping_record = SaveInstrumentReferenceMappingUseCase(repository).execute(mapping)
    content = InstrumentReferenceSnapshotContent(
        run_id=uuid4(),
        mapping_record=mapping_record,
        fetch_rounds=(InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidate),),
    )
    snapshot = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    for code in ("600036.SH", "601398.SH"):
        classification = snapshot.content.classify_security(code)
        assert classification is not None
        assert classification.source_exchange == "SSE"
        assert classification.rule_market == "SSE"
        assert classification.board == "MAIN"
    return repository, snapshot


def _current_reference_items(snapshot: Any) -> list[dict[str, str]]:
    """Build two exact selector entries from the actual saved source snapshot."""

    identity_pairs = (("600036.SH", "SSE:600036"), ("601398.SH", "SSE:601398"))
    result: list[dict[str, str]] = []
    for asset_code, security_id in identity_pairs:
        source_code = asset_code
        classification = snapshot.content.classify_security(source_code)
        if classification is None or classification.blocked_reason is not None:
            raise AssertionError(f"explicit fixture identity is unavailable: {asset_code}")
        result.append(
            {
                "security_id": security_id,
                "asset_code": asset_code,
                "source_code": source_code,
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


def _source_reference_clock_mode(kind: str) -> str:
    """Bind each admitted source kind to its only authorized precision mode."""

    modes = {
        "industry_membership": _INDUSTRY_MODE,
        "valuation": _VALUATION_MODE,
        "capacity_window": _CAPACITY_MODE,
        "execution_session_state": _SESSION_MODE,
    }
    try:
        return modes[kind]
    except KeyError as error:
        raise AssertionError(f"unexpected admission source kind: {kind}") from error


def _risk_profile_value(
    *,
    account_id: int,
    source_references: list[dict[str, object]],
) -> dict[str, object]:
    """Clone balanced source limits and bind only this account and exact sources."""

    template_path = (
        _REPOSITORY_ROOT
        / ".tmp"
        / "ash07-risk-20261103"
        / "config-drafts-overlay"
        / "config-data"
        / "balanced.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    source_value = template["values"][0]["value_json"]
    policy = json.loads(json.dumps(source_value))
    policy["account_ids"] = [account_id]
    policy["source_references"] = source_references
    policy["industry"]["allowed_observation_precisions"] = ["date", "timestamp"]
    policy["industry"]["allowed_source_restrictions"] = [
        "same_business_date_membership_only",
        "close_snapshot_only",
        "vendor_timestamped_quote",
    ]
    policy["capacity"]["allowed_observation_precisions"] = ["timestamp"]
    policy["capacity"]["allowed_source_restrictions"] = [
        "close_snapshot_only",
        "session_cumulative_quote",
        "vendor_reported_at_quote_time",
    ]
    return cast(dict[str, object], policy)


def _close_policy_payloads(
    *,
    candidate: dict[str, Any],
    account_id: int,
    rule_market_by_asset: dict[str, str],
    board_by_asset: dict[str, str],
) -> list[dict[str, object]]:
    """Create explicitly scoped paper-boundary policies from actual quote receipts."""

    from apps.data_center.domain.sina_quote_capture import SINA_VENDOR_STATUS_MAPPING_SHA256

    price_rule_hash = hashlib.sha256(
        b"ASH07 test-only exact vendor last quote after published close"
    ).hexdigest()
    boundary_hash = hashlib.sha256(b"ASH07 test-only 0.90/1.10 paper price boundary").hexdigest()
    policies: list[dict[str, object]] = []
    for quote in candidate["sina_quotes"]:
        received_at = datetime.fromisoformat(quote["response_completed_at"])
        trade_date = date.fromisoformat(candidate["business_date"])
        local_midnight = datetime.combine(trade_date + timedelta(days=1), time.min, _SHANGHAI)
        until = min(
            received_at + timedelta(seconds=300),
            local_midnight.astimezone(UTC) - timedelta(microseconds=1),
        )
        if received_at >= until:
            raise AssertionError("captured source is outside its explicit close policy window")
        policy = CloseSnapshotSimulationPolicy(
            policy_id=f"ash07-real-source-close-{account_id}-{quote['provider_asset_code']}",
            policy_version="explicit-test-source-binding-v1",
            account_id=account_id,
            security_id=quote["security_id"],
            asset_code=quote["risk_asset_code"],
            market=rule_market_by_asset[quote["risk_asset_code"]],
            board=board_by_asset[quote["risk_asset_code"]],
            trading_date=trade_date,
            source_id=quote["source_id"],
            source_name="Sina public quote; vendor-reported close snapshot only",
            usage_ttl_seconds=300,
            status_mapping_sha256=SINA_VENDOR_STATUS_MAPPING_SHA256,
            trusted_vendor_status_codes=("00",),
            available_from=received_at,
            available_until=until,
            price_rule="exact_vendor_last_after_close.v1",
            price_rule_source_hash=price_rule_hash,
            price_boundary_mode=PriceBoundaryMode.LIMITED,
            lower_boundary_factor=Decimal("0.90"),
            upper_boundary_factor=Decimal("1.10"),
            boundary_rule_source_id="ash07_test_paper_boundary",
            boundary_rule_version="explicit-test-v1",
            boundary_rule_source_hash=boundary_hash,
            unrestricted_reason_code=None,
        )
        policies.append(cast(dict[str, object], policy.to_payload()))
    return policies


def _seed_baseline(account_id: int) -> None:
    """Write explicit isolated-test baseline rows for the real baseline reader."""

    if GlobalRiskFloorModel.objects.filter(is_active=True).exists():
        raise AssertionError("test database already has an active global risk floor")
    floor = GlobalRiskFloorModel.objects.create(
        name=f"ASH07 real-source floor {account_id}",
        is_active=True,
        max_total_position_pct=Decimal("0.95"),
        max_single_position_pct=Decimal("0.50"),
        min_cash_pct=Decimal("0.05"),
        hard_exclusions=[],
    )
    del floor
    template = RiskTemplateModel.objects.create(
        key=f"ash07-real-source-{account_id}",
        name="ASH07 isolated real-source test template",
        risk_profile=RiskTemplateModel.MODERATE,
        is_active=True,
        max_total_position_pct=Decimal("0.80"),
        max_single_position_pct=Decimal("0.40"),
        min_cash_pct=Decimal("0.10"),
        hard_exclusions=[],
    )
    AccountRiskPolicyModel.objects.create(
        account_id=account_id,
        template=template,
        risk_profile=RiskTemplateModel.MODERATE,
        is_active=True,
        max_total_position_pct=None,
        max_single_position_pct=None,
        min_cash_pct=None,
        hard_exclusions=[],
    )


def _seed_positions(
    account: SimulatedAccountModel,
    *,
    candidate: dict[str, Any],
    names: dict[str, str],
    business_date: date,
) -> tuple[PositionModel, ...]:
    """Seed only two explicit test-scope simulated holdings at retained quote prices."""

    positions: list[PositionModel] = []
    for quote in candidate["sina_quotes"]:
        asset_code = quote["risk_asset_code"]
        price = Decimal(quote["quote"]["last_price"])
        quantity = Decimal("100")
        market_value = (price * quantity).quantize(Decimal("0.01"))
        position = PositionModel.objects.create(
            account=account,
            asset_code=asset_code,
            asset_name=names[asset_code],
            asset_type="equity",
            quantity=quantity,
            available_quantity=quantity,
            available_quantity_known=True,
            avg_cost=price.quantize(Decimal("0.0001")),
            total_cost=market_value,
            cost_basis_known=True,
            current_price=price,
            market_value=market_value,
            valuation_known=True,
            unrealized_pnl=Decimal("0.00"),
            unrealized_pnl_pct=0.0,
            first_buy_date=business_date - timedelta(days=20),
            first_buy_date_known=True,
            entry_reason="ASH07 isolated test fixture; not a real-account holding",
            invalidation_description="test-only initial position",
        )
        positions.append(position)
    account.current_market_value = sum(
        (position.market_value for position in positions), Decimal("0.00")
    )
    account.total_value = account.current_cash + account.current_market_value
    account.save(update_fields=("current_market_value", "total_value"))
    return tuple(positions)


def _assert_native_test_database() -> None:
    """Require the isolated migrated Native PostgreSQL database before any writes."""

    if connection.vendor != "postgresql":
        pytest.fail("real-source Owner acceptance requires isolated Native PostgreSQL")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip().endswith(".production"):
        pytest.fail("test source admission is not permitted under production settings")
    assert_native_postgres_test_database()


def test_retained_november_03_candidate_hits_harness_date_gate_only() -> None:
    """Check the harness date gate only, not production admission or Reader expiry."""

    if not _RETAINED_2026_11_03_CANDIDATE.is_file():
        pytest.skip(
            "the November 03 raw source facts are ignored external evidence and are absent in CI"
        )
    candidate = json.loads(_RETAINED_2026_11_03_CANDIDATE.read_text(encoding="utf-8-sig"))
    source_date = date.fromisoformat(candidate["business_date"])
    current_date = timezone.now().astimezone(_SHANGHAI).date()
    if source_date >= current_date:
        pytest.skip("the retained source date has not yet become historical")
    with pytest.raises(AssertionError, match="historical evidence must remain expired/unknown"):
        _load_candidate(_RETAINED_2026_11_03_CANDIDATE)


@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_ASH07_REAL_SOURCE_OWNER_ACCEPTANCE") != "1",
    reason=(
        "set AGOM_RUN_ASH07_REAL_SOURCE_OWNER_ACCEPTANCE=1 only after Root supplies a "
        "current-date retained public-source candidate"
    ),
)
def test_owner_tui_current_public_risk_sources_and_scenario_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qualify current real source facts through owner TUI and persist real Scenario evidence."""

    _assert_native_test_database()
    candidate_path = _candidate_path()
    candidate = _load_candidate(candidate_path)
    business_date = date.fromisoformat(candidate["business_date"])
    requests = admission_builder.build_real_source_admission_requests(candidate_path)
    if not requests:
        raise AssertionError("source candidate must yield exact typed admission requests")
    if len(requests) != 8:
        raise AssertionError(
            "two holdings require exact industry, valuation, capacity, and state refs"
        )
    for request in requests:
        capture = request.sina_capture
        if capture is None:
            continue
        if capture.body != request.original_body or capture.quote is None:
            raise AssertionError("Sina typed capture must be the exact admitted original response")
        if capture.quote.previous_close is None or capture.quote.last_price is None:
            raise AssertionError("close-only simulation requires source-provided prior/last prices")
        if capture.quote.reported_trading_state.value != "trading":
            raise AssertionError("the vendor quote-time state does not qualify as TRADING")
    unit_mapping = admission_builder.verify_source_unit_mapping(candidate)
    assert unit_mapping["canonical_quantity_unit"] == "share"
    assert unit_mapping["canonical_money_unit"] == "CNY"
    assert unit_mapping["numeric_scale"] == "1"

    configure_critical_runtime()
    account = auto_fixture._create_account()
    account_id = cast(int, account.pk)
    owner_id = cast(int, account.user_id)
    _seed_baseline(account_id)

    # Each body remains an exact retained original; the RawPayload manifest hash
    # is a separate policy pin and never substitutes for original-body SHA-256.
    raw_payloads: dict[tuple[str, str], str] = {}
    admission_use_case = build_portfolio_risk_source_admission_use_case()
    for request in requests:
        if request.original_url is None or not request.original_body:
            raise AssertionError("each admitted source must preserve URL and original bytes")
        receipt = request.capture_receipt
        if receipt is None:
            raise AssertionError("trusted capture adapter did not attach a typed receipt")
        body_hash = hashlib.sha256(request.original_body).hexdigest()
        if request.source_evidence.original_payload_sha256 != body_hash:
            raise AssertionError("admission facts are not bound to the retained original body")
        result = admission_use_case.execute(request, persist=True)
        if not result.stored or result.payload.fetched_at != receipt.response_completed_at:
            raise AssertionError("RawPayload did not preserve the trusted local capture clock")
        if result.payload.payload_hash == f"sha256:{body_hash}":
            raise AssertionError("manifest identity must remain distinct from source-body hash")
        raw_payloads[(request.kind, request.source_record_id)] = result.payload.payload_hash

    names: dict[str, str] = {}
    for identity in candidate["identity_resolution"]["records"]:
        source_path = Path(identity["sse_record_path"])
        if not source_path.is_absolute():
            source_path = _REPOSITORY_ROOT / source_path
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != identity["sse_record_sha256"]:
            raise AssertionError("official SSE identity source hash differs")
        company_payload = json.loads(source_bytes.decode("utf-8-sig"))
        company_rows = company_payload.get("result")
        if type(company_rows) is not list or len(company_rows) != 1:
            raise AssertionError("official SSE company identity row is not unique")
        row = company_rows[0]
        if row.get("A_STOCK_CODE") != identity["sse_company_code"]:
            raise AssertionError("official SSE source code differs from the local selector")
        names[identity["asset_code"]] = row["COMPANY_ABBR"]

    positions = _seed_positions(
        account,
        candidate=candidate,
        names=names,
        business_date=business_date,
    )
    assert len(positions) == 2
    ledger_before = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        tuple(
            (position.asset_code, position.quantity, position.available_quantity)
            for position in positions
        ),
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
    )

    reference_repository, source_snapshot = _persisted_reference_snapshot(monkeypatch)
    del reference_repository
    calendar = persist_auto_uow_formal_calendar(
        as_of=timezone.now().astimezone(UTC),
        exchange="SSE",
        timezone_name="Asia/Shanghai",
        live_clock=True,
    )
    if calendar.market_session != business_date:
        raise AssertionError(
            "candidate date and existing published execution-calendar session differ"
        )
    selector = {
        "schema": "normal-simulated-current-reference-selection.v1",
        "purpose": "normal_simulated_current_reference",
        "max_local_reference_age_seconds": 600,
        "items": _current_reference_items(source_snapshot),
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={
            _CURRENT_REFERENCE_SELECTION_KEY: selector,
            _EXCHANGE_TIMEZONE_MAP_KEY: {"SSE": "Asia/Shanghai"},
        },
        actor="ash07-real-source-current-reference-test",
        reason="bind the exact two-code local test reference to persisted source rows",
    )
    reference_reader = build_current_reference_identity_reader(runtime_environment="development")
    rule_market_by_asset: dict[str, str] = {}
    board_by_asset: dict[str, str] = {}
    for quote in candidate["sina_quotes"]:
        asset_code = quote["risk_asset_code"]
        security_id = quote["security_id"]
        identity = reference_reader.resolve_current_reference_identity(
            asset_code=asset_code,
            as_of=timezone.now().astimezone(UTC),
        )
        if identity is None or identity.security_id != security_id:
            raise AssertionError(f"explicit current-reference pair is not published: {asset_code}")
        if identity.source_exchange != "SSE":
            raise AssertionError("published identity source exchange is not the exact SSE venue")
        classification = source_snapshot.content.classify_security(asset_code)
        if classification is None or classification.blocked_reason is not None:
            raise AssertionError(f"reference classification is blocked: {asset_code}")
        if classification.rule_market is None or classification.board is None:
            raise AssertionError(f"market/board mapping is unavailable: {asset_code}")
        rule_market_by_asset[asset_code] = classification.rule_market
        board_by_asset[asset_code] = classification.board
        monkeypatch.setattr(auto_fixture, "AS_OF", timezone.now().astimezone(UTC))
        monkeypatch.setattr(
            auto_fixture,
            "KNOWLEDGE_AT",
            timezone.now().astimezone(UTC) - timedelta(seconds=1),
        )
        auto_fixture._seed_rule_bundle(
            security_id=security_id,
            market=classification.rule_market,
            board=classification.board,
        )

    source_references: list[dict[str, object]] = []
    for request in requests:
        manifest_hash = raw_payloads[(request.kind, request.source_record_id)]
        source_references.append(
            {
                "kind": request.kind,
                "asset_code": request.asset_code,
                "security_id": request.security_id,
                "raw_payload_hash": manifest_hash,
                "source_record_id": request.source_record_id,
                "clock_evidence_mode": _source_reference_clock_mode(request.kind),
            }
        )
    risk_policy = _risk_profile_value(
        account_id=account_id,
        source_references=source_references,
    )
    close_policies = _close_policy_payloads(
        candidate=candidate,
        account_id=account_id,
        rule_market_by_asset=rule_market_by_asset,
        board_by_asset=board_by_asset,
    )
    activate_runtime_profile_patch(
        environment="development",
        patch={
            _RISK_DEFINITION_KEY: risk_policy,
            _CLOSE_POLICIES_KEY: {"policies": close_policies},
        },
        actor="ash07-real-source-policy-test",
        reason=(
            "successor of the balanced test template; exact account/source bindings and "
            "close-only source restrictions"
        ),
    )
    active = get_active_runtime_profile("development")
    if active is None or active.version < 1:
        raise AssertionError("real ConfigCenter did not publish the successor profile")

    # The only replaced DI port is Scenario's historical return provider. The
    # owner risk service, source reader, close-state provider, baseline reader,
    # calendar reader, audit writer, and Scenario ORM repository stay real.
    synthetic_scenario_market = tui_flow._SyntheticScenarioMarketDataProvider()
    monkeypatch.setattr(
        risk_composition,
        "PublishedScenarioMarketDataProvider",
        lambda: synthetic_scenario_market,
    )

    client, csrf_token = _owner_session_client(owner_id)
    assert client.cookies[settings.CSRF_COOKIE_NAME].value == csrf_token
    report_url = reverse(
        "api_simulated_trading:portfolio-risk-report",
        kwargs={"account_id": account_id},
    )
    options_url = reverse(
        "api_simulated_trading:portfolio-pressure-scenarios",
        kwargs={"account_id": account_id},
    )
    action_url = "/api/tui/actions/simulated-trading.portfolio-pressure-run/run/"
    common_headers = {
        "secure": True,
        "HTTP_X_CSRFTOKEN": csrf_token,
        "HTTP_ORIGIN": "https://testserver",
    }

    report_response = client.get(report_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert report_response.status_code == 200, report_response.content
    report = report_response.json()
    assert report["account_id"] == account_id
    assert report["scope"] == "simulation_only"
    assert report["must_not_execute"] is True
    assert report["freshness"] == "qualified_snapshot"
    assert report["reliability"] == "source_bound"
    assert report["outcome"] == "allowed", report["checks"]
    assert all(check["status"] == "allowed" for check in report["checks"])
    original_hashes = {request.source_evidence.original_payload_sha256 for request in requests}
    source_hashes = {item["raw_payload_sha256"] for item in report["sources"]}
    assert original_hashes.issubset(source_hashes)
    assert len(report["sources"]) == 8
    input_scope = next(check for check in report["checks"] if check["dimension"] == "input_scope")
    manifest_hashes = {
        item["manifest_sha256"] for item in input_scope["details"]["source_reference_bindings"]
    }
    assert manifest_hashes == set(raw_payloads.values())
    assert not manifest_hashes.intersection(original_hashes)
    assert all(item["available_at"] is None for item in report["sources"])
    assert all(item["valid_until"] is None for item in report["sources"])
    assert all(item["raw_payload_sha256"] for item in report["sources"])
    industry_sources = [
        item for item in report["sources"] if item["source_id"] == "cnindex_industry_membership"
    ]
    assert len(industry_sources) == 2
    assert all(item["observed_on"] == business_date.isoformat() for item in industry_sources)
    assert all(item["observed_at"] is None for item in industry_sources)
    close_state_sources = [
        item
        for item in report["sources"]
        if item["source_record_id"].endswith(":execution_session_state")
    ]
    assert len(close_state_sources) == 2
    assert all(item["observation_precision"] == "timestamp" for item in close_state_sources)
    assert all(
        item["clock_evidence_proof"]["full_session_state"] == "unknown"
        for item in close_state_sources
    )
    assert all(
        item["clock_evidence_proof"]["required_restrictions"]
        == ["vendor_reported_at_quote_time", "close_snapshot_only"]
        for item in close_state_sources
    )

    revision_id = tui_flow._seeded_legacy_pressure_revision_id()
    options_response = client.get(options_url, secure=True, HTTP_ORIGIN="https://testserver")
    assert options_response.status_code == 200, options_response.content
    options = options_response.json()
    assert options["account_id"] == account_id
    assert options["scope"] == "simulation_only"
    assert options["read_only"] is True
    assert any(option["value"] == revision_id for option in options["options"])

    evidence_count_before = tui_flow._scenario_run_evidence_count()
    pressure_api_reports = tui_flow._capture_pressure_api_reports(monkeypatch)
    idempotency_key = f"ash07-real-source-{uuid4().hex}"
    action_body = {
        "params": {
            "account_id": account_id,
            "scenario_version_id": revision_id,
        }
    }
    confirmation_response = client.post(
        action_url,
        action_body,
        format="json",
        **common_headers,
    )
    assert confirmation_response.status_code == 200, confirmation_response.content
    confirmation = confirmation_response.json()
    assert confirmation["confirmation_required"] is True
    assert tui_flow._scenario_run_evidence_count() == evidence_count_before
    confirmation_material = confirmation.get("confirmation")
    assert isinstance(confirmation_material, dict)

    confirmed_body = {
        **action_body,
        "confirmed": True,
        "confirmation": confirmation_material,
    }
    action_response = client.post(
        action_url,
        confirmed_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
        **common_headers,
    )
    assert action_response.status_code == 200, action_response.content
    action = action_response.json()
    assert action["confirmation_required"] is False
    assert action["response"]["status_code"] == 200
    assert action["outcome"] == "success"
    assert action["view_model"]["scope"] == "simulation_only"
    assert action["view_model"]["must_not_execute"] is True

    run_id = tui_flow.portfolio_pressure_run_id(
        actor_user_id=owner_id,
        account_id=account_id,
        idempotency_key=idempotency_key,
    )
    assert len(pressure_api_reports) == 1
    pressure_report = pressure_api_reports[0]
    pressure_check = next(
        item for item in pressure_report["checks"] if item["dimension"] == "exit_pressure"
    )
    assert pressure_check["details"]["run_evidence_persisted"] is True
    assert pressure_check["details"]["run_evidence_id"] == run_id
    assert tui_flow._scenario_run_evidence_count() == evidence_count_before + 1
    saved = tui_flow._read_scenario_run_evidence(run_id)
    assert saved is not None
    assert saved.scenario_revision_id == revision_id
    assert saved.result_hash
    saved_report_as_of = datetime.fromisoformat(pressure_report["as_of"].replace("Z", "+00:00"))
    assert saved.as_of_time == saved_report_as_of
    assert saved.input_snapshot_json is not None
    assert saved.result_snapshot_json is not None
    input_snapshot = json.loads(saved.input_snapshot_json)
    result_snapshot = json.loads(saved.result_snapshot_json)
    assert input_snapshot["original_report_json"]
    assert input_snapshot["original_report_json"] == (
        input_snapshot["account_projection"]["original_report_json"]
    )
    frozen_report = json.loads(input_snapshot["original_report_json"])
    frozen_sources = {source["raw_payload_sha256"] for source in frozen_report["sources"]}
    assert original_hashes.issubset(frozen_sources)
    assert result_snapshot["assessment"]["result_hash"]
    public_template = tui_flow.report_payload_from_object(result_snapshot["public_report_template"])
    assert public_template is not None
    saved_pressure_check = next(
        item for item in public_template["checks"] if item["dimension"] == "exit_pressure"
    )
    assert saved_pressure_check["details"]["run_evidence_id"] == run_id
    assert saved_pressure_check["details"]["run_evidence_persisted"] is True
    assert synthetic_scenario_market.reads
    assert len(synthetic_scenario_market.reads) == 1
    assert ScenarioRunEvidenceModel.objects.filter(run_id=run_id).count() == 1
    assert StressScenarioRevisionModel.objects.get(revision_id=revision_id).status == "approved"
    assert TerminalAuditLogORM.objects.filter(
        user_id=owner_id,
        command_name="simulated-trading.portfolio-pressure-run",
        result_status="success",
    ).exists()
    account.refresh_from_db()
    for position in positions:
        position.refresh_from_db()
    ledger_after = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        tuple(
            (position.asset_code, position.quantity, position.available_quantity)
            for position in positions
        ),
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
    )
    assert ledger_after == ledger_before

    # The same underlying request key must replay the frozen report without
    # invoking Scenario data again, adding evidence, changing the ledger, or
    # creating another Terminal action record.
    terminal_audit_count_before_replay = TerminalAuditLogORM.objects.filter(
        user_id=owner_id,
        command_name="simulated-trading.portfolio-pressure-run",
    ).count()
    assert terminal_audit_count_before_replay >= 1
    pressure_url = reverse(
        "api_simulated_trading:portfolio-pressure-run",
        kwargs={"account_id": account_id},
    )
    replay_at = saved.as_of_time + timedelta(seconds=10)
    monkeypatch.setattr(timezone, "now", lambda: replay_at)
    replay_response = client.post(
        pressure_url,
        {"scenario_version_id": revision_id, "confirmed": True},
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="https://testserver",
    )
    assert replay_response.status_code == 200, replay_response.content
    assert replay_response["Content-Type"].startswith("application/json")
    expected_original_report = tui_flow.bind_portfolio_pressure_evidence_hash(
        public_template,
        saved.result_hash,
    )
    assert replay_response.json() == expected_original_report
    assert replay_response.json()["as_of"] == saved.as_of_time.isoformat()
    assert replay_at > saved.as_of_time
    assert len(synthetic_scenario_market.reads) == 1
    assert tui_flow._scenario_run_evidence_count() == evidence_count_before + 1
    saved_after_replay = tui_flow._read_scenario_run_evidence(run_id)
    assert saved_after_replay is not None
    assert saved_after_replay.result_hash == saved.result_hash
    assert saved_after_replay.input_snapshot_json == saved.input_snapshot_json
    assert saved_after_replay.result_snapshot_json == saved.result_snapshot_json
    account.refresh_from_db()
    for position in positions:
        position.refresh_from_db()
    replay_ledger = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        tuple(
            (position.asset_code, position.quantity, position.available_quantity)
            for position in positions
        ),
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
    )
    assert replay_ledger == ledger_before
    assert (
        TerminalAuditLogORM.objects.filter(
            user_id=owner_id,
            command_name="simulated-trading.portfolio-pressure-run",
        ).count()
        == terminal_audit_count_before_replay
    )
