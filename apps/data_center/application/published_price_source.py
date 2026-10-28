"""Read exact retained daily-price evidence without granting execution authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal, Protocol, cast

from apps.data_center.application.price_response_capture import (
    ExactPriceBarRequestScope,
    ExactPriceBarValues,
    extract_exact_tushare_price_values,
)
from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.application.publication_utils import member_reference
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import parse_provider_response_json
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
)
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError, DataValidationError


@dataclass(frozen=True, slots=True)
class PublishedPriceSourceFact:
    """One exact ORM price row with Decimal values and its current row seal."""

    asset_code: str
    trade_date: date
    frequency: str
    adjustment: PriceAdjustment
    values: ExactPriceBarValues
    ingested_run_id: str
    reference: PublicationFactReference


@dataclass(frozen=True, slots=True)
class PublishedPriceSourceEvidence:
    """Verified retained price inputs, not a fill, settlement, or trading permission."""

    publication_id: str
    publication_hash: str
    publication_key: str
    manifest_id: str
    manifest_hash: str
    member_id: str
    fact_pk: str
    fact_content_hash: str
    asset_code: str
    trade_date: date
    values: ExactPriceBarValues
    adjustment: PriceAdjustment
    source: str
    observed_at: datetime
    available_at: datetime
    source_published_at: datetime | None
    # PriceBarModel.fetched_at is auto_now_add: the row's first write, including on replay.
    fact_recorded_at: datetime
    publication_as_of: datetime
    publication_published_at: datetime
    knowledge_cutoff: datetime
    raw_audit_reference: CandidateRawAuditReference
    raw_payload_reference: ProviderResponsePayloadReference
    volume_unit: Literal["shares"] = "shares"
    amount_unit: Literal["CNY"] = "CNY"
    availability_basis: Literal["local_response_body_completion"] = "local_response_body_completion"


@dataclass(frozen=True, slots=True)
class PublishedPriceSourceResult:
    """Return source evidence or an explicit block without a floating-point fallback."""

    evidence: PublishedPriceSourceEvidence | None
    blocked_reason: str
    freshness_status: str = "unverified"

    def __post_init__(self) -> None:
        """Require exactly one of verified evidence and a stable blocking reason."""
        if (self.evidence is None) != bool(self.blocked_reason):
            raise ValueError("price source result must contain evidence or a blocking reason")

    @property
    def must_not_use_for_decision(self) -> bool:
        """Keep blocked source reads explicitly unavailable for decisions."""
        return self.evidence is None


class PublishedPriceSourceRepository(Protocol):
    """Read original rows only; implementations must never capture or repair data."""

    def read_facts(
        self, *, asset_code: str, trade_date: date, fact_pks: tuple[str, ...]
    ) -> tuple[PublishedPriceSourceFact, ...]:
        """Return at most two exact target rows to detect ambiguous selections."""

    def read_manifest(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Read the immutable manifest without write locks or candidate substitution."""

    def read_audit(self, raw_audit_id: str) -> RawAudit | None:
        """Read the precise audit selected by the manifest."""

    def read_payload(self, payload_hash: str) -> RawPayload | None:
        """Read one retained response by its immutable envelope hash."""


def validate_price_source_request(
    asset_code: str, trade_date: date, knowledge_cutoff: datetime, publication_key: str
) -> None:
    """Validate explicit input before opening a database snapshot."""
    _require(
        type(asset_code) is str
        and bool(asset_code)
        and asset_code == asset_code.strip().upper()
        and type(trade_date) is date
        and type(publication_key) is str
        and bool(publication_key)
        and publication_key == publication_key.strip(),
        "price_source_request_invalid",
    )
    _aware(knowledge_cutoff, "price_source_cutoff_invalid")


