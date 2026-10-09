"""Fail-closed contracts for one-off financial publication capacity work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Barrier, Event
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from apps.data_center.application import tasks
from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityActivationIntent,
    FinancialCapacityCheckpoint,
    FinancialCapacityCheckpointRepository,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityPublicationPlan,
    ProtocolClock,
    _manifest_sha256,
)
from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityBinding,
    FinancialCapacityReceipt,
    FinancialCapacitySliceAttempt,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflow,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
    InMemoryFinancialCapacityCheckpointRepository,
)
from apps.data_center.application.financial_slice_sync import FinancialSliceSyncResult
from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
    DjangoFinancialCapacityCheckpointRepository,
)

_VERIFIED_IMPORT_ID = "8e8f46f9-0f8f-4e96-8901-3ba1f0f1a500"
_VERIFIED_IMPORT_RECORD_SHA256 = "9" * 64


def _binding() -> FinancialCapacityBinding:
    """Return exact synthetic identity values for isolated contract tests."""

    return FinancialCapacityBinding(
        environment="isolated",
        candidate_sha="a" * 40,
        provider_id=17,
        provider_name="AKShare Public",
        provider_source="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="akshare.financial-main-data.notice-date",
        contract_version="2026-10-04.v1",
        contract_sha256="c" * 64,
        parser_id="akshare-financial-row-parser.v1",
        parser_sha256="d" * 64,
        deployment_region="test-egress",
        publication_policy_version="3",
        publication_policy_sha256="e" * 64,
        isolation_attestation_sha256="f" * 64,
    )


def _slice(index: int) -> FinancialPublicationSlice:
    """Build a unique synthetic asset/date pair without pinning a real security."""

    return FinancialPublicationSlice(
        asset_code=f"{index:06d}.SZ",
        announcement_date=date(2026, 8, 1) + timedelta(days=index),
    )


class _RuntimeBinding:
    """Expose a mutable exact identity so drift is tested before provider calls."""

    def __init__(self, binding: FinancialCapacityBinding) -> None:
        self.binding = binding

    def snapshot(self, *, environment: str, candidate_sha: str) -> FinancialCapacityBinding:
        assert self.binding.environment == environment
        assert self.binding.candidate_sha == candidate_sha
        return self.binding


class _Manifest:
    """Return a dynamically supplied scope that can be changed between stages."""

    def __init__(self, slices: tuple[FinancialPublicationSlice, ...]) -> None:
        self.slices = slices
        self.calls: list[tuple[str, FinancialCapacityBinding]] = []

    def freeze(
        self,
        *,
        stage: str,
        environment: str,
        binding: FinancialCapacityBinding,
    ) -> FinancialCapacityManifestSnapshot:
        assert stage in {"qualification", "capacity_rehearsal", "formal_publication"}
        assert binding.candidate_sha == "a" * 40
        assert environment == ("production" if stage == "formal_publication" else "isolated")
        assert binding.environment == environment
        self.calls.append((stage, binding))
        source_sha256 = _manifest_sha256(self.slices)
        return FinancialCapacityManifestSnapshot.build(
            slices=self.slices,
            active_universe_sha256=source_sha256,
            typed_source_snapshot_sha256=source_sha256,
        )


class _SliceRunner:
    """Record exact one-slice sync calls and return evidence-complete outcomes."""

    def __init__(self) -> None:
        self.calls: list[FinancialPublicationSlice] = []
        self.fail_at: int | None = None

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        assert binding.provider_source == "akshare"
        assert isinstance(run_id, UUID)
        self.calls.append(item)
        if self.fail_at == len(self.calls):
            return FinancialCapacitySliceAttempt(
                FinancialSliceSyncResult(
                    outcome="partial",
                    source="akshare",
                    provider_id=binding.provider_id,
                    provider_name=binding.provider_name,
                    requested=1,
                    succeeded=0,
                    failed=1,
                    stored=0,
                    planned_provider_requests=2,
                    failure_reason="akshare_provider_or_capture_failed",
                ),
                None,
                observed_provider_requests=0,
                duration_ms=10,
                error_code="akshare_provider_or_capture_failed",
            )
        evidence = FinancialCapacitySliceEvidence(
            asset_code=item.asset_code,
            announcement_date=item.announcement_date,
            financial_body_sha256="1" * 64,
            source_time_body_sha256="2" * 64,
            financial_body_size_bytes=100,
            source_time_body_size_bytes=100,
            financial_capture_id=f"financial-{len(self.calls)}",
            source_time_capture_id=f"source-time-{len(self.calls)}",
            financial_raw_audit_id=f"financial-audit-{len(self.calls)}",
            source_time_raw_audit_id=f"source-time-audit-{len(self.calls)}",
            financial_raw_audit_count=1,
            source_time_raw_audit_count=1,
            typed_financial_evidence_count=2,
            source_time_witness_count=2,
            atomic_fact_write_count=1,
            stored=2,
            duration_ms=10,
        )
        return FinancialCapacitySliceAttempt(
            FinancialSliceSyncResult(
                outcome="success",
                source="akshare",
                provider_id=binding.provider_id,
                provider_name=binding.provider_name,
                requested=1,
                succeeded=1,
                failed=0,
                stored=2,
                planned_provider_requests=2,
                atomic_fact_write_count=1,
            ),
            evidence,
            observed_provider_requests=2,
            duration_ms=10,
        )


class _HardWorkerInterruption(BaseException):
    """Model worker termination that bypasses ordinary task exception handling."""


class _InterruptingRunner(_SliceRunner):
    """Leave one persisted in-flight reservation when the worker is interrupted."""

    def __init__(self, interruption: BaseException) -> None:
        super().__init__()
        self.interruption = interruption

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        self.calls.append(item)
        raise self.interruption


class _BlockingRunner(_SliceRunner):
    """Pause after the durable claim so duplicate deliveries see a live lease."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test runner release timed out")
        return super().execute(binding=binding, item=item, run_id=run_id)


class _ZeroOutputRunner(_SliceRunner):
    """Return a nominal success with zero persisted facts to test fail-closed counts."""

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        self.calls.append(item)
        return FinancialCapacitySliceAttempt(
            FinancialSliceSyncResult(
                outcome="success",
                source="akshare",
                provider_id=binding.provider_id,
                provider_name=binding.provider_name,
                requested=1,
                succeeded=1,
                failed=0,
                stored=0,
                planned_provider_requests=2,
                observed_provider_requests=2,
            ),
            None,
            observed_provider_requests=2,
            duration_ms=1,
        )


class _UnknownRequestCountRunner(_SliceRunner):
    """Surface an attempt whose actual provider-call count cannot be established."""

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        self.calls.append(item)
        return FinancialCapacitySliceAttempt(
            FinancialSliceSyncResult(
                outcome="failed",
                source="akshare",
                provider_id=binding.provider_id,
                provider_name=binding.provider_name,
                requested=1,
                succeeded=0,
                failed=1,
                stored=0,
                planned_provider_requests=2,
                observed_provider_requests=0,
                failure_reason="provider_call_count_unknown",
            ),
            None,
            observed_provider_requests=None,
            duration_ms=10,
            error_code="provider_call_count_unknown",
        )


