"""Read one exact retained M1 price publication for historical reconstruction only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal, Protocol, cast
from uuid import UUID

from apps.data_center.application.price_response_capture import (
    ExactPriceBarRequestScope,
    ExactPriceBarValues,
    extract_exact_tushare_price_values,
)
from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
)
from apps.data_center.application.published_price_source import PublishedPriceSourceFact
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import parse_provider_response_json
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
)
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError, DataValidationError
from core.integration.data_center_audit import (
    AuditCategory,
    AuditEvidenceRef,
    AuditOutcome,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    RetainedSystemAuditPair,
    SystemAuditEvent,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)

_DATASET_KEY = "equity.price.bar"
_DATA_PUBLICATION_EVENT = "data.publication.published"
_ROLLBACK_EVENT = "data.publication.rolled_back"
_ACCEPTED_PUBLICATION_STATES = frozenset({PublicationState.PUBLISHED, PublicationState.SUPERSEDED})


class RetainedHistoricalPriceSourceError(DataValidationError):
    """The exact retained historical price source is absent or inconsistent."""

    default_message = "Retained historical price source evidence is unavailable"
    default_code = "RETAINED_HISTORICAL_PRICE_SOURCE_BLOCKED"


@dataclass(frozen=True, slots=True)
class RetainedHistoricalPriceSourceRequest:
    """Select one explicit M1 price-bar member at an explicit knowledge cutoff."""

    asset_code: str
    trade_date: date
    publication_id: str
    expected_publication_key: str
    knowledge_cutoff: datetime

    def __post_init__(self) -> None:
        """Require canonical selectors and an aware, explicit historical cutoff."""
        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code != self.asset_code.strip().upper()
            or type(self.trade_date) is not date
            or type(self.publication_id) is not str
            or type(self.expected_publication_key) is not str
            or self.expected_publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or type(self.knowledge_cutoff) is not datetime
            or self.knowledge_cutoff.tzinfo is None
            or self.knowledge_cutoff.utcoffset() is None
        ):
            raise RetainedHistoricalPriceSourceError("historical price selector is invalid")
        try:
            if str(UUID(self.publication_id)) != self.publication_id:
                raise ValueError("publication id is not canonical")
        except (AttributeError, TypeError, ValueError) as error:
            raise RetainedHistoricalPriceSourceError(
                "historical price publication id is invalid"
            ) from error


@dataclass(frozen=True, slots=True)
class RetainedHistoricalPriceActivation:
    """Original publication activation Audit event and exact retained Outbox pair."""

    pair: RetainedSystemAuditPair

    def __post_init__(self) -> None:
        """Require the Audit-owned immutable retained-pair contract."""
        if type(self.pair) is not RetainedSystemAuditPair:
            raise TypeError("activation must contain a RetainedSystemAuditPair")


@dataclass(frozen=True, slots=True)
class RetainedHistoricalPriceEvidence:
    """Historical raw-price evidence whose type never grants current use."""

    price: RetainedHistoricalPriceSourceFactEvidence
    activation: RetainedHistoricalPriceActivation
    knowledge_cutoff: datetime
    knowledge_semantics: Literal["currently_known_historical"] = "currently_known_historical"
    must_not_use_for_decision: Literal[True] = True

    def __post_init__(self) -> None:
        """Keep this evidence explicitly historical and non-decision-capable."""
        if type(self.price) is not RetainedHistoricalPriceSourceFactEvidence:
            raise TypeError("historical price evidence is untyped")
        if type(self.activation) is not RetainedHistoricalPriceActivation:
            raise TypeError("historical activation evidence is untyped")
        _aware(self.knowledge_cutoff, "historical knowledge cutoff")
        if self.knowledge_semantics != "currently_known_historical":
            raise ValueError("historical evidence semantics are invalid")
        if self.must_not_use_for_decision is not True:
            raise ValueError("retained historical price cannot grant decision authority")


@dataclass(frozen=True, slots=True)
class RetainedHistoricalPriceSourceFactEvidence:
    """Exact selected publication member, fact, manifest, and original response facts."""

    publication_id: str
    publication_hash: str
    publication_state: PublicationState
    publication_version: str
    publication_key: str
    run_id: str
    manifest_id: str
    manifest_hash: str
    member_id: str
    fact_pk: str
    fact_content_hash: str
    asset_code: str
    trade_date: date
    values: ExactPriceBarValues
    source: str
    interval_end_at: datetime
    source_observed_at: None
    source_available_at: datetime
    fact_recorded_at: datetime
    publication_as_of: datetime
    publication_published_at: datetime
    raw_audit_reference: CandidateRawAuditReference
    raw_payload_reference: ProviderResponsePayloadReference
    adjustment: Literal[PriceAdjustment.NONE] = PriceAdjustment.NONE
    volume_unit: Literal["shares"] = "shares"
    amount_unit: Literal["CNY"] = "CNY"

    def __post_init__(self) -> None:
        """Reject incomplete historical identity, non-raw values, or rewritten clocks."""
        if self.publication_state not in _ACCEPTED_PUBLICATION_STATES:
            raise ValueError("historical price publication was never activated")
        if self.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY:
            raise ValueError("historical price publication key is unsupported")
        if type(self.values) is not ExactPriceBarValues:
            raise TypeError("historical price values must remain exact Decimals")
        if self.adjustment is not PriceAdjustment.NONE:
            raise ValueError("historical price must remain unadjusted")
        if self.source_observed_at is not None:
            raise ValueError("supplier observation time must remain unknown")
        if self.volume_unit != "shares" or self.amount_unit != "CNY":
            raise ValueError("historical price units are unsupported")
        for field_name in (
            "interval_end_at",
            "source_available_at",
            "fact_recorded_at",
            "publication_as_of",
            "publication_published_at",
        ):
            _aware(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class RetainedHistoricalPriceSourceResult:
    """Return exact historical evidence or a stable block, always non-decision-capable."""

    evidence: RetainedHistoricalPriceEvidence | None
    blocked_reason: str
    must_not_use_for_decision: Literal[True] = True

    def __post_init__(self) -> None:
        """Require evidence or a block and permanently deny current decision use."""
        if (self.evidence is None) != bool(self.blocked_reason):
            raise ValueError("historical source result must contain evidence or a block")
        if self.evidence is not None and type(self.evidence) is not RetainedHistoricalPriceEvidence:
            raise TypeError("historical source result contains an invalid evidence value")
        if self.must_not_use_for_decision is not True:
            raise ValueError("historical source result cannot grant decision authority")


class RetainedHistoricalPublicationReader(Protocol):
    """Read exact persisted publication metadata and its complete member snapshot."""

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        """Return the exact canonical publication row without current-pointer substitution."""

    def list_members(self, publication_id: str) -> Sequence[PublicationMember]:
        """Return all immutable selected members for the exact publication."""


class RetainedHistoricalPriceRepository(Protocol):
    """Read the exact fact and source envelope already sealed by its publication."""

    def read_facts(
        self, *, asset_code: str, trade_date: date, fact_pks: tuple[str, ...]
    ) -> tuple[PublishedPriceSourceFact, ...]:
        """Return at most two exact daily rows, allowing ambiguity to fail closed."""

    def read_manifest(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Read the immutable RawAudit manifest for the exact publication id."""

    def read_audit(self, raw_audit_id: str) -> RawAudit | None:
        """Read one exact source RawAudit referenced by the selected manifest."""

    def read_payload(self, payload_hash: str) -> RawPayload | None:
        """Read the retained response envelope by its immutable payload hash."""


