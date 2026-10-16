"""Exact ORM reader for quote facts selected by a current publication."""

from __future__ import annotations

from datetime import datetime, timedelta

from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationCandidateSnapshot,
)
from apps.data_center.application.execution_quotes import (
    ExecutionQuoteBlockReason,
    ExecutionQuotePublicationGate,
    ExecutionQuoteUnavailable,
)
from apps.data_center.domain.control_plane import PublicationMember
from apps.data_center.domain.execution_quotes import ExecutionQuoteSnapshot
from apps.data_center.domain.publication_evidence import validate_publication_quality_status
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.execution_quote_freshness import (
    validate_execution_quote_member_freshness,
)
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.publication_fact_evidence import canonical_fact_content_hash
from apps.data_center.infrastructure.publication_fact_identity import (
    build_publication_fact_identity,
)

_DATASET_KEY = "equity.quote.snapshot"
_FACT_TABLE = "data_center_quote_snapshot"


class DjangoExecutionQuoteCandidateVersionGuard:
    """Require the quote candidate policy and facts to match one active contract."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind candidate verification to the supported publication database."""

        if using != "default":
            raise ValueError("execution quote candidates require the default database")
        self._using = using

    def validate_execution_candidate(
        self,
        candidate: CurrentPublicationCandidateSnapshot,
    ) -> None:
        """Reject missing or mismatched catalog and normalized-fact versions."""

        publication = candidate.publication
        if (
            publication.dataset_key != _DATASET_KEY
            or publication.publication_key != "execution"
            or candidate.policy.dataset.value != _DATASET_KEY
        ):
            raise ValueError("execution candidate publication scope is invalid")
        contract = DatasetContractRepository().get_active_for_execution(_DATASET_KEY)
        if (
            contract is None
            or contract.key != candidate.policy.dataset
            or contract.execution_freshness_seconds is None
        ):
            raise ValueError("execution candidate contract and policy versions differ")
        validate_execution_quote_member_freshness(
            tuple(reference.observed_at for reference in candidate.references),
            as_of=publication.coverage.generated_at,
            execution_freshness_seconds=contract.execution_freshness_seconds,
        )
        fact_ids: list[str] = []
        for reference in candidate.references:
            if reference.fact_table != _FACT_TABLE:
                raise ValueError("execution quote candidate references a different fact table")
            fact_ids.append(reference.fact_pk)
        if not fact_ids or len(fact_ids) != len(set(fact_ids)):
            raise ValueError("execution quote candidate fact identities are incomplete")
        rows = list(
            QuoteSnapshotModel._default_manager.using(self._using)
            .filter(pk__in=fact_ids)
            .values_list("pk", "contract_version", "schema_version")
        )
        versions_by_id = {
            str(fact_pk): (contract_version, schema_version)
            for fact_pk, contract_version, schema_version in rows
        }
        if len(versions_by_id) != len(fact_ids) or any(
            versions_by_id.get(fact_id)
            != (contract.key.contract_version, contract.key.schema_version)
            for fact_id in fact_ids
        ):
            raise ValueError("execution quote candidate fact versions differ from its contract")


