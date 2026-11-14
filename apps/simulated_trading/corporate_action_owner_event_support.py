"""Read and validate owner-bound current corporate-action evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import NoReturn, Protocol, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from apps.data_center.application.public_published_queries import resolve_asset_payload
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OWNER_CORPORATE_ACTION_OPERATIONS,
    OwnerCorporateActionOperation,
)
from apps.simulated_trading.application.corporate_action_owner_revision_preview import (
    OwnerCorporateActionRevisionPreview,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
    TransitionPlanDisclosureRuntimePolicy,
)
from core.exceptions import BusinessLogicError

_OFFICIAL_NAMESPACE = "exchange_official_disclosure"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_LEDGER_ROWS = 10_000
_TAX_OPERATIONS = frozenset({"tax_assess", "tax_recognize", "tax_collect"})


class CorporateActionOwnerEventPreparationBlocked(BusinessLogicError):
    """Raised when current retained source or owner ledger facts cannot form a request."""

    default_message = "公司行动来源或账户证据不足，无法准备安全操作"
    default_code = "CORPORATE_ACTION_OWNER_EVENT_BLOCKED"


@dataclass(frozen=True, slots=True)
class PreparedOwnerOfficialAction:
    """Read-only action proposal, separated from grant, Audit, and posting authority."""

    action: OwnerCorporateActionOperation
    event: SecurityDisclosureEvent
    source_reference: CorporateActionStageRequest
    requests: tuple[CorporateActionStageRequest, ...]
    tax_action: QualifiedCorporateActionTaxFacts | None
    settlement_date: date | None = None
    source_terms: SzseDistributionTerms | None = None
    revision_preview: OwnerCorporateActionRevisionPreview | None = None


@dataclass(frozen=True, slots=True)
class _CurrentEventChain:
    """One complete, unbranched public source lineage and its selected latest revision."""

    root: PersistedSecurityDisclosureEvent
    current: PersistedSecurityDisclosureEvent
    members: tuple[PersistedSecurityDisclosureEvent, ...]


class _OwnerHistoryReader(Protocol):
    """Read the exact account calendar and record-date proof from retained history."""

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        """Return one owner-bound exchange calendar from the configured timezone policy."""

    def read_record_date_ownership_proof(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        evidence_cutoff_at: datetime,
    ) -> RecordDateOwnershipProof:
        """Return a retained record-date ownership replay for the exact owner and asset."""


class _RequestSourceValues(TypedDict):
    """The shared strict source identity and clocks passed into stage requests."""

    source_namespace: str
    source_record_id: str
    source_event_id: str
    source_revision_id: str
    source_payload_sha256: str
    source_observed_at: datetime
    qualified_at: datetime
    posted_at: datetime
    qualifier_identity: str


def _validate_input(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event_id: str,
    action: OwnerCorporateActionOperation,
    settlement_date: date | None,
    as_of: datetime,
    runtime_environment: str,
    using: str,
) -> None:
    """Reject ambiguous, noncanonical, or client-shaped action scopes."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(asset_code) is not str
        or re.fullmatch(r"[0-9]{6}\.SZ", asset_code) is None
        or type(event_id) is not str
        or not event_id
        or event_id != event_id.strip()
        or len(event_id) > 192
        or any(character.isspace() for character in event_id)
        or type(action) is not str
        or action not in OWNER_CORPORATE_ACTION_OPERATIONS
        or (settlement_date is not None and type(settlement_date) is not date)
        or (action in _TAX_OPERATIONS and type(settlement_date) is not date)
        or (action not in _TAX_OPERATIONS and settlement_date is not None)
        or type(as_of) is not datetime
        or not timezone.is_aware(as_of)
        or type(runtime_environment) is not str
        or not runtime_environment.strip()
        or type(using) is not str
        or not using.strip()
    ):
        _blocked(
            "corporate-action preparation scope is invalid", "CORPORATE_ACTION_OWNER_INPUT_INVALID"
        )