class RetainedHistoricalActivationReader(Protocol):
    """Read the exact original publication activation event and Audit/Outbox pair."""

    def read_original_activation(
        self, publication_id: str, *, knowledge_cutoff: datetime
    ) -> RetainedHistoricalPriceActivation | None:
        """Return one fully checked original activation known by the supplied cutoff."""


class ReadRetainedHistoricalPriceSource:
    """Verify retained daily source lineage without consulting current pointers."""

    def __init__(
        self,
        *,
        publications: RetainedHistoricalPublicationReader,
        prices: RetainedHistoricalPriceRepository,
        activations: RetainedHistoricalActivationReader,
    ) -> None:
        """Bind exact, read-only ports supplied by the Data Center composition root."""
        self._publications = publications
        self._prices = prices
        self._activations = activations

    def execute(
        self, request: RetainedHistoricalPriceSourceRequest
    ) -> RetainedHistoricalPriceSourceResult:
        """Read one explicitly selected retained M1 daily close as historical evidence."""
        try:
            evidence = self._read(request)
        except _HistoricalPriceEvidenceInvalid as error:
            return RetainedHistoricalPriceSourceResult(None, error.code)
        except (SystemAuditEventOutboxCorruption, SystemAuditEventOutboxUnavailable):
            return RetainedHistoricalPriceSourceResult(
                None, "retained_price_original_activation_unavailable"
            )
        except (DataFetchError, DataValidationError, TypeError, ValueError, OverflowError):
            return RetainedHistoricalPriceSourceResult(
                None, "retained_historical_price_evidence_invalid"
            )
        return RetainedHistoricalPriceSourceResult(evidence, "")

    def _read(
        self, request: RetainedHistoricalPriceSourceRequest
    ) -> RetainedHistoricalPriceEvidence:
        """Validate publication, complete seal, original activation, and exact source body."""
        publication = self._publications.get_by_id(request.publication_id)
        _require(publication is not None, "retained_price_publication_missing")
        if publication is None:
            raise _HistoricalPriceEvidenceInvalid("retained_price_publication_missing")
        members = tuple(self._publications.list_members(publication.publication_id))
        _verify_publication(publication, members, request)
        activation = self._activations.read_original_activation(
            publication.publication_id,
            knowledge_cutoff=request.knowledge_cutoff,
        )
        _require(
            type(activation) is RetainedHistoricalPriceActivation,
            "retained_price_original_activation_missing",
        )
        if type(activation) is not RetainedHistoricalPriceActivation:
            raise _HistoricalPriceEvidenceInvalid("retained_price_original_activation_missing")
        manifest = self._prices.read_manifest(publication.publication_id)
        _require(type(manifest) is CandidateRawAuditManifest, "retained_price_manifest_missing")
        if type(manifest) is not CandidateRawAuditManifest:
            raise _HistoricalPriceEvidenceInvalid("retained_price_manifest_missing")
        _verify_manifest(manifest, publication)
        _verify_activation(activation, publication, manifest, request.knowledge_cutoff)
        facts = self._prices.read_facts(
            asset_code=request.asset_code,
            trade_date=request.trade_date,
            fact_pks=tuple(member.fact_pk for member in members),
        )
        _require(len(facts) == 1, "retained_price_fact_missing_or_ambiguous")
        if len(facts) != 1:
            raise _HistoricalPriceEvidenceInvalid("retained_price_fact_missing_or_ambiguous")
        fact = facts[0]
        selected = tuple(member for member in members if member.fact_pk == fact.reference.fact_pk)
        _require(len(selected) == 1, "retained_price_member_missing_or_ambiguous")
        if len(selected) != 1:
            raise _HistoricalPriceEvidenceInvalid("retained_price_member_missing_or_ambiguous")
        member = selected[0]
        _verify_fact(
            fact,
            member,
            request,
            publication_as_of=_aware(
                publication.as_of,
                "retained_price_publication_time_missing",
            ),
        )
        audit_refs = tuple(
            item for item in manifest.raw_audits if item.ingested_run_id == fact.ingested_run_id
        )
        _require(len(audit_refs) == 1, "retained_price_raw_audit_missing_or_ambiguous")
        if len(audit_refs) != 1:
            raise _HistoricalPriceEvidenceInvalid("retained_price_raw_audit_missing_or_ambiguous")
        audit_reference = audit_refs[0]
        audit = self._prices.read_audit(audit_reference.raw_audit_id)
        _require(type(audit) is RawAudit, "retained_price_raw_audit_missing")
        if type(audit) is not RawAudit:
            raise _HistoricalPriceEvidenceInvalid("retained_price_raw_audit_missing")
        _verify_raw_audit(audit, audit_reference, fact.reference.source, request.knowledge_cutoff)
        scope = _request_scope(audit, request.asset_code, request.trade_date)
        payload_reference = ProviderResponsePayloadReference.from_payload(
            _mapping(audit.extra.get("provider_response_payload_reference"))
        )
        _require(
            payload_reference.provider_name == scope.provider_name
            and payload_reference.dataset_key == scope.dataset_key
            and payload_reference.run_id == audit.run_id
            and payload_reference.payload_hash == audit.response_payload_hash,
            "retained_price_response_identity_mismatch",
        )
        raw = self._prices.read_payload(payload_reference.payload_hash)
        _require(
            type(raw) is RawPayload and payload_reference.verifies(raw),
            "retained_price_response_missing_or_changed",
        )
        if type(raw) is not RawPayload:
            raise _HistoricalPriceEvidenceInvalid("retained_price_response_missing_or_changed")
        _require(
            raw.request_params == scope.request_params()
            and raw.payload.get("api_name") == scope.api_name
            and raw.fetched_at <= request.knowledge_cutoff,
            "retained_price_response_request_or_clock_mismatch",
        )
        _require(
            payload_reference.original_body_retained
            and payload_reference.retained_content_encoding == "exact_original_utf8_json",
            "retained_price_original_body_unavailable",
        )
        retained = raw.payload.get("retained_response_json")
        _require(isinstance(retained, str), "retained_price_original_body_missing")
        if not isinstance(retained, str):
            raise _HistoricalPriceEvidenceInvalid("retained_price_original_body_missing")
        body = retained.encode("utf-8")
        _require(
            sha256(body).hexdigest() == payload_reference.body_sha256,
            "retained_price_original_body_hash_mismatch",
        )
        values = extract_exact_tushare_price_values(
            parse_provider_response_json(body), request_scope=scope
        )
        _require(values == fact.values, "retained_price_decimal_values_mismatch")
        known_at = payload_reference.response_completed_at
        published_at = _aware(publication.published_at, "retained_price_publication_time_missing")
        _require(
            member.observed_at is not None
            and member.fetched_at is not None
            and member.observed_at <= known_at <= audit.fetched_at <= published_at
            and member.fetched_at <= request.knowledge_cutoff
            and (member.available_at is None or member.available_at <= request.knowledge_cutoff)
            and (
                member.source_published_at is None
                or member.source_published_at <= request.knowledge_cutoff
            ),
            "retained_price_source_clock_invalid",
        )
        return RetainedHistoricalPriceEvidence(
            price=RetainedHistoricalPriceSourceFactEvidence(
                publication_id=publication.publication_id,
                publication_hash=publication.publication_hash,
                publication_state=publication.state,
                publication_version=publication.policy_version,
                publication_key=publication.publication_key,
                run_id=publication.run_id,
                manifest_id=manifest.manifest_id,
                manifest_hash=manifest.manifest_hash,
                member_id=member.member_id,
                fact_pk=member.fact_pk,
                fact_content_hash=member.fact_content_hash,
                asset_code=request.asset_code,
                trade_date=request.trade_date,
                values=values,
                source=fact.reference.source,
                interval_end_at=cast(datetime, member.observed_at),
                source_observed_at=None,
                source_available_at=known_at,
                fact_recorded_at=cast(datetime, member.fetched_at),
                publication_as_of=cast(datetime, publication.as_of),
                publication_published_at=cast(datetime, publication.published_at),
                raw_audit_reference=audit_reference,
                raw_payload_reference=payload_reference,
            ),
            activation=activation,
            knowledge_cutoff=request.knowledge_cutoff,
        )