class _Publisher:
    """Count calls to the candidate and atomic policy-v3 publication path."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._asset_codes: tuple[str, ...] = ()

    def begin_activation(
        self,
        *,
        binding: FinancialCapacityBinding,
        run_id: UUID,
        evidence: tuple[FinancialCapacitySliceEvidence, ...],
    ) -> FinancialCapacityActivationIntent:
        assert binding.publication_policy_version == "3"
        assert evidence
        return FinancialCapacityActivationIntent(
            run_id=run_id,
            activation_id=uuid5(NAMESPACE_URL, f"test-activation:{run_id}"),
            expected_current_publication_id=None,
            expected_current_publication_hash=None,
            financial_raw_audit_id="1",
            financial_raw_audit_content_hash="a" * 64,
            ingested_run_id=run_id,
            provider_key="akshare",
            occurred_at=datetime(2026, 10, 8, tzinfo=UTC),
        )

    def stage(
        self,
        *,
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        manifest_sha256: str,
    ) -> FinancialCapacityPublicationPlan:
        assert binding.publication_policy_version == "3"
        self._asset_codes = asset_codes
        return FinancialCapacityPublicationPlan(
            intent=intent,
            manifest_sha256=manifest_sha256,
            candidate_publication_id=str(uuid5(NAMESPACE_URL, f"test-candidate:{intent.run_id}")),
            candidate_publication_hash="f" * 64,
            member_manifest_sha256="b" * 64,
        )

    def activate(
        self,
        *,
        binding: FinancialCapacityBinding,
        plan: FinancialCapacityPublicationPlan,
    ) -> str:
        assert binding.publication_policy_version == "3"
        self.calls.append(self._asset_codes)
        return "f" * 64


class _RecoverablePublicationState:
    """Model durable staged/current rows independently of a publisher instance."""

    def __init__(self) -> None:
        self.staged_plan: FinancialCapacityPublicationPlan | None = None
        self.current_plan: FinancialCapacityPublicationPlan | None = None
        self.live_fact_revision = 0
        self.staged_fact_revision: int | None = None
        self.candidate_builds = 0
        self.live_fact_reads = 0
        self.activation_commits = 0
        self.activation_replays = 0


class _RecoveringPublisher(_Publisher):
    """Recover only the persisted candidate and same activation after worker loss."""

    def __init__(
        self,
        state: _RecoverablePublicationState,
        *,
        disconnect_after_commit: bool = False,
    ) -> None:
        super().__init__()
        self.state = state
        self.disconnect_after_commit = disconnect_after_commit
        self.activation_attempts = 0

    def stage(
        self,
        *,
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        manifest_sha256: str,
    ) -> FinancialCapacityPublicationPlan:
        self._asset_codes = asset_codes
        if self.state.staged_plan is not None:
            plan = self.state.staged_plan
            assert plan.intent == intent
            assert plan.manifest_sha256 == manifest_sha256
            assert tuple(sorted(asset_codes)) == self._asset_codes
            return plan
        self.state.candidate_builds += 1
        self.state.live_fact_reads += 1
        plan = super().stage(
            binding=binding,
            intent=intent,
            asset_codes=asset_codes,
            manifest_sha256=manifest_sha256,
        )
        self.state.staged_plan = plan
        self.state.staged_fact_revision = self.state.live_fact_revision
        return plan

    def activate(
        self,
        *,
        binding: FinancialCapacityBinding,
        plan: FinancialCapacityPublicationPlan,
    ) -> str:
        self.activation_attempts += 1
        current_plan = self.state.current_plan
        if current_plan is not None:
            assert current_plan == plan
            self.state.activation_replays += 1
            return plan.candidate_publication_hash
        assert self.state.staged_plan == plan
        assert self.state.staged_fact_revision == self.state.live_fact_revision
        self.state.live_fact_reads += 1
        self.state.activation_commits += 1
        self.state.current_plan = plan
        publication_hash = super().activate(binding=binding, plan=plan)
        if self.disconnect_after_commit:
            raise OSError("simulated database disconnect after activation commit")
        return publication_hash


class _CrashOnceCheckpointRepository(InMemoryFinancialCapacityCheckpointRepository):
    """Raise once at a selected durable checkpoint boundary, like a worker crash."""

    def __init__(self, *, crash_at: str) -> None:
        super().__init__()
        if crash_at not in {"plan", "success"}:
            raise ValueError("unsupported checkpoint crash boundary")
        self.crash_at = crash_at
        self.crashed = False
        self.enabled = False

    def save(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        expected_revision: int,
    ) -> FinancialCapacityCheckpoint:
        current = self.get(checkpoint.workflow_id)
        if (
            self.enabled
            and not self.crashed
            and self.crash_at == "plan"
            and (
                checkpoint.publication_plan is not None
                and (current is None or current.publication_plan is None)
            )
        ):
            self.crashed = True
            raise _HardWorkerInterruption()
        if (
            self.enabled
            and not self.crashed
            and self.crash_at == "success"
            and checkpoint.status == "success"
        ):
            self.crashed = True
            raise _HardWorkerInterruption()
        return super().save(checkpoint, expected_revision=expected_revision)


def _start_formal_replay_workflow(
    *,
    workflow_id: str,
    checkpoint_repository: FinancialCapacityCheckpointRepository,
    publisher: _Publisher,
) -> tuple[
    FinancialCapacityWorkflow,
    _RuntimeBinding,
    _Manifest,
    _SliceRunner,
    GovernedFinancialProductionCeiling,
]:
    """Prepare one approved formal run without executing its production slice."""

    isolated_binding = _binding()
    slices = (_slice(71),)
    isolated_manifest = _Manifest(slices)
    checkpoint_repository = checkpoint_repository or InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=isolated_manifest,
        runner=_SliceRunner(),
        checkpoint_repository=checkpoint_repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id=f"qualification-for-{workflow_id}",
        candidate_sha=isolated_binding.candidate_sha,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(
        workflow_id=f"qualification-for-{workflow_id}"
    ).receipt
    assert receipt is not None
    if isinstance(checkpoint_repository, _CrashOnceCheckpointRepository):
        checkpoint_repository.enabled = True

    production_binding = _RuntimeBinding(isolated_binding.for_environment("production"))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    ceiling = GovernedFinancialProductionCeiling(
        approval_id=f"governance:financial-capacity:{workflow_id}",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding.binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    formal = _workflow(
        binding=production_binding,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=checkpoint_repository,
    )
    formal.start_formal_publication(
        workflow_id=workflow_id,
        candidate_sha=isolated_binding.candidate_sha,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )
    return formal, production_binding, manifest, runner, ceiling


class _CeilingSource:
    """Stand in for the strict governance file loader used by production composition."""

    def __init__(self, ceiling: GovernedFinancialProductionCeiling | None = None) -> None:
        self.ceiling = ceiling

    def get(
        self,
        *,
        receipt_sha256: str,
        candidate_sha: str,
        manifest_sha256: str,
    ) -> GovernedFinancialProductionCeiling | None:
        if self.ceiling is None:
            return None
        if (
            self.ceiling.receipt_sha256 != receipt_sha256
            or self.ceiling.binding.candidate_sha != candidate_sha
            or self.ceiling.manifest_sha256 != manifest_sha256
        ):
            return None
        return self.ceiling


class _QualificationCeilingSource:
    """Return only the exact reviewed isolated binding and workload ceiling."""

    def __init__(
        self,
        ceiling: GovernedFinancialQualificationCeiling | None,
    ) -> None:
        self.ceiling = ceiling

    def get_qualification(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialQualificationCeiling | None:
        if self.ceiling is None:
            return None
        if self.ceiling.binding != binding or self.ceiling.manifest_sha256 != manifest_sha256:
            return None
        return self.ceiling


class _CapacityRehearsalCeilingSource:
    """Return only the exact reviewed full-scope isolated rehearsal ceiling."""

    def __init__(
        self,
        ceiling: GovernedFinancialCapacityRehearsalCeiling | None,
    ) -> None:
        self.ceiling = ceiling

    def get_capacity_rehearsal(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialCapacityRehearsalCeiling | None:
        if self.ceiling is None:
            return None
        if self.ceiling.binding != binding or self.ceiling.manifest_sha256 != manifest_sha256:
            return None
        return self.ceiling


class _AuthorityValidator:
    """Expose a controllable same-authority result for formal workflow tests."""

    def __init__(self, current: bool = True, fail_on_check: int | None = None) -> None:
        self.current = current
        self.fail_on_check = fail_on_check
        self.checks = 0

    def is_current(self) -> bool:
        self.checks += 1
        return self.current and self.checks != self.fail_on_check


class _ScopeCapacityImportAuthoritySource:
    """Accept one explicit synthetic verified-import identity in workflow tests."""

    def load_record_sha256(self, import_id: str) -> str | None:
        """Return the fixture digest only for its exact persisted import ID."""

        return _VERIFIED_IMPORT_RECORD_SHA256 if import_id == _VERIFIED_IMPORT_ID else None

    def validate_current(
        self,
        *,
        import_id: str,
        record_sha256: str,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        now: datetime,
        expected_consumed: bool,
    ) -> str | None:
        """Reject any import identity except the test fixture's verified record."""

        if import_id != _VERIFIED_IMPORT_ID or record_sha256 != _VERIFIED_IMPORT_RECORD_SHA256:
            return "financial_capacity_scope_import_invalid"
        return None

    def consume_formal_start(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        now: datetime,
    ) -> None:
        """Keep application-only workflow tests independent of persistence behavior."""

        return None


class _TrackingScopeCapacityImportAuthoritySource(_ScopeCapacityImportAuthoritySource):
    """Record formal boundary revalidation while returning a controlled revocation."""

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.expected_consumed: list[bool] = []

    def validate_current(
        self,
        *,
        import_id: str,
        record_sha256: str,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        now: datetime,
        expected_consumed: bool,
    ) -> str | None:
        self.expected_consumed.append(expected_consumed)
        reason = super().validate_current(
            import_id=import_id,
            record_sha256=record_sha256,
            workflow_id=workflow_id,
            binding=binding,
            manifest_sha256=manifest_sha256,
            active_universe_sha256=active_universe_sha256,
            source_revision_sha256=source_revision_sha256,
            now=now,
            expected_consumed=expected_consumed,
        )
        return reason or self.reason


def _workflow(
    *,
    binding: _RuntimeBinding,
    manifest: _Manifest,
    runner: _SliceRunner,
    publisher: _Publisher | None = None,
    ceiling_source: _CeilingSource | None = None,
    qualification_ceiling_source: _QualificationCeilingSource | None = None,
    capacity_rehearsal_ceiling_source: _CapacityRehearsalCeilingSource | None = None,
    authority_validator: _AuthorityValidator | None = None,
    checkpoint_repository: FinancialCapacityCheckpointRepository | None = None,
    clock: ProtocolClock | None = None,
) -> FinancialCapacityWorkflow:
    """Compose a deterministic in-memory workflow for unit tests."""

    qualification_ceiling = (
        GovernedFinancialQualificationCeiling(
            approval_id="qualification-review:capacity-test",
            approved_by="owner:financial-data",
            approved_at=datetime(2026, 10, 8, tzinfo=UTC),
            approval_receipt_sha256="6" * 64,
            binding=binding.binding,
            manifest_sha256=_manifest_sha256(manifest.slices),
            maximum_slices=len(manifest.slices),
            maximum_provider_requests=len(manifest.slices) * 2,
            expires_at=datetime(2026, 10, 9, tzinfo=UTC),
            approved=True,
        )
        if binding.binding.environment == "isolated"
        else None
    )
    rehearsal_ceiling = (
        GovernedFinancialCapacityRehearsalCeiling(
            approval_id="capacity-rehearsal-review:capacity-test",
            approved_by="owner:financial-data",
            approved_at=datetime(2026, 10, 8, tzinfo=UTC),
            approval_receipt_sha256="7" * 64,
            binding=binding.binding,
            manifest_sha256=_manifest_sha256(manifest.slices),
            maximum_slices=len(manifest.slices),
            maximum_provider_requests=len(manifest.slices) * 2,
            expires_at=datetime(2026, 10, 9, tzinfo=UTC),
            approved=True,
        )
        if binding.binding.environment == "isolated"
        else None
    )
    return FinancialCapacityWorkflow(
        checkpoint_repository=(
            checkpoint_repository or InMemoryFinancialCapacityCheckpointRepository()
        ),
        binding_source=binding,
        manifest_source=manifest,
        slice_runner=runner,
        publisher=publisher or _Publisher(),
        qualification_ceiling_source=(
            qualification_ceiling_source or _QualificationCeilingSource(qualification_ceiling)
        ),
        capacity_rehearsal_ceiling_source=(
            capacity_rehearsal_ceiling_source or _CapacityRehearsalCeilingSource(rehearsal_ceiling)
        ),
        production_ceiling_source=ceiling_source or _CeilingSource(),
        authority_validator=authority_validator or _AuthorityValidator(),
        scope_capacity_import_authority_source=_ScopeCapacityImportAuthoritySource(),
        clock=clock or (lambda: datetime(2026, 10, 8, tzinfo=UTC)),
    )


