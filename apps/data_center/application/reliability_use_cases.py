"""Decision-data reliability repair orchestration for Data Center."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from apps.audit.application.data_repair_audit import (
    DataRepairAuditObservation,
    RepairPublicationEvidence,
    RepairSectionEvidence,
)
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.decision_read_audit import (
    PublicationDecisionReadRecorder,
    RecordPublicationDecisionReadCommand,
)
from apps.data_center.application.dtos import (
    DecisionReliabilityRepairReport,
    DecisionReliabilityRepairRequest,
    DecisionReliabilitySection,
    LatestQuoteRequest,
    MacroSeriesRequest,
    SyncMacroRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
)
from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.application.query_use_cases import (
    QueryLatestQuoteUseCase,
    QueryMacroSeriesUseCase,
)
from apps.data_center.application.sync_identity import (
    IssueSyncExecutionIdentityCommand,
    IssueSyncExecutionIdentityUseCase,
    SyncExecutionIdentity,
    SyncExecutionIdentityIssuer,
)
from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataRepairAuditWriter,
)
from apps.data_center.application.sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    SyncMacroUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
)
from shared.date_utils import business_day_age

logger = logging.getLogger(__name__)

DEFAULT_DECISION_MACRO_INDICATORS = (
    "CN_PMI",
    "CN_NEW_CREDIT",
    "CN_CPI_NATIONAL_YOY",
    "CN_SHIBOR",
    "CN_LPR",
    "CN_M2",
)
DEFAULT_DECISION_ASSET_CODES = ("510300.SH", "000300.SH")
AKSHARE_MACRO_INDICATORS = frozenset(DEFAULT_DECISION_MACRO_INDICATORS)
TUSHARE_CPI_INDICATORS = frozenset(
    {
        "CN_CPI",
        "CN_CPI_NATIONAL_YOY",
        "CN_CPI_NATIONAL_MOM",
        "CN_CPI_URBAN_YOY",
        "CN_CPI_URBAN_MOM",
        "CN_CPI_RURAL_YOY",
        "CN_CPI_RURAL_MOM",
    }
)
_SOURCE_TYPE_CAPABILITIES = SOURCE_TYPE_CAPABILITIES


def _failure_evidence(exc: BaseException) -> dict[str, str]:
    """Return stable failure evidence without persisting provider payloads or secrets."""

    return {
        "error_type": exc.__class__.__name__,
        "error_message": "operation_failed",
    }


def _failure_reason(prefix: str, exc: BaseException) -> str:
    """Build a decision-safe failure reason from an exception class only."""

    return f"{prefix} ({exc.__class__.__name__})"


class RepairDecisionDataReliabilityUseCase:
    """Repair and re-check the data chain required for actionable decisions."""

    def __init__(
        self,
        *,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        macro_fact_repo: MacroFactRepositoryProtocol,
        indicator_catalog_repo: IndicatorCatalogRepositoryProtocol,
        indicator_unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        price_bar_repo: PriceBarRepositoryProtocol,
        quote_snapshot_repo: QuoteSnapshotRepositoryProtocol,
        macro_sync_use_case: SyncMacroUseCase,
        price_sync_use_case: SyncPriceUseCase,
        quote_sync_use_case: SyncQuoteUseCase,
        decision_read_recorder: PublicationDecisionReadRecorder,
        sync_identity_issuer: SyncExecutionIdentityIssuer,
        repair_run_identity_unit_of_work: DataCenterSyncUnitOfWork,
        data_repair_audit_writer: DataRepairAuditWriter,
        clock: DataCenterSyncClock,
        pulse_refresher: Callable[[date], Any] | None = None,
        alpha_refresher: Callable[[date, int | None], dict[str, Any]] | None = None,
        alpha_status_reader: Callable[[date, int | None], dict[str, Any]] | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._macro_fact_repo = macro_fact_repo
        self._indicator_catalog_repo = indicator_catalog_repo
        self._indicator_unit_rule_repo = indicator_unit_rule_repo
        self._price_bar_repo = price_bar_repo
        self._quote_snapshot_repo = quote_snapshot_repo
        self._macro_sync_use_case = macro_sync_use_case
        self._price_sync_use_case = price_sync_use_case
        self._quote_sync_use_case = quote_sync_use_case
        self._decision_read_recorder = decision_read_recorder
        self._sync_identity_use_case = IssueSyncExecutionIdentityUseCase(sync_identity_issuer)
        self._repair_run_identity_unit_of_work = repair_run_identity_unit_of_work
        self._data_repair_audit_writer = data_repair_audit_writer
        self._clock = clock
        self._pulse_refresher = pulse_refresher
        self._alpha_refresher = alpha_refresher
        self._alpha_status_reader = alpha_status_reader

    def execute(
        self,
        request: DecisionReliabilityRepairRequest,
    ) -> DecisionReliabilityRepairReport:
        identity = self._issue_repair_identity()
        target_date = request.target_date or date.today()
        publication_evidence: list[RepairPublicationEvidence] = []
        asset_codes = self._normalize_unique(
            request.asset_codes or list(DEFAULT_DECISION_ASSET_CODES)
        )
        macro_codes = self._normalize_unique(
            request.macro_indicator_codes or list(DEFAULT_DECISION_MACRO_INDICATORS)
        )

        provider_bootstrap = self._ensure_default_akshare_provider()
        macro_status = self._run_repair_section(
            "macro",
            lambda: self._repair_macro_inputs(
                request,
                target_date,
                macro_codes,
                publication_evidence,
            ),
        )
        quote_status = self._run_repair_section(
            "quote",
            lambda: self._repair_quote_inputs(
                request,
                target_date,
                asset_codes,
                publication_evidence,
            ),
        )
        pulse_status = self._run_repair_section(
            "pulse",
            lambda: self._repair_pulse(request, target_date),
        )
        alpha_status = self._run_repair_section(
            "alpha",
            lambda: self._repair_alpha(request, target_date),
        )

        sections = (
            self._section_evidence("macro", macro_status),
            self._section_evidence("quote", quote_status),
            self._section_evidence("pulse", pulse_status),
            self._section_evidence("alpha", alpha_status),
        )
        outcome = self._repair_outcome(sections)
        exact_publications = tuple(
            sorted(
                publication_evidence,
                key=lambda item: (item.dataset_key, item.publication_id),
            )
        )
        report = DecisionReliabilityRepairReport(
            target_date=target_date,
            portfolio_id=request.portfolio_id,
            macro_status=macro_status,
            quote_status=quote_status,
            pulse_status=pulse_status,
            alpha_status=alpha_status,
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            identity_hash=identity.identity_hash,
            audit_outcome=outcome,
            publication_ids=tuple(item.publication_id for item in exact_publications),
            provider_bootstrap=provider_bootstrap,
        )
        completed_at = self._clock.now()
        self._data_repair_audit_writer.write(
            DataRepairAuditObservation(
                identity=identity,
                target_date=target_date,
                sections=sections,
                publications=exact_publications,
                outcome=outcome,
                occurred_at=completed_at,
                recorded_at=completed_at,
            )
        )
        return report

    def _issue_repair_identity(self) -> SyncExecutionIdentity:
        """Persist one parent identity before any child repair section runs."""

        with self._repair_run_identity_unit_of_work.atomic():
            return self._sync_identity_use_case.execute(
                IssueSyncExecutionIdentityCommand(
                    dataset_key="decision.reliability.repair",
                    provider_name="data-center-repair",
                )
            )

    @staticmethod
    def _section_evidence(
        section_key: str,
        section: DecisionReliabilitySection,
    ) -> RepairSectionEvidence:
        """Reduce one user-facing section to sanitized parent-run evidence."""

        blocker_count = len(section.blocked_reasons)
        if section.must_not_use_for_decision and blocker_count == 0:
            blocker_count = 1
        return RepairSectionEvidence(
            section_key=section_key,
            status=section.status,
            must_not_use_for_decision=section.must_not_use_for_decision,
            remaining_blocker_count=blocker_count,
        )

    @staticmethod
    def _repair_outcome(
        sections: tuple[RepairSectionEvidence, ...],
    ) -> AuditOutcome:
        """Derive the registered parent completion outcome from all sections."""

        if any(section.status == "failed" for section in sections):
            return AuditOutcome.FAILED
        if any(section.must_not_use_for_decision for section in sections):
            return AuditOutcome.PARTIAL
        return AuditOutcome.SUCCESS

    def _run_repair_section(
        self,
        section_name: str,
        callback: Callable[[], DecisionReliabilitySection],
    ) -> DecisionReliabilitySection:
        """Run one repair section without letting it abort later sections."""

        try:
            return callback()
        except Exception as exc:
            error_type = exc.__class__.__name__
            logger.error(
                "Decision reliability %s repair failed (%s)",
                section_name,
                error_type,
            )
            return DecisionReliabilitySection(
                status="failed",
                must_not_use_for_decision=True,
                blocked_reasons=[f"{section_name} 修复异常 ({error_type})"],
                details={
                    "error_type": error_type,
                    "error_message": "repair_failed",
                },
            )

    def _ensure_default_akshare_provider(self) -> dict[str, Any]:
        existing = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.source_type == "akshare"
        ]
        active = [provider for provider in existing if provider.is_active]
        if active:
            return {
                "status": "exists",
                "provider_id": active[0].id,
                "provider_name": active[0].name,
            }
        if existing:
            return {
                "status": "inactive_exists",
                "provider_id": existing[0].id,
                "provider_name": existing[0].name,
                "message": "已存在非启用 AKShare provider，未覆盖用户配置。",
            }

        saved = self._provider_repo.save(
            ProviderConfig(
                id=None,
                name="AKShare Public",
                source_type="akshare",
                is_active=True,
                priority=10,
                api_key="",
                api_secret="",
                http_url="",
                api_endpoint="",
                extra_config={"managed_by": "decision_reliability_repair"},
                description="Default public AKShare provider for decision data repair.",
            )
        )
        return {
            "status": "created",
            "provider_id": saved.id,
            "provider_name": saved.name,
        }

    @staticmethod
    def _collect_publication_evidence(
        target: list[RepairPublicationEvidence],
        *,
        sync_result: SyncResult,
        dataset_key: str,
    ) -> None:
        """Collect one complete child publication identity or fail closed."""

        publication_id = sync_result.publication_id
        publication_version = sync_result.publication_version
        publication_hash = sync_result.publication_hash
        if publication_id is None and publication_version is None and publication_hash is None:
            return
        if publication_id is None or publication_version is None or publication_hash is None:
            raise ValueError("repair child returned incomplete publication evidence")
        if sync_result.run_id is None or sync_result.ingested_run_id is None:
            raise ValueError("repair child publication lacks exact sync identity")
        evidence = RepairPublicationEvidence(
            publication_id=publication_id,
            publication_version=publication_version,
            publication_hash=publication_hash,
            dataset_key=dataset_key,
        )
        matches = [item for item in target if item.publication_id == evidence.publication_id]
        if matches and matches[0] != evidence:
            raise ValueError("repair child publication identity is inconsistent")
        if not matches:
            target.append(evidence)

    def _repair_macro_inputs(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
        macro_codes: list[str],
        publication_evidence: list[RepairPublicationEvidence],
    ) -> DecisionReliabilitySection:
        start_date = target_date - timedelta(days=max(request.macro_lookback_days, 30))
        details: dict[str, Any] = {"indicators": {}}
        blocked_reasons: list[str] = []
        failed = False

        for indicator_code in macro_codes:
            provider = self._select_macro_provider(indicator_code)
            indicator_details: dict[str, Any] = {}
            if provider is None or provider.id is None:
                reason = f"{indicator_code}: 无可用宏观 provider。"
                blocked_reasons.append(reason)
                details["indicators"][indicator_code] = {
                    "status": "blocked",
                    "blocked_reason": reason,
                }
                continue

            indicator_details["provider_id"] = provider.id
            indicator_details["provider_name"] = provider.name
            sync_result: SyncResult | None = None
            try:
                sync_result = self._macro_sync_use_case.execute(
                    SyncMacroRequest(
                        provider_id=provider.id,
                        indicator_code=indicator_code,
                        start=start_date,
                        end=target_date,
                    )
                )
                indicator_details["sync"] = sync_result.to_dict()
                self._collect_publication_evidence(
                    publication_evidence,
                    sync_result=sync_result,
                    dataset_key="macro.fact",
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                failed = True
                blocked_reasons.append(_failure_reason(f"{indicator_code}: 同步失败", exc))
                indicator_details["sync"] = {
                    "status": "failed",
                    **_failure_evidence(exc),
                }

            query = QueryMacroSeriesUseCase(
                self._macro_fact_repo,
                self._indicator_catalog_repo,
                self._indicator_unit_rule_repo,
            ).execute(
                MacroSeriesRequest(
                    indicator_code=indicator_code,
                    end=target_date,
                    limit=1,
                )
            )
            query_dict = query.to_dict()
            indicator_details["freshness"] = query_dict["contract"]
            if query.must_not_use_for_decision:
                blocked_reasons.append(
                    f"{indicator_code}: {query.blocked_reason or query.freshness_status}"
                )
            if sync_result is not None:
                self._decision_read_recorder.execute(
                    RecordPublicationDecisionReadCommand(
                        sync_result=sync_result,
                        dataset_key="macro.fact",
                        publication_key=indicator_code,
                        decision_key=f"decision-reliability-macro:{indicator_code}",
                        freshness_status=query.freshness_status,
                        must_not_use_for_decision=query.must_not_use_for_decision,
                        blocked_reason=(
                            (
                                "core_data_coverage_unavailable"
                                if query.total < 1 or query.freshness_status == "missing"
                                else "provider_capability_success_stale"
                            )
                            if query.must_not_use_for_decision
                            else None
                        ),
                    )
                )
            details["indicators"][indicator_code] = indicator_details

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"

        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _repair_quote_inputs(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
        asset_codes: list[str],
        publication_evidence: list[RepairPublicationEvidence],
    ) -> DecisionReliabilitySection:
        details: dict[str, Any] = {"quotes": {}, "prices": {}}
        blocked_reasons: list[str] = []
        failed = False
        quote_sync_result: SyncResult | None = None
        price_sync_results: dict[str, SyncResult] = {}

        quote_provider = self._select_provider_by_types(
            ("akshare", "eastmoney", "tushare"),
            DataCapability.REALTIME_QUOTE.value,
        )
        if quote_provider is None or quote_provider.id is None:
            blocked_reasons.append("无可用实时行情 provider。")
        else:
            try:
                quote_sync_result = self._quote_sync_use_case.execute(
                    SyncQuoteRequest(
                        provider_id=quote_provider.id,
                        asset_codes=asset_codes,
                    )
                )
                details["quote_sync"] = quote_sync_result.to_dict()
                self._collect_publication_evidence(
                    publication_evidence,
                    sync_result=quote_sync_result,
                    dataset_key="equity.quote.snapshot",
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                failed = True
                blocked_reasons.append(_failure_reason("实时行情同步失败", exc))
                details["quote_sync"] = {
                    "status": "failed",
                    **_failure_evidence(exc),
                }

        price_provider = self._select_provider_by_types(
            ("akshare", "eastmoney", "tushare"),
            DataCapability.HISTORICAL_PRICE.value,
        )
        if price_provider is None or price_provider.id is None:
            blocked_reasons.append("无可用历史价格 provider。")
        else:
            for asset_code in asset_codes:
                try:
                    sync_result = self._price_sync_use_case.execute(
                        SyncPriceRequest(
                            provider_id=price_provider.id,
                            asset_code=asset_code,
                            start=target_date - timedelta(days=max(request.price_lookback_days, 5)),
                            end=target_date,
                        )
                    )
                    price_sync_results[asset_code] = sync_result
                    details["prices"][asset_code] = {"sync": sync_result.to_dict()}
                    self._collect_publication_evidence(
                        publication_evidence,
                        sync_result=sync_result,
                        dataset_key="equity.price.bar",
                    )
                except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                    failed = True
                    blocked_reasons.append(_failure_reason(f"{asset_code}: 历史价格同步失败", exc))
                    details["prices"][asset_code] = {
                        "sync": {"status": "failed", **_failure_evidence(exc)}
                    }

        quote_query = QueryLatestQuoteUseCase(self._quote_snapshot_repo)
        quote_freshness_statuses: list[str] = []
        quote_missing = False
        quote_blocked = False
        for asset_code in asset_codes:
            quote = quote_query.execute(
                LatestQuoteRequest(
                    asset_code=asset_code,
                    max_age_hours=request.quote_max_age_hours,
                )
            )
            if quote is None:
                quote_missing = True
                quote_blocked = True
                reason = f"{asset_code}: 无可用最新行情。"
                blocked_reasons.append(reason)
                details["quotes"][asset_code] = {
                    "status": "blocked",
                    "blocked_reason": reason,
                }
            else:
                quote_freshness_statuses.append(quote.freshness_status)
                details["quotes"][asset_code] = quote.to_dict()
                if quote.must_not_use_for_decision:
                    quote_blocked = True
                    blocked_reasons.append(
                        f"{asset_code}: {quote.blocked_reason or quote.freshness_status}"
                    )

        quote_freshness_status = "fresh"
        if quote_missing:
            quote_freshness_status = "missing"
        elif "stale" in quote_freshness_statuses:
            quote_freshness_status = "stale"
        elif any(status != "fresh" for status in quote_freshness_statuses):
            quote_freshness_status = "latest_completed_session"
        if quote_sync_result is not None:
            self._decision_read_recorder.execute(
                RecordPublicationDecisionReadCommand(
                    sync_result=quote_sync_result,
                    dataset_key="equity.quote.snapshot",
                    publication_key="current",
                    decision_key="decision-reliability-quotes",
                    freshness_status=quote_freshness_status,
                    must_not_use_for_decision=quote_blocked,
                    blocked_reason=(
                        "core_data_coverage_unavailable"
                        if quote_missing
                        else ("provider_capability_success_stale" if quote_blocked else None)
                    ),
                )
            )

        for asset_code in asset_codes:
            latest_bar = self._price_bar_repo.get_latest(asset_code)
            price_details = dict(details["prices"].get(asset_code) or {})
            price_details["latest_bar_date"] = (
                latest_bar.bar_date.isoformat() if latest_bar else None
            )
            price_freshness_status = "fresh"
            price_blocked_reason: str | None = None
            if latest_bar is None:
                price_freshness_status = "missing"
                price_blocked_reason = "core_data_coverage_unavailable"
                blocked_reasons.append(f"{asset_code}: 无可用历史价格。")
            elif latest_bar.bar_date < target_date:
                lag_days = business_day_age(latest_bar.bar_date, target_date)
                price_details["lag_days"] = lag_days
                if lag_days <= 3:
                    price_freshness_status = "latest_completed_session"
                else:
                    price_freshness_status = "stale"
                    price_blocked_reason = "provider_capability_success_stale"
                    blocked_reasons.append(
                        f"{asset_code}: 最新价格日线仅到 {latest_bar.bar_date.isoformat()}。"
                    )
            price_details["freshness_status"] = price_freshness_status
            details["prices"][asset_code] = price_details
            price_sync_result = price_sync_results.get(asset_code)
            if price_sync_result is not None:
                self._decision_read_recorder.execute(
                    RecordPublicationDecisionReadCommand(
                        sync_result=price_sync_result,
                        dataset_key="equity.price.bar",
                        publication_key="current",
                        decision_key=f"decision-reliability-price:{asset_code}",
                        freshness_status=price_freshness_status,
                        must_not_use_for_decision=price_blocked_reason is not None,
                        blocked_reason=price_blocked_reason,
                    )
                )

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"
        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _repair_pulse(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
    ) -> DecisionReliabilitySection:
        if not request.repair_pulse:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=False,
                details={"message": "Pulse repair disabled by request."},
            )
        if self._pulse_refresher is None:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=True,
                blocked_reasons=["Pulse refresher 未配置。"],
            )

        try:
            snapshot = self._pulse_refresher(target_date)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            return DecisionReliabilitySection(
                status="failed",
                must_not_use_for_decision=True,
                blocked_reasons=[_failure_reason("Pulse 重算失败", exc)],
                details=_failure_evidence(exc),
            )

        if snapshot is None:
            return DecisionReliabilitySection(
                status="blocked",
                must_not_use_for_decision=True,
                blocked_reasons=["Pulse 重算后仍无可用快照。"],
            )

        is_reliable = bool(getattr(snapshot, "is_reliable", False))
        stale_codes = [
            getattr(reading, "code", "")
            for reading in getattr(snapshot, "indicator_readings", []) or []
            if getattr(reading, "is_stale", False)
        ]
        observed_at = getattr(snapshot, "observed_at", None)
        details = {
            "observed_at": observed_at.isoformat() if observed_at else None,
            "data_source": getattr(snapshot, "data_source", ""),
            "is_reliable": is_reliable,
            "stale_indicator_count": getattr(snapshot, "stale_indicator_count", 0),
            "stale_indicator_codes": [code for code in stale_codes if code],
        }
        if is_reliable and not stale_codes:
            return DecisionReliabilitySection(
                status="ready",
                must_not_use_for_decision=False,
                details=details,
            )
        return DecisionReliabilitySection(
            status="blocked",
            must_not_use_for_decision=True,
            blocked_reasons=["Pulse 数据未通过 freshness/reliability 复验。"],
            details=details,
        )

    def _repair_alpha(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
    ) -> DecisionReliabilitySection:
        if not request.repair_alpha:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=False,
                details={"message": "Alpha repair disabled by request."},
            )
        if request.portfolio_id is None:
            return DecisionReliabilitySection(
                status="blocked",
                must_not_use_for_decision=True,
                blocked_reasons=["Alpha readiness 需要 portfolio_id。"],
            )

        details: dict[str, Any] = {}
        blocked_reasons: list[str] = []
        failed = False
        if self._alpha_refresher is not None:
            try:
                repair_payload = self._alpha_refresher(
                    target_date,
                    request.portfolio_id,
                )
                details["repair"] = repair_payload
                if repair_payload.get("status") in {"failed", "queue_failed"}:
                    failed = True
                    message = (
                        repair_payload.get("qlib_result", {}).get("error_message")
                        or repair_payload.get("message")
                        or repair_payload.get("status")
                    )
                    blocked_reasons.append(f"Alpha 修复失败: {message}")
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                failed = True
                blocked_reasons.append(_failure_reason("Alpha 修复失败", exc))
                details["repair"] = {
                    "status": "failed",
                    **_failure_evidence(exc),
                }

        status_payload: dict[str, Any] = {}
        if self._alpha_status_reader is not None:
            try:
                status_payload = self._alpha_status_reader(
                    target_date,
                    request.portfolio_id,
                )
                details["readiness"] = status_payload
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                failed = True
                blocked_reasons.append(_failure_reason("Alpha readiness 读取失败", exc))
                details["readiness"] = {
                    "status": "failed",
                    **_failure_evidence(exc),
                }

        recommendation_ready = bool(status_payload.get("recommendation_ready", False))
        requested_trade_date = str(
            status_payload.get("requested_trade_date") or target_date.isoformat()
        )
        verified_asof_date = str(status_payload.get("verified_asof_date") or "")
        scope_verified = status_payload.get("scope_verification_status") == "verified"
        latest_completed_session_result = (
            bool(status_payload.get("latest_completed_session_result", False))
            or status_payload.get("freshness_status") == "latest_completed_session"
        )
        if not recommendation_ready:
            blocked_reasons.append("Dashboard Alpha 尚未产出 actionable 推荐。")
        if (
            verified_asof_date
            and verified_asof_date != requested_trade_date
            and not latest_completed_session_result
        ):
            blocked_reasons.append(
                f"Alpha asof_date={verified_asof_date}，未达到请求交易日 {requested_trade_date}。"
            )
        if not scope_verified:
            blocked_reasons.append("Alpha scope 未通过 verified 校验。")

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"

        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _select_macro_provider(self, indicator_code: str) -> ProviderConfig | None:
        if indicator_code in TUSHARE_CPI_INDICATORS:
            provider = self._select_provider_by_types(
                ("tushare",),
                DataCapability.MACRO.value,
            )
            if provider is not None and str(provider.api_key or "").strip():
                return provider
        if indicator_code in AKSHARE_MACRO_INDICATORS:
            provider = self._select_provider_by_types(
                ("akshare",),
                DataCapability.MACRO.value,
            )
            if provider is not None:
                return provider
        return self._select_provider_by_types(
            ("akshare", "tushare", "fred", "wind", "choice"),
            DataCapability.MACRO.value,
        )

    def _select_provider_by_types(
        self,
        source_types: tuple[str, ...],
        capability: str,
    ) -> ProviderConfig | None:
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.is_active
            and provider.source_type in source_types
            and capability in _SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
        ]
        providers.sort(
            key=lambda provider: (source_types.index(provider.source_type), provider.priority)
        )
        return providers[0] if providers else None

    @staticmethod
    def _normalize_unique(values: list[str] | tuple[str, ...]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value).strip().upper()
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized


__all__ = [
    "AKSHARE_MACRO_INDICATORS",
    "DEFAULT_DECISION_ASSET_CODES",
    "DEFAULT_DECISION_MACRO_INDICATORS",
    "RepairDecisionDataReliabilityUseCase",
    "TUSHARE_CPI_INDICATORS",
]