def _verify_publication(
    publication: CanonicalPublication,
    members: tuple[PublicationMember, ...],
    request: RetainedHistoricalPriceSourceRequest,
) -> None:
    """Verify the full exact publication snapshot and original activation state."""
    if (
        type(publication) is not CanonicalPublication
        or type(publication.state) is not PublicationState
        or publication.state not in _ACCEPTED_PUBLICATION_STATES
        or publication.must_not_use_for_decision is not False
        or publication.publication_id != request.publication_id
        or publication.dataset_key != _DATASET_KEY
        or publication.publication_key != request.expected_publication_key
        or publication.member_count < 1
        or len(members) != publication.member_count
        or publication.conflict_count != 0
        or publication.coverage.publication_id != publication.publication_id
        or publication.coverage.selected_count != publication.member_count
        or publication.coverage.eligible_count != publication.member_count
        or publication.coverage.requested_count != publication.member_count
        or publication.coverage.missing_count != 0
        or publication.coverage.conflict_count != 0
        or publication.scope_blocks
        or publication.selected_source != "tushare"
    ):
        raise _HistoricalPriceEvidenceInvalid("retained_price_publication_invalid")
    published_at = _aware(publication.published_at, "retained_price_publication_time_missing")
    publication_as_of = _aware(publication.as_of, "retained_price_publication_time_missing")
    _require(
        publication_as_of <= published_at <= request.knowledge_cutoff
        and publication.coverage.generated_at <= request.knowledge_cutoff
        and publication.coverage.generated_at <= published_at
        and (
            publication.state is not PublicationState.SUPERSEDED
            or publication.superseded_at is not None
        ),
        "retained_price_publication_clock_invalid",
    )
    if any(
        type(member) is not PublicationMember
        or member.publication_id != publication.publication_id
        or member.dataset_key != publication.dataset_key
        or member.fact_table != "data_center_price_bar"
        for member in members
    ):
        raise _HistoricalPriceEvidenceInvalid("retained_price_member_scope_invalid")
    if (
        len({member.member_id for member in members}) != len(members)
        or len({member.natural_key for member in members}) != len(members)
        or len({(member.fact_table, member.fact_pk) for member in members}) != len(members)
    ):
        raise _HistoricalPriceEvidenceInvalid("retained_price_member_identity_ambiguous")
    try:
        references = tuple(member_reference(member) for member in members)
        expected_publication_hash = publication_hash(
            references,
            policy_identity=(
                publication.policy_version if publication.policy_version.startswith("p2:") else None
            ),
            scope_blocks=publication.scope_blocks,
        )
    except (TypeError, ValueError) as error:
        raise _HistoricalPriceEvidenceInvalid("retained_price_member_seal_invalid") from error
    _require(
        expected_publication_hash == publication.publication_hash,
        "retained_price_publication_hash_mismatch",
    )