def _read_owned_account(
    *, account_id: int, owner_user_id: int, using: str, as_of: datetime
) -> SimulatedAccountModel | None:
    """Read one current owner-bound simulated account from its owning app model."""

    return (
        SimulatedAccountModel._base_manager.using(using)
        .filter(
            pk=account_id,
            user_id=owner_user_id,
            account_type="simulated",
            is_active=True,
            created_at__lte=as_of,
        )
        .first()
    )


def _validate_calendar(
    calendar: VerifiedSimulatedAccountOriginCalendar, *, as_of: datetime
) -> tuple[date, ZoneInfo]:
    """Check the exact SZSE timezone calendar and ownership origin used by the reader."""

    if (
        getattr(calendar, "as_of", None) != as_of
        or getattr(getattr(calendar, "timezone_policy", None), "exchange", None)
        != SecurityDisclosureExchange.SZSE.value
        or type(getattr(calendar, "origin_on", None)) is not date
        or type(getattr(calendar, "decision_on", None)) is not date
        or calendar.origin_on > calendar.decision_on
    ):
        _blocked(
            "the account's exact SZSE ownership calendar is unavailable",
            "CORPORATE_ACTION_OWNER_CALENDAR_UNAVAILABLE",
        )
    timezone_name = getattr(calendar.timezone_policy, "timezone_name", None)
    if type(timezone_name) is not str or not timezone_name:
        _blocked(
            "the configured account exchange timezone is invalid",
            "CORPORATE_ACTION_OWNER_CALENDAR_UNAVAILABLE",
        )
    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        _blocked(
            "the configured account exchange timezone is invalid",
            "CORPORATE_ACTION_OWNER_CALENDAR_UNAVAILABLE",
        )
    decision = as_of.astimezone(exchange_timezone).date()
    if calendar.decision_on != decision:
        _blocked(
            "the account decision date disagrees with its sealed timezone",
            "CORPORATE_ACTION_OWNER_CALENDAR_UNAVAILABLE",
        )
    return decision, exchange_timezone


def _read_policy(
    *,
    runtime_environment: str,
    decision_on: date,
    exchange_timezone: ZoneInfo,
    event: SecurityDisclosureEvent,
    as_of: datetime,
) -> TransitionPlanDisclosureRuntimePolicy:
    """Resolve the configured immutable disclosure policy for this event and account day."""

    earliest = event.first_seen_at.astimezone(exchange_timezone).date()
    policy = ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
        runtime_environment=runtime_environment
    ).read_policy(
        decision_on=decision_on,
        earliest_required_on=earliest,
        as_of=as_of,
    )
    body_root = getattr(policy, "body_store_root", None)
    start_on = getattr(policy, "start_on", None)
    end_on = getattr(policy, "end_on", None)
    if (
        policy is None
        or not isinstance(body_root, Path)
        or not body_root.is_absolute()
        or ".." in body_root.parts
        or getattr(policy, "source_id", None) != "szse_official"
        or getattr(policy, "runtime_environment", None) != runtime_environment
        or type(start_on) is not date
        or type(end_on) is not date
        or not start_on <= earliest <= decision_on <= end_on
        or end_on != decision_on
    ):
        _blocked(
            "the configured official disclosure policy does not cover this event and date",
            "CORPORATE_ACTION_OWNER_POLICY_UNAVAILABLE",
        )
    for field_name in ("known_at", "effective_at", "read_at"):
        value = getattr(policy, field_name, None)
        if value is not None and (
            type(value) is not datetime or not timezone.is_aware(value) or value > as_of
        ):
            _blocked(
                "official disclosure policy provenance is after the requested cutoff",
                "CORPORATE_ACTION_OWNER_POLICY_UNAVAILABLE",
            )
    return policy


