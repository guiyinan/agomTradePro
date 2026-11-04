"""Opt-in Native PostgreSQL Owner TUI flow over retained public risk sources.

The risk inputs must be independently captured after the market close for the
current Shanghai business date and admitted through the real RawPayload path.
Scenario historical returns, local stock-reference rows, holdings, and baseline
rows are isolated test fixtures. The execution calendar is captured and
published through the real session/CSRF Workbench and its public consumer; the
industry, valuation, capacity, and close-quote bytes remain retained public
sources. This test never turns the older 2026-11-03 evidence into a current
source and never writes to a developer/default ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
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
    SimulatedOrderFillReceiptModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    FIELDS as _REFERENCE_FIELDS,
)
from tests.component.simulated_trading import test_auto_trading_current_reference_t1 as auto_fixture
from tests.component.simulated_trading import test_owner_order_submission_tui_browser as tui_flow
from tests.support import ash07_public_risk_sources as admission_builder
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_native_runtime_role import isolated_ash07_runtime_role
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    audit_runtime_patch,
    create_owner_account_seed,
    issue_current_owner_audit_selector,
    publish_current_owner_policy,
)
from tests.support.ash07_owner_m1_price_batch import (
    publish_and_verify_tushare_close_batch,
)
from tests.support.ash07_owner_risk_policy_binding import bind_audited_balanced_v2_policy
from tests.support.ash07_owner_session import (
    create_simulated_account_for_approved_owner,
    ordinary_owner_session_client,
)
from tests.support.ash07_real_calendar_publication import (
    RealCalendarPublicationLease,
    publish_real_calendar_for_acceptance,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RISK_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"
_CURRENT_REFERENCE_SELECTION_KEY = "config_center.market.simulated_current_reference_selection"
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


class _LiveFillClock:
    """Read actual UTC time for both locked risk evaluation and final verification."""

    def now(self) -> datetime:
        """Return a new server clock observation without freezing market facts."""

        return timezone.now().astimezone(UTC)


def _source_body_hashes_for_asset(
    *,
    sources: object,
    source_reference_bindings: object,
    asset_code: str,
) -> set[str]:
    """Join vendor-body hashes to one asset only through its exact report pins."""

    if type(sources) is not list or type(source_reference_bindings) is not list:
        raise AssertionError("risk source rows and reference bindings must be JSON lists")
    scopes_by_record: dict[str, set[tuple[str, str, str, str]]] = {}
    expected_scopes: set[tuple[str, str, str, str]] = set()
    for raw_binding in source_reference_bindings:
        if type(raw_binding) is not dict:
            raise AssertionError("risk source reference binding must be a JSON object")
        kind = raw_binding.get("kind")
        bound_asset = raw_binding.get("asset_code")
        security_id = raw_binding.get("security_id")
        source_record_id = raw_binding.get("source_record_id")
        if (
            type(kind) is not str
            or not kind.strip()
            or type(bound_asset) is not str
            or not bound_asset.strip()
            or type(security_id) is not str
            or not security_id.strip()
            or type(source_record_id) is not str
            or not source_record_id.strip()
        ):
            raise AssertionError("source binding lacks its exact kind, asset, security, or record")
        scope = (bound_asset, security_id, kind, source_record_id)
        scopes_by_record.setdefault(source_record_id, set()).add(scope)
        if bound_asset == asset_code:
            expected_scopes.add(scope)
    if not expected_scopes:
        raise AssertionError(f"no exact source pins were reported for {asset_code}")

    observed_scopes: set[tuple[str, str, str, str]] = set()
    body_hashes: set[str] = set()
    expected_records = {scope[3] for scope in expected_scopes}
    for raw_source in sources:
        if type(raw_source) is not dict:
            raise AssertionError("risk source must be a JSON object")
        source_record_id = raw_source.get("source_record_id")
        if type(source_record_id) is not str or source_record_id not in expected_records:
            continue
        if "clock_evidence_proof" not in raw_source:
            possible_scopes = scopes_by_record[source_record_id]
            if len(possible_scopes) != 1:
                raise AssertionError(
                    "an unscoped source row cannot identify a shared pinned source record"
                )
            source_scope = next(iter(possible_scopes))
        else:
            proof = raw_source["clock_evidence_proof"]
            if type(proof) is not dict:
                raise AssertionError("clock evidence proof must be a typed JSON object")
            proof_asset = proof.get("asset_code")
            proof_security = proof.get("security_id")
            proof_kind = proof.get("source_kind")
            proof_record = proof.get("source_record_id")
            if (
                type(proof_asset) is not str
                or type(proof_security) is not str
                or type(proof_kind) is not str
                or type(proof_record) is not str
                or proof_record != source_record_id
            ):
                raise AssertionError("clock proof record differs from its source row")
            source_scope = (proof_asset, proof_security, proof_kind, proof_record)
            if source_scope not in scopes_by_record[source_record_id]:
                raise AssertionError("clock proof scope is not present in the pinned bindings")
            if proof.get("original_body_sha256") != raw_source.get("raw_payload_sha256"):
                raise AssertionError("clock proof body hash differs from the source evidence hash")
        if source_scope[0] != asset_code:
            continue
        if source_scope not in expected_scopes or source_scope in observed_scopes:
            raise AssertionError("source evidence is unpinned or duplicated for this asset")
        body_hash = raw_source.get("raw_payload_sha256")
        if type(body_hash) is not str or not body_hash:
            raise AssertionError("asset-scoped source evidence has no vendor-body hash")
        observed_scopes.add(source_scope)
        body_hashes.add(body_hash)
    if observed_scopes != expected_scopes or not body_hashes:
        raise AssertionError(f"source evidence does not cover the exact pins for {asset_code}")
    return body_hashes


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
    snapshot_run_id = uuid4()
    candidate = source.fetch_candidate(run_id=snapshot_run_id, ingested_run_id=uuid4())
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
        run_id=snapshot_run_id,
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


class _RealCalendarPublisher(Protocol):
    """Require the exact business-date and coverage arguments at the call site."""

    def __call__(
        self,
        *,
        business_date: date,
        coverage_start: date,
        coverage_end: date,
    ) -> RealCalendarPublicationLease: ...


@pytest.fixture(name="runtime_role")
def _ash07_runtime_role(
    transactional_db: None,
    tmp_path: Path,
) -> Iterator[dict[str, object]]:
    """Restore the test DB runtime identity before transactional cleanup."""

    del transactional_db
    with isolated_ash07_runtime_role(tmp_path / "runtime-role") as report:
        yield report


@pytest.fixture
def _publish_real_calendar(
    request: pytest.FixtureRequest,
    runtime_role: dict[str, object],
) -> _RealCalendarPublisher:
    """Publish through the public catalog/provider/Workbench flow and restore it."""

    if runtime_role.get("runtime_acl_verified") is not True:
        raise AssertionError("the isolated runtime role was not verified")
    leases: list[RealCalendarPublicationLease] = []

    def publish(
        *,
        business_date: date,
        coverage_start: date,
        coverage_end: date,
    ) -> RealCalendarPublicationLease:
        lease = publish_real_calendar_for_acceptance(
            business_date=business_date,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
        leases.append(lease)
        return lease

    def close_leases() -> None:
        for lease in reversed(leases):
            lease.close()

    request.addfinalizer(close_leases)
    return publish


@pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
@override_settings(ROOT_URLCONF="tests.support.ash07_owner_acceptance_test_urls")
@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_ASH07_REAL_SOURCE_OWNER_ACCEPTANCE") != "1",
    reason=(
        "set AGOM_RUN_ASH07_REAL_SOURCE_OWNER_ACCEPTANCE=1 only after Root supplies a "
        "current-date retained public-source candidate"
    ),
)
def test_owner_tui_current_public_risk_sources_and_scenario_replay(
    monkeypatch: pytest.MonkeyPatch,
    _publish_real_calendar: _RealCalendarPublisher,
    runtime_role: dict[str, object],
    tmp_path: Path,
) -> None:
    """Qualify current real source facts through owner TUI and persist real Scenario evidence."""

    _assert_native_test_database()
    if runtime_role.get("runtime_acl_verified") is not True:
        raise AssertionError("the isolated runtime role was not verified")
    candidate_path = _candidate_path()
    candidate = _load_candidate(candidate_path)
    business_date = date.fromisoformat(candidate["business_date"])
    configure_critical_runtime()
    provider_settings = save_provider_settings_payload(
        default_source="tushare",
        enable_failover=False,
        failover_tolerance=0.01,
        actor="ash07-owner-real-source-test",
    )
    if (
        provider_settings.get("status") != "active"
        or provider_settings.get("default_source") != "tushare"
        or provider_settings.get("enable_failover") is not False
        or provider_settings.get("failover_tolerance") != 0.01
    ):
        raise AssertionError("provider-backed close readers need explicit Tushare runtime settings")
    publisher_seed = create_owner_account_seed()
    publish_current_owner_policy(publisher_seed)
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    from tests.component.data_center.test_calendar_workbench_tui_browser import (
        _create_browser_regular_user as create_approved_regular_user,
    )

    # This existing fixture writes an approved isolated test profile, not a real human approval.
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
        raise AssertionError("Risk account must use a separately approved ordinary test Owner")
    _seed_baseline(account_id)

    with monkeypatch.context() as identity_patch:
        reference_repository, source_snapshot = _persisted_reference_snapshot(identity_patch)
    del reference_repository
    calendar = _publish_real_calendar(
        business_date=business_date,
        coverage_start=business_date - timedelta(days=7),
        coverage_end=business_date + timedelta(days=14),
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

    # Use the existing explicit Fee V2 fixture once per exact market/board.
    fee_scopes = sorted(
        {
            (rule_market_by_asset[asset_code], board_by_asset[asset_code])
            for asset_code in rule_market_by_asset
        }
    )
    with monkeypatch.context() as fee_patch:
        fee_patch.setattr(
            auto_fixture, "AS_OF", timezone.now().astimezone(UTC) + timedelta(minutes=1)
        )
        for fee_market, fee_board in fee_scopes:
            auto_fixture._seed_fee_policy(
                account_id=account_id,
                market=fee_market,
                board=fee_board,
            )

    # ASH-03 requires both calendar and execution-rule knowledge before capture.
    # Keep their real clocks; collect new original quotes only after setup.
    candidate_path = admission_builder.refresh_current_quote_candidate(
        candidate_path=candidate_path,
        output_dir=tmp_path / "after-calendar-rule-quotes",
    )
    candidate = _load_candidate(candidate_path)
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

    # Each body remains an exact retained original; the RawPayload manifest hash
    # is a separate policy pin and never substitutes for original-body SHA-256.
    raw_payloads: dict[tuple[str, str, str, str], str] = {}
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
        raw_payloads[
            (request.kind, request.asset_code, request.security_id, request.source_record_id)
        ] = result.payload.payload_hash

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

    source_references: list[dict[str, object]] = []
    for request in requests:
        manifest_hash = raw_payloads[
            (request.kind, request.asset_code, request.security_id, request.source_record_id)
        ]
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
    risk_policy = bind_audited_balanced_v2_policy(
        account_id=account_id,
        source_references=source_references,
        admitted_requests=requests,
        admitted_manifest_hashes=raw_payloads,
        repository_root=_REPOSITORY_ROOT,
        unit_mapping=unit_mapping,
    )
    close_policies = _close_policy_payloads(
        candidate=candidate,
        account_id=account_id,
        rule_market_by_asset=rule_market_by_asset,
        board_by_asset=board_by_asset,
    )
    if risk_policy.get("account_ids") != [account_id]:
        raise AssertionError("Risk v2 policy is not bound to the ordinary Owner account")
    publisher_role = (
        AccountProfileModel.objects.filter(user_id=publisher_seed.owner.pk)
        .values_list("rbac_role", flat=True)
        .first()
    )
    if (
        publisher_seed.owner.pk == owner_id
        or not publisher_seed.owner.is_staff
        or publisher_seed.owner.is_superuser
        or publisher_seed.account.user_id != publisher_seed.owner.pk
        or publisher_role != "admin"
    ):
        raise AssertionError("SystemAudit publisher and ordinary Risk owner must be separate")
    audit_selector = issue_current_owner_audit_selector(publisher_seed)
    activate_runtime_profile_patch(
        environment="development",
        patch={
            **audit_runtime_patch(audit_selector),
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
    if active.status is not RuntimeProfileStatus.ACTIVE:
        raise AssertionError("Owner flow must read the actual active ConfigCenter profile")

    published_price_batch = publish_and_verify_tushare_close_batch(
        asset_codes=tuple(sorted(names)),
        target_trade_date=business_date,
    )

    # The only replaced DI port is Scenario's historical return provider. The
    # owner risk service, source reader, close-state provider, baseline reader,
    # calendar reader, audit writer, and Scenario ORM repository stay real.
    synthetic_scenario_market = tui_flow._SyntheticScenarioMarketDataProvider()
    monkeypatch.setattr(
        risk_composition,
        "PublishedScenarioMarketDataProvider",
        lambda: synthetic_scenario_market,
    )

    client, csrf_token = ordinary_owner_session_client(owner_id)
    assert csrf_token
    assert client.cookies.get(settings.CSRF_COOKIE_NAME) is not None
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
    (tmp_path / "owner-current-risk-before.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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
    assert input_scope["details"]["policy_profile_key"] == active.profile_key
    assert input_scope["details"]["policy_profile_version"] == active.version
    assert input_scope["details"]["policy_profile_content_hash"] == active.content_hash
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
    real_wall_clock = timezone.now
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
    monkeypatch.setattr(timezone, "now", real_wall_clock)

    # Reuse only the exact retained quote capture for the owner order. The test
    # still exercises the real order application, reservation UOW, and fill UOW.
    from django.db import transaction

    import apps.simulated_trading.close_snapshot_submission_composition as close_market
    from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
    from apps.risk_center.infrastructure.models import RiskPolicyAuditModel
    from apps.simulated_trading.application.portfolio_risk_execution_gate import (
        ConfiguredPortfolioRiskLockedOrderGuard,
    )
    from tests.component.simulated_trading import (
        test_live_sina_close_snapshot_owner_acceptance as close_flow,
    )

    retained_captures: dict[str, SinaQuoteCapture] = {
        request.asset_code: request.sina_capture
        for request in requests
        if request.kind == "execution_session_state" and request.sina_capture is not None
    }
    assert set(retained_captures) == set(names)

    def retained_capture(asset_code: str) -> SinaQuoteCapture:
        """Return the already admitted exact quote response for this asset."""
        capture = retained_captures.get(asset_code)
        if capture is None:
            raise AssertionError("the source admission did not retain this Sina quote")
        return capture

    monkeypatch.setattr(close_market, "capture_sina_quote", retained_capture)
    sell_position = positions[0]
    sell_asset = sell_position.asset_code
    retained_quote = retained_capture(sell_asset).quote
    assert retained_quote is not None and retained_quote.last_price is not None

    plan_response = client.post(
        reverse(
            "api_simulated_trading:daily-inspection-run",
            kwargs={"account_id": account_id},
        ),
        {
            "inspection_date": business_date.isoformat(),
            "auto_create_proposal": False,
            "reference_price_basis": "published_close",
            "temporary_target_weights": "\n".join(
                f"{position.asset_code},0" for position in positions
            ),
        },
        format="json",
        **common_headers,
    )
    (tmp_path / "owner-current-plan-response.json").write_bytes(plan_response.content)
    assert plan_response.status_code == 200, plan_response.content
    plan_body = plan_response.json()
    assert plan_body["success"] is True
    plan = plan_body["reports"][0]["plan"]
    assert plan["plan_kind"] == "rebalance_preview"
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    assert plan["must_not_execute"] is True
    assert plan["reference_price_basis"] == "published_close"
    assert plan["asset_items"]
    planned_sell = next(item for item in plan["asset_items"] if item["asset_code"] == sell_asset)
    assert planned_sell["action"] == "sell"
    assert planned_sell["actionable_quantity"] is not None, planned_sell["reason_codes"]
    planned_sell_quantity = Decimal(planned_sell["actionable_quantity"])
    assert planned_sell_quantity > 0
    assert planned_sell_quantity == sell_position.quantity
    assert planned_sell["reference_price"] is not None
    price_publication = planned_sell["price_publication"]
    assert price_publication is not None
    assert price_publication["publication_id"] == published_price_batch.publication.publication_id
    assert (
        price_publication["publication_hash"] == published_price_batch.publication.publication_hash
    )
    assert price_publication["bar_date"] == business_date.isoformat()
    plan_risk = plan["portfolio_risk"]
    assert plan_risk is not None
    assert plan_risk["outcome"] == "allowed", plan_risk["checks"]
    assert plan_risk["account_id"] == account_id
    assert plan_risk["policy_version"] == report["policy_version"]
    assert {item["raw_payload_sha256"] for item in plan_risk["sources"]} == source_hashes
    plan_scope = next(item for item in plan_risk["checks"] if item["dimension"] == "input_scope")
    policy_binding_fields = (
        "policy_snapshot_id",
        "policy_snapshot_hash",
        "policy_profile_key",
        "policy_profile_version",
        "policy_profile_content_hash",
        "policy_config_sha256",
    )
    for field in policy_binding_fields:
        assert plan_scope["details"][field] == input_scope["details"][field]
    assert (
        plan_scope["details"]["source_reference_bindings"]
        == input_scope["details"]["source_reference_bindings"]
    )
    original_pressure_by_asset = {
        row["asset_code"]: row for row in input_scope["details"]["sell_exit_pressure"]
    }
    for plan_pressure in plan_scope["details"]["sell_exit_pressure"]:
        original_pressure = original_pressure_by_asset[plan_pressure["asset_code"]]
        for shared_field in (
            "held_quantity",
            "available_quantity",
            "active_sell_remaining_quantity",
        ):
            assert plan_pressure[shared_field] == original_pressure[shared_field]
        if plan_pressure["asset_code"] == sell_asset:
            assert Decimal(plan_pressure["proposed_sell_quantity"]) == planned_sell_quantity
    plan_order_admission = plan_risk["order_admission"]
    assert plan_order_admission is not None
    assert any(
        row["order_id"] == f"preview:{sell_asset}:sell" and row["outcome"] == "allowed"
        for row in plan_order_admission["decisions"]
    )
    plan_capacity = next(
        item for item in plan_risk["checks"] if item["dimension"] == "liquidity_capacity"
    )
    assert plan_capacity["details"]["requested_purpose"] == "close_snapshot_simulation"
    ledger_before_order = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        sell_position.quantity,
        SimulatedTradeModel.objects.filter(account=account).count(),
    )
    reservations_before_order = SimulatedOrderReservationModel.objects.filter(
        account=account
    ).count()
    preview_response = client.post(
        reverse(
            "api_simulated_trading:order-preview",
            kwargs={"account_id": account_id},
        ),
        {
            "asset_code": sell_asset,
            "asset_name": names[sell_asset],
            "side": "sell",
            "quantity": format(planned_sell_quantity, "f"),
            "limit_price": format(retained_quote.last_price, "f"),
            "fee_budget": None,
            "reason": "ASH07 retained-source owner simulation",
            "market_purpose": "close_snapshot_simulation",
        },
        format="json",
        **common_headers,
    )
    (tmp_path / "owner-current-order-preview-response.json").write_bytes(preview_response.content)
    assert preview_response.status_code == 200, preview_response.content
    preview = preview_response.json()
    assert preview["read_only"] is True
    assert preview["purpose"] == "close_snapshot_simulation"
    assert preview["market_purpose"] == "close_snapshot_simulation"
    continuation_input = preview["continuation"]["input"]
    order_key = continuation_input["order_key"]
    preview_token = continuation_input["preview_token"]
    confirm_response = client.post(
        reverse(
            "api_simulated_trading:order-confirm",
            kwargs={"account_id": account_id, "order_key": order_key},
        ),
        {"preview_token": preview_token, "confirmed": True},
        format="json",
        **common_headers,
    )
    (tmp_path / "owner-current-order-confirm-response.json").write_bytes(confirm_response.content)
    assert confirm_response.status_code == 200, confirm_response.content
    assert confirm_response.json()["purpose"] == "close_snapshot_simulation"
    reservation = SimulatedOrderReservationModel.objects.get(
        pk=confirm_response.json()["order_id"],
        account_id=account_id,
    )
    assert reservation.side == "sell"
    assert reservation.shares_reserved == planned_sell_quantity
    assert reservation.shares_consumed == 0
    assert reservation.shares_released == 0
    account.refresh_from_db()
    sell_position.refresh_from_db()
    assert (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        sell_position.quantity,
        SimulatedTradeModel.objects.filter(account=account).count(),
    ) == ledger_before_order
    assert SimulatedOrderReservationModel.objects.filter(account=account).count() == (
        reservations_before_order + 1
    )

    held_report_response = client.get(
        report_url,
        secure=True,
        HTTP_ORIGIN="https://testserver",
    )
    assert held_report_response.status_code == 200, held_report_response.content
    held_report = held_report_response.json()
    (tmp_path / "owner-current-risk-with-reservation.json").write_text(
        json.dumps(held_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert held_report["account_id"] == account_id
    assert held_report["policy_version"] == report["policy_version"]
    assert held_report["outcome"] == "allowed", held_report["checks"]
    held_scope = next(item for item in held_report["checks"] if item["dimension"] == "input_scope")
    original_scope = next(item for item in report["checks"] if item["dimension"] == "input_scope")
    assert held_scope["details"]["source_reference_bindings"] == (
        original_scope["details"]["source_reference_bindings"]
    )
    pressure_rows = held_scope["details"]["sell_exit_pressure"]
    sell_pressure = next(item for item in pressure_rows if item["asset_code"] == sell_asset)
    assert Decimal(sell_pressure["held_quantity"]) == sell_position.quantity
    assert Decimal(sell_pressure["active_sell_remaining_quantity"]) == sell_position.quantity
    assert Decimal(sell_pressure["proposed_sell_quantity"]) == 0
    original_nav = next(
        item for item in report["checks"] if item["dimension"] == "pre_trade_gross_nav"
    )
    held_nav = next(
        item for item in held_report["checks"] if item["dimension"] == "pre_trade_gross_nav"
    )
    assert (
        held_nav["details"]["pre_trade_gross_nav"] == original_nav["details"]["pre_trade_gross_nav"]
    )
    for field in policy_binding_fields:
        assert held_scope["details"][field] == input_scope["details"][field]
    held_capacity = next(
        item for item in held_report["checks"] if item["dimension"] == "liquidity_capacity"
    )
    assert held_capacity["details"]["requested_purpose"] == "close_snapshot_simulation"
    held_source_hashes = {item["raw_payload_sha256"] for item in held_report["sources"]}
    assert held_source_hashes == source_hashes

    fill_at = timezone.now().astimezone(UTC)
    fill_quantity = reservation.quantity
    assert fill_quantity == planned_sell_quantity
    positions_before_fill = {
        position.asset_code: (
            cast(int, position.pk),
            position.quantity,
            position.available_quantity,
        )
        for position in positions
    }
    assert sell_asset in positions_before_fill
    assert positions_before_fill[sell_asset][1] == fill_quantity
    synthetic_fill = close_flow.LocalSimulatedFillEventV1(
        source_namespace="test.fixture.ash07-owner-close-fill",
        source_version="fixture-v1",
        source_event_id=f"ash07-fill-{uuid4().hex}",
        event_payload_hash=hashlib.sha256(
            b"explicit synthetic ASH07 close-snapshot fill event"
        ).hexdigest(),
        source_snapshot_id="test.fixture.synthetic-ash07-fill",
        source_snapshot_hash=hashlib.sha256(
            b"synthetic local fill fixture; not a market execution"
        ).hexdigest(),
        reservation_id=cast(int, reservation.pk),
        account_id=account_id,
        user_id=owner_id,
        order_idempotency_key=order_key,
        intent_payload_hash=reservation.intent_payload_hash,
        reservation_request_hash=reservation.reservation_request_hash,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        security_id=reservation.security_id,
        asset_code=reservation.asset_code,
        side=close_flow.SimulatedTradeSide.SELL,
        event_kind=close_flow.LocalSimulatedFillEventKind.FILL,
        quantity=fill_quantity,
        price=retained_quote.last_price,
        occurred_at=fill_at,
        source_observed_at=fill_at,
        source_available_at=fill_at,
        recorded_at=fill_at,
    )
    with transaction.atomic():
        fill_chain = close_flow._locked_fill_chain(
            reservation_row=reservation,
            using="default",
        )
        expected_fill = close_flow.prepare_order_reservation_fill(
            close_flow.OrderReservationFillRequest(
                fill_event_id=synthetic_fill.source_event_id,
                intent=fill_chain.intent,
                stored_intent_payload_hash=reservation.intent_payload_hash,
                reservation=fill_chain.reservation,
                fee_policy=fill_chain.fee_policy,
                fill_occurred_at=fill_at,
                quantity=fill_quantity,
                price=retained_quote.last_price,
                prior=fill_chain.accrual,
                close_order=False,
            )
        )
    settlement_proof = close_flow.build_order_fill_settlement_proof(
        calendar_evidence=calendar.calendar_evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=fill_at,
        settlement_exchange=calendar.calendar_evidence.snapshot.exchange,
        settlement_lag_sessions=cast(int, reservation.settlement_lag_sessions),
    )
    account.refresh_from_db()
    sell_position.refresh_from_db()
    cash_before_fill = account.current_cash
    market_value_before_fill = account.current_market_value
    sell_mark_before_fill = sell_position.market_value
    quantity_before_fill = sell_position.quantity
    risk_audit_count_before_fill = RiskPolicyAuditModel.objects.filter(
        actor_id=owner_id,
        action="portfolio_preexecution",
    ).count()
    fill_result = close_flow.DjangoSimulatedOrderFillRepository(
        event_reader=close_flow._EventReader(synthetic_fill, []),
        using="default",
        portfolio_risk_guard=ConfiguredPortfolioRiskLockedOrderGuard(using="default"),
    ).apply_fill_event(
        event=synthetic_fill,
        expected_event_payload_hash=synthetic_fill.event_payload_hash,
        settlement_proof=settlement_proof,
        clock=_LiveFillClock(),
    )
    assert fill_result.replayed is False
    assert fill_result.economics == expected_fill
    persisted_trade = SimulatedTradeModel.objects.get(
        pk=fill_result.trade_id,
        account_id=account_id,
    )
    expected_fees = expected_fill.incremental_fees
    persisted_fee_values = (
        persisted_trade.commission,
        persisted_trade.transfer_fee,
        persisted_trade.stamp_duty,
        persisted_trade.slippage,
    )
    assert persisted_trade.asset_code == sell_asset
    assert persisted_trade.action == close_flow.SimulatedTradeSide.SELL.value
    assert persisted_trade.quantity == fill_quantity
    assert persisted_trade.price == retained_quote.last_price
    assert persisted_trade.amount == expected_fill.gross_amount
    assert persisted_fee_values == (
        expected_fees.commission,
        expected_fees.transfer_fee,
        expected_fees.stamp_duty,
        expected_fees.slippage,
    )
    assert persisted_trade.total_cost == expected_fees.total_fee
    assert persisted_trade.fee_amounts_known is True
    assert any(value > 0 for value in persisted_fee_values)
    assert reservation.account_id == account_id
    assert reservation.owner_user_id == owner_id
    assert reservation.idempotency_key == order_key
    fill_receipt = SimulatedOrderFillReceiptModel.objects.get(
        reservation_id=reservation.pk,
        trade_id=persisted_trade.pk,
    )
    assert fill_receipt.reservation_id == reservation.pk
    assert fill_receipt.trade_id == persisted_trade.pk
    assert fill_receipt.source_event_id == synthetic_fill.source_event_id
    assert fill_receipt.source_namespace == synthetic_fill.source_namespace
    assert fill_receipt.plan_snapshot_hash == reservation.plan_snapshot_hash
    assert fill_receipt.receipt_hash == persisted_trade.request_payload_hash
    event_payload = fill_receipt.source_event_payload
    assert event_payload["reservation_id"] == reservation.pk
    assert event_payload["account_id"] == account_id
    assert event_payload["user_id"] == owner_id
    assert event_payload["order_idempotency_key"] == order_key
    assert event_payload["plan_snapshot_hash"] == reservation.plan_snapshot_hash
    receipt_identity = fill_receipt.economics_payload["reservation_identity"]
    assert receipt_identity["account_id"] == account_id
    assert receipt_identity["security_id"] == reservation.security_id
    assert receipt_identity["idempotency_key"] == order_key
    receipt_fees = fill_receipt.economics_payload["incremental_fees"]
    assert Decimal(str(receipt_fees["commission"])) == expected_fees.commission
    assert Decimal(str(receipt_fees["transfer_fee"])) == expected_fees.transfer_fee
    assert Decimal(str(receipt_fees["stamp_duty"])) == expected_fees.stamp_duty
    assert Decimal(str(receipt_fees["slippage"])) == expected_fees.slippage
    assert Decimal(str(receipt_fees["total_fee"])) == expected_fees.total_fee
    assert (
        RiskPolicyAuditModel.objects.filter(
            actor_id=owner_id,
            action="portfolio_preexecution",
        ).count()
        == risk_audit_count_before_fill + 1
    )
    fill_audit = (
        RiskPolicyAuditModel.objects.filter(
            actor_id=owner_id,
            action="portfolio_preexecution",
            after__account_id=account_id,
        )
        .order_by("-created_at")
        .first()
    )
    assert fill_audit is not None
    assert fill_audit.after["idempotency_key"] == synthetic_fill.source_event_id
    locked_report = fill_audit.after["risk_result"]
    assert locked_report["account_id"] == account_id
    assert locked_report["policy_version"] == report["policy_version"]
    assert locked_report["scope"] == "simulation_only"
    assert locked_report["must_not_execute"] is True
    assert fill_audit.after["policy_binding_sha256"]
    locked_source_hashes = {item["raw_payload_sha256"] for item in locked_report["sources"]}
    assert locked_source_hashes == held_source_hashes
    locked_scope = next(
        item for item in locked_report["checks"] if item["dimension"] == "input_scope"
    )
    for field in policy_binding_fields:
        assert locked_scope["details"][field] == input_scope["details"][field]
    locked_capacity = next(
        item for item in locked_report["checks"] if item["dimension"] == "liquidity_capacity"
    )
    assert locked_capacity["details"]["requested_purpose"] == "close_snapshot_simulation"
    locked_sell_pressure = next(
        item
        for item in locked_scope["details"]["sell_exit_pressure"]
        if item["asset_code"] == sell_asset
    )
    assert Decimal(locked_sell_pressure["held_quantity"]) == fill_quantity
    assert Decimal(locked_sell_pressure["active_sell_remaining_quantity"]) == fill_quantity
    assert "test.fixture" in synthetic_fill.source_namespace

    reservation.refresh_from_db()
    account.refresh_from_db()
    assert quantity_before_fill == fill_quantity
    assert not PositionModel.objects.filter(
        pk=positions_before_fill[sell_asset][0],
        account_id=account_id,
    ).exists()
    persisted_positions = tuple(
        PositionModel.objects.filter(account_id=account_id).order_by("asset_code", "pk")
    )
    surviving_assets = set(positions_before_fill).difference({sell_asset})
    persisted_by_asset = {position.asset_code: position for position in persisted_positions}
    assert set(persisted_by_asset) == surviving_assets
    for asset_code in surviving_assets:
        original_id, original_quantity, original_available = positions_before_fill[asset_code]
        persisted_position = persisted_by_asset[asset_code]
        assert persisted_position.pk == original_id
        assert persisted_position.quantity == original_quantity
        assert persisted_position.available_quantity == original_available
    net_proceeds = expected_fill.gross_amount - expected_fill.incremental_fees.total_fee
    assert account.current_cash == cash_before_fill + net_proceeds
    assert account.current_market_value == market_value_before_fill - sell_mark_before_fill
    assert account.total_value == account.current_cash + account.current_market_value
    assert quantity_before_fill - fill_quantity == 0
    post_fill_response = client.get(
        report_url,
        secure=True,
        HTTP_ORIGIN="https://testserver",
    )
    assert post_fill_response.status_code == 200, post_fill_response.content
    post_fill_report = post_fill_response.json()
    (tmp_path / "owner-current-risk-post-fill.json").write_text(
        json.dumps(post_fill_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert post_fill_report["account_id"] == account_id
    assert post_fill_report["policy_version"] == report["policy_version"]
    assert post_fill_report["outcome"] == "allowed", post_fill_report["checks"]
    retained_prices = {
        quote["risk_asset_code"]: Decimal(quote["quote"]["last_price"])
        for quote in candidate["sina_quotes"]
    }
    expected_holdings_value = sum(
        (
            position.quantity * retained_prices[position.asset_code]
            for position in persisted_positions
        ),
        Decimal("0"),
    )
    post_fill_nav = next(
        item for item in post_fill_report["checks"] if item["dimension"] == "pre_trade_gross_nav"
    )
    assert Decimal(post_fill_nav["details"]["cash"]) == account.current_cash
    assert Decimal(post_fill_nav["details"]["actual_holdings_value"]) == expected_holdings_value
    assert Decimal(post_fill_nav["details"]["pre_trade_gross_nav"]) == (
        account.current_cash + expected_holdings_value
    )
    post_fill_scope = next(
        item for item in post_fill_report["checks"] if item["dimension"] == "input_scope"
    )
    for field in policy_binding_fields:
        assert post_fill_scope["details"][field] == input_scope["details"][field]
    binding_fields = ("kind", "asset_code", "security_id", "manifest_sha256", "source_record_id")
    original_pin_tuples = {
        tuple(row[field] for field in binding_fields)
        for row in input_scope["details"]["source_reference_bindings"]
    }
    post_fill_pin_tuples = {
        tuple(row[field] for field in binding_fields)
        for row in post_fill_scope["details"]["source_reference_bindings"]
    }
    assert post_fill_pin_tuples.issubset(original_pin_tuples)
    post_fill_source_hashes = {item["raw_payload_sha256"] for item in post_fill_report["sources"]}
    assert post_fill_source_hashes.issubset(source_hashes)
    for surviving_asset in sorted(surviving_assets):
        assert {pin for pin in post_fill_pin_tuples if pin[1] == surviving_asset} == {
            pin for pin in original_pin_tuples if pin[1] == surviving_asset
        }
        original_survivor_hashes = _source_body_hashes_for_asset(
            sources=report["sources"],
            source_reference_bindings=input_scope["details"]["source_reference_bindings"],
            asset_code=surviving_asset,
        )
        post_survivor_hashes = _source_body_hashes_for_asset(
            sources=post_fill_report["sources"],
            source_reference_bindings=post_fill_scope["details"]["source_reference_bindings"],
            asset_code=surviving_asset,
        )
        assert post_survivor_hashes == original_survivor_hashes
    post_capacity = next(
        item for item in post_fill_report["checks"] if item["dimension"] == "liquidity_capacity"
    )
    assert post_capacity["details"]["requested_purpose"] == "close_snapshot_simulation"
    post_fill_rows = post_fill_scope["details"]["sell_exit_pressure"]
    post_fill_quantities = {
        row["asset_code"]: Decimal(row["held_quantity"]) for row in post_fill_rows
    }
    for position in persisted_positions:
        assert post_fill_quantities.get(position.asset_code, Decimal("0")) == position.quantity
    expected_positive_quantities = {
        position.asset_code: position.quantity
        for position in persisted_positions
        if position.quantity > 0
    }
    reported_positive_quantities = {
        asset_code: quantity
        for asset_code, quantity in post_fill_quantities.items()
        if quantity > 0
    }
    assert reported_positive_quantities == expected_positive_quantities
    sold_after_fill = next(
        (item for item in post_fill_rows if item["asset_code"] == sell_asset),
        None,
    )
    if sold_after_fill is not None:
        sold_held = sold_after_fill.get("held_quantity")
        sold_active = sold_after_fill.get("active_sell_remaining_quantity")
        assert type(sold_held) is str
        assert type(sold_active) is str
        assert Decimal(sold_held) == 0
        assert Decimal(sold_active) == 0
    assert reservation.status == SimulatedOrderReservationModel.STATUS_COMPLETED
    assert reservation.filled_quantity == reservation.quantity
    assert reservation.shares_consumed == reservation.quantity
    assert reservation.shares_released == 0
    assert not SimulatedOrderReservationModel.objects.filter(
        account_id=account_id,
        asset_code=sell_asset,
        side=close_flow.SimulatedTradeSide.SELL.value,
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    ).exists()
    assert SimulatedTradeModel.objects.filter(account=account).count() == (
        ledger_before_order[4] + 1
    )

    fill_evidence_summary = {
        "scope": "simulation_only",
        "event": {
            "source_namespace": synthetic_fill.source_namespace,
            "source_event_id": synthetic_fill.source_event_id,
            "occurred_at": synthetic_fill.occurred_at.isoformat(),
            "source_snapshot_hash": synthetic_fill.source_snapshot_hash,
            "is_synthetic_fixture": True,
        },
        "market_input": {
            "basis": "retained_public_sina_close_snapshot",
            "purpose": "close_snapshot_simulation",
            "asset_code": sell_asset,
            "last_price": str(retained_quote.last_price),
            "risk_source_hashes": sorted(locked_source_hashes),
            "must_not_execute": True,
        },
        "trade": {
            "trade_id": persisted_trade.pk,
            "security_id": reservation.security_id,
            "quantity": str(persisted_trade.quantity),
            "gross_amount": str(persisted_trade.amount),
            "fees": {
                "commission": str(persisted_trade.commission),
                "transfer_fee": str(persisted_trade.transfer_fee),
                "stamp_duty": str(persisted_trade.stamp_duty),
                "slippage": str(persisted_trade.slippage),
                "total": str(persisted_trade.total_cost),
            },
            "receipt_hash": fill_receipt.receipt_hash,
            "reservation_status": reservation.status,
        },
        "account": {
            "cash": str(account.current_cash),
            "market_value": str(account.current_market_value),
            "total_value": str(account.total_value),
            "positions": [
                {
                    "asset_code": position.asset_code,
                    "quantity": str(position.quantity),
                    "available_quantity": str(position.available_quantity),
                }
                for position in persisted_positions
            ],
        },
        "post_fill_risk": {
            "outcome": post_fill_report["outcome"],
            "source_hashes": sorted(post_fill_source_hashes),
            "nav": post_fill_nav["details"]["pre_trade_gross_nav"],
        },
    }
    (tmp_path / "owner-current-fill-receipt-summary.json").write_text(
        json.dumps(fill_evidence_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