def _verify_manifest(
    manifest: CandidateRawAuditManifest, publication: CanonicalPublication
) -> None:
    """Verify every manifest identity and its complete ordered Audit reference set."""
    if type(manifest) is not CandidateRawAuditManifest:
        raise _HistoricalPriceEvidenceInvalid("retained_price_manifest_invalid")
    try:
        manifest.__post_init__()
    except (TypeError, ValueError) as error:
        raise _HistoricalPriceEvidenceInvalid("retained_price_manifest_invalid") from error
    references = manifest.raw_audits
    _require(
        manifest.publication_id == publication.publication_id
        and manifest.publication_hash == publication.publication_hash
        and manifest.run_id == publication.run_id
        and manifest.dataset_key == publication.dataset_key
        and manifest.publication_key == publication.publication_key
        and manifest.raw_audit_count == publication.member_count
        and len(references) == publication.member_count
        and len({item.raw_audit_id for item in references}) == len(references)
        and len({item.run_id for item in references}) == len(references)
        and len({item.ingested_run_id for item in references}) == len(references)
        and all(
            item.capability == canonical_capability_for_publication_dataset(_DATASET_KEY)
            and item.provider_name == publication.selected_source
            for item in references
        ),
        "retained_price_manifest_identity_mismatch",
    )


