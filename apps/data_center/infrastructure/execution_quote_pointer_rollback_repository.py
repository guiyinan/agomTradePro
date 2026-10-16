"""Fenced rollback for the dedicated execution quote current pointer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from django.db import DatabaseError, connections
from django.utils import timezone

from apps.data_center.application.execution_quote_pointer_rollback import (
    ExecutionQuotePointerRollbackAuditObservation,
    ExecutionQuotePointerRollbackAuditReceipt,
    ExecutionQuotePointerRollbackAuditWriter,
    ExecutionQuotePointerRollbackCommand,
    ExecutionQuotePointerRollbackError,
    ExecutionQuotePointerRollbackResult,
)
from apps.data_center.application.publication_activation import (
    PublicationActivationAuthorityFence,
    PublicationActivationAuthorityLease,
    publication_activation_lease_from_complete_graph,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_manifest_hash,
)
from apps.data_center.domain.contracts import DatasetContract, PublicationPolicy
from apps.data_center.domain.control_plane import (
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.execution_quote_freshness import (
    validate_execution_quote_member_freshness,
)
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.publication_fact_identity import (
    publication_fact_model_registry,
)
from apps.data_center.infrastructure.publication_fact_write_lock import (
    acquire_execution_catalog_activation_lock,
    acquire_publication_fact_activation_locks,
)
from apps.data_center.infrastructure.publication_member_store import (
    publication_fact_content_hashes_and_ingested_runs,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)

_DEFAULT_ALIAS: Final[str] = "default"
_DATASET_KEY: Final[str] = "equity.quote.snapshot"
_PUBLICATION_KEY: Final[str] = "execution"
_FACT_TABLE: Final[str] = "data_center_quote_snapshot"
_ROLLBACK_VERSION: Final[str] = "1"


class DjangoExecutionQuotePointerRollbackRepository:
    """Restore one exact execution pointer under Account, catalog, and fact fences."""

    def __init__(self, *, using: str = _DEFAULT_ALIAS) -> None:
        """Bind the rollback repository to the supported publication alias."""

        if using != _DEFAULT_ALIAS:
            raise ValueError("execution quote pointer rollback requires the default database")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias shared by Account, Data Center, and Audit storage."""

        return self._using

    def rollback_execution_quote_pointer(
        self,
        command: ExecutionQuotePointerRollbackCommand,
        *,
        audit_writer: ExecutionQuotePointerRollbackAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> ExecutionQuotePointerRollbackResult:
        """Apply or exactly replay one pointer rollback in the Account outer transaction."""

        if type(command) is not ExecutionQuotePointerRollbackCommand:
            raise ExecutionQuotePointerRollbackError("rollback command is invalid")
        command.__post_init__()
        connection = connections[self._using]
        if connection.in_atomic_block:
            raise ExecutionQuotePointerRollbackError(
                "execution pointer rollback cannot join an ambient transaction"
            )
        if getattr(audit_writer, "database_alias", None) != self._using:
            raise ExecutionQuotePointerRollbackError("rollback Audit database alias differs")
        if not callable(getattr(authority_fence, "fence_complete", None)):
            raise ExecutionQuotePointerRollbackError("complete Account authority fence is missing")
        try:
            with authority_fence.fence_complete(authority_proof) as graph_result:
                lease = publication_activation_lease_from_complete_graph(graph_result)
                if type(lease) is not PublicationActivationAuthorityLease:
                    raise ExecutionQuotePointerRollbackError(
                        "complete Account authority lease is invalid"
                    )
                if lease.database_alias != self._using:
                    raise ExecutionQuotePointerRollbackError(
                        "complete Account authority alias differs"
                    )
                return self._rollback_in_fence(
                    command,
                    audit_writer=audit_writer,
                    lease=lease,
                )
        except ExecutionQuotePointerRollbackError:
            raise
        except Exception as error:
            raise ExecutionQuotePointerRollbackError(
                "execution pointer rollback transaction failed closed"
            ) from error

    def _rollback_in_fence(
        self,
        command: ExecutionQuotePointerRollbackCommand,
        *,
        audit_writer: ExecutionQuotePointerRollbackAuditWriter,
        lease: PublicationActivationAuthorityLease,
    ) -> ExecutionQuotePointerRollbackResult:
        """Lock the catalog, facts, pointer, and publications before validating evidence."""

        connection = connections[self._using]
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if (
            not connection.in_atomic_block
            or connection.get_autocommit()
            or not isinstance(atomic_blocks, list)
            or len(atomic_blocks) != 1
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback requires the complete Account fence's outermost transaction"
            )
        self._validate_authority(lease)

        try:
            acquire_execution_catalog_activation_lock(using=self._using)
            fact_model = publication_fact_model_registry().get(_DATASET_KEY)
            if fact_model is not QuoteSnapshotModel:
                raise ExecutionQuotePointerRollbackError(
                    "execution quote fact model is not registered exactly"
                )
            acquire_publication_fact_activation_locks((fact_model,), using=self._using)
        except DatabaseError as error:
            raise ExecutionQuotePointerRollbackError(
                "execution rollback catalog or fact fence is unavailable"
            ) from error

        pointer = (
            CanonicalPublicationPointerModel._default_manager.using(self._using)
            .select_for_update()
            .filter(dataset_key=_DATASET_KEY, publication_key=_PUBLICATION_KEY)
            .first()
        )
        if pointer is None:
            raise ExecutionQuotePointerRollbackError("execution quote pointer is missing")

        rollback_row = (
            PublicationRollbackModel._default_manager.using(self._using)
            .select_for_update()
            .filter(rollback_id=UUID(command.rollback_id))
            .first()
        )
        if rollback_row is not None:
            target, previous = self._lock_publications(
                UUID(command.target_publication_id),
                UUID(command.expected_current_publication_id),
            )
            target_members, previous_members = self._lock_members(target, previous)
            contract, policy = self._lock_current_configuration()
            self._validate_replay_identity(
                command,
                rollback_row=rollback_row,
                pointer=pointer,
                target=target,
                previous=previous,
            )
            self._validate_publication_evidence(
                target,
                target_members,
                contract=contract,
                policy=policy,
                now=timezone.now(),
                knowledge_cutoff=lease.checked_at,
                require_execution_freshness=True,
            )
            self._validate_publication_evidence(
                previous,
                previous_members,
                contract=contract,
                policy=policy,
                now=timezone.now(),
                knowledge_cutoff=lease.checked_at,
                require_execution_freshness=False,
            )
            rollback_hash = _rollback_content_hash(rollback_row)
            observation = self._audit_observation(
                command,
                rollback_row=rollback_row,
                target=target,
                previous=previous,
                previous_pointer_activation_id=command.expected_current_activation_id,
                rollback_hash=rollback_hash,
                lease=lease,
                recorded_at=rollback_row.created_at,
            )
            pre_audit_checked_at = timezone.now()
            self._validate_authority(lease, now=pre_audit_checked_at)
            self._validate_publication_evidence(
                target,
                target_members,
                contract=contract,
                policy=policy,
                now=pre_audit_checked_at,
                knowledge_cutoff=lease.checked_at,
                require_execution_freshness=True,
            )
            self._validate_publication_evidence(
                previous,
                previous_members,
                contract=contract,
                policy=policy,
                now=pre_audit_checked_at,
                knowledge_cutoff=lease.checked_at,
                require_execution_freshness=False,
            )
            receipt = audit_writer.execute_in_caller_transaction(
                observation,
                exact_replay=True,
            )
            self._validate_post_audit(
                lease=lease,
                target=target,
                target_members=target_members,
                previous=previous,
                previous_members=previous_members,
                contract=contract,
                policy=policy,
                pointer_id=pointer.pointer_id,
                rollback_id=rollback_row.rollback_id,
                target_hash=target.publication_hash,
                observed_at=rollback_row.observed_at,
                expected_previous_activation_id=command.expected_current_activation_id,
                receipt=receipt,
                pre_audit_checked_at=pre_audit_checked_at,
            )
            return self._result(target, rollback_row.rollback_id, receipt)

        target, previous = self._lock_publications(
            UUID(command.target_publication_id),
            UUID(command.expected_current_publication_id),
        )
        target_members, previous_members = self._lock_members(target, previous)
        contract, policy = self._lock_current_configuration()
        self._validate_new_identity(command, pointer=pointer, target=target, previous=previous)
        self._validate_publication_evidence(
            target,
            target_members,
            contract=contract,
            policy=policy,
            now=timezone.now(),
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=True,
        )
        self._validate_publication_evidence(
            previous,
            previous_members,
            contract=contract,
            policy=policy,
            now=timezone.now(),
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=False,
        )

        now = timezone.now()
        self._validate_authority(lease, now=now)
        if command.observed_at > now:
            raise ExecutionQuotePointerRollbackError("rollback operation time is in the future")
        self._validate_execution_freshness(target_members, contract, now)

        updated_current = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .filter(
                publication_id=previous.publication_id,
                dataset_key=_DATASET_KEY,
                publication_key=_PUBLICATION_KEY,
                publication_hash=command.expected_current_publication_hash,
                state=PublicationState.PUBLISHED.value,
            )
            .update(
                state=PublicationState.SUPERSEDED.value,
                superseded_at=command.observed_at,
            )
        )
        updated_target = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .filter(
                publication_id=target.publication_id,
                dataset_key=_DATASET_KEY,
                publication_key=_PUBLICATION_KEY,
                publication_hash=command.target_publication_hash,
                state=PublicationState.SUPERSEDED.value,
            )
            .update(
                state=PublicationState.PUBLISHED.value,
                reinstated_at=command.observed_at,
            )
        )
        updated_pointer = (
            CanonicalPublicationPointerModel._default_manager.using(self._using)
            .filter(
                pointer_id=pointer.pointer_id,
                dataset_key=_DATASET_KEY,
                publication_key=_PUBLICATION_KEY,
                publication_id=previous.publication_id,
                publication_hash=command.expected_current_publication_hash,
                activation_id=command.expected_current_activation_id,
            )
            .update(
                publication_id=target.publication_id,
                publication_hash=target.publication_hash,
                activation_id=command.rollback_id,
            )
        )
        if updated_current != 1 or updated_target != 1 or updated_pointer != 1:
            raise ExecutionQuotePointerRollbackError(
                "execution quote pointer compare-and-swap failed"
            )
        rollback_row = PublicationRollbackModel._default_manager.using(self._using).create(
            rollback_id=UUID(command.rollback_id),
            target_publication_id=target.publication_id,
            previous_publication_id=previous.publication_id,
            dataset_key=_DATASET_KEY,
            publication_key=_PUBLICATION_KEY,
            reason=command.reason,
            operator=command.operator,
            observed_at=command.observed_at,
        )
        rollback_hash = _rollback_content_hash(rollback_row)
        observation = self._audit_observation(
            command,
            rollback_row=rollback_row,
            target=target,
            previous=previous,
            previous_pointer_activation_id=command.expected_current_activation_id,
            rollback_hash=rollback_hash,
            lease=lease,
            recorded_at=rollback_row.created_at,
        )
        pre_audit_checked_at = timezone.now()
        self._validate_authority(lease, now=pre_audit_checked_at)
        self._validate_publication_evidence(
            target,
            target_members,
            contract=contract,
            policy=policy,
            now=pre_audit_checked_at,
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=True,
        )
        self._validate_publication_evidence(
            previous,
            previous_members,
            contract=contract,
            policy=policy,
            now=pre_audit_checked_at,
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=False,
        )
        receipt = audit_writer.execute_in_caller_transaction(
            observation,
            exact_replay=False,
        )
        self._validate_post_audit(
            lease=lease,
            target=target,
            target_members=target_members,
            previous=previous,
            previous_members=previous_members,
            contract=contract,
            policy=policy,
            pointer_id=pointer.pointer_id,
            rollback_id=rollback_row.rollback_id,
            target_hash=target.publication_hash,
            observed_at=rollback_row.observed_at,
            expected_previous_activation_id=command.expected_current_activation_id,
            receipt=receipt,
            pre_audit_checked_at=pre_audit_checked_at,
        )
        restored = CanonicalPublicationModel._default_manager.using(self._using).get(
            publication_id=target.publication_id
        )
        return self._result(restored, rollback_row.rollback_id, receipt)

    def _lock_publications(
        self,
        target_id: UUID,
        previous_id: UUID,
    ) -> tuple[CanonicalPublicationModel, CanonicalPublicationModel]:
        """Lock both exact publication records in stable primary-key order."""

        if target_id == previous_id:
            raise ExecutionQuotePointerRollbackError("rollback publications must differ")
        rows = list(
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=(target_id, previous_id))
            .order_by("publication_id")
        )
        if len(rows) != 2:
            raise ExecutionQuotePointerRollbackError(
                "one or more rollback publications are missing"
            )
        by_id = {row.publication_id: row for row in rows}
        target = by_id.get(target_id)
        previous = by_id.get(previous_id)
        if target is None or previous is None:
            raise ExecutionQuotePointerRollbackError(
                "rollback publication identities are incomplete"
            )
        return target, previous

    def _lock_members(
        self,
        target: CanonicalPublicationModel,
        previous: CanonicalPublicationModel,
    ) -> tuple[tuple[PublicationMember, ...], tuple[PublicationMember, ...]]:
        """Lock both immutable member sets and require complete exact coverage."""

        publication_ids = tuple(sorted((target.publication_id, previous.publication_id)))
        coverage_rows = tuple(
            CoverageSnapshotModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=publication_ids)
            .order_by("publication_id", "coverage_id")
        )
        if len(coverage_rows) != 2:
            raise ExecutionQuotePointerRollbackError("rollback coverage evidence is missing")
        coverage_by_publication = {row.publication_id: row for row in coverage_rows}
        for publication in (target, previous):
            coverage = coverage_by_publication.get(publication.publication_id)
            if (
                coverage is None
                or coverage.requested_count != publication.coverage_requested_count
                or coverage.eligible_count != publication.coverage_eligible_count
                or coverage.selected_count != publication.coverage_selected_count
                or coverage.missing_count != publication.coverage_missing_count
                or coverage.conflict_count != publication.coverage_conflict_count
            ):
                raise ExecutionQuotePointerRollbackError(
                    "rollback coverage snapshot differs from its publication"
                )
        rows = tuple(
            PublicationMemberModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=publication_ids)
            .order_by("publication_id", "natural_key", "member_id")
        )
        grouped: dict[UUID, list[PublicationMember]] = {item: [] for item in publication_ids}
        for row in rows:
            member = row.to_domain()
            grouped[row.publication_id].append(member)
        target_members = tuple(grouped[target.publication_id])
        previous_members = tuple(grouped[previous.publication_id])
        self._validate_member_shape(target, target_members)
        self._validate_member_shape(previous, previous_members)
        return target_members, previous_members

    @staticmethod
    def _validate_member_shape(
        publication: CanonicalPublicationModel,
        members: tuple[PublicationMember, ...],
    ) -> None:
        """Require one sealed execution quote member set with no duplicate facts."""

        if (
            publication.members_sealed_at is None
            or not publication.member_manifest_hash
            or publication.member_count != len(members)
            or publication.coverage_selected_count != len(members)
            or not members
        ):
            raise ExecutionQuotePointerRollbackError("rollback member evidence is incomplete")
        if publication.as_of is None or publication.published_at is None:
            raise ExecutionQuotePointerRollbackError(
                "rollback publication time evidence is missing"
            )
        if publication.as_of > publication.published_at:
            raise ExecutionQuotePointerRollbackError("rollback publication chronology is invalid")
        if (
            publication_member_manifest_hash(
                members,
                policy_identity=publication.policy_version,
            )
            != publication.member_manifest_hash
        ):
            raise ExecutionQuotePointerRollbackError("rollback member manifest hash drifted")
        if len({item.natural_key for item in members}) != len(members):
            raise ExecutionQuotePointerRollbackError("rollback member keys are ambiguous")
        if len({(item.fact_table, item.fact_pk) for item in members}) != len(members):
            raise ExecutionQuotePointerRollbackError(
                "rollback member fact references are ambiguous"
            )
        if any(
            item.dataset_key != _DATASET_KEY
            or item.publication_id != str(publication.publication_id)
            or item.fact_table != _FACT_TABLE
            or item.observed_at is None
            or item.observed_at > publication.as_of
            for item in members
        ):
            raise ExecutionQuotePointerRollbackError("rollback member scope or cutoff is invalid")

    def _lock_current_configuration(self) -> tuple[DatasetContract, PublicationPolicy]:
        """Lock one active execution contract and policy, rejecting ambiguity."""

        contracts = list(
            DatasetContractModel._default_manager.using(self._using)
            .select_for_update()
            .filter(dataset_key=_DATASET_KEY, active=True)
            .order_by("id")[:2]
        )
        if len(contracts) != 1:
            raise ExecutionQuotePointerRollbackError(
                "execution quote active contract is missing or ambiguous"
            )
        policies = list(
            DatasetPublicationPolicyModel._default_manager.using(self._using)
            .select_for_update()
            .filter(dataset_key=_DATASET_KEY, active=True)
            .order_by("id")[:2]
        )
        if len(policies) != 1:
            raise ExecutionQuotePointerRollbackError(
                "execution quote active policy is missing or ambiguous"
            )
        try:
            contract = contracts[0].to_domain()
            policy = policies[0].to_domain()
        except (TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "execution quote active configuration is invalid"
            ) from error
        if (
            type(contract) is not DatasetContract
            or type(policy) is not PublicationPolicy
            or contract.key.value != _DATASET_KEY
            or contract.key != policy.dataset
            or contract.execution_freshness_seconds is None
        ):
            raise ExecutionQuotePointerRollbackError(
                "execution quote contract and policy versions differ"
            )
        return contract, policy

    def _validate_publication_evidence(
        self,
        publication: CanonicalPublicationModel,
        members: tuple[PublicationMember, ...],
        *,
        contract: DatasetContract,
        policy: PublicationPolicy,
        now: datetime,
        knowledge_cutoff: datetime,
        require_execution_freshness: bool,
    ) -> None:
        """Recompute publication, source, version, and optionally execution TTL evidence."""

        if (
            publication.dataset_key != _DATASET_KEY
            or publication.publication_key != _PUBLICATION_KEY
            or publication.policy_version != policy.identity
            or policy.dataset != contract.key
            or publication.must_not_use_for_decision
            or publication.published_at is None
            or publication.published_at > knowledge_cutoff
            or publication.published_at > now
            or publication.state
            not in {PublicationState.PUBLISHED.value, PublicationState.SUPERSEDED.value}
        ):
            raise ExecutionQuotePointerRollbackError("rollback publication identity is invalid")
        publication_domain = publication.to_domain()
        try:
            validate_publication_snapshot_policy(policy, publication_domain, members=members)
            assert publication.published_at is not None
            validate_publication_evidence(
                policy,
                members,
                published_at=publication.published_at,
                knowledge_cutoff=knowledge_cutoff,
            )
        except (AssertionError, TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "rollback publication policy or knowledge-cutoff evidence is invalid"
            ) from error

        expected_hash = publication_hash(
            [
                member_reference(member)
                for member in sorted(members, key=lambda item: item.natural_key)
            ],
            policy_identity=(
                publication.policy_version if publication.policy_version.startswith("p2:") else None
            ),
            scope_blocks=publication_domain.scope_blocks,
        )
        if expected_hash != publication.publication_hash:
            raise ExecutionQuotePointerRollbackError("rollback publication hash drifted")
        hashes, _ingested_runs = publication_fact_content_hashes_and_ingested_runs(
            members,
            lock_rows=True,
        )
        if any(
            hashes.get((member.fact_table, member.fact_pk)) != member.fact_content_hash
            for member in members
        ):
            raise ExecutionQuotePointerRollbackError("rollback normalized fact content changed")
        fact_ids = tuple(member.fact_pk for member in members)
        fact_rows = list(
            QuoteSnapshotModel._default_manager.using(self._using)
            .filter(pk__in=fact_ids)
            .values_list("pk", "contract_version", "schema_version")
        )
        if len(fact_rows) != len(fact_ids) or any(
            contract_version != contract.key.contract_version
            or schema_version != contract.key.schema_version
            for _pk, contract_version, schema_version in fact_rows
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback quote fact versions differ from the active contract"
            )
        if require_execution_freshness:
            self._validate_execution_freshness(members, contract, now)

    @staticmethod
    def _validate_execution_freshness(
        members: tuple[PublicationMember, ...],
        contract: DatasetContract,
        now: datetime,
    ) -> None:
        """Require each restored source observation to remain within its catalog TTL."""

        ttl = contract.execution_freshness_seconds
        if ttl is None:
            raise ExecutionQuotePointerRollbackError("execution quote TTL is missing")
        try:
            validate_execution_quote_member_freshness(
                tuple(member.observed_at for member in members),
                as_of=now,
                execution_freshness_seconds=ttl,
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "rollback target source evidence is outside its execution TTL"
            ) from error

    @staticmethod
    def _validate_new_identity(
        command: ExecutionQuotePointerRollbackCommand,
        *,
        pointer: CanonicalPublicationPointerModel,
        target: CanonicalPublicationModel,
        previous: CanonicalPublicationModel,
    ) -> None:
        """Require exact same-scope source states and all current-pointer CAS fields."""

        if (
            pointer.publication_id != previous.publication_id
            or pointer.publication_hash != command.expected_current_publication_hash
            or pointer.activation_id != command.expected_current_activation_id
        ):
            raise ExecutionQuotePointerRollbackError(
                "execution quote pointer compare-and-swap failed"
            )
        if (
            target.publication_id != UUID(command.target_publication_id)
            or target.publication_hash != command.target_publication_hash
            or target.state != PublicationState.SUPERSEDED.value
            or target.must_not_use_for_decision
            or target.superseded_at is None
            or target.published_at is None
            or target.as_of is None
            or target.as_of > target.published_at
            or target.superseded_at < target.published_at
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback target must be the exact superseded execution publication"
            )
        if (
            previous.publication_id != UUID(command.expected_current_publication_id)
            or previous.publication_hash != command.expected_current_publication_hash
            or previous.state != PublicationState.PUBLISHED.value
            or previous.must_not_use_for_decision
            or previous.published_at is None
            or previous.as_of is None
            or previous.as_of > previous.published_at
            or command.observed_at <= previous.published_at
            or command.observed_at < target.published_at
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback current publication or operation chronology is invalid"
            )

    @staticmethod
    def _validate_replay_identity(
        command: ExecutionQuotePointerRollbackCommand,
        *,
        rollback_row: PublicationRollbackModel,
        pointer: CanonicalPublicationPointerModel,
        target: CanonicalPublicationModel,
        previous: CanonicalPublicationModel,
    ) -> None:
        """Require the complete rollback, pointer, and publication winner to be exact."""

        if (
            rollback_row.target_publication_id != target.publication_id
            or rollback_row.previous_publication_id != previous.publication_id
            or rollback_row.dataset_key != _DATASET_KEY
            or rollback_row.publication_key != _PUBLICATION_KEY
            or rollback_row.reason != command.reason
            or rollback_row.operator != command.operator
            or rollback_row.observed_at != command.observed_at
            or previous.publication_hash != command.expected_current_publication_hash
            or pointer.publication_id != target.publication_id
            or pointer.publication_hash != target.publication_hash
            or pointer.activation_id != command.rollback_id
            or target.publication_hash != command.target_publication_hash
            or target.state != PublicationState.PUBLISHED.value
            or target.reinstated_at != rollback_row.observed_at
            or previous.state != PublicationState.SUPERSEDED.value
            or previous.superseded_at != rollback_row.observed_at
        ):
            raise ExecutionQuotePointerRollbackError(
                "execution pointer rollback replay no longer matches the exact winner"
            )

    @staticmethod
    def _validate_authority(
        lease: PublicationActivationAuthorityLease,
        *,
        now: datetime | None = None,
    ) -> None:
        """Keep the complete Account lease valid across locks and Audit I/O."""

        checked_now = now or timezone.now()
        if (
            lease.checked_at >= lease.valid_until
            or checked_now >= lease.valid_until
            or checked_now < lease.checked_at
        ):
            raise ExecutionQuotePointerRollbackError("complete Account authority lease expired")

    def _validate_post_audit(
        self,
        *,
        lease: PublicationActivationAuthorityLease,
        target: CanonicalPublicationModel,
        target_members: tuple[PublicationMember, ...],
        previous: CanonicalPublicationModel,
        previous_members: tuple[PublicationMember, ...],
        contract: DatasetContract,
        policy: PublicationPolicy,
        pointer_id: UUID,
        rollback_id: UUID,
        target_hash: str,
        observed_at: datetime,
        expected_previous_activation_id: str,
        receipt: ExecutionQuotePointerRollbackAuditReceipt,
        pre_audit_checked_at: datetime,
    ) -> None:
        """Recheck fresh clocks and locked evidence after Audit I/O before commit."""

        now = timezone.now()
        if (
            not isinstance(now, datetime)
            or not isinstance(pre_audit_checked_at, datetime)
            or not isinstance(receipt.recorded_at, datetime)
            or now.tzinfo is None
            or pre_audit_checked_at.tzinfo is None
            or receipt.recorded_at.tzinfo is None
            or now.utcoffset() is None
            or pre_audit_checked_at.utcoffset() is None
            or receipt.recorded_at.utcoffset() is None
        ):
            raise ExecutionQuotePointerRollbackError(
                "clock regressed during required Audit persistence"
            )
        try:
            now = now.astimezone(UTC)
            pre_audit_checked_at = pre_audit_checked_at.astimezone(UTC)
            receipt_recorded_at = receipt.recorded_at.astimezone(UTC)
        except (OverflowError, OSError, TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "clock evidence is invalid during required Audit persistence"
            ) from error
        if now < pre_audit_checked_at or now < receipt_recorded_at:
            raise ExecutionQuotePointerRollbackError(
                "clock regressed during required Audit persistence"
            )
        self._validate_authority(lease, now=now)
        self._validate_publication_evidence(
            target,
            target_members,
            contract=contract,
            policy=policy,
            now=now,
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=True,
        )
        self._validate_publication_evidence(
            previous,
            previous_members,
            contract=contract,
            policy=policy,
            now=now,
            knowledge_cutoff=lease.checked_at,
            require_execution_freshness=False,
        )
        current_contract, current_policy = self._lock_current_configuration()
        if current_contract != contract or current_policy != policy:
            raise ExecutionQuotePointerRollbackError(
                "execution quote contract or policy changed during Audit persistence"
            )
        persisted_target = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id=target.publication_id)
            .first()
        )
        persisted_previous = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id=previous.publication_id)
            .first()
        )
        rollback_row = (
            PublicationRollbackModel._default_manager.using(self._using)
            .select_for_update()
            .filter(rollback_id=rollback_id)
            .first()
        )
        if (
            persisted_target is None
            or persisted_previous is None
            or rollback_row is None
            or persisted_target.state != PublicationState.PUBLISHED.value
            or persisted_target.publication_hash != target_hash
            or persisted_target.reinstated_at != observed_at
            or persisted_previous.state != PublicationState.SUPERSEDED.value
            or persisted_previous.superseded_at != observed_at
            or rollback_row.target_publication_id != target.publication_id
            or rollback_row.previous_publication_id != previous.publication_id
            or rollback_row.observed_at != observed_at
            or _rollback_content_hash(rollback_row) != receipt.rollback_content_hash
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback records changed during required Audit persistence"
            )
        if (
            receipt.target_publication_id != str(target.publication_id)
            or receipt.target_publication_hash != target_hash
            or receipt.rollback_id != str(rollback_id)
            or receipt.previous_publication_id != str(previous.publication_id)
            or receipt.previous_publication_hash != previous.publication_hash
            or receipt.previous_pointer_activation_id != expected_previous_activation_id
            or receipt.occurred_at != observed_at
            or receipt.recorded_at != rollback_row.created_at
            or receipt.tenant_id != lease.tenant_id
            or receipt.owner_id != lease.owner_id
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback Audit receipt is not bound to the persisted operation"
            )
        pointer = (
            CanonicalPublicationPointerModel._default_manager.using(self._using)
            .filter(
                pointer_id=pointer_id,
                dataset_key=_DATASET_KEY,
                publication_key=_PUBLICATION_KEY,
            )
            .first()
        )
        if (
            pointer is None
            or pointer.publication_id != target.publication_id
            or pointer.publication_hash != target_hash
            or pointer.activation_id != str(rollback_id)
        ):
            raise ExecutionQuotePointerRollbackError(
                "execution pointer changed during required Audit persistence"
            )

    @staticmethod
    def _audit_observation(
        command: ExecutionQuotePointerRollbackCommand,
        *,
        rollback_row: PublicationRollbackModel,
        target: CanonicalPublicationModel,
        previous: CanonicalPublicationModel,
        previous_pointer_activation_id: str,
        rollback_hash: str,
        lease: PublicationActivationAuthorityLease,
        recorded_at: datetime,
    ) -> ExecutionQuotePointerRollbackAuditObservation:
        """Build a Data Center-owned Audit fact record from locked source rows."""

        if target.run_id is None:
            raise ExecutionQuotePointerRollbackError("rollback target run identity is missing")
        return ExecutionQuotePointerRollbackAuditObservation(
            target_publication_id=str(target.publication_id),
            target_publication_version=target.policy_version,
            target_publication_hash=target.publication_hash,
            rollback_id=str(rollback_row.rollback_id),
            rollback_version=_ROLLBACK_VERSION,
            rollback_content_hash=rollback_hash,
            previous_publication_id=str(previous.publication_id),
            previous_publication_version=previous.policy_version,
            previous_publication_hash=previous.publication_hash,
            previous_pointer_activation_id=previous_pointer_activation_id,
            run_id=str(target.run_id),
            occurred_at=command.observed_at,
            recorded_at=recorded_at,
            tenant_id=lease.tenant_id,
            owner_id=lease.owner_id,
        )

    @staticmethod
    def _result(
        publication: CanonicalPublicationModel,
        rollback_id: UUID,
        receipt: ExecutionQuotePointerRollbackAuditReceipt,
    ) -> ExecutionQuotePointerRollbackResult:
        """Convert the exact persisted target and receipt into an application result."""

        if type(receipt) is not ExecutionQuotePointerRollbackAuditReceipt:
            raise ExecutionQuotePointerRollbackError("rollback Audit receipt is invalid")
        try:
            return ExecutionQuotePointerRollbackResult(
                publication=publication.to_domain(),
                rollback_id=str(rollback_id),
                audit_receipt=receipt,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "rollback result evidence is inconsistent"
            ) from error


def _rollback_content_hash(rollback: PublicationRollbackModel) -> str:
    """Hash the complete durable rollback row without exposing human reason text."""

    observed_at = rollback.observed_at
    created_at = rollback.created_at
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or not isinstance(created_at, datetime)
        or created_at.tzinfo is None
        or created_at.utcoffset() is None
    ):
        raise ExecutionQuotePointerRollbackError("rollback row timestamps are invalid")
    payload = {
        "rollback_id": str(rollback.rollback_id),
        "target_publication_id": str(rollback.target_publication_id),
        "previous_publication_id": str(rollback.previous_publication_id),
        "dataset_key": rollback.dataset_key,
        "publication_key": rollback.publication_key,
        "reason": rollback.reason,
        "operator": rollback.operator,
        "observed_at": _utc_text(observed_at),
        "created_at": _utc_text(created_at),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    """Return one aware timestamp in canonical UTC text."""

    try:
        if value.utcoffset() is None:
            raise ValueError
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError) as error:
        raise ExecutionQuotePointerRollbackError("rollback timestamp is invalid") from error


__all__ = ["DjangoExecutionQuotePointerRollbackRepository"]
