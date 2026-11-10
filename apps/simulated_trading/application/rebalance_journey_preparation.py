"""Prepare immutable portfolio plan revisions from one captured server context."""

from __future__ import annotations

from datetime import datetime, tzinfo
from decimal import Decimal
from typing import Literal

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanRevisionClock,
    TransitionPlanRevisionRequest,
)
from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderSpecification,
    TransitionPlanRevision,
    TransitionPlanRevisionPreparation,
    build_transition_plan_revision,
)
from apps.portfolio.domain.transition_plan_revision_basis import (
    TransitionPlanBasis,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanSourceBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetInputs,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.portfolio_risk_snapshot import (
    exact_decimal_product,
)
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    RebalanceJourneyEventCoveragePinner,
)
from apps.simulated_trading.application.rebalance_journey_event_refresh import (
    RebalanceJourneyOfficialEventRefresher,
)
from apps.simulated_trading.application.rebalance_journey_event_refresh_support import (
    _event_asset_identities,
    _require_refresh_context_stable,
    _validate_event_sources,
)
from apps.simulated_trading.application.rebalance_journey_preparation_support import (
    _asset_map,
    _asset_rows,
    _composite_policy_binding,
    _datetime_text,
    _decimal,
    _decision_payload,
    _derive_whole_share_target_quantity,
    _identity_security_id,
    _json_object,
    _minimum_deadline,
    _parse_mapping,
    _portfolio_resources,
    _preparation_evidence,
    _require_aware,
    _required_digest,
    _required_unit,
    _string,
    _unique_rows_by_code,
    _whole_share_quantity,
    bind_plan_execution_calendar,
    build_plan_risk_binding,
    resolve_plan_target_assets,
    verify_preview_asset_math,
    verify_preview_resources,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.application.rebalance_journey_readers import ServerRebalanceJourneyReads
from apps.simulated_trading.application.rebalance_journey_sources import bind_prepared_plan_sources
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import SimulatedTradeSide

ReferencePriceBasis = Literal["market", "published_close"]
_CONDITIONAL_BUY_REASON = "BUY_DEPENDS_ON_SETTLED_SALES"


class PortfolioJourneyPreparationProvider:
    """Map a real captured preview and qualified risk context into a plan revision.

    The provider never reads caller-supplied account values, prices, source clocks,
    or policies. Its inputs are a target selection and server-owned Application
    readers; all financial facts come from one captured preview plus its separately
    read, value-checked account-risk context.
    """

    def __init__(
        self,
        reads: ServerRebalanceJourneyReads,
        *,
        target_weights: str,
        reference_price_basis: ReferencePriceBasis,
        business_timezone: tzinfo,
        clock: TransitionPlanRevisionClock,
        event_coverage_pinner: RebalanceJourneyEventCoveragePinner | None = None,
        event_refresher: RebalanceJourneyOfficialEventRefresher | None = None,
        event_coverage_required: bool = False,
    ) -> None:
        """Inject one server reader and retain only the explicitly chosen target."""

        if not isinstance(reads, ServerRebalanceJourneyReads):
            raise TypeError("reads must be the server-owned journey reader")
        if reference_price_basis not in {"market", "published_close"}:
            raise ValueError("reference_price_basis is unsupported")
        if not isinstance(business_timezone, tzinfo):
            raise TypeError("business_timezone must be an explicit timezone")
        self._reads = reads
        self._target_weights = target_weights
        self._reference_price_basis = reference_price_basis
        self._business_timezone = business_timezone
        self._clock = clock
        self._event_coverage_pinner = event_coverage_pinner
        self._event_refresher = event_refresher
        self._event_coverage_required = event_coverage_required

    def _refresh_official_events(
        self,
        asset_identities: tuple[PortfolioRiskAssetIdentity, ...],
    ) -> None:
        """Require the official capture adapter to complete for every exact identity."""

        refresher = self._event_refresher
        if refresher is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_UNAVAILABLE")
        try:
            refreshed_identities = refresher.refresh(asset_identities=asset_identities)
        except RebalanceJourneyUnavailable:
            raise
        except Exception as error:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_FAILED") from error
        if (
            type(refreshed_identities) is not tuple
            or any(
                type(identity) is not PortfolioRiskAssetIdentity
                for identity in refreshed_identities
            )
            or refreshed_identities != asset_identities
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REFRESH_INCOMPLETE")

    def prepare(
        self,
        request: TransitionPlanRevisionRequest,
        *,
        prepared_at: datetime,
        parent: TransitionPlanRevision | None,
    ) -> TransitionPlanRevisionPreparation:
        """Read one real context and seal its sources, policies, positions, and plan."""

        if type(request) is not TransitionPlanRevisionRequest:
            raise TypeError("request must be a TransitionPlanRevisionRequest")
        if self._event_coverage_required and (
            self._event_coverage_pinner is None or self._event_refresher is None
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_UNAVAILABLE")
        if self._event_refresher is not None and self._event_coverage_pinner is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_UNAVAILABLE")
        _require_aware(prepared_at, "prepared_at")
        preview = self._reads.read_preview(
            user_id=request.actor_user_id,
            account_id=request.account_id,
            target_weights=self._target_weights,
            reference_price_basis=self._reference_price_basis,
        )
        if type(preview) is not RebalancePlanPreview:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PREVIEW_CONTRACT_INVALID")
        prepared = self._reads.read_risk(
            user_id=request.actor_user_id,
            account_id=request.account_id,
            preview=preview,
        )
        if type(prepared) is not PreparedPortfolioRisk:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_CONTEXT_INVALID")
        event_asset_identities: tuple[PortfolioRiskAssetIdentity, ...] = ()
        if self._event_coverage_pinner is not None:
            event_asset_identities = _event_asset_identities(prepared)
            if self._event_refresher is not None:
                self._refresh_official_events(event_asset_identities)
                refresh_completed_at = self._clock.now()
                _require_aware(refresh_completed_at, "event_refresh_completed_at")
                refreshed_preview = self._reads.read_preview(
                    user_id=request.actor_user_id,
                    account_id=request.account_id,
                    target_weights=self._target_weights,
                    reference_price_basis=self._reference_price_basis,
                )
                if type(refreshed_preview) is not RebalancePlanPreview:
                    raise RebalanceJourneyUnavailable(
                        code="REBALANCE_PLAN_PREVIEW_CONTRACT_INVALID"
                    )
                refreshed_prepared = self._reads.read_risk(
                    user_id=request.actor_user_id,
                    account_id=request.account_id,
                    preview=refreshed_preview,
                )
                if type(refreshed_prepared) is not PreparedPortfolioRisk:
                    raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_CONTEXT_INVALID")
                refreshed_identities = _event_asset_identities(refreshed_prepared)
                _require_refresh_context_stable(
                    initial=prepared,
                    refreshed=refreshed_prepared,
                    expected_identities=event_asset_identities,
                    refreshed_identities=refreshed_identities,
                )
                if (
                    refreshed_preview.financial_snapshot_read_at is None
                    or refreshed_preview.financial_snapshot_read_at < refresh_completed_at
                    or refreshed_prepared.snapshot.read_at < refresh_completed_at
                ):
                    raise RebalanceJourneyUnavailable(
                        code="REBALANCE_PLAN_EVENT_REFRESH_CONTEXT_STALE"
                    )
                preview = refreshed_preview
                prepared = refreshed_prepared
                event_asset_identities = refreshed_identities
        assembled_at = self._clock.now()
        _require_aware(assembled_at, "assembled_at")
        if assembled_at < prepared_at:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_READ_CLOCK_INVALID")
        prepared_at = assembled_at
        event_sources: tuple[TransitionPlanSourceBinding, ...] = ()
        if self._event_coverage_pinner is not None:
            asset_identities = tuple(
                (identity.asset_code, identity.security_id)
                for identity in event_asset_identities
                if identity.security_id is not None
            )
            event_sources = self._event_coverage_pinner.pin(
                asset_identities=asset_identities,
                as_of=prepared_at,
                parent=parent,
            )
            _validate_event_sources(
                event_sources,
                expected_identities=asset_identities,
                plan_clock=prepared_at,
            )
        self._validate_context(
            request=request,
            preview=preview,
            prepared=prepared,
            prepared_at=prepared_at,
        )
        if parent is not None and (
            parent.identity.account_id != request.account_id
            or parent.identity.owner_user_id != prepared.snapshot.owner_user_id
            or parent.basis.account_id != request.account_id
            or parent.basis.owner_user_id != prepared.snapshot.owner_user_id
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_PARENT_SCOPE_MISMATCH")
        policy = prepared.policy
        money_unit = prepared.snapshot.money_unit
        if policy is None or money_unit is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_POLICY_MISSING")
        baseline_policy = prepared.baseline_source.policy
        if baseline_policy is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_BASELINE_UNAVAILABLE")
        targets = parse_temporary_security_targets(self._target_weights)
        target_payload: dict[str, object] = {
            "weights": targets.exact_weight_strings(),
            "residual_cash_weight": str(targets.residual_cash_weight),
        }
        target_content_hash = portfolio_risk_content_hash(target_payload)
        selection_id = f"temporary_security_targets:{self._reference_price_basis}"
        selection_hash = portfolio_risk_content_hash(
            {"target": target_payload, "reference_price_basis": self._reference_price_basis}
        )
        if (
            request.target_portfolio_id != target_content_hash
            or request.selection_id != selection_id
            or request.expected_selection_hash != selection_hash
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_SELECTION_MISMATCH")

        risk_sources = bind_prepared_plan_sources(
            prepared,
            business_timezone=self._business_timezone,
        )
        sources = (*risk_sources, *event_sources)
        source_payloads = [source.to_payload() for source in sources]
        source_evidence_hash = _canonical_hash({"source_bindings": source_payloads})
        portfolio_resources = _portfolio_resources(preview, prepared)
        portfolio_snapshot_hash = _canonical_hash(portfolio_resources)
        portfolio_snapshot_id = portfolio_snapshot_hash
        asset_by_pair = _asset_map(prepared)
        rows = _asset_rows(preview)
        _unique_rows_by_code(rows)
        code_to_asset = resolve_plan_target_assets(
            prepared=prepared,
            rows=rows,
            asset_by_pair=asset_by_pair,
            targets=targets.exact_weight_strings(),
            source_payloads=source_payloads,
        )
        verify_preview_asset_math(preview, code_to_asset)
        current_positions, target_positions = self._positions(
            prepared=prepared,
            rows=rows,
            code_to_asset=code_to_asset,
            source_payloads=source_payloads,
            target_weights=targets.exact_weight_strings(),
        )
        policy_groups, order_drafts, order_specs, order_policy_members = self._orders(
            prepared=prepared,
            rows=rows,
            code_to_asset=code_to_asset,
        )
        calendar_binding = bind_plan_execution_calendar(
            prepared.calendar,
            prepared_at=prepared_at,
            expected_session=prepared.snapshot.execution_session,
        )
        fee_binding = policy_groups["fee_policy"]
        quantity_binding = policy_groups["quantity_rule"]
        settlement_binding = policy_groups["settlement_rule"]
        planning_binding = TransitionPlanPolicyBinding(
            kind="portfolio_planning_policy",
            status="not_applicable",
            reference_id=None,
            version=None,
            content_hash=None,
            effective_at=None,
            known_at=None,
            valid_until=None,
            reason_code="NO_SEPARATE_PLANNING_POLICY_CONSUMED",
        )
        risk_binding = build_plan_risk_binding(prepared, source_payloads)
        decision_payload = _decision_payload(
            preview=preview,
            prepared=prepared,
            business_timezone=str(self._business_timezone),
            portfolio_snapshot_id=portfolio_snapshot_id,
            portfolio_snapshot_hash=portfolio_snapshot_hash,
            target_portfolio_id=target_content_hash,
            target_content_hash=target_content_hash,
            selection_id=selection_id,
            selection_hash=selection_hash,
            source_payloads=source_payloads,
            order_policy_members=order_policy_members,
            order_specifications=[item.to_payload() for item in order_specs],
            positions={
                "current": [item.to_payload() for item in current_positions],
                "target": [item.to_payload() for item in target_positions],
            },
            risk_binding=risk_binding.to_payload(),
            calendar_binding=calendar_binding.to_payload(),
            policy_bindings={
                "fee_policy": fee_binding.to_payload(),
                "quantity_rule": quantity_binding.to_payload(),
                "settlement_rule": settlement_binding.to_payload(),
            },
        )
        decision_hash = _canonical_hash(decision_payload)
        decision_id = decision_hash
        valid_until = _minimum_deadline(
            tuple(source.admission_until for source in sources)
            + (
                fee_binding.valid_until,
                quantity_binding.valid_until,
                settlement_binding.valid_until,
                calendar_binding.valid_until,
                baseline_policy.effective_until,
            )
        )
        if valid_until is None or valid_until <= prepared_at:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVIDENCE_EXPIRED")

        current_cash = prepared.snapshot.cash
        if current_cash is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CASH_UNKNOWN")
        basis_values: dict[str, object] = {
            "account_id": request.account_id,
            "owner_user_id": prepared.snapshot.owner_user_id,
            "requested_by_user_id": request.actor_user_id,
            "money_unit": money_unit,
            "portfolio_snapshot_id": portfolio_snapshot_id,
            "portfolio_snapshot_hash": portfolio_snapshot_hash,
            "portfolio_snapshot_as_of": prepared.snapshot.read_at,
            "portfolio_source_evidence_hash": source_evidence_hash,
            "decision_snapshot_id": decision_id,
            "decision_snapshot_hash": decision_hash,
            "target_portfolio_id": target_content_hash,
            "target_content_hash": target_content_hash,
            "selection_id": selection_id,
            "selection_hash": selection_hash,
            "planning_policy": planning_binding,
            "risk": risk_binding,
            "fee_policy": fee_binding,
            "quantity_rule": quantity_binding,
            "settlement_rule": settlement_binding,
            "execution_calendar": calendar_binding,
            "source_bindings": sources,
            "current_positions": current_positions,
            "target_positions": target_positions,
            "business_date": prepared.business_date,
            "execution_session": prepared.snapshot.execution_session,
            "prepared_at": prepared_at,
            "valid_until": valid_until,
        }
        evidence_document = _preparation_evidence(
            basis_values=basis_values,
            portfolio_resources=portfolio_resources,
            decision_payload=decision_payload,
            target_payload=target_payload,
            source_payloads=source_payloads,
        )
        basis = TransitionPlanBasis(
            account_id=request.account_id,
            owner_user_id=prepared.snapshot.owner_user_id,
            requested_by_user_id=request.actor_user_id,
            money_unit=money_unit,
            portfolio_snapshot_id=portfolio_snapshot_id,
            portfolio_snapshot_hash=portfolio_snapshot_hash,
            portfolio_snapshot_as_of=prepared.snapshot.read_at,
            portfolio_source_evidence_hash=source_evidence_hash,
            decision_snapshot_id=decision_id,
            decision_snapshot_hash=decision_hash,
            target_portfolio_id=target_content_hash,
            target_content_hash=target_content_hash,
            selection_id=selection_id,
            selection_hash=selection_hash,
            planning_policy=planning_binding,
            risk=risk_binding,
            fee_policy=fee_binding,
            quantity_rule=quantity_binding,
            settlement_rule=settlement_binding,
            execution_calendar=calendar_binding,
            source_bindings=sources,
            current_positions=current_positions,
            target_positions=target_positions,
            business_date=prepared.business_date,
            execution_session=prepared.snapshot.execution_session,
            prepared_at=prepared_at,
            valid_until=valid_until,
            preparation_evidence_json=canonical_portfolio_risk_json(evidence_document),
        )
        plan = TransitionPlan(
            plan_id="",
            idempotency_key=request.idempotency_key,
            account_id=str(request.account_id),
            decision_snapshot_id=decision_id,
            portfolio_snapshot_id=portfolio_snapshot_id,
            target_portfolio_id=target_content_hash,
            as_of_time=prepared.snapshot.read_at,
            expires_at=valid_until,
            orders=order_drafts,
            constraints=tuple(decision for order in order_drafts for decision in order.constraints),
            cash_before=current_cash,
            cash_after=current_cash,
            status="DRAFT",
            version=1 if parent is None else parent.identity.version + 1,
            metadata={"planning_policy_version": "not_applicable"},
        )
        if parent is None:
            family_id = _canonical_hash(
                {
                    "family": "ash08.transition-plan",
                    "account_id": request.account_id,
                    "owner_user_id": prepared.snapshot.owner_user_id,
                    "idempotency_key": request.idempotency_key,
                }
            )
            root_plan_id = None
            version = 1
            parent_plan_id = None
            parent_version = None
            parent_hash = None
        else:
            family_id = parent.identity.family_id
            root_plan_id = parent.identity.root_plan_id
            version = parent.identity.version + 1
            parent_plan_id = parent.identity.plan_id
            parent_version = parent.identity.version
            parent_hash = parent.identity.revision_hash
        preparation = TransitionPlanRevisionPreparation(
            plan=plan,
            basis=basis,
            family_id=family_id,
            root_plan_id=root_plan_id,
            version=version,
            parent_plan_id=parent_plan_id,
            parent_version=parent_version,
            parent_revision_hash=parent_hash,
            order_specifications=order_specs,
        )
        return preparation

    def build_revision(
        self,
        request: TransitionPlanRevisionRequest,
        *,
        prepared_at: datetime,
        parent: TransitionPlanRevision | None,
    ) -> TransitionPlanRevision:
        """Build one exact immutable revision for non-persistence domain callers."""

        return build_transition_plan_revision(
            self.prepare(request, prepared_at=prepared_at, parent=parent)
        )

    def _validate_context(
        self,
        *,
        request: TransitionPlanRevisionRequest,
        preview: RebalancePlanPreview,
        prepared: PreparedPortfolioRisk,
        prepared_at: datetime,
    ) -> None:
        """Require exact owner, account, timing, risk, source, and ledger evidence."""

        if (
            prepared.resources.scope is None
            or prepared.actor_user_id != request.actor_user_id
            or prepared.snapshot.account_id != request.account_id
            or prepared.snapshot.owner_user_id != prepared.resources.scope.owner_user_id
            or not prepared.resources.scope.can_write
            or prepared.resources.reason_codes
            or prepared.resources.snapshot is None
            or prepared.resources.snapshot.snapshot_id != prepared.snapshot.snapshot_id
            or prepared.resources.snapshot.read_at != prepared.snapshot.read_at
            or prepared.resources.money_unit_basis != "native_simulated_ledger_config"
            or prepared.snapshot.cash is None
            or prepared.snapshot.money_unit is None
            or not prepared.snapshot.active_orders_complete
            or not prepared.snapshot.executed_usage_complete
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ACCOUNT_CONTEXT_UNAVAILABLE")
        # The preview market cutoff precedes its ledger read. Validate each clock
        # against preparation and require the later risk read to follow the ledger read.
        if (
            type(preview.as_of) is not datetime
            or type(preview.financial_snapshot_read_at) is not datetime
            or preview.financial_snapshot_read_at is None
            or prepared.as_of > prepared_at
            or prepared.snapshot.read_at > prepared_at
            or preview.as_of > prepared_at
            or preview.financial_snapshot_read_at > prepared_at
            or prepared.snapshot.read_at > prepared.as_of
            or preview.financial_snapshot_read_at > prepared.snapshot.read_at
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_READ_CLOCK_INVALID")
        policy = prepared.policy
        if (
            policy is None
            or policy.scope != "simulation_only"
            or request.account_id not in policy.account_ids
            or policy.ledger_money_unit != prepared.snapshot.money_unit
            or policy.as_of != prepared.as_of
            or policy.business_date != prepared.business_date
            or policy.known_at > prepared.as_of
            or policy.effective_at > prepared.as_of
            or prepared.assets.status != "complete"
            or prepared.assets.reason_codes
            or prepared.assets.policy_snapshot_id != policy.snapshot_id
            or prepared.assets.policy_snapshot_hash != policy.snapshot_hash
            or prepared.baseline_source.policy is None
            or prepared.baseline_source.reason_codes
            or prepared.baseline_source.policy.account_id != request.account_id
            or prepared.baseline_source.policy.known_at > prepared.as_of
            or (
                prepared.baseline_source.policy.effective_until is not None
                and prepared.baseline_source.policy.effective_until <= prepared.as_of
            )
            or prepared.calendar.requested_session_qualified is not True
            or prepared.calendar.open_sessions is None
            or prepared.snapshot.execution_session not in prepared.calendar.open_sessions
            or prepared.calendar.evidence_hash is None
            or prepared.calendar.valid_until is None
            or prepared.calendar.valid_until <= prepared.as_of
            or prepared.report.get("scope") != "simulation_only"
            or prepared.report.get("outcome") != "allowed"
            or prepared.report.get("freshness") != "qualified_snapshot"
            or prepared.report.get("reliability") != "source_bound"
            or prepared.report.get("must_not_use_for_decision") is not False
            or prepared.report.get("must_not_execute") is not True
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_NOT_QUALIFIED")
        input_document = _parse_mapping(prepared.input_snapshot_json, "risk input snapshot")
        if (
            canonical_portfolio_risk_json(input_document) != prepared.input_snapshot_json
            or portfolio_risk_content_hash(input_document)
            != prepared.report.get("resource_snapshot_hash")
            or prepared.policy_binding_sha256 is None
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RISK_INPUT_BINDING_MISMATCH")
        _required_digest(prepared.policy_binding_sha256, "policy binding")
        _required_digest(prepared.native_limits_sha256, "native limits binding")
        verify_preview_resources(preview, prepared.snapshot)

    def _positions(
        self,
        *,
        prepared: PreparedPortfolioRisk,
        rows: tuple[RebalancePlanPreviewItem, ...],
        code_to_asset: dict[str, PortfolioRiskAssetInputs],
        source_payloads: list[dict[str, object]],
        target_weights: dict[str, str],
    ) -> tuple[
        tuple[TransitionPlanPositionBinding, ...], tuple[TransitionPlanPositionBinding, ...]
    ]:
        """Build exact current and target rows without guessing quantities or values."""

        money_unit = prepared.snapshot.money_unit
        if money_unit is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_LEDGER_UNIT_UNKNOWN")
        row_by_code = _unique_rows_by_code(rows)
        source_hashes: dict[tuple[str, str], tuple[str, ...]] = {}
        for code, asset in code_to_asset.items():
            if asset.security_id is None:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_POSITION_IDENTITY_UNKNOWN")
            hashes = tuple(
                sorted(
                    portfolio_risk_content_hash(source)
                    for source in source_payloads
                    if source.get("asset_code") == code
                    and source.get("security_id") == asset.security_id
                )
            )
            if not hashes:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_POSITION_SOURCE_MISSING")
            source_hashes[(code, asset.security_id)] = hashes
        current: list[TransitionPlanPositionBinding] = []
        for holding in prepared.snapshot.holdings:
            security_id = holding.security_id
            if security_id is None:
                bindings = [
                    binding
                    for binding in prepared.identity_bindings
                    if binding.asset_code == holding.asset_code
                    and binding.basis == "pinned_policy_source_mapping"
                ]
                if len(bindings) != 1:
                    raise RebalanceJourneyUnavailable(
                        code="REBALANCE_PLAN_HOLDING_IDENTITY_UNKNOWN"
                    )
                security_id = bindings[0].source_security_id
            holding_asset = code_to_asset.get(holding.asset_code)
            if holding_asset is None or holding_asset.security_id != security_id:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_HOLDING_ASSET_UNBOUND")
            price = holding_asset.price
            value = exact_decimal_product(holding.quantity, price) if price is not None else None
            row = row_by_code.get(holding.asset_code)
            current.append(
                TransitionPlanPositionBinding(
                    asset_code=holding.asset_code,
                    security_id=security_id,
                    quantity=holding.quantity,
                    available_quantity=holding.available_quantity,
                    target_weight=(row.target_weight if row is not None else None),
                    target_quantity=(row.target_quantity if row is not None else None),
                    reference_price=price,
                    market_value=value,
                    quantity_unit=_required_unit(holding_asset.quantity_unit, "quantity_unit"),
                    money_unit=money_unit,
                    source_binding_hashes=source_hashes[(holding.asset_code, security_id)],
                )
            )
        current_rows = tuple(sorted(current, key=lambda item: (item.asset_code, item.security_id)))
        target: list[TransitionPlanPositionBinding] = []
        for code, raw_weight in target_weights.items():
            target_asset = code_to_asset.get(code)
            row = row_by_code.get(code)
            if target_asset is None or row is None or target_asset.security_id is None:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_TARGET_POSITION_UNRESOLVED")
            matching_holding = next(
                (
                    holding
                    for holding in prepared.snapshot.holdings
                    if holding.asset_code == code
                    and holding.security_id == target_asset.security_id
                ),
                None,
            )
            quantity = matching_holding.quantity if matching_holding is not None else Decimal("0")
            available = (
                matching_holding.available_quantity
                if matching_holding is not None
                else Decimal("0")
            )
            reference_price = target_asset.price
            market_value = row.target_amount
            if reference_price is not None and row.reference_price is not None:
                if reference_price != row.reference_price:
                    raise RebalanceJourneyUnavailable(
                        code="REBALANCE_PLAN_REFERENCE_PRICE_MISMATCH"
                    )
            target.append(
                TransitionPlanPositionBinding(
                    asset_code=code,
                    security_id=target_asset.security_id,
                    quantity=quantity,
                    available_quantity=available,
                    target_weight=_decimal(raw_weight, "target_weight"),
                    target_quantity=row.target_quantity,
                    reference_price=reference_price,
                    market_value=market_value,
                    quantity_unit=_required_unit(target_asset.quantity_unit, "quantity_unit"),
                    money_unit=money_unit,
                    source_binding_hashes=source_hashes[(code, target_asset.security_id)],
                )
            )
        return current_rows, tuple(
            sorted(target, key=lambda item: (item.asset_code, item.security_id))
        )

    def _orders(
        self,
        *,
        prepared: PreparedPortfolioRisk,
        rows: tuple[RebalancePlanPreviewItem, ...],
        code_to_asset: dict[str, PortfolioRiskAssetInputs],
    ) -> tuple[
        dict[str, TransitionPlanPolicyBinding],
        tuple[OrderDraft, ...],
        tuple[TransitionPlanOrderSpecification, ...],
        list[dict[str, object]],
    ]:
        """Bind every suggested BUY/SELL to current V2 fees, V3 rules, and identity."""

        fee_members: dict[str, dict[str, object]] = {}
        quantity_members: dict[str, dict[str, object]] = {}
        settlement_members: dict[str, dict[str, object]] = {}
        order_policy_members: list[dict[str, object]] = []
        fee_clocks: list[tuple[datetime, datetime, datetime]] = []
        rule_clocks: list[tuple[datetime, datetime, datetime]] = []
        orders: list[OrderDraft] = []
        specifications: list[TransitionPlanOrderSpecification] = []
        money_unit = prepared.snapshot.money_unit
        if money_unit is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_LEDGER_UNIT_UNKNOWN")
        for row in rows:
            if row.action not in {"buy", "sell"}:
                continue
            quantity_derivation = _derive_whole_share_target_quantity(row.suggested_quantity)
            requested = quantity_derivation.requested_quantity
            if requested <= 0:
                continue
            asset = code_to_asset.get(row.asset_code)
            if asset is None or asset.security_id is None:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_IDENTITY_MISSING")
            security_id = _identity_security_id(row.identity)
            identity = _json_object(row.identity, "order identity")
            classification = _json_object(row.classification_evidence, "classification evidence")
            if security_id != asset.security_id or row.asset_type is None:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_IDENTITY_MISMATCH")
            classification_payload = _json_object(
                classification.get("evidence"), "classification evidence payload"
            )
            if portfolio_risk_content_hash(classification_payload) != classification.get(
                "content_hash"
            ):
                raise RebalanceJourneyUnavailable(
                    code="REBALANCE_PLAN_CLASSIFICATION_HASH_MISMATCH"
                )
            try:
                retained_classification = SimulatedInstrumentClassificationEvidenceV1.from_payload(
                    classification_payload
                )
                retained_classification.validate_at(as_of=prepared.as_of)
            except (TypeError, ValueError) as error:
                raise RebalanceJourneyUnavailable(
                    code="REBALANCE_PLAN_CLASSIFICATION_UNQUALIFIED"
                ) from error
            retained_source = retained_classification.identity_evidence.source_evidence
            if (
                classification.get("simulated_asset_type") != row.asset_type
                or classification.get("simulated_asset_type")
                != retained_classification.simulated_asset_type
                or classification.get("purpose")
                != retained_classification.identity_evidence.selection.purpose
                or classification.get("read_at") != _datetime_text(retained_classification.read_at)
                or classification.get("must_not_use_for_decision")
                is not retained_source.must_not_use_for_decision
                or classification.get("must_not_execute") is not retained_source.must_not_execute
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_CLASSIFICATION_UNQUALIFIED")
            classification_hash = _required_digest(
                _string(classification.get("content_hash"), "classification content hash"),
                "classification content hash",
            )
            identity_hash = _required_digest(
                _string(identity.get("identity_hash"), "instrument identity hash"),
                "instrument identity hash",
            )
            classified_identity = _json_object(
                classification_payload.get("identity_evidence"),
                "classification identity evidence",
            )
            if portfolio_risk_content_hash(classified_identity) != identity_hash:
                raise RebalanceJourneyUnavailable(
                    code="REBALANCE_PLAN_CLASSIFICATION_IDENTITY_MISMATCH"
                )
            market = _string(identity.get("rule_market"), "rule market")
            board = _string(identity.get("board"), "instrument board")
            if asset.price is None or asset.price <= 0 or row.reference_price != asset.price:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_REFERENCE_PRICE_MISMATCH")
            if asset.price_unit is None or asset.price_unit != prepared.snapshot.money_unit:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_VALUATION_UNIT_MISMATCH")
            fee_policy, rule_record = self._reads.read_order_policies(row=row, prepared=prepared)
            if (
                type(fee_policy) is not SimulatedFeePolicyV2
                or type(rule_record) is not ExecutionSettlementV3ReadRecord
            ):
                raise RebalanceJourneyUnavailable(
                    code="REBALANCE_PLAN_ORDER_POLICY_CONTRACT_INVALID"
                )
            bundle = rule_record.bundle
            if type(bundle) is not ExecutionSettlementBundleV3:
                raise RebalanceJourneyUnavailable(
                    code="REBALANCE_PLAN_ORDER_POLICY_CONTRACT_INVALID"
                )
            fee_policy.__post_init__()
            rule_record.__post_init__()
            bundle.__post_init__()
            rule = bundle.execution_submission_v2.execution_rule_v1
            settlement = bundle.settlement_policy_v1
            if (
                rule.security_id != security_id
                or rule.market != market
                or rule.board != board
                or settlement.security_id != security_id
                or settlement.market != market
                or settlement.board != board
                or fee_policy.recorded_at > prepared.as_of
                or fee_policy.effective_from > prepared.as_of
                or prepared.as_of >= fee_policy.valid_until
                or rule_record.recorded_at > prepared.as_of
                or bundle.source_available_at > prepared.as_of
                or bundle.latest_source_observed_at > prepared.as_of
                or bundle.effective_from > prepared.as_of
                or prepared.as_of >= bundle.valid_until
            ):
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_POLICY_SCOPE_INVALID")
            side = SimulatedTradeSide.BUY if row.action == "buy" else SimulatedTradeSide.SELL
            fee_policy.case_for(
                asset_type=row.asset_type,
                market=market,
                board=board,
                side=side,
                as_of=prepared.as_of,
            )
            actual_quantity = _whole_share_quantity(
                row.actionable_quantity if row.actionable_quantity is not None else Decimal("0"),
                "actionable_quantity",
            )
            conditional_buy = row.action == "buy" and _CONDITIONAL_BUY_REASON in row.reason_codes
            if row.status != "blocked" and row.actionable_quantity is None and not conditional_buy:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_UNKNOWN")
            if row.status == "blocked" or conditional_buy:
                approved = 0
            elif row.status in {"ready", "partial"}:
                approved = actual_quantity
            else:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_STATUS_UNKNOWN")
            if approved > requested:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_INVALID")
            if row.status == "ready" and approved != requested and not conditional_buy:
                raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_QUANTITY_INCONSISTENT")
            unapproved = requested - approved
            fee_estimate = Decimal("0")
            if approved:
                notional = exact_decimal_product(Decimal(approved), asset.price)
                fee_estimate = fee_policy.calculate_for(
                    asset_type=row.asset_type,
                    market=market,
                    board=board,
                    side=side,
                    amount=notional,
                    as_of=prepared.as_of,
                ).total_fee
            ordinal = len(orders)
            quantity_unit = _required_unit(asset.quantity_unit, "quantity_unit")
            specification = TransitionPlanOrderSpecification(
                ordinal=ordinal,
                asset_code=row.asset_code,
                security_id=security_id,
                asset_type=row.asset_type,
                classification_content_hash=classification_hash,
                quantity_unit=quantity_unit,
                money_unit=money_unit,
                approved_limit_price=None,
            )
            reasons = tuple(dict.fromkeys(row.reason_codes))
            decisions = tuple(
                ConstraintDecision(
                    rule_code=reason,
                    asset_code=row.asset_code,
                    allowed=approved == requested,
                    original_quantity=requested,
                    allowed_quantity=approved,
                    reason=reason,
                )
                for reason in reasons
            )
            orders.append(
                OrderDraft(
                    asset_code=row.asset_code,
                    side=row.action,
                    quantity=approved,
                    reference_price=asset.price,
                    estimated_fee=fee_estimate,
                    status=row.status,
                    remaining_quantity=unapproved,
                    constraints=decisions,
                )
            )
            specifications.append(specification)
            fee_payload = fee_policy.to_payload()
            fee_members[fee_policy.content_hash] = fee_payload
            fee_clocks.append(
                (fee_policy.effective_from, fee_policy.recorded_at, fee_policy.valid_until)
            )
            quantity_payload: dict[str, object] = {
                "security_id": security_id,
                "market": market,
                "board": board,
                "bundle_id": bundle.bundle_id,
                "bundle_version": bundle.bundle_version,
                "bundle_hash": bundle.content_hash,
                "execution_rule": rule.to_payload(),
                "price_submission_range": bundle.execution_submission_v2.price_submission_range.to_payload(),
                "allowed_stages": [
                    stage.value for stage in bundle.execution_submission_v2.allowed_stages
                ],
            }
            settlement_payload: dict[str, object] = {
                "security_id": security_id,
                "market": market,
                "board": board,
                "bundle_id": bundle.bundle_id,
                "bundle_version": bundle.bundle_version,
                "bundle_hash": bundle.content_hash,
                "settlement_policy": settlement.to_payload(),
            }
            quantity_members[bundle.execution_submission_v2.content_hash] = quantity_payload
            settlement_members[settlement.content_hash] = settlement_payload
            order_policy_members.append(
                {
                    "ordinal": ordinal,
                    "asset_code": row.asset_code,
                    "security_id": security_id,
                    "side": row.action,
                    "target_quantity_derivation": quantity_derivation.to_payload(),
                    "fee_policy": fee_payload,
                    "execution_settlement_recorded_at": _datetime_text(rule_record.recorded_at),
                    "execution_settlement_bundle": bundle.to_payload(),
                }
            )
            rule_clocks.append(
                (
                    bundle.effective_from,
                    rule_record.recorded_at,
                    bundle.valid_until,
                )
            )
        if not fee_members or not quantity_members or not settlement_members:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_POLICIES_MISSING")
        policy_groups = {
            "fee_policy": _composite_policy_binding(
                kind="fee_policy_v2_set",
                members=fee_members,
                clocks=fee_clocks,
                prepared_at=prepared.as_of,
            ),
            "quantity_rule": _composite_policy_binding(
                kind="execution_rule_v2_set",
                members=quantity_members,
                clocks=rule_clocks,
                prepared_at=prepared.as_of,
            ),
            "settlement_rule": _composite_policy_binding(
                kind="settlement_policy_v3_set",
                members=settlement_members,
                clocks=rule_clocks,
                prepared_at=prepared.as_of,
            ),
        }
        return policy_groups, tuple(orders), tuple(specifications), order_policy_members


__all__ = ("PortfolioJourneyPreparationProvider", "ReferencePriceBasis")