def _verify_activation(
    activation: RetainedHistoricalPriceActivation,
    publication: CanonicalPublication,
    manifest: CandidateRawAuditManifest,
    cutoff: datetime,
) -> None:
    """Bind the original full-manifest publication event and exact retained pair."""
    pair = activation.pair
    pair.verify_at_cutoff(as_of=cutoff)
    event = pair.event
    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise _HistoricalPriceEvidenceInvalid("retained_price_activation_hash_invalid") from error
    expected_refs = (
        AuditEvidenceRef(
            "data_center",
            "candidate_raw_audit_manifest",
            manifest.manifest_id,
            manifest.manifest_version,
            manifest.manifest_hash,
        ),
        *(
            AuditEvidenceRef(
                "data_center", "raw_audit", item.raw_audit_id, item.version, item.content_hash
            )
            for item in manifest.raw_audits
        ),
        AuditEvidenceRef(
            "data_center",
            "canonical_publication",
            publication.publication_id,
            publication.policy_version,
            publication.publication_hash,
        ),
    )
    expected_detail_manifest = {
        "manifest_id": manifest.manifest_id,
        "manifest_version": manifest.manifest_version,
        "manifest_hash": manifest.manifest_hash,
        "raw_audit_count": manifest.raw_audit_count,
        "raw_audit_hash": manifest.raw_audit_hash,
    }
    detail_manifest = event.detail.get("raw_audit_manifest")
    _require(
        type(event) is SystemAuditEvent
        and type(event.scope) is AuditScopeRef
        and event.event_version == "1"
        and event.schema_version == "system-audit-event.v1"
        and event.category is AuditCategory.DATA_RELIABILITY
        and event.event_type == _DATA_PUBLICATION_EVENT
        and event.owner == "data_center"
        and event.write_policy is AuditWritePolicy.REQUIRED
        and event.outcome is AuditOutcome.PUBLISHED
        and event.severity is AuditSeverity.INFO
        and event.reason_codes == ("publication_published",)
        and event.observed_at is None
        and event.actor.actor_type == "service"
        and event.actor.actor_id == "data-center"
        and event.actor.actor_display == "data-center"
        and event.source_app == "data_center"
        and event.source_component == "publication"
        and event.source_surface == "application"
        and event.dataset_key == publication.dataset_key
        and event.provider_key == publication.selected_source
        and event.capability == "publication"
        and event.publication_id == publication.publication_id
        and event.stream_id == f"data.publication:{publication.dataset_key}"
        and event.correlations.run_id == publication.run_id
        and event.correlations.dataset_key == publication.dataset_key
        and event.correlations.provider_key == publication.selected_source
        and event.correlations.publication_id == publication.publication_id
        and event.resource is not None
        and event.resource.resource_type == "canonical_publication"
        and event.resource.resource_id == publication.publication_id
        and event.resource.resource_version == publication.policy_version
        and event.occurred_at == publication.as_of
        and event.recorded_at == publication.published_at
        and event.idempotency_key
        == (
            f"data-publication-manifest:{publication.run_id}:{publication.publication_id}:"
            f"{manifest.manifest_id}:{manifest.manifest_hash}"
        )
        and event.evidence_refs == expected_refs
        and event.detail_schema == "data.publication.published.v1"
        and event.detail.get("publication_key") == publication.publication_key
        and event.detail.get("publication_hash") == publication.publication_hash
        and _exact_int(event.detail.get("member_count"), publication.member_count)
        and _exact_int(
            event.detail.get("coverage_requested_count"),
            publication.coverage.requested_count,
        )
        and _exact_int(
            event.detail.get("coverage_eligible_count"),
            publication.coverage.eligible_count,
        )
        and _exact_int(
            event.detail.get("coverage_selected_count"),
            publication.coverage.selected_count,
        )
        and isinstance(detail_manifest, Mapping)
        and dict(detail_manifest) == expected_detail_manifest
        and pair.event == event
        and pair.audit_persisted_at <= cutoff
        and pair.outbox_created_at <= cutoff,
        "retained_price_activation_identity_mismatch",
    )