class DjangoExecutionQuoteRepository:
    """Read a quote only from the fact row frozen in the active publication."""

    def get_exact_quote(
        self,
        asset_code: str,
        *,
        publication_gate: ExecutionQuotePublicationGate,
        as_of: datetime,
    ) -> ExecutionQuoteSnapshot | None:
        """Read and verify the exact latest member without converting Decimals."""

        asset = asset_code.strip().upper()
        if (
            publication_gate.dataset_key != _DATASET_KEY
            or publication_gate.publication_key != "execution"
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.PUBLICATION_BLOCKED)
        publications = CanonicalPublicationRepository()
        publication = publications.get_current(
            publication_gate.dataset_key,
            publication_gate.publication_key,
        )
        if publication is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.PUBLICATION_MISSING)
        if (
            publication.dataset_key != publication_gate.dataset_key
            or publication.publication_key != publication_gate.publication_key
            or publication.publication_id != publication_gate.publication_id
            or publication.publication_hash != publication_gate.publication_hash
            or publication.policy_version != publication_gate.policy_identity
            or publication.as_of != publication_gate.publication_as_of
            or publication.published_at != publication_gate.published_at
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED)

        members = publications.list_members(publication.publication_id)
        if not members:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.MEMBER_MISSING)
        if any(
            member.dataset_key != _DATASET_KEY or member.fact_table != _FACT_TABLE
            for member in members
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED)
        asset_members = tuple(
            member
            for member in members
            if member.natural_key.split(":", 1)[0].strip().upper() == asset
        )
        if not asset_members:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.MEMBER_MISSING)
        if any(member.observed_at is None for member in asset_members):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_EVIDENCE_MISSING)
        latest_observation = max(
            member.observed_at for member in asset_members if member.observed_at is not None
        )
        latest_members = tuple(
            member for member in asset_members if member.observed_at == latest_observation
        )
        if len(latest_members) != 1:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.MEMBER_AMBIGUOUS)
        member = latest_members[0]
        if not isinstance(member, PublicationMember):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED)
        if member.source.startswith("qmt-bridge:"):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_UNVERIFIED)
        try:
            validate_publication_quality_status(member.quality_status)
        except ValueError:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_UNVERIFIED) from None

        row = QuoteSnapshotModel._default_manager.filter(pk=member.fact_pk).first()
        if row is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_MISSING)
        if (
            row.contract_version != publication_gate.contract_version
            or row.schema_version != publication_gate.schema_version
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.CONTRACT_MISMATCH)
        try:
            identity = build_publication_fact_identity(_DATASET_KEY, row)
            digest = canonical_fact_content_hash(row)
        except (TypeError, ValueError):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED) from None
        if (
            str(row.pk) != member.fact_pk
            or identity.natural_key != member.natural_key
            or identity.source != member.source
            or identity.observed_at != member.observed_at
            or identity.source_record_id != member.source_record_id
            or identity.raw_payload_hash != member.raw_payload_hash
            or identity.quality_status != member.quality_status
            or identity.revision_number != member.revision_number
            or row.fetched_at != member.fetched_at
            or digest != member.fact_content_hash
        ):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED)
        if row.fetched_at is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.SOURCE_EVIDENCE_MISSING)
        if row.snapshot_at > as_of or row.fetched_at > as_of:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FUTURE_EVIDENCE)

        execution_freshness_seconds = publication_gate.execution_freshness_seconds
        if execution_freshness_seconds is None:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.POLICY_MISSING)
        try:
            freshness_deadline = row.snapshot_at + timedelta(seconds=execution_freshness_seconds)
        except OverflowError:
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
        if as_of >= freshness_deadline:
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.STALE)
        try:
            return ExecutionQuoteSnapshot(
                asset_code=row.asset_code,
                last=row.current_price,
                bid=row.bid,
                ask=row.ask,
                previous_close=row.prev_close,
                snapshot_at=row.snapshot_at,
                fetched_at=row.fetched_at,
                fact_pk=str(row.pk),
                fact_content_hash=digest,
                publication_id=publication.publication_id,
                publication_hash=publication.publication_hash,
                publication_as_of=publication.as_of,
                published_at=publication.published_at,
                freshness_deadline=freshness_deadline,
                queried_at=as_of,
                policy_identity=publication.policy_version,
                source=row.source,
                quality_status=row.quality_status,
                dataset_key=publication_gate.dataset_key,
                contract_version=publication_gate.contract_version,
                schema_version=publication_gate.schema_version,
                contract_resolution=publication_gate.contract_resolution,
                execution_freshness_seconds=execution_freshness_seconds,
            )
        except (AttributeError, TypeError, ValueError):
            raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.FACT_CHANGED) from None


__all__ = [
    "DjangoExecutionQuoteCandidateVersionGuard",
    "DjangoExecutionQuoteRepository",
]