class ReadPublishedPriceSource:
    """Verify the selected fact and its original body after the existing publication gate."""

    def __init__(self, repository: PublishedPriceSourceRepository) -> None:
        """Bind read-only evidence ports supplied by the composition root."""
        self._repository = repository

    def execute(
        self,
        *,
        asset_code: str,
        trade_date: date,
        knowledge_cutoff: datetime,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        freshness_status: str,
    ) -> PublishedPriceSourceResult:
        """Verify one target inside the caller's already-gated consistent snapshot."""
        try:
            evidence = self._read(asset_code, trade_date, knowledge_cutoff, publication, members)
        except _SourceEvidenceInvalid as error:
            return PublishedPriceSourceResult(None, error.code)
        except (DataFetchError, DataValidationError, TypeError, ValueError, OverflowError):
            return PublishedPriceSourceResult(None, "price_source_evidence_invalid")
        return PublishedPriceSourceResult(evidence, "", freshness_status)

    def _read(
        self,
        asset_code: str,
        trade_date: date,
        cutoff: datetime,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> PublishedPriceSourceEvidence:
        """Follow the frozen member, fact, manifest, audit and retained-body identities."""
        validate_price_source_request(asset_code, trade_date, cutoff, publication.publication_key)
        _require(
            publication.dataset_key == "equity.price.bar"
            and publication.state is PublicationState.PUBLISHED
            and publication.must_not_use_for_decision is False
            and bool(members)
            and len(members) == publication.member_count,
            "price_source_publication_invalid",
        )
        published_at = _aware(publication.published_at, "price_source_publication_time_missing")
        publication_as_of = _aware(publication.as_of, "price_source_publication_time_missing")
        _require(published_at <= cutoff and publication_as_of <= cutoff, "price_source_not_known")
        _require(publication_as_of <= published_at, "price_source_publication_time_invalid")
        _require(
            all(
                member.publication_id == publication.publication_id
                and member.dataset_key == publication.dataset_key
                and member.fact_table == "data_center_price_bar"
                for member in members
            ),
            "price_source_member_scope_invalid",
        )
        facts = self._repository.read_facts(
            asset_code=asset_code,
            trade_date=trade_date,
            fact_pks=tuple(member.fact_pk for member in members),
        )
        _require(len(facts) == 1, "price_source_fact_missing_or_ambiguous")
        fact = facts[0]
        selected = tuple(member for member in members if member.fact_pk == fact.reference.fact_pk)
        _require(len(selected) == 1, "price_source_member_missing_or_ambiguous")
        member = selected[0]
        _require(
            fact.asset_code == asset_code
            and fact.trade_date == trade_date
            and fact.frequency == "1d"
            and fact.adjustment is PriceAdjustment.NONE
            and bool(fact.ingested_run_id)
            and member_reference(member) == fact.reference,
            "price_source_fact_scope_or_content_mismatch",
        )
        observed = _aware(member.observed_at, "price_source_observation_missing")
        fetched = _aware(member.fetched_at, "price_source_fact_time_missing")
        _require(
            observed == cn_market_session_close_utc(trade_date)
            and observed <= publication_as_of
            and fetched <= cutoff,
            "price_source_fact_time_invalid",
        )
        manifest = self._repository.read_manifest(publication.publication_id)
        _require(manifest is not None, "price_source_manifest_missing")
        if manifest is None:
            raise _SourceEvidenceInvalid("price_source_manifest_missing")
        manifest.__post_init__()
        _require(
            manifest.publication_id == publication.publication_id
            and manifest.publication_hash == publication.publication_hash
            and manifest.run_id == publication.run_id
            and manifest.dataset_key == publication.dataset_key
            and manifest.publication_key == publication.publication_key,
            "price_source_manifest_identity_mismatch",
        )
        audit_refs = tuple(
            item for item in manifest.raw_audits if item.ingested_run_id == fact.ingested_run_id
        )
        _require(len(audit_refs) == 1, "price_source_audit_missing_or_ambiguous")
        audit_ref = audit_refs[0]
        audit = self._repository.read_audit(audit_ref.raw_audit_id)
        _require(audit is not None, "price_source_audit_missing")
        if audit is None:
            raise _SourceEvidenceInvalid("price_source_audit_missing")
        _verify_audit(audit, audit_ref, fact.reference.source, cutoff)
        scope = _request_scope(audit, asset_code, trade_date)
        reference = ProviderResponsePayloadReference.from_payload(
            _mapping(audit.extra.get("provider_response_payload_reference"))
        )
        _require(
            reference.provider_name == scope.provider_name
            and reference.dataset_key == scope.dataset_key
            and reference.run_id == audit.run_id
            and reference.payload_hash == audit.response_payload_hash,
            "price_source_response_identity_mismatch",
        )
        raw = self._repository.read_payload(reference.payload_hash)
        _require(raw is not None and reference.verifies(raw), "price_source_raw_missing_or_changed")
        if raw is None:
            raise _SourceEvidenceInvalid("price_source_raw_missing_or_changed")
        _require(
            raw.request_params == scope.request_params()
            and raw.payload.get("api_name") == scope.api_name,
            "price_source_raw_request_mismatch",
        )
        # This port promises independent replay of original HTTP values. A redacted
        # canonical body remains useful audit data but is not those original bytes.
        _require(
            reference.original_body_retained
            and reference.retained_content_encoding == "exact_original_utf8_json",
            "price_source_original_body_unavailable",
        )
        retained: object = raw.payload.get("retained_response_json")
        _require(isinstance(retained, str), "price_source_body_missing")
        if not isinstance(retained, str):
            raise _SourceEvidenceInvalid("price_source_body_missing")
        body = retained.encode("utf-8")
        _require(
            sha256(body).hexdigest() == reference.body_sha256, "price_source_body_hash_mismatch"
        )
        values = extract_exact_tushare_price_values(
            parse_provider_response_json(body), request_scope=scope
        )
        _require(values == fact.values, "price_source_decimal_values_mismatch")
        known_at = reference.response_completed_at
        _require(
            observed <= known_at <= audit.fetched_at <= published_at <= cutoff,
            "price_source_response_time_invalid",
        )
        return PublishedPriceSourceEvidence(
            publication_id=publication.publication_id,
            publication_hash=publication.publication_hash,
            publication_key=publication.publication_key,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            member_id=member.member_id,
            fact_pk=member.fact_pk,
            fact_content_hash=member.fact_content_hash,
            asset_code=asset_code,
            trade_date=trade_date,
            values=values,
            adjustment=fact.adjustment,
            source=fact.reference.source,
            observed_at=observed,
            available_at=known_at,
            source_published_at=member.source_published_at,
            fact_recorded_at=fetched,
            publication_as_of=publication_as_of,
            publication_published_at=published_at,
            knowledge_cutoff=cutoff,
            raw_audit_reference=audit_ref,
            raw_payload_reference=reference,
        )


class _SourceEvidenceInvalid(DataValidationError):
    """Carry one stable block without exposing retained response contents."""

    def __init__(self, code: str) -> None:
        """Bind a safe machine-readable block code."""
        super().__init__("Published price source evidence is unavailable", code=code)


def _require(condition: bool, code: str) -> None:
    """Reject a failed source invariant without inventing replacement evidence."""
    if not condition:
        raise _SourceEvidenceInvalid(code)


def _aware(value: object, code: str) -> datetime:
    """Narrow persisted clocks while preserving their original instants."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _SourceEvidenceInvalid(code)
    return value


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow one JSON object before passing it to an existing typed decoder."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _SourceEvidenceInvalid("price_source_metadata_invalid")
    return cast(Mapping[str, object], value)


def _verify_audit(
    audit: RawAudit, reference: CandidateRawAuditReference, source: str, cutoff: datetime
) -> None:
    """Verify only the selected audit against the immutable manifest's exact reference."""
    _require(
        audit.raw_audit_id == reference.raw_audit_id
        and audit.content_hash == reference.content_hash == raw_audit_content_hash(audit)
        and audit.provider_name == reference.provider_name
        and audit.capability
        == reference.capability
        == canonical_capability_for_publication_dataset("equity.price.bar")
        and audit.run_id == reference.run_id
        and audit.ingested_run_id == reference.ingested_run_id
        and audit.status == "ok"
        and type(audit.row_count) is int
        and audit.row_count == 1
        and audit.extra.get("source_type") == source == "tushare",
        "price_source_audit_identity_or_content_mismatch",
    )
    _require(
        _aware(audit.fetched_at, "price_source_audit_time_missing") <= cutoff,
        "price_source_not_known",
    )


def _request_scope(audit: RawAudit, asset_code: str, trade_date: date) -> ExactPriceBarRequestScope:
    """Recover the exact request and require both sealed audit copies to agree."""
    raw = _mapping(audit.extra.get("provider_response_request_scope"))
    provider_id = raw.get("provider_id")
    _require(type(provider_id) is int, "price_source_request_scope_mismatch")
    if not isinstance(provider_id, int):
        raise _SourceEvidenceInvalid("price_source_request_scope_mismatch")
    scope = ExactPriceBarRequestScope(
        provider_id=provider_id,
        provider_name=audit.provider_name,
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code=asset_code,
        trade_date=trade_date,
    )
    _require(
        raw == scope.to_payload()
        and audit.request_params == {"exact_price_request_scope": scope.to_payload()},
        "price_source_request_scope_mismatch",
    )
    return scope