def _verify_fact(
    fact: PublishedPriceSourceFact,
    member: PublicationMember,
    request: RetainedHistoricalPriceSourceRequest,
    *,
    publication_as_of: datetime,
) -> None:
    """Bind the one selected exact daily PriceBar row back to its frozen member."""
    _require(
        type(fact) is PublishedPriceSourceFact
        and fact.asset_code == request.asset_code
        and fact.trade_date == request.trade_date
        and fact.frequency == "1d"
        and fact.adjustment is PriceAdjustment.NONE
        and fact.reference.fact_table == "data_center_price_bar"
        and fact.reference == member_reference(member)
        and member.source == fact.reference.source == "tushare"
        and member.observed_at is not None
        and member.observed_at == cn_market_session_close_utc(request.trade_date)
        and member.observed_at <= publication_as_of
        and member.fetched_at is not None
        and member.observed_at <= member.fetched_at
        and member.fetched_at <= request.knowledge_cutoff,
        "retained_price_fact_scope_or_clock_mismatch",
    )


def _verify_raw_audit(
    audit: RawAudit,
    reference: CandidateRawAuditReference,
    source: str,
    cutoff: datetime,
) -> None:
    """Verify the selected source audit and its original content digest."""
    _require(
        type(audit) is RawAudit
        and audit.raw_audit_id == reference.raw_audit_id
        and audit.content_hash == reference.content_hash == raw_audit_content_hash(audit)
        and audit.provider_name == reference.provider_name
        and audit.capability == reference.capability == "historical_price"
        and audit.run_id == reference.run_id
        and audit.ingested_run_id == reference.ingested_run_id
        and audit.status == "ok"
        and type(audit.row_count) is int
        and audit.row_count == 1
        and audit.extra.get("source_type") == source == "tushare",
        "retained_price_audit_identity_or_content_mismatch",
    )
    _require(
        _aware(audit.fetched_at, "retained_price_audit_time_missing") <= cutoff,
        "retained_price_audit_not_known",
    )


