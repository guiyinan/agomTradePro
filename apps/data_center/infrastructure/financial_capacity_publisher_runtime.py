"""Exact candidate staging and pointer-CAS runtime for financial capacity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationCandidateSnapshot,
)
from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityActivationIntent,
    FinancialCapacityBinding,
    FinancialCapacityPublicationIndeterminateError,
    FinancialCapacityPublicationPlan,
    FinancialCapacityPublisher,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflowError,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationRequest,
)
from apps.data_center.application.publication_utils import publication_member_manifest_hash
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_member_store import (
    publication_fact_content_hashes_and_ingested_runs,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)
from apps.data_center.publication_rebuild_composition import build_current_publication_rebuild
from core.exceptions import DataFetchError, DataValidationError
from core.integration.data_center_audit import (
    AuditOutcome,
    AuditScopeRef,
    DataPublicationAuditObservation,
    SystemAuditCompositionUnavailable,
    get_data_publication_activation_audit_writer,
    preflight_data_reliability_audit_runtime,
)
from core.integration.production_account_authority_capture import (
    capture_production_account_authority,
)


def _require_digest(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 value before it enters an activation plan."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FinancialCapacityWorkflowError(f"financial capacity {field_name} is invalid")
    return value


class AtomicFinancialPolicyV3Publisher(FinancialCapacityPublisher):
    """Stage immutable financial candidates and CAS the canonical current pointer."""

    _DATASET_KEY = "equity.financial.fact"
    _PUBLICATION_KEY = "current"
    _DATABASE_ALIAS = "default"

    def begin_activation(
        self,
        *,
        binding: FinancialCapacityBinding,
        run_id: UUID,
        evidence: tuple[FinancialCapacitySliceEvidence, ...],
    ) -> FinancialCapacityActivationIntent:
        """Freeze pointer CAS and the final exact RawAudit lineage before staging."""

        if (
            binding.environment != "production"
            or binding.provider_source != "akshare"
            or binding.publication_policy_version != "3"
            or type(run_id) is not UUID
            or not evidence
        ):
            raise FinancialCapacityWorkflowError(
                "financial policy-v3 publication binding is invalid"
            )
        self._validate_binding(binding)
        audits = RawAuditRepository()
        last_financial_audit: object | None = None
        for item in evidence:
            financial_audit = audits.get_by_id(item.financial_raw_audit_id)
            source_time_audit = audits.get_by_id(item.source_time_raw_audit_id)
            if financial_audit is None or source_time_audit is None:
                raise DataFetchError(
                    "financial capacity workflow RawAudit lineage is incomplete",
                    code="financial_capacity_raw_audit_lineage_missing",
                )
            self._validate_capture_audit(
                financial_audit,
                run_id=run_id,
                provider_name=binding.provider_name,
                expected_capability="financial",
                expected_capture_id=item.financial_capture_id,
            )
            self._validate_capture_audit(
                source_time_audit,
                run_id=run_id,
                provider_name=binding.provider_name,
                expected_capability="financial_source_time",
                expected_capture_id=item.source_time_capture_id,
            )
            last_financial_audit = financial_audit
        if last_financial_audit is None:
            raise DataFetchError(
                "financial capacity workflow RawAudit lineage is incomplete",
                code="financial_capacity_raw_audit_lineage_missing",
            )
        raw_audit_id = getattr(last_financial_audit, "raw_audit_id", None)
        raw_audit_hash = getattr(last_financial_audit, "content_hash", None)
        occurred_at = getattr(last_financial_audit, "fetched_at", None)
        if (
            type(raw_audit_id) is not str
            or type(raw_audit_hash) is not str
            or type(occurred_at) is not datetime
        ):
            raise DataFetchError(
                "financial capacity activation audit identity is incomplete",
                code="financial_capacity_activation_audit_identity_invalid",
            )
        pointer = self._read_current_pointer()
        activation_id = uuid5(
            NAMESPACE_URL,
            f"agomtradepro:financial-capacity-activation:{run_id}",
        )
        return FinancialCapacityActivationIntent(
            run_id=run_id,
            activation_id=activation_id,
            expected_current_publication_id=pointer.publication_id,
            expected_current_publication_hash=pointer.publication_hash,
            financial_raw_audit_id=raw_audit_id,
            financial_raw_audit_content_hash=raw_audit_hash,
            ingested_run_id=run_id,
            provider_key=binding.provider_source,
            occurred_at=occurred_at,
        )

    def stage(
        self,
        *,
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        manifest_sha256: str,
    ) -> FinancialCapacityPublicationPlan:
        """Persist one candidate or recover it after an uncertain staging response."""

        try:
            return self._stage_candidate(
                binding=binding,
                intent=intent,
                asset_codes=asset_codes,
                manifest_sha256=manifest_sha256,
            )
        except FinancialCapacityPublicationIndeterminateError:
            raise
        except (DatabaseError, OSError, RuntimeError) as exc:
            try:
                matches = tuple(
                    CanonicalPublicationModel._default_manager.filter(
                        dataset_key=self._DATASET_KEY,
                        publication_key=self._PUBLICATION_KEY,
                        run_id=intent.run_id,
                    ).order_by("publication_id")
                )
            except (DatabaseError, OSError, RuntimeError) as lookup_error:
                raise FinancialCapacityPublicationIndeterminateError("staging") from lookup_error
            if len(matches) > 1:
                raise DataFetchError(
                    "financial capacity workflow has multiple staged candidates",
                    code="financial_capacity_staged_candidate_ambiguous",
                ) from exc
            if not matches:
                raise FinancialCapacityPublicationIndeterminateError("staging") from exc
            publication, members, member_hash = self._load_staged_candidate(matches[0])
            if publication.state is not PublicationState.CANDIDATE:
                raise DataFetchError(
                    "financial capacity run already belongs to a non-candidate publication",
                    code="financial_capacity_staged_candidate_state_invalid",
                ) from exc
            self._validate_candidate(
                publication=publication,
                members=members,
                binding=binding,
                intent=intent,
                asset_codes=asset_codes,
            )
            self._validate_member_ingestion_lineage(members, intent.run_id)
            return FinancialCapacityPublicationPlan(
                intent=intent,
                manifest_sha256=manifest_sha256,
                candidate_publication_id=publication.publication_id,
                candidate_publication_hash=publication.publication_hash,
                member_manifest_sha256=member_hash,
            )

    def _stage_candidate(
        self,
        *,
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        manifest_sha256: str,
    ) -> FinancialCapacityPublicationPlan:
        """Persist or recover one exact candidate by the fixed workflow run identity."""

        self._validate_binding(binding)
        if (
            type(intent) is not FinancialCapacityActivationIntent
            or type(intent.run_id) is not UUID
            or intent.activation_id
            != uuid5(NAMESPACE_URL, f"agomtradepro:financial-capacity-activation:{intent.run_id}")
            or type(asset_codes) is not tuple
            or not asset_codes
            or len(asset_codes) != len(set(asset_codes))
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity staged activation intent or scope is invalid"
            )
        _require_digest(manifest_sha256, "manifest_sha256")
        self._validate_activation_audit(intent, binding)

        matches = tuple(
            CanonicalPublicationModel._default_manager.filter(
                dataset_key=self._DATASET_KEY,
                publication_key=self._PUBLICATION_KEY,
                run_id=intent.run_id,
            ).order_by("publication_id")
        )
        if len(matches) > 1:
            raise DataFetchError(
                "financial capacity workflow has multiple staged candidates",
                code="financial_capacity_staged_candidate_ambiguous",
            )
        if matches:
            publication, members, member_hash = self._load_staged_candidate(matches[0])
            if publication.state is not PublicationState.CANDIDATE:
                raise DataFetchError(
                    "financial capacity run already belongs to a non-candidate publication",
                    code="financial_capacity_staged_candidate_state_invalid",
                )
            self._validate_candidate(
                publication=publication,
                members=members,
                binding=binding,
                intent=intent,
                asset_codes=asset_codes,
            )
            self._validate_member_ingestion_lineage(members, intent.run_id)
            return FinancialCapacityPublicationPlan(
                intent=intent,
                manifest_sha256=manifest_sha256,
                candidate_publication_id=publication.publication_id,
                candidate_publication_hash=publication.publication_hash,
                member_manifest_sha256=member_hash,
            )

        rebuild = build_current_publication_rebuild(
            created_by="celery.financial_publication_capacity",
            dataset_keys=(self._DATASET_KEY,),
        )
        rebuilders = tuple(
            item for item in rebuild.rebuilders if item.dataset.dataset_key == self._DATASET_KEY
        )
        if len(rebuilders) != 1:
            raise DataFetchError(
                "financial policy-v3 publication rebuilder is unavailable",
                code="financial_capacity_atomic_activation_invalid",
            )
        policy = PublicationPolicyRepository().get_active(self._DATASET_KEY)
        if (
            policy is None
            or policy.policy_version != binding.publication_policy_version
            or policy.content_hash != binding.publication_policy_sha256
        ):
            raise DataFetchError(
                "financial policy-v3 publication policy changed before candidate staging",
                code="financial_capacity_publication_policy_drift",
            )
        candidate: CurrentPublicationCandidateSnapshot = rebuilders[0].prepare_candidate(
            asset_codes=asset_codes,
            published_at=timezone.now(),
            run_id=str(intent.run_id),
        )
        self._validate_candidate(
            publication=candidate.publication,
            members=candidate.members,
            binding=binding,
            intent=intent,
            asset_codes=asset_codes,
        )
        self._validate_member_ingestion_lineage(candidate.members, intent.run_id)
        try:
            persisted = DjangoPublicationActivationRepository(
                using=self._DATABASE_ALIAS
            ).stage_candidate_with_members(candidate.publication, candidate.members)
        except (DataValidationError, TypeError, ValueError) as exc:
            raise DataFetchError(
                "financial policy-v3 candidate staging failed closed",
                code="financial_capacity_candidate_staging_failed",
            ) from exc
        if persisted != candidate.publication:
            raise DataFetchError(
                "financial policy-v3 staged candidate differs from its exact snapshot",
                code="financial_capacity_staged_candidate_drift",
            )
        member_hash = publication_member_manifest_hash(
            candidate.members,
            policy_identity=candidate.publication.policy_version,
        )
        return FinancialCapacityPublicationPlan(
            intent=intent,
            manifest_sha256=manifest_sha256,
            candidate_publication_id=candidate.publication.publication_id,
            candidate_publication_hash=candidate.publication.publication_hash,
            member_manifest_sha256=member_hash,
        )

    def activate(
        self,
        *,
        binding: FinancialCapacityBinding,
        plan: FinancialCapacityPublicationPlan,
    ) -> str:
        """Activate one exact plan or preserve it for an indeterminate retry."""

        try:
            return self._activate_candidate(binding=binding, plan=plan)
        except FinancialCapacityPublicationIndeterminateError:
            raise
        except (DatabaseError, OSError, RuntimeError) as exc:
            raise FinancialCapacityPublicationIndeterminateError("activation") from exc

    def _activate_candidate(
        self,
        *,
        binding: FinancialCapacityBinding,
        plan: FinancialCapacityPublicationPlan,
    ) -> str:
        """CAS the pointer or accept only an exact same-activation recovery replay."""

        self._validate_binding(binding)
        if type(plan) is not FinancialCapacityPublicationPlan:
            raise FinancialCapacityWorkflowError("financial capacity publication plan is invalid")
        intent = plan.intent
        self._validate_activation_audit(intent, binding)
        publication, members, member_hash = self._load_candidate_by_id(
            plan.candidate_publication_id
        )
        self._validate_candidate(
            publication=publication,
            members=members,
            binding=binding,
            intent=intent,
            asset_codes=tuple(sorted({member.natural_key.split(":", 1)[0] for member in members})),
            plan=plan,
            member_hash=member_hash,
        )
        pointer = self._read_current_pointer_with_activation_id()
        if (
            pointer.publication_id == plan.candidate_publication_id
            and pointer.publication_hash == plan.candidate_publication_hash
        ):
            if (
                pointer.activation_id != str(intent.activation_id)
                or publication.state is not PublicationState.PUBLISHED
            ):
                raise DataFetchError(
                    "financial capacity current pointer activation identity differs",
                    code="financial_capacity_current_pointer_activation_drift",
                )
            self._verify_current_publication(plan)
            return plan.candidate_publication_hash
        if (
            pointer.publication_id != intent.expected_current_publication_id
            or pointer.publication_hash != intent.expected_current_publication_hash
        ):
            raise DataFetchError(
                "financial capacity current publication pointer changed before activation",
                code="financial_capacity_current_pointer_compare_and_swap_failed",
            )
        if publication.state is not PublicationState.CANDIDATE:
            raise DataFetchError(
                "financial capacity candidate is not staged for activation",
                code="financial_capacity_staged_candidate_state_invalid",
            )
        self._validate_member_ingestion_lineage(members, intent.run_id)

        activation_at = timezone.now()
        context = preflight_data_reliability_audit_runtime(
            environment="production",
            using=self._DATABASE_ALIAS,
            as_of=activation_at,
        )
        capture = capture_production_account_authority(
            using=self._DATABASE_ALIAS,
            as_of=activation_at,
            preflight_context=context,
        )
        audit_writer = get_data_publication_activation_audit_writer(
            environment="production",
            using=self._DATABASE_ALIAS,
        )
        if getattr(audit_writer, "database_alias", None) != self._DATABASE_ALIAS:
            raise SystemAuditCompositionUnavailable(
                "financial publication audit writer uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        observation = DataPublicationAuditObservation(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            publication_id=publication.publication_id,
            publication_version=publication.policy_version,
            publication_hash=publication.publication_hash,
            provider_key=intent.provider_key,
            run_id=str(intent.run_id),
            ingested_run_id=str(intent.ingested_run_id),
            member_count=publication.member_count,
            coverage_requested_count=publication.coverage.requested_count,
            coverage_eligible_count=publication.coverage.eligible_count,
            coverage_selected_count=publication.coverage.selected_count,
            outcome=AuditOutcome.PUBLISHED,
            raw_audit_id=intent.financial_raw_audit_id,
            raw_audit_version="1",
            raw_audit_content_hash=intent.financial_raw_audit_content_hash,
            occurred_at=intent.occurred_at,
            recorded_at=intent.occurred_at,
            scope=AuditScopeRef(tenant_id=context.tenant_id, owner_id=context.owner_id),
        )
        request = PublicationActivationRequest(
            dataset_key=self._DATASET_KEY,
            publication_key=self._PUBLICATION_KEY,
            candidate_publication_id=plan.candidate_publication_id,
            candidate_publication_hash=plan.candidate_publication_hash,
            activation_id=str(intent.activation_id),
            audit_observation=observation,
            expected_current_publication_id=intent.expected_current_publication_id,
            expected_current_publication_hash=intent.expected_current_publication_hash,
        )
        try:
            activated = ActivateCanonicalPublicationUseCase(
                DjangoPublicationActivationRepository(using=self._DATABASE_ALIAS)
            ).execute(
                request,
                audit_writer=audit_writer,
                authority_fence=capture.authority_fence,
                authority_proof=capture.authority_proof,
            )
        except (DataValidationError, TypeError, ValueError):
            # The authority transaction is atomic. If a caller lost the response after the
            # commit, only the same pointer and activation identity can establish success.
            if self._is_exact_current_activation(plan):
                self._verify_current_publication(plan)
                return plan.candidate_publication_hash
            raise
        except (DatabaseError, OSError, RuntimeError) as exc:
            # Database disconnects and transport errors can obscure whether the outer
            # authority transaction committed. Accept only the exact CAS target; otherwise
            # leave the durable plan running for a same-identity retry.
            try:
                exact_current = self._is_exact_current_activation(plan)
            except (DatabaseError, OSError, RuntimeError) as pointer_error:
                raise FinancialCapacityPublicationIndeterminateError(
                    "activation"
                ) from pointer_error
            if exact_current:
                self._verify_current_publication(plan)
                return plan.candidate_publication_hash
            raise FinancialCapacityPublicationIndeterminateError("activation") from exc
        if (
            activated.publication_id != plan.candidate_publication_id
            or activated.publication_hash != plan.candidate_publication_hash
            or activated.state is not PublicationState.PUBLISHED
        ):
            raise DataFetchError(
                "financial policy-v3 activation returned a different publication",
                code="financial_capacity_atomic_activation_invalid",
            )
        self._verify_current_publication(plan)
        return plan.candidate_publication_hash

    @staticmethod
    def _validate_binding(binding: FinancialCapacityBinding) -> None:
        """Require the exact production AKShare policy-v3 binding."""

        if (
            binding.environment != "production"
            or binding.provider_source != "akshare"
            or binding.publication_policy_version != "3"
            or binding.provider_name != binding.provider_source
        ):
            raise FinancialCapacityWorkflowError(
                "financial policy-v3 publication binding is invalid"
            )

    @staticmethod
    def _validate_capture_audit(
        audit: object,
        *,
        run_id: UUID,
        provider_name: str,
        expected_capability: str,
        expected_capture_id: str,
    ) -> None:
        """Require one persisted, content-bound audit from this exact dual capture."""

        run_text = str(run_id)
        extra = getattr(audit, "extra", None)
        link_key = (
            "financial_response_artifact"
            if expected_capability == "financial"
            else "financial_source_time_artifact"
        )
        link = extra.get(link_key) if isinstance(extra, dict) else None
        if (
            type(audit) is not RawAudit
            or getattr(audit, "capability", None) != expected_capability
            or getattr(audit, "status", None) != "ok"
            or getattr(audit, "provider_name", None) != provider_name
            or getattr(audit, "run_id", None) != run_text
            or getattr(audit, "ingested_run_id", None) != run_text
            or type(getattr(audit, "content_hash", None)) is not str
            or len(getattr(audit, "content_hash", "")) != 64
            or raw_audit_content_hash(audit) != audit.content_hash
            or not isinstance(link, dict)
            or link.get("capture_id") != expected_capture_id
        ):
            raise DataFetchError(
                "financial capacity RawAudit does not match the fixed workflow lineage",
                code="financial_capacity_raw_audit_lineage_invalid",
            )

    def _validate_activation_audit(
        self,
        intent: FinancialCapacityActivationIntent,
        binding: FinancialCapacityBinding,
    ) -> None:
        """Re-read the exact RawAudit before staging or replaying activation."""

        audit = RawAuditRepository().get_by_id(intent.financial_raw_audit_id)
        if audit is None or audit.raw_audit_id != intent.financial_raw_audit_id:
            raise DataFetchError(
                "financial capacity activation RawAudit is missing",
                code="financial_capacity_raw_audit_lineage_missing",
            )
        self._validate_capture_audit(
            audit,
            run_id=intent.run_id,
            provider_name=binding.provider_name,
            expected_capability="financial",
            expected_capture_id=(
                str(audit.extra.get("financial_response_artifact", {}).get("capture_id", ""))
                if isinstance(audit.extra.get("financial_response_artifact"), dict)
                else ""
            ),
        )
        if (
            audit.content_hash != intent.financial_raw_audit_content_hash
            or audit.provider_name != intent.provider_key
            or audit.ingested_run_id != str(intent.ingested_run_id)
            or audit.fetched_at != intent.occurred_at
        ):
            raise DataFetchError(
                "financial capacity activation RawAudit identity drifted",
                code="financial_capacity_activation_audit_identity_invalid",
            )

    def _load_staged_candidate(
        self,
        row: CanonicalPublicationModel,
    ) -> tuple[CanonicalPublication, tuple[PublicationMember, ...], str]:
        """Load a sealed staged bundle using only immutable persisted identities."""

        members = tuple(
            member_row.to_domain()
            for member_row in PublicationMemberModel._default_manager.filter(
                publication_id=row.publication_id
            ).order_by("natural_key")
        )
        publication = row.to_domain()
        if row.members_sealed_at is None or not row.member_manifest_hash:
            raise DataFetchError(
                "financial capacity candidate member manifest is not sealed",
                code="financial_capacity_member_manifest_invalid",
            )
        member_hash = publication_member_manifest_hash(
            members,
            policy_identity=publication.policy_version,
        )
        if row.member_manifest_hash != member_hash:
            raise DataFetchError(
                "financial capacity candidate member manifest drifted",
                code="financial_capacity_member_manifest_drift",
            )
        return publication, members, member_hash

    def _load_candidate_by_id(
        self,
        publication_id: str,
    ) -> tuple[CanonicalPublication, tuple[PublicationMember, ...], str]:
        """Load one exact candidate identity from its durable publication and member rows."""

        try:
            canonical_id = UUID(publication_id)
        except (TypeError, ValueError) as exc:
            raise DataFetchError(
                "financial capacity candidate publication ID is invalid",
                code="financial_capacity_candidate_identity_invalid",
            ) from exc
        row = CanonicalPublicationModel._default_manager.filter(publication_id=canonical_id).first()
        if row is None:
            raise DataFetchError(
                "financial capacity staged candidate is missing",
                code="financial_capacity_staged_candidate_missing",
            )
        return self._load_staged_candidate(row)

    def _validate_candidate(
        self,
        *,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        plan: FinancialCapacityPublicationPlan | None = None,
        member_hash: str | None = None,
    ) -> None:
        """Bind dataset, policy, active universe, workflow run, and exact member seal."""

        if (
            publication.dataset_key != "equity.financial.fact"
            or publication.publication_key != self._PUBLICATION_KEY
            or publication.run_id != str(intent.run_id)
            or publication.selected_source != intent.provider_key
            or publication.member_count <= 0
            or publication.coverage.requested_count != len(members)
            or publication.coverage.eligible_count != len(members)
            or publication.coverage.selected_count != len(members)
            or publication.coverage.missing_count != 0
            or len({member.source for member in members}) != 1
            or {member.source for member in members} != {intent.provider_key}
            or tuple(sorted({member.natural_key.split(":", 1)[0] for member in members}))
            != tuple(sorted(asset_codes))
        ):
            raise DataFetchError(
                "financial policy-v3 publication does not cover the exact workflow lineage",
                code="financial_capacity_atomic_activation_incomplete",
            )
        if plan is not None and (
            publication.publication_id != plan.candidate_publication_id
            or publication.publication_hash != plan.candidate_publication_hash
            or member_hash != plan.member_manifest_sha256
        ):
            raise DataFetchError(
                "financial capacity staged candidate differs from its checkpoint plan",
                code="financial_capacity_staged_candidate_drift",
            )
        policy = PublicationPolicyRepository().get_active(self._DATASET_KEY)
        if (
            policy is None
            or policy.policy_version != binding.publication_policy_version
            or policy.content_hash != binding.publication_policy_sha256
            or publication.policy_version != policy.identity
        ):
            raise DataFetchError(
                "financial capacity publication policy differs from its runtime binding",
                code="financial_capacity_publication_policy_drift",
            )

    @staticmethod
    def _validate_member_ingestion_lineage(
        members: tuple[PublicationMember, ...],
        run_id: UUID,
    ) -> None:
        """Require every candidate fact to originate in the exact capacity workflow run."""

        _hashes, ingested_run_ids = publication_fact_content_hashes_and_ingested_runs(members)
        for member in members:
            if ingested_run_ids.get((member.fact_table, member.fact_pk)) != str(run_id):
                raise DataFetchError(
                    "financial capacity candidate contains a foreign ingestion run",
                    code="financial_capacity_fact_lineage_invalid",
                )

    def _read_current_pointer(self) -> CurrentPublicationPointerSnapshot:
        """Read and validate the current financial publication pointer pair."""

        pointer = self._read_current_pointer_with_activation_id()
        try:
            return CurrentPublicationPointerSnapshot(
                pointer.publication_id,
                pointer.publication_hash,
            )
        except (DataValidationError, ValueError) as exc:
            raise DataFetchError(
                "financial capacity current publication pointer is malformed",
                code="financial_capacity_current_pointer_invalid",
            ) from exc

    def _read_current_pointer_with_activation_id(self) -> _FinancialPointerIdentity:
        """Read pointer identity including activation ID for exact replay detection."""

        row = CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key=self._DATASET_KEY,
            publication_key=self._PUBLICATION_KEY,
        ).first()
        if row is None:
            return _FinancialPointerIdentity(None, None, "")
        if row.publication_id is None:
            if row.publication_hash or row.activation_id:
                raise DataFetchError(
                    "empty financial publication pointer has stale identity",
                    code="financial_capacity_current_pointer_invalid",
                )
            return _FinancialPointerIdentity(None, None, "")
        try:
            snapshot = CurrentPublicationPointerSnapshot(
                str(row.publication_id), row.publication_hash
            )
        except (DataValidationError, ValueError) as exc:
            raise DataFetchError(
                "financial capacity current publication pointer is malformed",
                code="financial_capacity_current_pointer_invalid",
            ) from exc
        return _FinancialPointerIdentity(
            snapshot.publication_id,
            snapshot.publication_hash,
            row.activation_id,
        )

    def _is_exact_current_activation(self, plan: FinancialCapacityPublicationPlan) -> bool:
        """Return whether the pointer commit survived an ambiguous activation response."""

        pointer = self._read_current_pointer_with_activation_id()
        return (
            pointer.publication_id == plan.candidate_publication_id
            and pointer.publication_hash == plan.candidate_publication_hash
            and pointer.activation_id == str(plan.intent.activation_id)
        )

    def _verify_current_publication(self, plan: FinancialCapacityPublicationPlan) -> None:
        """Verify final pointer ID/hash/activation and immutable candidate member seal."""

        if not self._is_exact_current_activation(plan):
            raise DataFetchError(
                "financial capacity current pointer does not match the activated candidate",
                code="financial_capacity_current_pointer_verification_failed",
            )
        publication, members, member_hash = self._load_candidate_by_id(
            plan.candidate_publication_id
        )
        if (
            publication.state is not PublicationState.PUBLISHED
            or publication.publication_hash != plan.candidate_publication_hash
            or member_hash != plan.member_manifest_sha256
            or len(members) != publication.member_count
        ):
            raise DataFetchError(
                "financial capacity activated publication identity drifted",
                code="financial_capacity_current_publication_verification_failed",
            )


@dataclass(frozen=True, slots=True)
class _FinancialPointerIdentity:
    """Exact pointer projection including the activation identity used for replay."""

    publication_id: str | None
    publication_hash: str | None
    activation_id: str


__all__ = ["AtomicFinancialPolicyV3Publisher"]