def _select_current_event_chain(
    records: tuple[PersistedSecurityDisclosureEvent, ...],
    *,
    event_id: str,
    asset_code: str,
    as_of: datetime,
) -> _CurrentEventChain:
    """Require one complete, cutoff-known, unbranched source lineage and current leaf."""

    if type(records) is not tuple or not records or len(records) > 10_000:
        _blocked(
            "the source event history is missing or exceeds its read bound",
            "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
        )
    by_identity: dict[tuple[str, str], PersistedSecurityDisclosureEvent] = {}
    children: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for persisted in records:
        if (
            type(persisted) is not PersistedSecurityDisclosureEvent
            or type(persisted.event) is not SecurityDisclosureEvent
        ):
            _blocked(
                "source reader returned an untyped event row",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        event = persisted.event
        try:
            event.__post_init__()
        except ValueError as error:
            _blocked(
                "source event identity is malformed",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
                cause=error,
            )
        if (
            event.asset_code != asset_code
            or event.exchange is not SecurityDisclosureExchange.SZSE
            or event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
            or event.source_security_code != asset_code[:6]
            or not timezone.is_aware(persisted.recorded_at)
            or persisted.recorded_at > as_of
            or event.first_seen_at > as_of
        ):
            _blocked(
                "source event is outside the exact SZSE cutoff scope",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        key = (event.source_event_id, event.source_revision_id)
        if key in by_identity:
            _blocked(
                "source history repeats one event revision",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        by_identity[key] = persisted
        parent_event = event.supersedes_source_event_id
        parent_revision = event.supersedes_source_revision_id
        if (parent_event is None) != (parent_revision is None):
            _blocked(
                "source revision has an incomplete predecessor identity",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        if parent_event is not None and parent_revision is not None:
            children.setdefault((parent_event, parent_revision), []).append(key)

    candidates = tuple(
        key for key, item in by_identity.items() if item.event.source_event_id == event_id
    )
    matching_roots: set[tuple[str, str]] = set()
    for candidate in candidates:
        seen: set[tuple[str, str]] = set()
        walk_key = candidate
        while True:
            if walk_key in seen:
                _blocked(
                    "source revision lineage contains a cycle",
                    "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
                )
            seen.add(walk_key)
            candidate_persisted = by_identity.get(walk_key)
            if candidate_persisted is None:
                _blocked(
                    "source revision predecessor is missing",
                    "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
                )
            parent_event = candidate_persisted.event.supersedes_source_event_id
            parent_revision = candidate_persisted.event.supersedes_source_revision_id
            if parent_event is None or parent_revision is None:
                matching_roots.add(walk_key)
                break
            parent_key = (parent_event, parent_revision)
            if len(children.get(parent_key, ())) != 1:
                _blocked(
                    "source revision lineage is branched",
                    "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
                )
            walk_key = parent_key

    if len(matching_roots) != 1:
        _blocked(
            "requested event is missing or ambiguous in current source history",
            "CORPORATE_ACTION_OWNER_SOURCE_NOT_FOUND",
        )
    root_key = next(iter(matching_roots))
    reachable: list[tuple[str, str]] = []
    pending = [root_key]
    while pending:
        key = pending.pop()
        if key in reachable:
            _blocked(
                "source revision lineage contains a cycle",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        if key not in by_identity:
            _blocked(
                "source revision predecessor is missing",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        children_for_key = children.get(key, ())
        if len(children_for_key) > 1:
            _blocked(
                "source revision lineage is branched",
                "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
            )
        reachable.append(key)
        pending.extend(children_for_key)
    group = tuple(by_identity[key] for key in reachable)
    leaf_keys = tuple(key for key in reachable if len(children.get(key, ())) == 0)
    if len(leaf_keys) != 1:
        _blocked(
            "source lineage does not have one exact current revision",
            "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
        )
    leaf_key = leaf_keys[0]
    root = by_identity[root_key]
    current_record = by_identity[leaf_key]
    members = tuple(
        sorted(group, key=lambda item: (item.recorded_at, item.event.source_revision_id))
    )
    if (
        current_record.event.source_revision_id
        != f"sha256:{current_record.event.source_body_sha256}"
    ):
        _blocked(
            "current source revision is not bound to its original body hash",
            "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID",
        )
    return _CurrentEventChain(root=root, current=current_record, members=members)


def _validate_distribution_event(
    *, event: SecurityDisclosureEvent, terms: SzseDistributionTerms
) -> None:
    """Bind source category, exact security, dates, and parser terms before arithmetic."""

    expected_type = (
        SecurityDisclosureEventType.CASH_DIVIDEND
        if terms.cash_per_ten is not None
        else SecurityDisclosureEventType.STOCK_DIVIDEND
    )
    if (
        event.event_type is not expected_type
        or event.asset_code != event.source_security_code + ".SZ"
        or type(event.effective_at) is not date
        or event.effective_at != terms.ex_date
        or type(terms.record_date) is not date
        or type(terms.ex_date) is not date
        or (terms.payment_date is not None and type(terms.payment_date) is not date)
        or (terms.share_delivery_date is not None and type(terms.share_delivery_date) is not date)
        or (terms.share_sellable_date is not None and type(terms.share_sellable_date) is not date)
        or terms.record_date > terms.ex_date
        or (terms.payment_date is not None and terms.payment_date < terms.ex_date)
        or (terms.share_delivery_date is not None and terms.share_delivery_date < terms.ex_date)
        or (terms.share_sellable_date is not None and terms.share_sellable_date < terms.ex_date)
        or (
            terms.share_delivery_date is not None
            and terms.share_sellable_date is not None
            and terms.share_sellable_date < terms.share_delivery_date
        )
        or terms.tax_treatment not in {"not_applicable", "deferred_withholding"}
    ):
        _blocked(
            "source category, security, or effective date conflicts with parsed terms",
            "CORPORATE_ACTION_OWNER_SOURCE_TERMS_INVALID",
        )
    if event.event_type is SecurityDisclosureEventType.CASH_DIVIDEND:
        if (
            terms.cash_per_ten is None
            or type(terms.cash_per_ten) is not Decimal
            or not terms.cash_per_ten.is_finite()
        ):
            _blocked(
                "cash distribution amount is absent or invalid",
                "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
            )
    elif (
        terms.shares_per_ten is None
        or type(terms.shares_per_ten) is not Decimal
        or not terms.shares_per_ten.is_finite()
    ):
        _blocked(
            "share distribution ratio is absent or invalid",
            "CORPORATE_ACTION_OWNER_SHARE_TERMS_UNSUPPORTED",
        )


def _read_record_date_proof(
    *,
    reader: _OwnerHistoryReader,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    record_date: date,
    as_of: datetime,
    runtime_environment: str,
) -> RecordDateOwnershipProof:
    """Read and bind one real persisted owner position proof at its own cutoff."""

    proof = reader.read_record_date_ownership_proof(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        record_date=record_date,
        evidence_cutoff_at=as_of,
    )
    if type(proof) is not RecordDateOwnershipProof:
        _blocked(
            "record-date ownership replay is not typed",
            "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID",
        )
    if not _supported_share_quantity(proof.eligible_quantity):
        _blocked(
            "record-date ownership quantity exceeds supported share precision",
            "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID",
        )
    if (
        proof.account_id != account_id
        or proof.owner_user_id != owner_user_id
        or proof.security_id != asset_code
        or proof.asset_code != asset_code
        or not _ownership_market_matches(
            proof=proof,
            asset_code=asset_code,
            as_of=as_of,
            runtime_environment=runtime_environment,
        )
        or proof.record_date != record_date
        or proof.ownership_snapshot_as_of_date != record_date
        or not timezone.is_aware(proof.ownership_snapshot_observed_at)
        or proof.ownership_snapshot_observed_at > as_of
        or not _SHA256_RE.fullmatch(proof.ownership_snapshot_sha256)
        or not proof.ownership_snapshot_id
    ):
        _blocked(
            "record-date ownership replay does not match the current owner scope",
            "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID",
        )
    return proof


def _ownership_market_matches(
    *,
    proof: RecordDateOwnershipProof,
    asset_code: str,
    as_of: datetime,
    runtime_environment: str,
) -> bool:
    """Bind a V4 rule market through its current typed source-exchange crosswalk."""
    if proof.exchange == SecurityDisclosureExchange.SZSE.value:
        return True
    evidence = build_current_reference_classification_reader(
        runtime_environment=runtime_environment
    ).resolve_simulated_instrument_classification(
        security_id=asset_code, asset_code=asset_code, as_of=as_of
    )
    if type(evidence) is not SimulatedInstrumentClassificationEvidenceV1:
        return False
    evidence.validate_at(as_of=as_of)
    identity = evidence.identity_evidence
    return (
        evidence.read_at == as_of
        and identity.security_id == asset_code
        and identity.asset_code == asset_code
        and identity.source_exchange == SecurityDisclosureExchange.SZSE.value
        and identity.rule_market == proof.exchange
    )


def _asset_name(asset_code: str) -> str:
    """Resolve the canonical descriptive asset name from the public Data Center query."""

    payload = resolve_asset_payload(asset_code)
    if type(payload) is not dict:
        _blocked(
            "canonical asset description is unavailable",
            "CORPORATE_ACTION_OWNER_ASSET_NAME_UNAVAILABLE",
        )
    item = cast(dict[str, object], payload)
    name = item.get("name")
    if type(name) is not str or not name or name != name.strip() or len(name) > 128:
        _blocked(
            "canonical asset description is incomplete",
            "CORPORATE_ACTION_OWNER_ASSET_NAME_UNAVAILABLE",
        )
    return name


def _source_values(
    *,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    as_of: datetime,
    qualified_at: datetime | None = None,
) -> _RequestSourceValues:
    """Build exact source identity and clocks shared by one proposed request."""

    source_qualified_at = (
        max(event.first_seen_at, chain.current.recorded_at)
        if qualified_at is None
        else qualified_at
    )
    if (
        source_qualified_at > as_of
        or source_qualified_at < event.first_seen_at
        or source_qualified_at < chain.current.recorded_at
    ):
        _blocked(
            "current source was not known at the requested cutoff",
            "CORPORATE_ACTION_OWNER_SOURCE_AFTER_CUTOFF",
        )
    return {
        "source_namespace": _OFFICIAL_NAMESPACE,
        "source_record_id": event.source_event_id,
        "source_event_id": chain.root.event.source_event_id,
        "source_revision_id": event.source_revision_id,
        "source_payload_sha256": event.source_body_sha256,
        "source_observed_at": event.first_seen_at,
        "qualified_at": source_qualified_at,
        "posted_at": as_of,
        "qualifier_identity": "szse_official_pdf.v1",
    }


def _read_event_postings(
    *, account_id: int, source_event_id: str, using: str
) -> tuple[CorporateActionPostingModel, ...]:
    """Read all immutable stage rows for one account and logical event."""

    return tuple(
        CorporateActionPostingModel._base_manager.using(using)
        .filter(account_id=account_id, source_event_id=source_event_id)
        .order_by("account_revision")
    )


def _read_existing_tax_action_identities(
    *, account_id: int, source_event_id: str, using: str
) -> tuple[CorporateActionTaxAssessmentHeaderModel, ...]:
    """Read retained action identities without interpreting any assessment economics."""

    return tuple(
        CorporateActionTaxAssessmentHeaderModel._base_manager.using(using)
        .filter(account_id=account_id, source_event_id=source_event_id)
        .order_by("pk")
    )


def _validate_ledger_rows(
    *,
    rows: tuple[CorporateActionPostingModel, ...],
    chain: _CurrentEventChain,
    account_id: int,
    asset_code: str,
    action_kind: CorporateActionKind,
    record_date: date,
    effective_date: date,
    as_of: datetime,
) -> None:
    """Fail closed on mismatched, future, duplicate, or partial correction histories."""

    if type(rows) is not tuple or len(rows) > _MAX_LEDGER_ROWS:
        _blocked(
            "event posting history is missing or exceeds its safe read bound",
            "CORPORATE_ACTION_OWNER_LEDGER_INVALID",
        )
    revision_records = {item.event.source_revision_id: item for item in chain.members}
    seen_stages: set[str] = set()
    previous_revision = 0
    current_revision = chain.current.event.source_revision_id
    if any(
        row.entry_kind
        in {CorporateActionEntryKind.REVERSAL.value, CorporateActionEntryKind.SUCCESSOR.value}
        or row.source_revision_id != current_revision
        for row in rows
    ):
        _blocked(
            "existing source corrections require one complete reverse-and-successor replay",
            "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRES_FULL_REPLAY",
        )
    for row in rows:
        if (
            type(row.account_revision) is not int
            or row.account_revision <= previous_revision
            or row.account_id != account_id
            or row.source_event_id != chain.root.event.source_event_id
            or row.source_revision_id not in revision_records
            or row.source_record_id
            != revision_records[row.source_revision_id].event.source_event_id
            or row.source_namespace != _OFFICIAL_NAMESPACE
            or row.asset_code != asset_code
            or row.security_id != asset_code
            or row.action_kind != action_kind.value
            or row.record_date != record_date
            or row.effective_date != effective_date
            or row.stage
            not in {
                CorporateActionStage.CASH_ENTITLEMENT.value,
                CorporateActionStage.CASH_PAYMENT.value,
                CorporateActionStage.TAX_WITHHOLDING.value,
                CorporateActionStage.SHARE_ENTITLEMENT.value,
                CorporateActionStage.SHARE_DELIVERY.value,
                CorporateActionStage.SHARE_SELLABLE_RELEASE.value,
                CorporateActionStage.RIGHTS_NOT_EXERCISED.value,
            }
            or row.created_at > as_of
            or row.posted_at > as_of
            or row.entry_kind
            not in {
                CorporateActionEntryKind.POSTING.value,
                CorporateActionEntryKind.NO_EFFECT.value,
            }
            or row.stage in seen_stages
        ):
            _blocked(
                "event posting row does not match the current official action scope",
                "CORPORATE_ACTION_OWNER_LEDGER_INVALID",
            )
        seen_stages.add(row.stage)
        previous_revision = row.account_revision


def _outstanding_cash_receivable(rows: tuple[CorporateActionPostingModel, ...]) -> Decimal:
    """Return exact positive unpaid cash receivable after all retained stage deltas."""

    if not rows or any(row.stage != CorporateActionStage.CASH_ENTITLEMENT.value for row in rows):
        _blocked(
            "a full posted cash entitlement is required before payment",
            "CORPORATE_ACTION_OWNER_CASH_ENTITLEMENT_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        outstanding = sum((row.cash_receivable_delta for row in rows), Decimal("0"))
        if outstanding <= 0:
            _blocked(
                "no positive outstanding cash entitlement is available",
                "CORPORATE_ACTION_OWNER_CASH_RECEIVABLE_EMPTY",
            )
        return _exact_money(outstanding)


def _exact_money(value: Decimal) -> Decimal:
    """Keep historical money exactly cent-representable at ledger precision."""

    if type(value) is not Decimal or not value.is_finite():
        _blocked("ledger cash value is invalid", "CORPORATE_ACTION_OWNER_LEDGER_INVALID")
    with localcontext() as context:
        context.prec = 80
        try:
            cents = value.quantize(Decimal("0.01"))
        except InvalidOperation:
            _blocked(
                "ledger cash value exceeds supported precision",
                "CORPORATE_ACTION_OWNER_LEDGER_INVALID",
            )
        if cents != value or cents <= 0 or cents.adjusted() >= 13:
            _blocked(
                "ledger cash value is not an exact positive cent amount",
                "CORPORATE_ACTION_OWNER_LEDGER_INVALID",
            )
        return cents


def _supported_share_quantity(value: object) -> bool:
    """Check one positive ledger share amount within the model's exact precision."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        return False
    exponent = value.as_tuple().exponent
    return type(exponent) is int and exponent >= -6 and value.adjusted() < 14


def _require_paid_cash_receivable(rows: tuple[CorporateActionPostingModel, ...]) -> None:
    """Require an actual full payment posting before collection may be prepared."""

    if not rows or not any(row.stage == CorporateActionStage.CASH_PAYMENT.value for row in rows):
        _blocked(
            "tax collection requires an actual posted cash payment",
            "CORPORATE_ACTION_OWNER_PAYMENT_BASIS_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        remaining = sum((row.cash_receivable_delta for row in rows), Decimal("0"))
        paid = sum(
            (
                row.cash_delta
                for row in rows
                if row.stage == CorporateActionStage.CASH_PAYMENT.value
            ),
            Decimal("0"),
        )
        if remaining != 0 or paid <= 0:
            _blocked(
                "cash payment history does not fully settle the event entitlement",
                "CORPORATE_ACTION_OWNER_PAYMENT_BASIS_REQUIRED",
            )


def _outstanding_cash_receivable_from_revision_head(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> Decimal:
    """Return the exact unpaid receivable from a fully validated active cash head."""

    if (
        type(entries) is not tuple
        or not entries
        or any(
            type(entry) is not OwnerCorporateActionRevisionEntry
            or entry.request.action_kind is not CorporateActionKind.CASH_DIVIDEND
            or entry.request.stage
            not in {CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT}
            for entry in entries
        )
        or sum(entry.request.stage is CorporateActionStage.CASH_ENTITLEMENT for entry in entries)
        != 1
    ):
        _blocked(
            "a complete active cash entitlement head is required before payment",
            "CORPORATE_ACTION_OWNER_CASH_ENTITLEMENT_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        outstanding = sum((entry.delta.cash_receivable for entry in entries), Decimal("0"))
        if outstanding <= 0:
            _blocked(
                "no positive active cash receivable is available",
                "CORPORATE_ACTION_OWNER_CASH_RECEIVABLE_EMPTY",
            )
        return _exact_money(outstanding)


def _require_paid_cash_receivable_from_revision_head(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> None:
    """Require the active cash head to contain a full real payment before tax collection."""

    if (
        type(entries) is not tuple
        or not entries
        or any(
            type(entry) is not OwnerCorporateActionRevisionEntry
            or entry.request.action_kind is not CorporateActionKind.CASH_DIVIDEND
            or entry.request.stage
            not in {CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT}
            for entry in entries
        )
        or not any(entry.request.stage is CorporateActionStage.CASH_PAYMENT for entry in entries)
    ):
        _blocked(
            "tax collection requires an active, posted cash payment",
            "CORPORATE_ACTION_OWNER_PAYMENT_BASIS_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        remaining = sum((entry.delta.cash_receivable for entry in entries), Decimal("0"))
        paid = sum(
            (
                entry.delta.cash
                for entry in entries
                if entry.request.stage is CorporateActionStage.CASH_PAYMENT
            ),
            Decimal("0"),
        )
        if remaining != 0 or paid <= 0:
            _blocked(
                "active cash history does not fully settle the event entitlement",
                "CORPORATE_ACTION_OWNER_PAYMENT_BASIS_REQUIRED",
            )


def _outstanding_share_receivable(rows: tuple[CorporateActionPostingModel, ...]) -> Decimal:
    """Return only the complete, undelivered whole-share event receivable."""

    entitlements = tuple(
        row for row in rows if row.stage == CorporateActionStage.SHARE_ENTITLEMENT.value
    )
    if not entitlements:
        _blocked(
            "a posted whole-share entitlement is required before delivery",
            "CORPORATE_ACTION_OWNER_SHARE_ENTITLEMENT_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        outstanding = sum((row.share_receivable_delta for row in rows), Decimal("0"))
        if outstanding <= 0 or outstanding != outstanding.to_integral_value():
            _blocked(
                "no complete whole-share receivable is available for delivery",
                "CORPORATE_ACTION_OWNER_SHARE_RECEIVABLE_EMPTY",
            )
        return outstanding.quantize(Decimal("0.000001"))


def _outstanding_share_receivable_from_revision_head(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> Decimal:
    """Return the full whole-share receivable from a validated active share head."""

    if (
        type(entries) is not tuple
        or not entries
        or any(
            type(entry) is not OwnerCorporateActionRevisionEntry
            or entry.request.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION
            or entry.request.stage
            not in {
                CorporateActionStage.SHARE_ENTITLEMENT,
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            for entry in entries
        )
        or not any(
            entry.request.stage is CorporateActionStage.SHARE_ENTITLEMENT for entry in entries
        )
    ):
        _blocked(
            "a complete active share entitlement head is required before delivery",
            "CORPORATE_ACTION_OWNER_SHARE_ENTITLEMENT_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        outstanding = sum((entry.delta.share_receivable for entry in entries), Decimal("0"))
        if outstanding <= 0 or outstanding != outstanding.to_integral_value():
            _blocked(
                "no complete whole-share receivable is available for delivery",
                "CORPORATE_ACTION_OWNER_SHARE_RECEIVABLE_EMPTY",
            )
        return outstanding.quantize(Decimal("0.000001"))


def _outstanding_locked_shares(rows: tuple[CorporateActionPostingModel, ...]) -> Decimal:
    """Return all delivered, not-yet-released whole shares for this event."""

    if not any(row.stage == CorporateActionStage.SHARE_DELIVERY.value for row in rows):
        _blocked(
            "a retained share delivery is required before sellable release",
            "CORPORATE_ACTION_OWNER_DELIVERY_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        delivered = sum(
            (
                row.share_delta
                for row in rows
                if row.stage == CorporateActionStage.SHARE_DELIVERY.value
            ),
            Decimal("0"),
        )
        released = sum(
            (
                row.available_share_delta
                for row in rows
                if row.stage == CorporateActionStage.SHARE_SELLABLE_RELEASE.value
            ),
            Decimal("0"),
        )
        outstanding = delivered - released
        if outstanding <= 0 or outstanding != outstanding.to_integral_value():
            _blocked(
                "no unreleased whole shares remain for this event",
                "CORPORATE_ACTION_OWNER_SELLABLE_SHARES_EMPTY",
            )
        return outstanding.quantize(Decimal("0.000001"))


def _outstanding_locked_shares_from_revision_head(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> Decimal:
    """Return delivered whole shares not released in a validated active share head."""

    if (
        type(entries) is not tuple
        or not entries
        or any(
            type(entry) is not OwnerCorporateActionRevisionEntry
            or entry.request.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION
            or entry.request.stage
            not in {
                CorporateActionStage.SHARE_ENTITLEMENT,
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            for entry in entries
        )
        or not any(entry.request.stage is CorporateActionStage.SHARE_DELIVERY for entry in entries)
    ):
        _blocked(
            "an active share delivery is required before sellable release",
            "CORPORATE_ACTION_OWNER_DELIVERY_REQUIRED",
        )
    with localcontext() as context:
        context.prec = 80
        delivered = sum(
            (
                entry.delta.shares
                for entry in entries
                if entry.request.stage is CorporateActionStage.SHARE_DELIVERY
            ),
            Decimal("0"),
        )
        released = sum(
            (
                entry.delta.available_shares
                for entry in entries
                if entry.request.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE
            ),
            Decimal("0"),
        )
        outstanding = delivered - released
        if outstanding <= 0 or outstanding != outstanding.to_integral_value():
            _blocked(
                "no unreleased whole shares remain for this event",
                "CORPORATE_ACTION_OWNER_SELLABLE_SHARES_EMPTY",
            )
        return outstanding.quantize(Decimal("0.000001"))


def _blocked(
    message: str,
    code: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise a stable preparation block without exposing raw provider or database details."""

    error = CorporateActionOwnerEventPreparationBlocked(message, code=code)
    if cause is None:
        raise error
    raise error from cause