def _request_scope(audit: RawAudit, asset_code: str, trade_date: date) -> ExactPriceBarRequestScope:
    """Restore and compare both exact provider request-scope copies."""
    raw = _mapping(audit.extra.get("provider_response_request_scope"))
    provider_id = raw.get("provider_id")
    _require(type(provider_id) is int, "retained_price_request_scope_mismatch")
    if type(provider_id) is not int:
        raise _HistoricalPriceEvidenceInvalid("retained_price_request_scope_mismatch")
    scope = ExactPriceBarRequestScope(
        provider_id=provider_id,
        provider_name=audit.provider_name,
        dataset_key=_DATASET_KEY,
        api_name="daily",
        asset_code=asset_code,
        trade_date=trade_date,
    )
    _require(
        raw == scope.to_payload()
        and audit.request_params == {"exact_price_request_scope": scope.to_payload()},
        "retained_price_request_scope_mismatch",
    )
    return scope


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow one persisted JSON object before passing it to a strict decoder."""
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _HistoricalPriceEvidenceInvalid("retained_price_metadata_invalid")
    return cast(Mapping[str, object], value)


def _exact_int(value: object, expected: int) -> bool:
    """Compare an audit count without accepting bool-as-int equality."""
    return type(value) is int and value == expected


def _require(condition: bool, code: str) -> None:
    """Reject one failed historical identity without inventing a replacement."""
    if not condition:
        raise _HistoricalPriceEvidenceInvalid(code)


def _aware(value: object, code: str) -> datetime:
    """Narrow a persisted aware source clock without replacing its value."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _HistoricalPriceEvidenceInvalid(code)
    return value


class _HistoricalPriceEvidenceInvalid(DataValidationError):
    """Carry one safe machine-readable historical source block."""

    def __init__(self, code: str) -> None:
        """Bind one stable code without including retained response contents."""
        super().__init__("Retained historical price evidence is unavailable", code=code)


__all__ = [
    "ReadRetainedHistoricalPriceSource",
    "RetainedHistoricalActivationReader",
    "RetainedHistoricalPriceActivation",
    "RetainedHistoricalPriceEvidence",
    "RetainedHistoricalPriceRepository",
    "RetainedHistoricalPriceSourceError",
    "RetainedHistoricalPriceSourceFactEvidence",
    "RetainedHistoricalPriceSourceRequest",
    "RetainedHistoricalPriceSourceResult",
    "RetainedHistoricalPublicationReader",
]