def test_full_scope_capacity_rehearsal_receipt_can_start_formal_workflow() -> None:
    slices = (_slice(31), _slice(32))
    isolated_binding = _RuntimeBinding(_binding())
    isolated_runner = _SliceRunner()
    repository = InMemoryFinancialCapacityCheckpointRepository()
    rehearsal = _workflow(
        binding=isolated_binding,
        manifest=_Manifest(slices),
        runner=isolated_runner,
        checkpoint_repository=repository,
    )

    started = rehearsal.start_capacity_rehearsal(
        workflow_id="full-scope-capacity-rehearsal",
        candidate_sha=isolated_binding.binding.candidate_sha,
        total_provider_request_budget=4,
    )
    measured = rehearsal.run_capacity_rehearsal(workflow_id="full-scope-capacity-rehearsal")
    receipt = measured.receipt

    assert started.checkpoint.status == "running"
    assert measured.outcome == "success"
    assert receipt is not None
    assert receipt.stage == "capacity_rehearsal"
    assert receipt.manifest_count == len(slices)
    assert receipt.schema_version == "v3"
    assert "manifest" not in receipt.to_dict()
    assert "evidence" not in receipt.to_dict()
    assert receipt.provider_requests == 4

    production_binding = _RuntimeBinding(isolated_binding.binding.for_environment("production"))
    production_manifest = _Manifest(slices)
    production_ceiling = GovernedFinancialProductionCeiling(
        approval_id="production-review:capacity-rehearsal-positive",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="8" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding.binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=2,
        maximum_provider_requests=4,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    formal = _workflow(
        binding=production_binding,
        manifest=production_manifest,
        runner=_SliceRunner(),
        ceiling_source=_CeilingSource(production_ceiling),
        checkpoint_repository=repository,
    )
    formal_started = formal.start_formal_publication(
        workflow_id="formal-after-full-rehearsal",
        candidate_sha=isolated_binding.binding.candidate_sha,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )

    assert formal_started.checkpoint.status == "running"
    assert formal_started.blocked_reason is None
    assert formal_started.checkpoint is not None
    assert formal_started.checkpoint.capacity_receipt == receipt
    from apps.data_center.infrastructure.financial_capacity_checkpoint_codec import (
        _checkpoint_from_payload,
        _checkpoint_to_payload,
    )

    encoded_checkpoint = _checkpoint_to_payload(formal_started.checkpoint)
    decoded_checkpoint = _checkpoint_from_payload(encoded_checkpoint)
    assert encoded_checkpoint["schema"] == "financial-publication-capacity-checkpoint.v6"
    assert decoded_checkpoint.scope_capacity_import_id == _VERIFIED_IMPORT_ID
    assert decoded_checkpoint.scope_capacity_import_record_sha256 == _VERIFIED_IMPORT_RECORD_SHA256
    assert decoded_checkpoint.active_universe_sha256 is not None


def test_formal_start_rejects_capacity_receipt_without_verified_s6_import() -> None:
    """A local rehearsal receipt alone cannot authorize the production workflow."""

    slices = (_slice(33),)
    isolated_binding = _RuntimeBinding(_binding())
    repository = InMemoryFinancialCapacityCheckpointRepository()
    rehearsal = _workflow(
        binding=isolated_binding,
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    rehearsal.start_capacity_rehearsal(
        workflow_id="capacity-before-import-gate",
        candidate_sha=isolated_binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    receipt = rehearsal.run_capacity_rehearsal(workflow_id="capacity-before-import-gate").receipt
    assert receipt is not None

    production_binding = _RuntimeBinding(isolated_binding.binding.for_environment("production"))
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="production-review:no-s6-import",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="8" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding.binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    formal = _workflow(
        binding=production_binding,
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )

    result = formal.start_formal_publication(
        workflow_id="formal-rejects-capacity-without-s6-import",
        candidate_sha=isolated_binding.binding.candidate_sha,
        capacity_receipt=receipt,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_scope_import_required"


def test_single_slice_qualification_receipt_never_qualifies_for_formal_start() -> None:
    slices = (_slice(41),)
    isolated_binding = _RuntimeBinding(_binding())
    qualification = _workflow(
        binding=isolated_binding,
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
    )
    qualification.start_qualification(
        workflow_id="n1-qualification-never-formal",
        candidate_sha=isolated_binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_qualification(workflow_id="n1-qualification-never-formal").receipt
    assert receipt is not None
    assert receipt.stage == "qualification"

    production_binding = _RuntimeBinding(isolated_binding.binding.for_environment("production"))
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="production-review:n1-rejection",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="8" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding.binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    formal_runner = _SliceRunner()
    formal = _workflow(
        binding=production_binding,
        manifest=_Manifest(slices),
        runner=formal_runner,
        ceiling_source=_CeilingSource(ceiling),
    )
    started = formal.start_formal_publication(
        workflow_id="formal-rejects-n1",
        candidate_sha=isolated_binding.binding.candidate_sha,
        capacity_receipt=receipt,
    )

    assert started.outcome == "blocked"
    assert started.blocked_reason == "financial_capacity_receipt_stage_not_eligible"
    assert formal_runner.calls == []


def test_capacity_observed_physical_requests_over_ceiling_keep_provider_error_code() -> None:
    """An observed over-budget egress is audited exactly and cannot produce success."""

    class _OverBudgetRunner(_SliceRunner):
        def execute(
            self,
            *,
            binding: FinancialCapacityBinding,
            item: FinancialPublicationSlice,
            run_id: UUID,
        ) -> FinancialCapacitySliceAttempt:
            self.calls.append(item)
            return FinancialCapacitySliceAttempt(
                FinancialSliceSyncResult(
                    outcome="partial",
                    source="akshare",
                    provider_id=binding.provider_id,
                    provider_name=binding.provider_name,
                    requested=1,
                    succeeded=0,
                    failed=1,
                    stored=0,
                    planned_provider_requests=2,
                    failure_reason="financial_provider_request_hard_limit_exceeded",
                ),
                None,
                observed_provider_requests=3,
                duration_ms=10,
                error_code="financial_provider_request_hard_limit_exceeded",
            )

    binding = _RuntimeBinding(_binding())
    runner = _OverBudgetRunner()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((_slice(42),)),
        runner=runner,
    )
    workflow.start_qualification(
        workflow_id="capacity-over-budget-observed",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )

    result = workflow.run_qualification(workflow_id="capacity-over-budget-observed")

    assert result.outcome == "failed"
    assert result.checkpoint.observed_provider_requests == 3
    assert result.checkpoint.error_codes == ("financial_provider_request_hard_limit_exceeded",)
    assert result.receipt is None


def test_post_write_evidence_failure_preserves_known_sync_counts_without_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed evidence inspection cannot erase a known atomic provider result."""

    from types import SimpleNamespace

    from apps.data_center.infrastructure import financial_publication_capacity_runtime as runtime

    binding = _RuntimeBinding(_binding())
    provider = SimpleNamespace(
        id=binding.binding.provider_id, is_active=True, source_type="akshare"
    )
    sync_result = FinancialSliceSyncResult(
        outcome="success",
        source="akshare",
        provider_id=binding.binding.provider_id,
        provider_name=binding.binding.provider_name,
        requested=1,
        succeeded=1,
        failed=0,
        stored=2,
        planned_provider_requests=2,
        atomic_fact_write_count=1,
        observed_provider_requests=2,
        maximum_physical_provider_attempts=2,
    )

    class _SyncUseCase:
        def execute(self, request: object) -> FinancialSliceSyncResult:
            return sync_result

    monkeypatch.setattr(
        runtime,
        "load_akshare_financial_slice_sync_budget",
        lambda: SimpleNamespace(max_period_rows_per_capture=100),
    )
    monkeypatch.setattr(
        runtime,
        "get_provider_config_repository",
        lambda: SimpleNamespace(get_by_id=lambda _provider_id: provider),
    )
    monkeypatch.setattr(
        runtime,
        "make_sync_akshare_financial_slices_use_case",
        lambda *, max_route_attempts: _SyncUseCase(),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_financial_response_artifact_config",
        lambda: SimpleNamespace(root="unused-by-the-failing-verifier"),
    )
    monkeypatch.setattr(
        runtime,
        "_verify_persisted_pair",
        lambda **_: (_ for _ in ()).throw(ValueError("persisted pair evidence changed")),
    )
    repository = InMemoryFinancialCapacityCheckpointRepository()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((_slice(43),)),
        runner=runtime.ControlledAkshareFinancialCapacitySliceRunner(),
        checkpoint_repository=repository,
    )
    workflow.start_qualification(
        workflow_id="post-write-evidence-invalid",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )

    result = workflow.run_qualification(workflow_id="post-write-evidence-invalid")

    assert result.outcome == "partial"
    assert result.blocked_reason == "financial_capacity_post_write_evidence_invalid"
    assert result.receipt is None
    assert result.checkpoint.requested == 1
    assert result.checkpoint.succeeded == 1
    assert result.checkpoint.failed == 0
    assert result.checkpoint.stored == 2
    assert result.checkpoint.observed_provider_requests == 2
    assert result.checkpoint.atomic_fact_write_count == 1
    assert result.checkpoint.evidence_count == 0


def test_capacity_observed_requests_at_cumulative_budget_ceiling_are_not_overrun() -> None:
    """A prior two attempts plus a current two-attempt failure exactly fills budget four."""

    class _SecondSliceFailureRunner(_SliceRunner):
        def execute(
            self,
            *,
            binding: FinancialCapacityBinding,
            item: FinancialPublicationSlice,
            run_id: UUID,
        ) -> FinancialCapacitySliceAttempt:
            if not self.calls:
                return super().execute(binding=binding, item=item, run_id=run_id)
            self.calls.append(item)
            return FinancialCapacitySliceAttempt(
                FinancialSliceSyncResult(
                    outcome="partial",
                    source="akshare",
                    provider_id=binding.provider_id,
                    provider_name=binding.provider_name,
                    requested=1,
                    succeeded=0,
                    failed=1,
                    stored=0,
                    planned_provider_requests=2,
                    failure_reason="provider_response_failed",
                    observed_provider_requests=2,
                ),
                None,
                observed_provider_requests=2,
                duration_ms=10,
                error_code="provider_response_failed",
            )

    binding = _RuntimeBinding(_binding())
    runner = _SecondSliceFailureRunner()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((_slice(44), _slice(45))),
        runner=runner,
    )
    workflow.start_qualification(
        workflow_id="capacity-exact-cumulative-budget",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=4,
    )

    result = workflow.run_qualification(workflow_id="capacity-exact-cumulative-budget")

    assert result.outcome == "partial"
    assert result.checkpoint.observed_provider_requests == 4
    assert result.receipt is not None
    assert result.receipt.provider_requests == 4
    assert result.receipt.total_provider_request_budget == 4


@pytest.mark.parametrize(
    ("budget", "ceiling_slices", "expected_reason"),
    (
        (2, 2, "financial_capacity_total_request_budget_insufficient"),
        (6, 2, "financial_capacity_rehearsal_budget_not_exact"),
        (4, 1, "financial_capacity_rehearsal_ceiling_not_approved"),
    ),
)
def test_capacity_rehearsal_requires_exact_full_scope_ceiling_before_egress(
    budget: int,
    ceiling_slices: int,
    expected_reason: str,
) -> None:
    slices = (_slice(51), _slice(52))
    binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    ceiling = GovernedFinancialCapacityRehearsalCeiling(
        approval_id=f"rehearsal-review:{budget}:{ceiling_slices}",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="7" * 64,
        binding=binding.binding,
        manifest_sha256=_manifest_sha256(slices),
        maximum_slices=ceiling_slices,
        maximum_provider_requests=ceiling_slices * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest(slices),
        runner=runner,
        capacity_rehearsal_ceiling_source=_CapacityRehearsalCeilingSource(ceiling),
    )

    started = workflow.start_capacity_rehearsal(
        workflow_id=f"rehearsal-reject:{budget}:{ceiling_slices}",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=budget,
    )

    assert started.outcome == "blocked"
    assert started.blocked_reason == expected_reason
    assert runner.calls == []


def test_rejected_rehearsal_budget_does_not_consume_approval_id() -> None:
    """A validation failure cannot consume the owner approval needed by a valid retry."""

    slices = (_slice(57), _slice(58))
    binding = _RuntimeBinding(_binding())
    ceiling = GovernedFinancialCapacityRehearsalCeiling(
        approval_id="rehearsal-review:retry-after-invalid-budget",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="7" * 64,
        binding=binding.binding,
        manifest_sha256=_manifest_sha256(slices),
        maximum_slices=len(slices),
        maximum_provider_requests=len(slices) * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    repository = InMemoryFinancialCapacityCheckpointRepository()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        capacity_rehearsal_ceiling_source=_CapacityRehearsalCeilingSource(ceiling),
        checkpoint_repository=repository,
    )

    rejected = workflow.start_capacity_rehearsal(
        workflow_id="rehearsal-invalid-budget-attempt",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    accepted = workflow.start_capacity_rehearsal(
        workflow_id="rehearsal-valid-budget-retry",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=4,
    )

    assert rejected.blocked_reason == "financial_capacity_total_request_budget_insufficient"
    assert rejected.checkpoint.capacity_rehearsal_ceiling is None
    assert accepted.outcome == "partial"
    assert accepted.checkpoint.capacity_rehearsal_ceiling == ceiling


def test_capacity_rehearsal_without_owner_approval_has_zero_provider_egress() -> None:
    slices = (_slice(61), _slice(62))
    binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest(slices),
        runner=runner,
        capacity_rehearsal_ceiling_source=_CapacityRehearsalCeilingSource(None),
    )

    started = workflow.start_capacity_rehearsal(
        workflow_id="rehearsal-without-owner-approval",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=4,
    )

    assert started.outcome == "blocked"
    assert started.blocked_reason == "financial_capacity_rehearsal_ceiling_not_approved"
    assert runner.calls == []


def test_capacity_workflow_rejects_insufficient_total_budget_before_provider_access() -> None:
    """The full frozen manifest budget is checked before the first slice starts."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1), _slice(2)))
    runner = _SliceRunner()
    workflow = _workflow(binding=binding, manifest=manifest, runner=runner)

    started = workflow.start_qualification(
        workflow_id="capacity-low-budget",
        candidate_sha="a" * 40,
        total_provider_request_budget=3,
    )

    assert started.outcome == "blocked"
    assert started.blocked_reason == "financial_capacity_total_request_budget_insufficient"
    assert runner.calls == []
    assert started.checkpoint.manifest == tuple(sorted(manifest.slices))


def test_qualification_starts_from_one_explicit_isolated_manifest_slice() -> None:
    """Qualification receives the exact stage and isolated binding for its N=1 scope."""

    slices = (_slice(1),)
    binding = _RuntimeBinding(_binding())
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    workflow = _workflow(binding=binding, manifest=manifest, runner=runner)

    started = workflow.start_qualification(
        workflow_id="qualification-one-typed-slice",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    completed = workflow.run_qualification(workflow_id="qualification-one-typed-slice")

    assert started.checkpoint.manifest == slices
    assert manifest.calls == [
        ("qualification", binding.binding),
        ("qualification", binding.binding),
    ]
    assert completed.outcome == "success"
    assert completed.receipt is not None
    assert completed.receipt.requested == 1
    assert completed.receipt.provider_requests == 2
    assert runner.calls == list(slices)


def test_expired_qualification_approval_blocks_before_provider_access() -> None:
    """A structurally valid approval is unusable after its reviewed expiry time."""

    slices = (_slice(3),)
    binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    expired_ceiling = GovernedFinancialQualificationCeiling(
        approval_id="qualification-review:expired",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 7, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        binding=binding.binding,
        manifest_sha256=_manifest_sha256(slices),
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 7, tzinfo=UTC),
        approved=True,
    )
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest(slices),
        runner=runner,
        qualification_ceiling_source=_QualificationCeilingSource(expired_ceiling),
    )

    result = workflow.start_qualification(
        workflow_id="expired-qualification-approval",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    assert result.blocked_reason == "financial_capacity_qualification_ceiling_not_approved"
    assert runner.calls == []


def test_future_qualification_approval_blocks_before_provider_access() -> None:
    """An unexpired approval is still unusable before its approved_at time."""

    slices = (_slice(4),)
    binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    future_ceiling = GovernedFinancialQualificationCeiling(
        approval_id="qualification-review:not-yet-effective",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 9, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        binding=binding.binding,
        manifest_sha256=_manifest_sha256(slices),
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 10, tzinfo=UTC),
        approved=True,
    )
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest(slices),
        runner=runner,
        qualification_ceiling_source=_QualificationCeilingSource(future_ceiling),
    )

    result = workflow.start_qualification(
        workflow_id="future-qualification-approval",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_qualification_ceiling_not_approved"
    assert runner.calls == []


def test_capacity_workflow_rejects_caller_budget_above_reviewed_ceiling_before_egress() -> None:
    """A caller cannot authorize a larger isolated workload by increasing its input budget."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1), _slice(2)))
    runner = _SliceRunner()
    workflow = _workflow(binding=binding, manifest=manifest, runner=runner)

    result = workflow.start_qualification(
        workflow_id="capacity-arbitrary-budget",
        candidate_sha="a" * 40,
        total_provider_request_budget=6,
    )

    assert result.outcome == "blocked"
    assert (
        result.blocked_reason == "financial_capacity_qualification_budget_exceeds_approved_ceiling"
    )
    assert runner.calls == []
    assert result.checkpoint.reserved_provider_requests == 0


def test_capacity_workflow_blocks_when_qualification_approval_is_missing() -> None:
    """The default-null qualification approval cannot be replaced by a task input."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1),))
    runner = _SliceRunner()
    workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        qualification_ceiling_source=_QualificationCeilingSource(None),
    )

    result = workflow.start_qualification(
        workflow_id="capacity-no-qualification-approval",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_qualification_ceiling_not_approved"
    assert result.checkpoint.reserved_provider_requests == 0
    assert runner.calls == []


def test_two_qualification_workflows_cannot_consume_one_approval_concurrently() -> None:
    """Revision-safe checkpoint creation grants one concurrent consumer of an approval."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1),))
    repository = InMemoryFinancialCapacityCheckpointRepository()
    first_runner = _SliceRunner()
    second_runner = _SliceRunner()
    barrier = Barrier(2)

    def start(workflow_id: str, runner: _SliceRunner) -> str:
        workflow = _workflow(
            binding=binding,
            manifest=manifest,
            runner=runner,
            checkpoint_repository=repository,
        )
        barrier.wait()
        try:
            return workflow.start_qualification(
                workflow_id=workflow_id,
                candidate_sha="a" * 40,
                total_provider_request_budget=2,
            ).outcome
        except FinancialCapacityWorkflowError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result()
            for future in (
                executor.submit(start, "concurrent-qualification-a", first_runner),
                executor.submit(start, "concurrent-qualification-b", second_runner),
            )
        )

    assert outcomes.count("partial") == 1
    assert outcomes.count("financial capacity approval or receipt has already been consumed") == 1
    assert first_runner.calls == []
    assert second_runner.calls == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("provider_identity_sha256", "f" * 64, "financial_capacity_runtime_identity_drift"),
        ("contract_sha256", "f" * 64, "financial_capacity_runtime_identity_drift"),
        ("parser_sha256", "f" * 64, "financial_capacity_runtime_identity_drift"),
        ("publication_policy_sha256", "f" * 64, "financial_capacity_runtime_identity_drift"),
        ("deployment_region", "other-egress", "financial_capacity_runtime_identity_drift"),
    ),
)
def test_capacity_workflow_blocks_exact_provider_contract_parser_policy_or_region_drift(
    field: str,
    value: str,
    reason: str,
) -> None:
    """Qualification refuses runtime identity drift before another provider request."""

    runtime = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1),))
    runner = _SliceRunner()
    workflow = _workflow(binding=runtime, manifest=manifest, runner=runner)
    workflow.start_qualification(
        workflow_id=f"capacity-drift-{field}",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    runtime.binding = replace(runtime.binding, **{field: value})

    result = workflow.run_qualification(workflow_id=f"capacity-drift-{field}")

    assert result.outcome == "blocked"
    assert result.blocked_reason == reason
    assert runner.calls == []


def test_capacity_workflow_reserves_cumulative_budget_and_resumes_from_checkpoint() -> None:
    """A normal task restart resumes the next frozen pair without repeating completed work."""

    binding = _RuntimeBinding(_binding())
    slices = (_slice(1), _slice(2), _slice(3))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    publisher = _Publisher()
    workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
    )
    workflow.start_qualification(
        workflow_id="capacity-resume",
        candidate_sha="a" * 40,
        total_provider_request_budget=len(slices) * 2,
    )

    first = workflow.run_qualification(workflow_id="capacity-resume", max_slices=2)
    resumed = workflow.run_qualification(workflow_id="capacity-resume")

    assert first.outcome == "partial"
    assert first.checkpoint.next_slice_index == 2
    assert first.checkpoint.reserved_provider_requests == 4
    assert resumed.outcome == "success"
    assert resumed.checkpoint.next_slice_index == len(slices)
    assert resumed.checkpoint.reserved_provider_requests == len(slices) * 2
    assert runner.calls == list(slices)
    assert publisher.calls == []
    assert isinstance(resumed.receipt, FinancialCapacityReceipt)
    assert resumed.receipt.requested == len(slices)
    assert resumed.receipt.succeeded == len(slices)
    assert resumed.receipt.failed == 0
    assert resumed.receipt.stored == len(slices) * 2
    assert resumed.receipt.provider_requests == len(slices) * 2
    assert resumed.receipt.raw_body_count == len(slices) * 2
    assert resumed.receipt.raw_audit_count == len(slices) * 2
    assert resumed.receipt.typed_evidence_count == len(slices) * 2
    assert resumed.receipt.atomic_fact_write_count == len(slices)
    assert resumed.receipt.review_status == "pending_review"


def test_capacity_workflow_stops_when_cumulative_request_budget_is_exhausted() -> None:
    """No batch loop can exceed the frozen workflow-level logical request ceiling."""

    binding = _RuntimeBinding(_binding())
    slices = (_slice(1), _slice(2))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    workflow = _workflow(binding=binding, manifest=manifest, runner=runner)
    started = workflow.start_qualification(
        workflow_id="capacity-over-budget",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    workflow._checkpoints.save(
        replace(started.checkpoint, total_provider_request_budget=2),
        expected_revision=started.checkpoint.revision,
    )
    result = workflow.run_qualification(workflow_id="capacity-over-budget")

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_total_request_budget_exceeded"
    assert len(runner.calls) == 1
    assert result.checkpoint.reserved_provider_requests == 2
    assert result.checkpoint.next_slice_index == 1


def test_capacity_workflow_partial_failure_never_builds_or_publishes_candidate() -> None:
    """Any failed slice makes the qualification terminal and creates no Publication."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1), _slice(2)))
    runner = _SliceRunner()
    runner.fail_at = 2
    publisher = _Publisher()
    workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
    )
    workflow.start_qualification(
        workflow_id="capacity-partial",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )

    result = workflow.run_qualification(workflow_id="capacity-partial")

    assert result.outcome == "partial"
    assert result.checkpoint.requested == 2
    assert result.checkpoint.succeeded == 1
    assert result.checkpoint.failed == 1
    assert result.checkpoint.stored == 2
    assert result.receipt is not None
    assert result.receipt.review_status == "not_eligible"
    assert publisher.calls == []


def test_capacity_workflow_zero_output_is_not_success_and_never_builds_candidate() -> None:
    """A zero-row write fails the slice evidence contract and leaves no candidate."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1),))
    runner = _ZeroOutputRunner()
    publisher = _Publisher()
    workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
    )
    workflow.start_qualification(
        workflow_id="capacity-zero-output",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    result = workflow.run_qualification(workflow_id="capacity-zero-output")

    assert result.outcome == "failed"
    assert result.blocked_reason == "financial_capacity_slice_evidence_invalid"
    assert result.checkpoint.requested == 1
    assert result.checkpoint.succeeded == 0
    assert result.checkpoint.failed == 1
    assert result.checkpoint.stored == 0
    assert publisher.calls == []


def test_unknown_actual_provider_request_count_is_not_qualified_or_accumulated() -> None:
    """Unknown egress counts fail qualification without inventing usage or a receipt."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(2),))
    runner = _UnknownRequestCountRunner()
    workflow = _workflow(binding=binding, manifest=manifest, runner=runner)
    workflow.start_qualification(
        workflow_id="capacity-unknown-request-count",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    result = workflow.run_qualification(workflow_id="capacity-unknown-request-count")

    assert result.outcome == "failed"
    assert result.blocked_reason == "financial_capacity_actual_request_count_unknown"
    assert result.checkpoint.observed_provider_requests == 0
    assert result.checkpoint.capacity_receipt is None
    assert result.receipt is None


@pytest.mark.parametrize(
    "interruption",
    (SoftTimeLimitExceeded(), _HardWorkerInterruption()),
    ids=("soft-timeout", "hard-worker-stop"),
)
def test_capacity_workflow_keeps_orphan_evidence_and_never_replays_an_inflight_slice(
    interruption: BaseException,
) -> None:
    """A restarted worker blocks on the durable in-flight reservation after interruption."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(1),))
    repository = InMemoryFinancialCapacityCheckpointRepository()
    interrupted_runner = _InterruptingRunner(interruption)
    first_workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=interrupted_runner,
        checkpoint_repository=repository,
    )
    first_workflow.start_qualification(
        workflow_id="capacity-interrupted",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    with pytest.raises(type(interruption)):
        first_workflow.run_qualification(workflow_id="capacity-interrupted")

    retry_runner = _SliceRunner()
    live_checkpoint = repository.get("capacity-interrupted")
    assert live_checkpoint is not None
    assert live_checkpoint.in_flight_claim_token
    assert live_checkpoint.in_flight_claim_expires_at is not None
    revision_before_duplicate = live_checkpoint.revision
    restarted_workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=retry_runner,
        checkpoint_repository=repository,
    )
    live_duplicate = restarted_workflow.run_qualification(workflow_id="capacity-interrupted")

    assert live_duplicate.outcome == "partial"
    assert live_duplicate.checkpoint.status == "running"
    assert live_duplicate.checkpoint.revision == revision_before_duplicate
    assert live_duplicate.checkpoint.in_flight_claim_token == live_checkpoint.in_flight_claim_token
    assert retry_runner.calls == []

    expired_workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=retry_runner,
        checkpoint_repository=repository,
        clock=lambda: live_checkpoint.in_flight_claim_expires_at + timedelta(seconds=1),
    )
    restarted = expired_workflow.run_qualification(workflow_id="capacity-interrupted")
    assert restarted.outcome == "blocked"
    assert restarted.blocked_reason == "financial_capacity_inflight_outcome_indeterminate"
    assert restarted.checkpoint.in_flight_slice_index == 0
    assert restarted.checkpoint.reserved_provider_requests == 2
    assert restarted.checkpoint.in_flight_claim_token == live_checkpoint.in_flight_claim_token
    assert interrupted_runner.calls == list(manifest.slices)
    assert retry_runner.calls == []


def test_formal_inflight_claim_rechecks_import_and_owner_authority_before_returning() -> None:
    """A live claim does not bypass current S6 import or formal task authority checks."""

    repository = InMemoryFinancialCapacityCheckpointRepository()
    formal, _binding_source, _manifest, runner, _ceiling = _start_formal_replay_workflow(
        workflow_id="formal-live-claim-authority-recheck",
        checkpoint_repository=repository,
        publisher=_Publisher(),
    )
    checkpoint = repository.get("formal-live-claim-authority-recheck")
    assert checkpoint is not None
    claimed = replace(
        checkpoint,
        reserved_provider_requests=2,
        in_flight_slice_index=0,
        in_flight_claim_token=str(uuid4()),
        in_flight_claim_expires_at=datetime(2026, 10, 8, 0, 10, tzinfo=UTC),
    )
    repository.save(claimed, expected_revision=checkpoint.revision)
    source = _TrackingScopeCapacityImportAuthoritySource(
        reason="financial_capacity_scope_import_authority_revoked"
    )
    formal._scope_capacity_import_authority_source = source

    revoked = formal.run_formal_publication(workflow_id="formal-live-claim-authority-recheck")

    assert revoked.blocked_reason == "financial_capacity_scope_import_authority_revoked"
    assert source.expected_consumed == [True]
    assert runner.calls == []

    source.reason = None
    formal._authority_validator = _AuthorityValidator(current=False)
    stale_owner = formal.run_formal_publication(workflow_id="formal-live-claim-authority-recheck")

    assert stale_owner.blocked_reason == "financial_capacity_authority_not_current"
    assert source.expected_consumed == [True, True]
    assert runner.calls == []


def test_concurrent_duplicate_returns_live_claim_without_mutating_checkpoint() -> None:
    """A duplicate invocation observes the durable running claim and does no work."""

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(9),))
    repository = InMemoryFinancialCapacityCheckpointRepository()
    runner = _BlockingRunner()
    workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        checkpoint_repository=repository,
    )
    workflow.start_qualification(
        workflow_id="concurrent-live-claim",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(workflow.run_qualification, workflow_id="concurrent-live-claim")
        assert runner.entered.wait(timeout=5)
        before_duplicate = repository.get("concurrent-live-claim")
        assert before_duplicate is not None

        duplicate = workflow.run_qualification(workflow_id="concurrent-live-claim")

        after_duplicate = repository.get("concurrent-live-claim")
        assert after_duplicate == before_duplicate
        assert duplicate.outcome == "partial"
        assert duplicate.checkpoint.status == "running"
        assert duplicate.checkpoint.in_flight_claim_token
        assert runner.calls == []
        runner.release.set()
        completed = active.result(timeout=5)

    assert completed.outcome == "success"
    assert runner.calls == list(manifest.slices)


def test_formal_workflow_requires_governed_ceiling_bound_to_receipt_scope_and_candidate() -> None:
    """An unapproved or mismatched capacity receipt cannot start formal provider work."""

    isolated_binding = _binding()
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification_manifest = _Manifest((_slice(1), _slice(2)))
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=qualification_manifest,
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-scope-drift",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    receipt = qualification.run_capacity_rehearsal(workflow_id="qual-scope-drift").receipt
    assert receipt is not None
    binding_value = isolated_binding.for_environment("production")
    runtime = _RuntimeBinding(binding_value)
    slices = (_slice(1), _slice(2))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    assert receipt.sha256
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="governance:financial-capacity:test",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=binding_value,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=len(slices),
        maximum_provider_requests=len(slices) * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    manifest.slices = (slices[0], _slice(3))
    workflow = _workflow(
        binding=runtime,
        manifest=manifest,
        runner=runner,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )

    result = workflow.start_formal_publication(
        workflow_id="formal-scope-drift",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_scope_drift"
    assert runner.calls == []


def test_formal_start_maps_production_ceiling_source_error_to_blocked() -> None:
    """A governance read failure produces a stable blocked checkpoint before egress."""

    isolated = _RuntimeBinding(_binding())
    slices = (_slice(24),)
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=isolated,
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-production-ceiling-source-error",
        candidate_sha=isolated.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(
        workflow_id="qual-production-ceiling-source-error"
    ).receipt
    assert receipt is not None

    class _FailingCeilingSource:
        def get(
            self,
            *,
            receipt_sha256: str,
            candidate_sha: str,
            manifest_sha256: str,
        ) -> GovernedFinancialProductionCeiling | None:
            raise RuntimeError("governance store unavailable")

    runner = _SliceRunner()
    formal = _workflow(
        binding=_RuntimeBinding(isolated.binding.for_environment("production")),
        manifest=_Manifest(slices),
        runner=runner,
        ceiling_source=_FailingCeilingSource(),
        checkpoint_repository=repository,
    )

    result = formal.start_formal_publication(
        workflow_id="formal-production-ceiling-source-error",
        candidate_sha=isolated.binding.candidate_sha,
        capacity_receipt=receipt,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_production_ceiling_unavailable"
    assert result.checkpoint.governed_ceiling is None
    assert runner.calls == []


def test_formal_workflow_activates_policy_v3_only_after_every_slice_succeeds() -> None:
    """The atomic finance publication path runs once and only after complete success."""

    isolated_binding = _binding()
    runtime = _RuntimeBinding(isolated_binding.for_environment("production"))
    slices = (_slice(1), _slice(2))
    manifest = _Manifest(slices)
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification_runner = _SliceRunner()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=manifest,
        runner=qualification_runner,
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-complete",
        candidate_sha="a" * 40,
        total_provider_request_budget=len(slices) * 2,
    )
    qualified = qualification.run_capacity_rehearsal(workflow_id="qual-complete")
    assert qualified.receipt is not None

    production_runner = _SliceRunner()
    publisher = _Publisher()
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="governance:financial-capacity:approved",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=qualified.receipt.sha256,
        binding=runtime.binding,
        manifest_sha256=qualified.receipt.manifest_sha256,
        maximum_slices=len(slices),
        maximum_provider_requests=len(slices) * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    formal = _workflow(
        binding=runtime,
        manifest=_Manifest(slices),
        runner=production_runner,
        publisher=publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    started = formal.start_formal_publication(
        workflow_id="formal-success",
        candidate_sha="a" * 40,
        capacity_receipt=qualified.receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )
    assert started.outcome == "partial"
    assert publisher.calls == []

    completed = formal.run_formal_publication(workflow_id="formal-success")
    duplicate_delivery = formal.run_formal_publication(workflow_id="formal-success")

    assert completed.outcome == "success"
    assert duplicate_delivery.outcome == "success"
    assert completed.publication_hash == "f" * 64
    assert duplicate_delivery.publication_hash == completed.publication_hash
    assert publisher.calls == [tuple(sorted({item.asset_code for item in slices}))]
    assert production_runner.calls == list(slices)


def test_formal_staging_response_loss_recovers_same_candidate_without_rebuilding_facts() -> None:
    """A staged candidate survives checkpoint failure and is reused by fixed run ID."""

    repository = _CrashOnceCheckpointRepository(crash_at="plan")
    state = _RecoverablePublicationState()
    first_publisher = _RecoveringPublisher(state)
    workflow, binding, manifest, runner, ceiling = _start_formal_replay_workflow(
        workflow_id="formal-stage-response-loss",
        checkpoint_repository=repository,
        publisher=first_publisher,
    )

    with pytest.raises(_HardWorkerInterruption):
        workflow.run_formal_publication(workflow_id="formal-stage-response-loss")

    interrupted = repository.get("formal-stage-response-loss")
    assert interrupted is not None
    assert interrupted.status == "running"
    assert interrupted.activation_intent is not None
    assert interrupted.publication_plan is None
    staged_plan = state.staged_plan
    assert staged_plan is not None
    assert state.candidate_builds == 1

    retry_publisher = _RecoveringPublisher(state)
    retry = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=retry_publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    result = retry.run_formal_publication(workflow_id="formal-stage-response-loss")

    assert result.outcome == "success"
    assert result.checkpoint.publication_plan == staged_plan
    assert state.candidate_builds == 1
    assert state.activation_commits == 1
    assert runner.calls == list(manifest.slices)


def test_formal_activation_commit_unknown_remains_running_for_exact_replay() -> None:
    """A lost DB response after CAS returns an indeterminate result, then replays exactly."""

    repository = InMemoryFinancialCapacityCheckpointRepository()
    state = _RecoverablePublicationState()
    first_publisher = _RecoveringPublisher(state, disconnect_after_commit=True)
    workflow, binding, manifest, runner, ceiling = _start_formal_replay_workflow(
        workflow_id="formal-activation-db-disconnect",
        checkpoint_repository=repository,
        publisher=first_publisher,
    )

    indeterminate = workflow.run_formal_publication(workflow_id="formal-activation-db-disconnect")

    assert indeterminate.outcome == "partial"
    assert indeterminate.blocked_reason == (
        "financial_capacity_publication_activation_outcome_indeterminate"
    )
    assert indeterminate.checkpoint.status == "running"
    assert indeterminate.checkpoint.activation_intent is not None
    assert indeterminate.checkpoint.publication_plan is not None
    assert indeterminate.checkpoint.finished_at is None
    current_plan = state.current_plan
    assert current_plan is not None
    fact_reads_after_commit = state.live_fact_reads
    state.live_fact_revision += 1

    retry_publisher = _RecoveringPublisher(state)
    retry = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=retry_publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    completed = retry.run_formal_publication(workflow_id="formal-activation-db-disconnect")

    assert completed.outcome == "success"
    assert completed.checkpoint.publication_plan == current_plan
    assert state.candidate_builds == 1
    assert state.activation_commits == 1
    assert state.activation_replays == 1
    assert state.live_fact_reads == fact_reads_after_commit
    assert runner.calls == list(manifest.slices)


def test_formal_checkpoint_crash_after_activation_ignores_later_live_fact_changes() -> None:
    """After pointer commit, checkpoint recovery verifies the same candidate without facts."""

    repository = _CrashOnceCheckpointRepository(crash_at="success")
    state = _RecoverablePublicationState()
    first_publisher = _RecoveringPublisher(state)
    workflow, binding, manifest, runner, ceiling = _start_formal_replay_workflow(
        workflow_id="formal-checkpoint-crash-after-activation",
        checkpoint_repository=repository,
        publisher=first_publisher,
    )

    with pytest.raises(_HardWorkerInterruption):
        workflow.run_formal_publication(workflow_id="formal-checkpoint-crash-after-activation")

    interrupted = repository.get("formal-checkpoint-crash-after-activation")
    assert interrupted is not None
    assert interrupted.status == "running"
    assert interrupted.activation_intent is not None
    assert interrupted.publication_plan == state.current_plan
    assert state.activation_commits == 1
    fact_reads_after_commit = state.live_fact_reads
    state.live_fact_revision += 1

    retry_publisher = _RecoveringPublisher(state)
    retry = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        publisher=retry_publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    completed = retry.run_formal_publication(workflow_id="formal-checkpoint-crash-after-activation")

    assert completed.outcome == "success"
    assert completed.checkpoint.publication_plan == state.current_plan
    assert state.candidate_builds == 1
    assert state.activation_commits == 1
    assert state.activation_replays == 1
    assert state.live_fact_reads == fact_reads_after_commit
    assert runner.calls == list(manifest.slices)


@pytest.mark.parametrize(
    ("drift", "expected_reason"),
    (
        ("revoked", "financial_capacity_governed_ceiling_drift"),
        ("expired", "financial_capacity_governed_ceiling_expired_or_drifted"),
        ("provider", "financial_capacity_runtime_identity_drift"),
    ),
)
def test_formal_workflow_revalidates_exact_binding_and_ceiling_before_each_slice(
    drift: str,
    expected_reason: str,
) -> None:
    """Revocation, expiry, or provider drift blocks the next slice before egress."""

    isolated_binding = _binding()
    slices = (_slice(22), _slice(23))
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id=f"qual-slice-revalidation-{drift}",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    receipt = qualification.run_capacity_rehearsal(
        workflow_id=f"qual-slice-revalidation-{drift}"
    ).receipt
    assert receipt is not None

    production_binding = isolated_binding.for_environment("production")
    runtime = _RuntimeBinding(production_binding)
    manifest = _Manifest(slices)
    ceiling = GovernedFinancialProductionCeiling(
        approval_id=f"governance:financial-capacity:per-slice-{drift}",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=len(slices),
        maximum_provider_requests=len(slices) * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    ceiling_source = _CeilingSource(ceiling)
    clock_value = [datetime(2026, 10, 8, tzinfo=UTC)]

    class _MutatingRunner(_SliceRunner):
        def execute(
            self,
            *,
            binding: FinancialCapacityBinding,
            item: FinancialPublicationSlice,
            run_id: UUID,
        ) -> FinancialCapacitySliceAttempt:
            attempt = super().execute(binding=binding, item=item, run_id=run_id)
            if len(self.calls) == 1:
                if drift == "revoked":
                    ceiling_source.ceiling = None
                elif drift == "expired":
                    clock_value[0] = ceiling.expires_at + timedelta(seconds=1)
                else:
                    runtime.binding = replace(
                        production_binding,
                        provider_identity_sha256="9" * 64,
                    )
            return attempt

    runner = _MutatingRunner()
    publisher = _Publisher()
    formal = _workflow(
        binding=runtime,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
        ceiling_source=ceiling_source,
        clock=lambda: clock_value[0],
        checkpoint_repository=repository,
    )
    formal.start_formal_publication(
        workflow_id=f"formal-slice-revalidation-{drift}",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )

    result = formal.run_formal_publication(
        workflow_id=f"formal-slice-revalidation-{drift}",
        max_slices=2,
    )

    assert result.outcome == "blocked"
    assert result.blocked_reason == expected_reason
    assert len(runner.calls) == 1
    assert publisher.calls == []


def test_future_production_approval_blocks_before_provider_access() -> None:
    """A future-dated production approval cannot start provider egress."""

    isolated_binding = _binding()
    slices = (_slice(5),)
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-future-production-approval",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(
        workflow_id="qual-future-production-approval"
    ).receipt
    assert receipt is not None

    production_binding = isolated_binding.for_environment("production")
    future_ceiling = GovernedFinancialProductionCeiling(
        approval_id="production-review:not-yet-effective",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 9, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 10, tzinfo=UTC),
        approved=True,
    )
    runner = _SliceRunner()
    workflow = _workflow(
        binding=_RuntimeBinding(production_binding),
        manifest=_Manifest(slices),
        runner=runner,
        ceiling_source=_CeilingSource(future_ceiling),
        checkpoint_repository=repository,
    )

    result = workflow.start_formal_publication(
        workflow_id="formal-future-approval",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
    )

    assert result.outcome == "blocked"
    assert (
        result.blocked_reason == "financial_capacity_production_ceiling_approval_not_yet_effective"
    )
    assert runner.calls == []


def test_formal_approval_cannot_be_consumed_by_two_workflow_ids() -> None:
    """The same production ceiling cannot authorize two independent provider runs."""

    isolated_binding = _binding()
    slices = (_slice(15),)
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-single-consumption",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(workflow_id="qual-single-consumption").receipt
    assert receipt is not None

    production_binding = isolated_binding.for_environment("production")
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="governance:financial-capacity:single-use",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    first_runner = _SliceRunner()
    first = _workflow(
        binding=_RuntimeBinding(production_binding),
        manifest=_Manifest(slices),
        runner=first_runner,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    second_runner = _SliceRunner()
    second = _workflow(
        binding=_RuntimeBinding(production_binding),
        manifest=_Manifest(slices),
        runner=second_runner,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    first.start_formal_publication(
        workflow_id="formal-single-consumption-a",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )

    with pytest.raises(
        FinancialCapacityWorkflowError,
        match="financial capacity approval or receipt has already been consumed",
    ):
        second.start_formal_publication(
            workflow_id="formal-single-consumption-b",
            candidate_sha="a" * 40,
            capacity_receipt=receipt,
            scope_capacity_import_id=_VERIFIED_IMPORT_ID,
            scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
        )

    assert first_runner.calls == []
    assert second_runner.calls == []


def test_formal_partial_failure_does_not_create_policy_v3_candidate_or_activate() -> None:
    """A failed formal slice leaves the current financial Publication untouched."""

    isolated_binding = _binding()
    slices = (_slice(1), _slice(2))
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-for-partial-formal",
        candidate_sha="a" * 40,
        total_provider_request_budget=len(slices) * 2,
    )
    receipt = qualification.run_capacity_rehearsal(workflow_id="qual-for-partial-formal").receipt
    assert receipt is not None

    runtime = _RuntimeBinding(isolated_binding.for_environment("production"))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    runner.fail_at = 2
    publisher = _Publisher()
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="governance:financial-capacity:approved",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=runtime.binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=len(slices),
        maximum_provider_requests=len(slices) * 2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    workflow = _workflow(
        binding=runtime,
        manifest=manifest,
        runner=runner,
        publisher=publisher,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    workflow.start_formal_publication(
        workflow_id="formal-partial",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )

    result = workflow.run_formal_publication(workflow_id="formal-partial")

    assert result.outcome == "partial"
    assert result.publication_hash is None
    assert publisher.calls == []


@pytest.mark.parametrize(
    ("fail_on_check", "expected_provider_calls"),
    ((2, 0), (3, 1)),
    ids=("authority-before-provider", "authority-before-activation"),
)
def test_formal_workflow_revalidates_authority_at_provider_and_activation_boundaries(
    fail_on_check: int,
    expected_provider_calls: int,
) -> None:
    """Formal work stops if the same authority is lost before either write boundary."""

    isolated_binding = _binding()
    slices = (_slice(21),)
    repository = InMemoryFinancialCapacityCheckpointRepository()
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id=f"qual-authority-{fail_on_check}",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(
        workflow_id=f"qual-authority-{fail_on_check}"
    ).receipt
    assert receipt is not None

    production_binding = isolated_binding.for_environment("production")
    runtime = _RuntimeBinding(production_binding)
    runner = _SliceRunner()
    publisher = _Publisher()
    ceiling = GovernedFinancialProductionCeiling(
        approval_id=f"governance:financial-capacity:authority-{fail_on_check}",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    authority = _AuthorityValidator(fail_on_check=fail_on_check)
    formal = _workflow(
        binding=runtime,
        manifest=_Manifest(slices),
        runner=runner,
        publisher=publisher,
        ceiling_source=_CeilingSource(ceiling),
        authority_validator=authority,
        checkpoint_repository=repository,
    )
    formal.start_formal_publication(
        workflow_id=f"formal-authority-{fail_on_check}",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )

    result = formal.run_formal_publication(workflow_id=f"formal-authority-{fail_on_check}")

    assert result.outcome == "blocked"
    assert result.blocked_reason == "financial_capacity_authority_not_current"
    assert len(runner.calls) == expected_provider_calls
    assert publisher.calls == []


def test_capacity_task_blocks_without_approved_ceiling_before_formal_provider_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_binding = _RuntimeBinding(_binding())
    slices = (_slice(31),)
    runner = _SliceRunner()
    workflow = _workflow(
        binding=runtime_binding,
        manifest=_Manifest(slices),
        runner=runner,
    )
    workflow.start_capacity_rehearsal(
        workflow_id="qualification-receipt",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    qualified = workflow.run_capacity_rehearsal(workflow_id="qualification-receipt")
    assert qualified.receipt is not None
    calls_before_formal_gate = len(runner.calls)
    runtime_binding.binding = replace(
        _binding(),
        environment="production",
        isolation_attestation_sha256="",
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: workflow,
    )
    monkeypatch.setattr(
        tasks,
        "_preflight_data02_task_authority",
        lambda **_: (object(), None),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="formal_start",
        workflow_id="formal-publication",
        candidate_sha="a" * 40,
        capacity_rehearsal_workflow_id="qualification-receipt",
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
    )

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "financial_capacity_production_ceiling_not_approved"
    assert len(runner.calls) == calls_before_formal_gate
    assert result["provider_requests"] == 0


@pytest.mark.parametrize("action", ("formal_start", "formal_run"))
def test_capacity_task_authority_denial_precedes_formal_workflow_composition(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    authority_failure = {
        "outcome": "blocked",
        "stage": "authority",
        "blocked_reason": "authority_unavailable",
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
    }
    monkeypatch.setattr(
        tasks,
        "_preflight_data02_task_authority",
        lambda **_: (None, authority_failure),
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: pytest.fail("authority must be checked before checkpoint composition"),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action=action,
        workflow_id=f"authority-{action}",
        candidate_sha="a" * 40,
        capacity_rehearsal_workflow_id="qualification-receipt",
        scope_capacity_import_id=(_VERIFIED_IMPORT_ID if action == "formal_start" else ""),
    )

    assert result == authority_failure


def test_capacity_task_rejects_invalid_input_before_isolation_or_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_: pytest.fail("isolation preflight must not run for invalid input"),
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: pytest.fail("workflow composition must not run for invalid input"),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="invalid",
        workflow_id="qualification",
        candidate_sha="a" * 40,
    )

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    assert result["requested"] == 0


def test_capacity_task_formal_start_requires_persisted_scope_import_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capacity receipt and chat/task arguments cannot replace the durable S6 import."""

    monkeypatch.setattr(
        tasks,
        "_preflight_data02_task_authority",
        lambda **_: pytest.fail("missing S6 import must block before authority or composition"),
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: pytest.fail("missing S6 import must block before checkpoint access"),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="formal_start",
        workflow_id="formal-task-without-import",
        candidate_sha="a" * 40,
        capacity_rehearsal_workflow_id="verified-capacity-rehearsal",
    )

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "financial_capacity_scope_import_required"
    assert result["stored"] == 0


def test_capacity_task_formal_start_rejects_noncanonical_scope_import_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The formal task rejects malformed import identities before any DB authority read."""

    monkeypatch.setattr(
        tasks,
        "_preflight_data02_task_authority",
        lambda **_: pytest.fail("invalid S6 import ID must fail before authority preflight"),
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: pytest.fail("invalid S6 import ID must fail before composition"),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="formal_start",
        workflow_id="formal-task-with-invalid-import",
        candidate_sha="a" * 40,
        capacity_rehearsal_workflow_id="verified-capacity-rehearsal",
        scope_capacity_import_id="not-a-canonical-uuid",
    )

    assert result["outcome"] == "failed"
    assert result["blocked_reason"] == "invalid_financial_capacity_scope_import_id"
    assert result["stored"] == 0


def test_capacity_task_can_finish_one_explicit_isolated_qualification_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    workflow = _workflow(
        binding=runtime_binding,
        manifest=_Manifest((_slice(41),)),
        runner=runner,
    )
    workflow.start_qualification(
        workflow_id="task-qualification",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_: "f" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: workflow,
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="qualification_run",
        workflow_id="task-qualification",
        candidate_sha="a" * 40,
        expected_database_name="isolated-db",
        expected_database_host="isolated-host",
    )

    assert result["outcome"] == "success"
    assert result["requested"] == 1
    assert result["succeeded"] == 1


def test_capacity_task_can_run_explicit_full_scope_isolated_rehearsal_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task exposes the separately approved full-scope rehearsal stage."""

    runtime_binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    workflow = _workflow(
        binding=runtime_binding,
        manifest=_Manifest((_slice(42), _slice(43))),
        runner=runner,
    )
    workflow.start_capacity_rehearsal(
        workflow_id="task-capacity-rehearsal",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_: "f" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: workflow,
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="capacity_rehearsal_run",
        workflow_id="task-capacity-rehearsal",
        candidate_sha="a" * 40,
        max_slices=2,
        expected_database_name="isolated-db",
        expected_database_host="isolated-host",
    )

    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["provider_requests"] == 4
    assert len(runner.calls) == 2
    assert result["capacity_receipt_sha256"]


@pytest.mark.parametrize(
    ("action", "expected_stage"),
    (("qualification_run", "qualification"), ("formal_run", "formal_publication")),
)
def test_capacity_task_candidate_sha_must_match_durable_checkpoint_before_run(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_stage: str,
) -> None:
    """A task payload cannot resume a durable provider workflow under another candidate."""

    binding = _RuntimeBinding(_binding())
    runner = _SliceRunner()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((_slice(42),)),
        runner=runner,
    )
    started = workflow.start_qualification(
        workflow_id=f"candidate-mismatch-{action}",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    mismatch_binding = replace(
        started.checkpoint.binding,
        candidate_sha="b" * 40,
        environment="production" if expected_stage == "formal_publication" else "isolated",
        isolation_attestation_sha256=("" if expected_stage == "formal_publication" else "f" * 64),
    )
    mismatched_checkpoint = replace(
        started.checkpoint,
        stage=expected_stage,
        binding=mismatch_binding,
        scope_capacity_import_id=(
            _VERIFIED_IMPORT_ID if expected_stage == "formal_publication" else None
        ),
        scope_capacity_import_record_sha256=(
            _VERIFIED_IMPORT_RECORD_SHA256 if expected_stage == "formal_publication" else None
        ),
    )
    monkeypatch.setattr(workflow, "get_checkpoint", lambda _workflow_id: mismatched_checkpoint)
    monkeypatch.setattr(
        workflow,
        "run_qualification",
        lambda **_kwargs: pytest.fail("candidate mismatch must block before provider work"),
    )
    monkeypatch.setattr(
        workflow,
        "run_formal_publication",
        lambda **_kwargs: pytest.fail("candidate mismatch must block before provider work"),
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_kwargs: workflow,
    )
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "_preflight_data02_task_authority",
        lambda **_kwargs: (object(), None),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action=action,
        workflow_id=f"candidate-mismatch-{action}",
        candidate_sha="a" * 40,
        expected_database_name="isolated-db",
        expected_database_host="isolated-host",
    )

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "financial_capacity_checkpoint_candidate_binding_mismatch"
    assert result["provider_requests"] == 0
    assert runner.calls == []


def test_capacity_task_runs_one_step_without_broker_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint progress is caller-resumable and does not enqueue broker continuations."""

    runner = _SliceRunner()
    workflow = _workflow(
        binding=_RuntimeBinding(_binding()),
        manifest=_Manifest((_slice(61), _slice(62))),
        runner=runner,
    )
    workflow.start_qualification(
        workflow_id="no-broker-continuation",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_: "f" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: workflow,
    )
    monkeypatch.setattr(
        tasks.refresh_financial_publication_capacity_task,
        "apply_async",
        lambda **_: pytest.fail("one-step capacity work cannot self-enqueue"),
    )

    result = tasks.refresh_financial_publication_capacity_task.run(
        action="qualification_run",
        workflow_id="no-broker-continuation",
        candidate_sha="a" * 40,
        expected_database_name="isolated-db",
        expected_database_host="isolated-host",
    )

    assert result["outcome"] == "partial"
    assert result["requested"] == 1
    assert result["next_slice_index"] == 1
    assert len(runner.calls) == 1


def test_capacity_task_duplicate_delivery_returns_terminal_result_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redelivered completed Celery action returns its saved result without provider I/O."""

    runner = _SliceRunner()
    workflow = _workflow(
        binding=_RuntimeBinding(_binding()),
        manifest=_Manifest((_slice(71),)),
        runner=runner,
    )
    workflow.start_qualification(
        workflow_id="duplicate-delivery",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    monkeypatch.setattr(
        tasks,
        "preflight_financial_capacity_isolation",
        lambda **_: "f" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "make_financial_publication_capacity_workflow",
        lambda **_: workflow,
    )
    arguments = {
        "action": "qualification_run",
        "workflow_id": "duplicate-delivery",
        "candidate_sha": "a" * 40,
        "expected_database_name": "isolated-db",
        "expected_database_host": "isolated-host",
    }

    first = tasks.refresh_financial_publication_capacity_task.run(**arguments)
    duplicate = tasks.refresh_financial_publication_capacity_task.run(**arguments)

    assert first["outcome"] == duplicate["outcome"] == "success"
    assert first["capacity_receipt_sha256"] == duplicate["capacity_receipt_sha256"]
    assert runner.calls == [_slice(71)]


@pytest.mark.django_db
def test_django_checkpoint_repository_resumes_after_workflow_reconstruction() -> None:
    from apps.data_center.infrastructure.models import FinancialPublicationCapacityEvidenceModel

    slices = (_slice(51), _slice(52))
    binding = _RuntimeBinding(_binding())
    manifest = _Manifest(slices)
    first_runner = _SliceRunner()
    first_repository = DjangoFinancialCapacityCheckpointRepository()
    first_workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=first_runner,
        checkpoint_repository=first_repository,
    )
    started = first_workflow.start_qualification(
        workflow_id="durable-qualification",
        candidate_sha="a" * 40,
        total_provider_request_budget=4,
    )
    first_step = first_workflow.run_qualification(
        workflow_id="durable-qualification",
        max_slices=1,
    )
    assert first_step.checkpoint.evidence_count == 1
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="durable-qualification"
        ).count()
        == 1
    )
    resumed_runner = _SliceRunner()
    reconstructed = _workflow(
        binding=binding,
        manifest=manifest,
        runner=resumed_runner,
        checkpoint_repository=DjangoFinancialCapacityCheckpointRepository(),
    )

    resumed = reconstructed.run_qualification(workflow_id="durable-qualification")

    assert started.checkpoint.revision < first_step.checkpoint.revision
    assert first_step.outcome == "partial"
    assert resumed.outcome == "success"
    assert resumed.receipt is not None
    assert resumed.receipt.succeeded == len(slices)
    assert resumed.checkpoint.evidence_count == 2
    assert resumed_runner.calls == [_slice(52)]
    duplicate = reconstructed.run_qualification(workflow_id="durable-qualification")
    assert duplicate.receipt == resumed.receipt
    assert resumed_runner.calls == [_slice(52)]
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="durable-qualification"
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_django_evidence_append_rolls_back_when_checkpoint_cas_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence rows and their checkpoint cursor commit or roll back together."""

    from django.db.models.query import QuerySet

    from apps.data_center.application.financial_capacity_models import (
        _append_evidence_sha256,
    )
    from apps.data_center.infrastructure.models import (
        FinancialPublicationCapacityEvidenceModel,
        FinancialPublicationCapacityWorkflowModel,
    )

    item = _slice(54)
    binding = _RuntimeBinding(_binding())
    repository = DjangoFinancialCapacityCheckpointRepository()
    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((item,)),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    started = workflow.start_qualification(
        workflow_id="evidence-append-cas-rollback",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    checkpoint = started.checkpoint
    claimed = repository.save(
        replace(
            checkpoint,
            reserved_provider_requests=2,
            in_flight_slice_index=0,
            in_flight_claim_token="durable-claim",
            in_flight_claim_expires_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        ),
        expected_revision=checkpoint.revision,
    )
    attempt = _SliceRunner().execute(
        binding=binding.binding,
        item=item,
        run_id=UUID(claimed.run_id or ""),
    )
    assert attempt.evidence is not None
    evidence = attempt.evidence
    append = replace(
        claimed,
        next_slice_index=1,
        in_flight_slice_index=None,
        in_flight_claim_token=None,
        in_flight_claim_expires_at=None,
        requested=1,
        succeeded=1,
        stored=evidence.stored,
        observed_provider_requests=2,
        evidence_count=1,
        evidence_previous_sha256=claimed.evidence_sha256,
        evidence_sha256=_append_evidence_sha256(
            claimed.evidence_sha256,
            index=0,
            evidence=evidence,
        ),
        raw_body_count=2,
        raw_audit_count=2,
        typed_evidence_count=evidence.typed_financial_evidence_count,
        atomic_fact_write_count=1,
        evidence_append=evidence,
    )
    original_update = QuerySet.update

    def fail_checkpoint_update(queryset: QuerySet, **fields: object) -> int:
        if (
            queryset.model is FinancialPublicationCapacityWorkflowModel
            and fields.get("revision") == claimed.revision + 1
            and "checkpoint" in fields
        ):
            return 0
        return original_update(queryset, **fields)

    monkeypatch.setattr(QuerySet, "update", fail_checkpoint_update)
    with pytest.raises(FinancialCapacityWorkflowError, match="revision changed"):
        repository.save(append, expected_revision=claimed.revision)

    persisted = repository.get("evidence-append-cas-rollback")
    assert persisted is not None
    assert persisted.revision == claimed.revision
    assert persisted.evidence_count == 0
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="evidence-append-cas-rollback"
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_django_ledger_rejects_bad_initial_seal_and_wrong_manifest_evidence() -> None:
    """The repository enforces immutable manifest-to-evidence binding on its own."""

    from apps.data_center.application.financial_capacity_models import (
        _append_evidence_sha256,
    )
    from apps.data_center.infrastructure.models import FinancialPublicationCapacityEvidenceModel

    item = _slice(55)
    binding = _RuntimeBinding(_binding())
    source_repository = InMemoryFinancialCapacityCheckpointRepository()
    source_workflow = _workflow(
        binding=binding,
        manifest=_Manifest((item,)),
        runner=_SliceRunner(),
        checkpoint_repository=source_repository,
    )
    valid_start = source_workflow.start_qualification(
        workflow_id="valid-checkpoint-source",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    repository = DjangoFinancialCapacityCheckpointRepository()
    with pytest.raises(FinancialCapacityWorkflowError, match="initial checkpoint ledger"):
        repository.create(
            replace(
                valid_start.checkpoint,
                workflow_id="invalid-initial-manifest-seal",
                manifest_count=2,
            )
        )
    assert repository.get("invalid-initial-manifest-seal") is None

    workflow = _workflow(
        binding=binding,
        manifest=_Manifest((item,)),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    started = workflow.start_qualification(
        workflow_id="wrong-manifest-evidence",
        candidate_sha=binding.binding.candidate_sha,
        total_provider_request_budget=2,
    )
    claimed = repository.save(
        replace(
            started.checkpoint,
            reserved_provider_requests=2,
            in_flight_slice_index=0,
            in_flight_claim_token="durable-claim",
            in_flight_claim_expires_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        ),
        expected_revision=started.checkpoint.revision,
    )
    attempt = _SliceRunner().execute(
        binding=binding.binding,
        item=_slice(56),
        run_id=UUID(claimed.run_id or ""),
    )
    assert attempt.evidence is not None
    evidence = attempt.evidence
    append = replace(
        claimed,
        next_slice_index=1,
        in_flight_slice_index=None,
        in_flight_claim_token=None,
        in_flight_claim_expires_at=None,
        requested=1,
        succeeded=1,
        stored=evidence.stored,
        observed_provider_requests=2,
        evidence_count=1,
        evidence_previous_sha256=claimed.evidence_sha256,
        evidence_sha256=_append_evidence_sha256(
            claimed.evidence_sha256,
            index=0,
            evidence=evidence,
        ),
        raw_body_count=2,
        raw_audit_count=2,
        typed_evidence_count=evidence.typed_financial_evidence_count,
        atomic_fact_write_count=1,
        evidence_append=evidence,
    )

    with pytest.raises(FinancialCapacityWorkflowError, match="does not match its manifest item"):
        repository.save(append, expected_revision=claimed.revision)

    persisted = repository.get("wrong-manifest-evidence")
    assert persisted is not None
    assert persisted.revision == claimed.revision
    assert persisted.evidence_count == 0
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="wrong-manifest-evidence"
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_django_capacity_rehearsal_5572_slice_ledger_stays_linear_and_compact() -> None:
    """A full active-universe rehearsal keeps checkpoint and SQL work bounded per slice."""

    import json

    from django.db import connection

    from apps.data_center.infrastructure.models import (
        FinancialPublicationCapacityEvidenceModel,
        FinancialPublicationCapacityManifestItemModel,
        FinancialPublicationCapacityWorkflowModel,
    )

    slices = tuple(_slice(index) for index in range(1, 5_573))
    manifest = _Manifest(slices)
    runner = _SliceRunner()
    repository = DjangoFinancialCapacityCheckpointRepository()
    workflow = _workflow(
        binding=_RuntimeBinding(_binding()),
        manifest=manifest,
        runner=runner,
        checkpoint_repository=repository,
    )
    query_count = 0
    write_query_count = 0
    business_query_count = 0
    transaction_control_count = 0

    def count_database_work(execute, sql, params, many, context):
        nonlocal query_count, write_query_count, business_query_count
        nonlocal transaction_control_count
        query_count += 1
        statement = sql.lstrip().split(None, 1)[0].upper()
        if statement in {"INSERT", "UPDATE", "DELETE"}:
            write_query_count += 1
        if statement in {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}:
            transaction_control_count += 1
        else:
            business_query_count += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count_database_work):
        workflow.start_capacity_rehearsal(
            workflow_id="capacity-ledger-5572",
            candidate_sha="a" * 40,
            total_provider_request_budget=len(slices) * 2,
        )
        completed = workflow.run_capacity_rehearsal(
            workflow_id="capacity-ledger-5572",
        )

    checkpoint_row = FinancialPublicationCapacityWorkflowModel.objects.get(
        workflow_id="capacity-ledger-5572"
    )
    assert completed.outcome == "success"
    assert completed.receipt is not None
    assert completed.receipt.manifest_count == 5_572
    assert completed.receipt.evidence_count == 5_572
    assert len(runner.calls) == 5_572
    assert len(manifest.calls) == 2
    assert (
        FinancialPublicationCapacityManifestItemModel.objects.filter(
            workflow_id="capacity-ledger-5572"
        ).count()
        == 5_572
    )
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="capacity-ledger-5572"
        ).count()
        == 5_572
    )
    assert len(json.dumps(checkpoint_row.checkpoint, separators=(",", ":"))) < 16_384
    checkpoint_bytes = len(json.dumps(checkpoint_row.checkpoint, separators=(",", ":")))
    print(
        f"capacity_ledger_scale: sql={query_count}, orm={business_query_count}, "
        f"tx={transaction_control_count}, writes={write_query_count}, "
        f"checkpoint_bytes={checkpoint_bytes}, "
        f"source_freeze_calls={len(manifest.calls)}"
    )
    # BEGIN/COMMIT are SQLite transaction-control statements around two durable saves per slice.
    assert business_query_count <= 5 * len(slices) + 64
    assert write_query_count <= 3 * len(slices) + 64
    assert query_count <= 9 * len(slices) + 64
    assert len(manifest.calls) == 2
    assert checkpoint_bytes < 16_384

    duplicate = workflow.run_capacity_rehearsal(workflow_id="capacity-ledger-5572")

    assert duplicate.outcome == "success"
    assert len(runner.calls) == 5_572
    assert (
        FinancialPublicationCapacityEvidenceModel.objects.filter(
            workflow_id="capacity-ledger-5572"
        ).count()
        == 5_572
    )


@pytest.mark.django_db(transaction=True)
def test_django_concurrent_duplicate_observes_live_claim_without_database_mutation() -> None:
    """The database claim prevents concurrent Celery deliveries from replaying a slice."""

    from django.db import close_old_connections

    binding = _RuntimeBinding(_binding())
    manifest = _Manifest((_slice(53),))
    repository = DjangoFinancialCapacityCheckpointRepository()
    runner = _BlockingRunner()
    active_workflow = _workflow(
        binding=binding,
        manifest=manifest,
        runner=runner,
        checkpoint_repository=repository,
    )
    active_workflow.start_qualification(
        workflow_id="database-concurrent-live-claim",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )

    def run_active_claim() -> object:
        close_old_connections()
        try:
            return active_workflow.run_qualification(workflow_id="database-concurrent-live-claim")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(run_active_claim)
        assert runner.entered.wait(timeout=5)
        before_duplicate = repository.get("database-concurrent-live-claim")
        assert before_duplicate is not None

        duplicate = _workflow(
            binding=binding,
            manifest=manifest,
            runner=_SliceRunner(),
            checkpoint_repository=DjangoFinancialCapacityCheckpointRepository(),
        ).run_qualification(workflow_id="database-concurrent-live-claim")

        after_duplicate = repository.get("database-concurrent-live-claim")
        assert after_duplicate == before_duplicate
        assert duplicate.outcome == "partial"
        assert duplicate.checkpoint.status == "running"
        assert duplicate.checkpoint.in_flight_claim_token
        runner.release.set()
        completed = active.result(timeout=10)

    assert completed.outcome == "success"
    assert runner.calls == list(manifest.slices)


@pytest.mark.django_db
def test_django_checkpoint_repository_consumes_receipt_once_even_after_reapproval() -> None:
    """A new approval ID cannot authorize a second use of the same receipt."""

    isolated_binding = _binding()
    slices = (_slice(81),)
    repository = DjangoFinancialCapacityCheckpointRepository(
        scope_capacity_import_authority_source=_ScopeCapacityImportAuthoritySource()
    )
    qualification = _workflow(
        binding=_RuntimeBinding(isolated_binding),
        manifest=_Manifest(slices),
        runner=_SliceRunner(),
        checkpoint_repository=repository,
    )
    qualification.start_capacity_rehearsal(
        workflow_id="qual-database-consumption",
        candidate_sha="a" * 40,
        total_provider_request_budget=2,
    )
    receipt = qualification.run_capacity_rehearsal(workflow_id="qual-database-consumption").receipt
    assert receipt is not None

    production_binding = isolated_binding.for_environment("production")
    ceiling = GovernedFinancialProductionCeiling(
        approval_id="governance:financial-capacity:database-single-use",
        approved_by="owner:financial-data",
        approved_at=datetime(2026, 10, 8, tzinfo=UTC),
        approval_receipt_sha256="6" * 64,
        receipt_sha256=receipt.sha256,
        binding=production_binding,
        manifest_sha256=receipt.manifest_sha256,
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=datetime(2026, 10, 9, tzinfo=UTC),
        approved=True,
    )
    first_runner = _SliceRunner()
    first = _workflow(
        binding=_RuntimeBinding(production_binding),
        manifest=_Manifest(slices),
        runner=first_runner,
        ceiling_source=_CeilingSource(ceiling),
        checkpoint_repository=repository,
    )
    second_runner = _SliceRunner()
    reapproved_ceiling = replace(
        ceiling,
        approval_id="governance:financial-capacity:database-reapproved",
    )
    second = _workflow(
        binding=_RuntimeBinding(production_binding),
        manifest=_Manifest(slices),
        runner=second_runner,
        ceiling_source=_CeilingSource(reapproved_ceiling),
        checkpoint_repository=repository,
    )
    first_start = first.start_formal_publication(
        workflow_id="formal-database-consumption-a",
        candidate_sha="a" * 40,
        capacity_receipt=receipt,
        scope_capacity_import_id=_VERIFIED_IMPORT_ID,
        scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
    )
    first_checkpoint = repository.get("formal-database-consumption-a")
    assert first_checkpoint is not None
    assert first_checkpoint.status == "running", first_start.blocked_reason
    assert first_checkpoint.capacity_receipt == receipt

    with pytest.raises(
        FinancialCapacityWorkflowError,
        match="financial capacity approval or receipt has already been consumed",
    ):
        second.start_formal_publication(
            workflow_id="formal-database-consumption-b",
            candidate_sha="a" * 40,
            capacity_receipt=receipt,
            scope_capacity_import_id=_VERIFIED_IMPORT_ID,
            scope_capacity_import_record_sha256=_VERIFIED_IMPORT_RECORD_SHA256,
        )

    assert first_runner.calls == []
    assert second_runner.calls == []
