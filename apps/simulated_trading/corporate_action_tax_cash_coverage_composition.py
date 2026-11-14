"""Read complete local simulated tax exposure under the physical account lock."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import DEFAULT_DB_ALIAS, connections, models
from django.utils import timezone

from apps.audit.retained_system_audit_pair_composition import RETAINED_SYSTEM_AUDIT_READ_FAILURES
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    read_verified_szse_distribution,
)
from apps.portfolio.domain.transition_plan_event_review import transition_plan_event_snapshot_sha256
from apps.simulated_trading.application.corporate_action_official_window_scope import (
    CorporateActionOfficialWindowScope,
)
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageQuery,
    TaxCashCoverageReason,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.application.corporate_action_window_policy_provenance import (
    CorporateActionWindowPolicyProvenance,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.corporate_action_current_entitlement_coverage import (
    CurrentAssetEntitlementCoverage,
    combine_current_entitlement_coverage,
    inspect_current_distribution_entitlement,
)
from apps.simulated_trading.corporate_action_current_official_window_composition import (
    build_corporate_action_current_official_window_reader,
)
from apps.simulated_trading.corporate_action_original_body_composition import (
    DataCenterCorporateActionOriginalBodyVerifier,
)
from apps.simulated_trading.corporate_action_owner_event_composition import (
    prepare_owner_official_corporate_action,
)
from apps.simulated_trading.corporate_action_owner_event_support import _select_current_event_chain
from apps.simulated_trading.corporate_action_owner_execution_composition import (
    DeferredOwnerShareCapitalTaxQualification,
    DeferredOwnerTaxQualification,
    read_current_owner_action_pdf_root,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    read_locked_owner_corporate_action_posting_state,
)
from apps.simulated_trading.corporate_action_owner_runtime_composition import (
    read_owner_corporate_action_workflow_runtime,
)
from apps.simulated_trading.corporate_action_owner_tax_prepare_composition import (
    prepare_owner_corporate_action_tax_assessment,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.corporate_action_tax_exposure_history_composition import (
    read_current_simulated_tax_exposure_history,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxExchange,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel as Posting,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_balance_repository import (
    read_locked_corporate_action_tax_payable,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_payment_basis_reader import (
    _request_from_row,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import AgomTradeProException, BusinessLogicError

_MAX_ASSETS = 2_000
_MAX_EVENTS = 10_000
_COVERAGE_FAILURES: tuple[type[Exception], ...] = (
    AgomTradeProException,
    ArithmeticError,
    AttributeError,
    OSError,
    TypeError,
    ValueError,
) + RETAINED_SYSTEM_AUDIT_READ_FAILURES


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "模拟税款责任尚不能完整核对。", code="SIMULATED_TAX_CASH_COVERAGE_UNVERIFIED"
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_json_clock,
        ).encode()
    ).hexdigest()


def _json_clock(value: object) -> str:
    if type(value) is not datetime:
        raise TypeError("coverage source contains a non-JSON value")
    return value.isoformat()


def _owner_id(account: SimulatedAccountModel) -> int:
    value = account.user_id
    if type(value) is not int or value <= 0:
        raise _blocked()
    return value


def _classification_source_identity(
    evidence: object,
    *,
    security_id: str,
    asset_code: str,
    as_of: datetime,
) -> tuple[str, datetime, datetime]:
    """Validate exact SZSE source classification and retain its original finite identity."""

    if type(evidence) is not SimulatedInstrumentClassificationEvidenceV1:
        raise _blocked()
    try:
        evidence.__post_init__()
        evidence.validate_at(as_of=as_of)
    except (AttributeError, TypeError, ValueError) as error:
        raise _blocked() from error
    identity = evidence.identity_evidence
    source = identity.source_evidence
    selection = identity.selection
    if (
        identity.security_id != security_id
        or identity.asset_code != asset_code
        or identity.source_exchange != SecurityDisclosureExchange.SZSE.value
        or identity.rule_market != SimulatedDividendTaxExchange.SZ.value
        or type(evidence.simulated_asset_type) is not str
        or not evidence.simulated_asset_type
    ):
        raise _blocked()
    payload = evidence.to_payload()
    identity_payload = payload.get("identity_evidence")
    if type(identity_payload) is not dict:
        raise _blocked()
    selection_payload = identity_payload.get("selection")
    if type(selection_payload) is not dict:
        raise _blocked()
    if "read_at" not in payload or "selected_at" not in selection_payload:
        raise _blocked()
    # These two clocks describe this local reread. All original profile, selector,
    # snapshot, mapping, source, occurrence, and expiry fields remain fingerprinted.
    payload.pop("read_at")
    selection_payload.pop("selected_at")
    knowledge_times = tuple(
        value
        for value in (
            selection.profile_activated_at,
            selection.runtime_snapshot_generated_at,
            source.first_seen_at,
            source.snapshot_recorded_at,
            source.mapping_recorded_at,
            source.response_completed_at,
            identity.reference_response_completed_at,
            source.source_observed_at,
            source.source_available_at,
            source.identity_valid_from,
        )
        if value is not None
    )
    valid_until = source.identity_valid_until
    if (
        not knowledge_times
        or type(valid_until) is not datetime
        or not max(knowledge_times) <= as_of < valid_until
    ):
        raise _blocked()
    return _digest(payload), max(knowledge_times), valid_until


@dataclass(frozen=True, slots=True)
class _CoverageWitness:
    account_id: int
    owner_user_id: int
    asset_codes: tuple[str, ...]
    source_epoch_sha256: str
    initial_account_updated_at: datetime
    entitlements: tuple[CurrentAssetEntitlementCoverage, ...]
    canonical_account_id: str


class DjangoCorporateActionTaxCashCoverageReader:
    """Require actual current source coverage, closed histories and applied assessments.

    All reads use the caller's existing PostgreSQL transaction. Missing accepted
    rows never stand in for unassessed exposure. This reader creates no consent,
    assessment, tax collection, Audit event or HTTP source refresh.
    """

    def __init__(self, *, runtime_environment: str, using: str = DEFAULT_DB_ALIAS) -> None:
        """Bind one explicit server environment and database; cache only request-local witnesses."""
        if (
            using != DEFAULT_DB_ALIAS
            or type(runtime_environment) is not str
            or not runtime_environment.strip()
        ):
            raise _blocked()
        self._environment = runtime_environment
        self._using = using
        self._witnesses: dict[str, _CoverageWitness] = {}
        self._current_entitlements: dict[str, CurrentAssetEntitlementCoverage] = {}

    @property
    def database_alias(self) -> str:
        """Return the alias shared by ownership, history and financial evidence."""
        return self._using

    def _account(self, *, account_id: int, owner_user_id: int, using: str) -> SimulatedAccountModel:
        connection = connections[using]
        if (
            using != self._using
            or connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or connection.get_autocommit()
        ):
            raise _blocked()
        account = (
            SimulatedAccountModel._base_manager.using(using)
            .select_for_update()
            .filter(pk=account_id, user_id=owner_user_id, account_type="simulated", is_active=True)
            .first()
        )
        if account is None:
            raise _blocked()
        return account

    def _asset_codes(self, account: SimulatedAccountModel) -> tuple[str, ...]:
        codes: set[str] = set()
        queries = (
            PositionModel._base_manager.using(self._using)
            .filter(account_id=account.pk)
            .values_list("asset_code", flat=True),
            SimulatedTradeModel._base_manager.using(self._using)
            .filter(account_id=account.pk, status="executed")
            .values_list("asset_code", flat=True),
            Posting._base_manager.using(self._using)
            .filter(account_id=account.pk)
            .values_list("asset_code", flat=True),
            Header._base_manager.using(self._using)
            .filter(account_id=account.pk)
            .values_list("asset_code", flat=True),
        )
        for rows in queries:
            values = tuple(rows.order_by("asset_code").distinct()[: _MAX_ASSETS + 1])
            codes.update(values)
            if len(codes) > _MAX_ASSETS:
                raise _blocked()
        return tuple(sorted(codes))

    def read_locked(
        self, *, physical_account_id: int, owner_user_id: int, using: str
    ) -> TaxCashCoverageSnapshot:
        """Resolve the actual canonical account before independently covering every retained asset."""
        account = self._account(
            account_id=physical_account_id, owner_user_id=owner_user_id, using=using
        )
        codes = self._asset_codes(account)
        result, epoch = self._read(account=account, codes=codes)
        if (
            result.coverage_status is TaxCashCoverageStatus.COMPLETE
            and result.coverage_sha256 is not None
        ):
            # One repository instance belongs to one request. Never accept a
            # client-supplied proof without this independently retained witness.
            self._witnesses[result.coverage_sha256] = _CoverageWitness(
                physical_account_id,
                owner_user_id,
                codes,
                epoch,
                account.updated_at,
                tuple(
                    self._current_entitlements[code]
                    for code in codes
                    if code in self._current_entitlements
                ),
                result.query.canonical_account_id,
            )
        return result

    def read_current_entitlement_coverage(
        self,
        snapshot: TaxCashCoverageSnapshot,
        *,
        using: str,
    ) -> tuple[CurrentAssetEntitlementCoverage, ...]:
        """Return independently checked rights from this request's exact source witness.

        Tax completeness does not register missing cash/share rights. The returned
        rights are scoped to the same finite source lease and owned-account lock.
        """
        snapshot.verify_for(snapshot.query, as_of=timezone.now())
        witness = self._witnesses.get(snapshot.coverage_sha256 or "")
        if (
            using != self._using
            or witness is None
            or witness.account_id != snapshot.query.physical_account_id
            or witness.owner_user_id != snapshot.query.owner_user_id
            or witness.canonical_account_id != snapshot.query.canonical_account_id
            or snapshot.query.environment != self._environment
            or tuple(item.asset_code for item in witness.entitlements) != witness.asset_codes
        ):
            raise _blocked()
        account = self._account(
            account_id=witness.account_id, owner_user_id=witness.owner_user_id, using=using
        )
        if account.updated_at != witness.initial_account_updated_at:
            raise _blocked()
        return witness.entitlements

    def assert_still_current(
        self,
        snapshot: TaxCashCoverageSnapshot,
        *,
        using: str,
        expected_account_updated_at: datetime | None = None,
    ) -> None:
        """Reopen current original sources after writes, without renewing the original lease.

        The account lock excludes other financial writers. The caller's own new
        BUY may add an asset; it cannot create historical record-date ownership.
        Recheck the original asset universe, not that newly created position.
        """
        snapshot.verify_for(snapshot.query, as_of=timezone.now())
        witness = self._witnesses.get(snapshot.coverage_sha256 or "")
        if (
            witness is None
            or witness.account_id != snapshot.query.physical_account_id
            or witness.owner_user_id != snapshot.query.owner_user_id
        ):
            raise _blocked()
        account = self._account(
            account_id=witness.account_id, owner_user_id=witness.owner_user_id, using=using
        )
        expected = (
            witness.initial_account_updated_at
            if expected_account_updated_at is None
            else expected_account_updated_at
        )
        if (
            type(expected) is not datetime
            or expected.tzinfo is None
            or expected.utcoffset() is None
            or expected < witness.initial_account_updated_at
            or expected > timezone.now()
            or account.updated_at != expected
        ):
            raise _blocked()
        current, epoch = self._read(
            account=account,
            codes=witness.asset_codes,
            initial_source_row_updated_at=witness.initial_account_updated_at,
        )
        if (
            current.query != snapshot.query
            or current.coverage_status is not TaxCashCoverageStatus.COMPLETE
            or current.tax_cash_unavailable != snapshot.tax_cash_unavailable
            or epoch != witness.source_epoch_sha256
        ):
            raise _blocked()
        snapshot.verify_for(snapshot.query, as_of=timezone.now())

    def _read(
        self,
        *,
        account: SimulatedAccountModel,
        codes: tuple[str, ...],
        initial_source_row_updated_at: datetime | None = None,
    ) -> tuple[TaxCashCoverageSnapshot, str]:
        self._current_entitlements = {}
        started = timezone.now()
        mapping = DjangoSimulatedAccountRowSourceV2Repository(using=self._using)
        mapping.lock_current_sources_for_read()
        heads = mapping.get_physical_account_heads(
            underlying_unified_account_id=account.pk, as_of=started
        )
        if len(heads) != 1:
            raise _blocked()
        source = heads[0].source
        source.__post_init__()
        if (
            source.account_namespace != "account"
            or source.underlying_unified_account_namespace != "simulated-account-row"
            or source.underlying_unified_account_id != account.pk
            or source.row_user_id != account.user_id
            or source.row_created_at != account.created_at
            or source.row_updated_at
            != (
                account.updated_at
                if initial_source_row_updated_at is None
                else initial_source_row_updated_at
            )
            or source.raw_account_type != "simulated"
            or source.is_active is not True
            or source.is_present is not True
            or source.is_tombstone is not False
            or not source.is_current_at(started)
        ):
            raise _blocked()
        query = TaxCashCoverageQuery(
            account.pk, _owner_id(account), source.account_id, self._environment
        )
        field = SimulatedAccountModel._meta.get_field("current_cash")
        if not isinstance(field, models.DecimalField) or field.decimal_places is None:
            raise _blocked()
        quantum = Decimal(1).scaleb(-field.decimal_places)
        known = source.recorded_at
        deadline = source.valid_until
        epochs: list[object] = [source.content_hash]
        reasons: list[TaxCashCoverageReason] = []
        debt: Decimal | None = None
        try:
            original_ledger = read_locked_owner_corporate_action_posting_state(
                account=account,
                canonical_account_id=source.account_id,
                as_of=timezone.now(),
                using=self._using,
            )
            epochs.append(original_ledger.audit_receipts)
            debt = read_locked_corporate_action_tax_payable(
                account=account, using=self._using, as_of=timezone.now()
            )
            ownership = build_corporate_action_ownership_history_repository(
                runtime_environment=self._environment, using=self._using
            )
            if codes:
                origin = ownership.read_verified_zero_origin_calendar(
                    account_id=account.pk,
                    owner_user_id=_owner_id(account),
                    exchange=SecurityDisclosureExchange.SZSE.value,
                    as_of=timezone.now(),
                )
                epochs.append(
                    (
                        origin.origin_on.isoformat(),
                        origin.decision_on.isoformat(),
                        origin.timezone_policy.policy_id,
                        origin.timezone_policy.policy_sha256,
                    )
                )
            else:
                origin_at = ownership.read_verified_zero_origin_at(
                    account_id=account.pk,
                    owner_user_id=_owner_id(account),
                    as_of=timezone.now(),
                )
                if (
                    type(origin_at) is not datetime
                    or origin_at.tzinfo is None
                    or origin_at.utcoffset() is None
                ):
                    raise _blocked()
                epochs.append(("verified-zero-origin-at", origin_at))
            for code in codes:
                classification_reader: CurrentReferenceClassificationReader = (
                    build_current_reference_classification_reader(
                        runtime_environment=self._environment
                    )
                )
                classification_as_of = timezone.now()
                classification = classification_reader.resolve_simulated_instrument_classification(
                    security_id=code,
                    asset_code=code,
                    as_of=classification_as_of,
                )
                classification_epoch, classification_known, classification_deadline = (
                    _classification_source_identity(
                        classification,
                        security_id=code,
                        asset_code=code,
                        as_of=timezone.now(),
                    )
                )
                asset_epoch, asset_known, asset_deadline = self._cover_asset(
                    account=account, canonical_account_id=source.account_id, code=code
                )
                epochs.append((code, classification_epoch, asset_epoch))
                known = max(known, classification_known, asset_known)
                deadline = min(deadline, classification_deadline, asset_deadline)
        except _COVERAGE_FAILURES:
            reasons.append(TaxCashCoverageReason.HISTORY_UNVERIFIED)
        checked = timezone.now()
        if checked < started or not known <= checked < deadline:
            reasons.append(TaxCashCoverageReason.SOURCE_CHANGED)
        epoch = _digest(epochs)
        result = TaxCashCoverageSnapshot(
            query,
            quantum,
            debt,
            None if reasons else Decimal("0"),
            TaxCashCoverageStatus.UNKNOWN if reasons else TaxCashCoverageStatus.COMPLETE,
            tuple(dict.fromkeys(reasons)),
            checked,
            known if not reasons else None,
            deadline if not reasons else None,
            epoch if not reasons else None,
        )
        return result, epoch

    def _cover_asset(
        self, *, account: SimulatedAccountModel, canonical_account_id: str, code: str
    ) -> tuple[str, datetime, datetime]:
        window = build_corporate_action_current_official_window_reader(
            runtime_environment=self._environment,
            original_body_verifier=DataCenterCorporateActionOriginalBodyVerifier(using=self._using),
            using=self._using,
        ).read_current_scope(
            CorporateActionOfficialWindowScope(account.pk, _owner_id(account), code, code),
            as_of=timezone.now(),
        )
        if (
            not window.window_ready
            or window.snapshot is None
            or window.policy is None
            or window.checked_at is None
            or window.expires_at is None
        ):
            raise _blocked()
        root = read_current_owner_action_pdf_root(
            account_id=account.pk,
            owner_user_id=_owner_id(account),
            environment=self._environment,
            as_of=timezone.now(),
        )
        records = make_security_disclosure_event_reader(using=self._using).execute(
            SecurityDisclosureEventReadScope(
                as_of=timezone.now(), exchange=SecurityDisclosureExchange.SZSE, asset_code=code
            )
        )
        if len(records) > _MAX_EVENTS:
            raise _blocked()
        events = {item.source_event_id for item in window.snapshot.events}
        epochs: list[object] = [
            transition_plan_event_snapshot_sha256(window.snapshot),
            window.calendar_policy_id,
            window.calendar_policy_sha256,
            asdict(CorporateActionWindowPolicyProvenance.from_policy(window.policy)),
        ]
        known = window.snapshot.proof_recorded_at
        deadline = window.expires_at
        entitlement_events: list[CurrentAssetEntitlementCoverage] = []
        retained_rows = tuple(
            Posting._base_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account.pk, asset_code=code)
            .order_by("account_revision")[: _MAX_EVENTS + 1]
        )
        if len(retained_rows) > _MAX_EVENTS:
            raise _blocked()
        for event_id in sorted(events):
            chain = _select_current_event_chain(
                records, event_id=event_id, asset_code=code, as_of=timezone.now()
            )
            event = chain.current.event
            if event.source_event_id != event_id:
                continue
            if event.event_type not in {
                SecurityDisclosureEventType.CASH_DIVIDEND,
                SecurityDisclosureEventType.STOCK_DIVIDEND,
                SecurityDisclosureEventType.RIGHTS_ISSUE,
            }:
                raise _blocked()
            if event.event_type is SecurityDisclosureEventType.RIGHTS_ISSUE:
                rows = tuple(
                    Posting._base_manager.using(self._using).filter(
                        account_id=account.pk,
                        source_event_id=chain.root.event.source_event_id,
                        source_revision_id=event.source_revision_id,
                        stage="rights_not_exercised",
                    )
                )
                if len(rows) != 1:
                    raise _blocked()
                epochs.append(event.content_hash)
                continue
            terms = read_verified_szse_distribution(event, body_store_root=root)
            if terms is None:
                raise _blocked()
            epochs.append(event.content_hash)
            local_day = (
                timezone.now().astimezone(ZoneInfo(window.exchange_timezone_name or "")).date()
            )
            if terms.record_date > local_day:
                continue
            proof = build_corporate_action_ownership_history_repository(
                runtime_environment=self._environment, using=self._using
            ).read_record_date_ownership_proof(
                account_id=account.pk,
                owner_user_id=_owner_id(account),
                security_id=code,
                asset_code=code,
                record_date=terms.record_date,
                evidence_cutoff_at=timezone.now(),
            )
            if proof.exchange_timezone_name != window.exchange_timezone_name:
                raise _blocked()
            if proof.eligible_quantity == 0:
                continue
            entitlement_events.append(
                inspect_current_distribution_entitlement(
                    event=event,
                    terms=terms,
                    logical_source_event_id=chain.root.event.source_event_id,
                    proof=proof,
                    rows=retained_rows,
                )
            )
            if event.event_type is SecurityDisclosureEventType.STOCK_DIVIDEND:
                rows = tuple(
                    Posting._base_manager.using(self._using).filter(
                        account_id=account.pk,
                        source_event_id=chain.root.event.source_event_id,
                        source_revision_id=event.source_revision_id,
                        stage="share_entitlement",
                    )
                )
                if len(rows) != 1:
                    raise _blocked()
                reference = _request_from_row(rows[0], owner_user_id=_owner_id(account))
                model = DeferredOwnerShareCapitalTaxQualification(
                    environment=self._environment, canonical_account_id=canonical_account_id
                ).read_current(reference, as_of=timezone.now())
                epochs.append(model.selection_sha256)
                deadline = min(deadline, model.valid_until)
                known = max(known, model.model.known_at)
                continue
            runtime = read_owner_corporate_action_workflow_runtime(
                environment=self._environment, as_of=timezone.now()
            )
            calendar = build_current_published_execution_calendar_reader(
                dataset_key=runtime.calendar_dataset_key,
                runtime_environment=self._environment,
                read_publication=read_current_exchange_calendar_reference,
            ).get_effective_execution_calendar(
                exchange="SZSE", as_of=timezone.now(), coverage_start=terms.record_date
            )
            if calendar is None:
                raise _blocked()
            closed = tuple(
                day.calendar_date
                for day in calendar.snapshot.days
                if day.is_open and terms.record_date < day.calendar_date < local_day
            )
            if not closed:
                raise _blocked()
            through = max(closed)
            prepared = prepare_owner_official_corporate_action(
                account_id=account.pk,
                owner_user_id=_owner_id(account),
                asset_code=code,
                event_id=event.source_event_id,
                action="tax_assess",
                settlement_date=through,
                as_of=timezone.now(),
                runtime_environment=self._environment,
                using=self._using,
            )
            if prepared.tax_action is None:
                raise _blocked()
            exposure = read_current_simulated_tax_exposure_history(
                action=prepared.tax_action,
                canonical_account_id=canonical_account_id,
                complete_through=through,
                environment=self._environment,
                calendar_dataset_key=runtime.calendar_dataset_key,
                statutory_provider_id=runtime.statutory_provider_id,
                statutory_body_store_root=runtime.statutory_body_store_root,
                action_body_store_root=root,
                deployment_region=runtime.deployment_region,
                using=self._using,
            )
            # Every retained SELL must be represented by its actual modeled date.
            # An unclosed fill or offset outside this prefix keeps cash unknown.
            covered = {
                item.trade_id
                for item in exposure.history.observation.date_observations
                if item.date_evidence.side == "sell"
            }
            sales = tuple(
                SimulatedTradeModel._base_manager.using(self._using).filter(
                    account_id=account.pk, asset_code=code, status="executed", action="sell"
                )
            )
            if any(sale.pk not in covered for sale in sales):
                raise _blocked()
            epochs.append(exposure.source_epoch_sha256)
            known = max(known, exposure.known_at)
            deadline = min(deadline, exposure.valid_until)
            for day in exposure.history.history.settlement_days:
                if day.settlement_date <= terms.record_date or day.net_quantity_change >= 0:
                    continue
                preview = prepare_owner_corporate_action_tax_assessment(
                    action=prepared.tax_action,
                    operation="tax_recognize",
                    canonical_account_id=canonical_account_id,
                    settlement_date=day.settlement_date,
                    environment=self._environment,
                )
                qualification = (
                    DeferredOwnerTaxQualification(environment=self._environment)
                    .build_provider(
                        account_id=account.pk,
                        owner_user_id=_owner_id(account),
                        as_of=timezone.now(),
                    )
                    .read_current(
                        preview.assessment,
                        canonical_account_id=canonical_account_id,
                        environment=self._environment,
                        using=self._using,
                        as_of=timezone.now(),
                    )
                )
                epochs.append(
                    (preview.assessment.semantic_sha256, qualification.qualification_sha256)
                )
                deadline = min(deadline, qualification.valid_until)
        final_clock = timezone.now()
        if (
            not window.checked_at <= final_clock < deadline
            or final_clock.astimezone(ZoneInfo(window.exchange_timezone_name or "")).date()
            != window.snapshot.end_on
        ):
            raise _blocked()
        entitlement = combine_current_entitlement_coverage(
            asset_code=code,
            window_sha256=transition_plan_event_snapshot_sha256(window.snapshot),
            events=tuple(entitlement_events),
        )
        epochs.append(entitlement.evidence_sha256)
        self._current_entitlements[code] = entitlement
        return _digest(epochs), known, deadline
