"""Contracts for binding reviewed dynamic scope to existing financial capacity input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError
from django.test import override_settings

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
)
from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInput,
    FinancialScopeCapacityInputError,
    install_financial_scope_manifest_pointer,
    prepare_financial_scope_manifest_pointer,
    resolve_current_financial_scope_capacity_input,
    validate_capacity_scope_input,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAsset,
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCandidate,
    FinancialScopeManifestReview,
    make_candidate,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_manifest_current_pointer import (
    DjangoFinancialScopeManifestCurrentPointerSource,
)
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityGovernanceRevocationModel,
    FinancialCapacityOwnerApprovalEventModel,
    FinancialFactModel,
    FinancialPublicationCapacityWorkflowModel,
    FinancialScopeManifestCurrentPointerModel,
)

_NOW = datetime.now(UTC) + timedelta(minutes=1)
_ASSET_CODES = ("000001.SZ",)


def _scope_binding() -> FinancialScopeDiscoveryBinding:
    """Return one synthetic but domain-valid provider/report binding."""

    return FinancialScopeDiscoveryBinding(
        candidate_sha="a" * 40,
        provider_id=17,
        provider_name="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="akshare.financial-scope.latest-notice",
        contract_version="2026-10-09.v1",
        contract_sha256="c" * 64,
        parser_id="akshare.financial-scope-parser.v1",
        parser_sha256="d" * 64,
        deployment_region="isolated-test",
    )


def _candidate() -> FinancialScopeDiscoveryCandidate:
    """Build a complete dynamic manifest with opaque native row and RawAudit IDs."""

    binding = _scope_binding()
    generated_at = _NOW - timedelta(hours=2)
    authorization = FinancialScopeDiscoveryAuthorization.for_universe(
        binding=binding,
        asset_codes=_ASSET_CODES,
        approval_id="discovery-owner-approval",
        approved_by="scope-owner",
        recorded_by="scope-operator",
        event_id="discovery-owner-event",
        receipt_sha256="e" * 64,
        approved_at=_NOW - timedelta(hours=3),
        expires_at=_NOW + timedelta(days=1),
        maximum_logical_requests=2,
        maximum_rows_per_asset=200,
    )
    item = FinancialScopeDiscoveryAsset(
        asset_code=_ASSET_CODES[0],
        announcement_date=date(2026, 8, 30),
        available_at=datetime(2026, 8, 30, 16, tzinfo=UTC),
        native_row_ids=("akshare:000001.SZ:2026-06-30:2026-08-30",),
        financial_capture_id="capture-financial-1",
        financial_body_sha256="f" * 64,
        financial_raw_audit_id=101,
        source_time_capture_id="capture-source-time-1",
        source_time_body_sha256="1" * 64,
        source_time_raw_audit_id=102,
        response_completed_at=(
            datetime(2026, 8, 31, 1, tzinfo=UTC),
            datetime(2026, 8, 31, 2, tzinfo=UTC),
        ),
    )
    return make_candidate(
        binding=binding,
        authorization=authorization,
        asset_codes=_ASSET_CODES,
        items=(item,),
        generated_at=generated_at,
    )


def _report() -> dict[str, object]:
    """Return the exact successful disposable-PostgreSQL discovery projection."""

    candidate = _candidate()
    candidate_payload = candidate.payload()
    candidate_payload["manifest_sha256"] = candidate.manifest_sha256
    return {
        "schema": "release.financial-scope-discovery.v1",
        "kind": "financial_scope_discovery",
        "candidate_sha": candidate.binding.candidate_sha,
        "started_at": (_NOW - timedelta(minutes=40)).isoformat(),
        "finished_at": (_NOW - timedelta(minutes=35)).isoformat(),
        "outcome": "success",
        "review_status": "pending_independent_review",
        "binding": {
            "provider_id": candidate.binding.provider_id,
            "provider_name": candidate.binding.provider_name,
            "provider_identity_sha256": candidate.binding.provider_identity_sha256,
            "contract_id": candidate.binding.contract_id,
            "contract_version": candidate.binding.contract_version,
            "contract_sha256": candidate.binding.contract_sha256,
            "parser_id": candidate.binding.parser_id,
            "parser_sha256": candidate.binding.parser_sha256,
            "deployment_region": candidate.binding.deployment_region,
        },
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "name": "agom_release_rehearsal_financial_scope",
            "host": "agom-s6-postgres-financial-scope",
            "isolation_attestation_sha256": "2" * 64,
        },
        "authorization": {
            "approval_id": candidate.discovery_approval_id,
            "owner_event_id": candidate.discovery_owner_event_id,
            "owner_receipt_sha256": candidate.discovery_owner_receipt_sha256,
        },
        "candidate_image_id": "sha256:" + "3" * 64,
        "artifact_root": "financial-scope-artifacts",
        "encrypted_artifacts": [],
        "result": {
            "schema": "data-center.financial-scope-discovery-result.v1",
            "outcome": "success",
            "error_codes": [],
            "counts": {
                "requested": 1,
                "captured": 1,
                "failed_capture": 0,
                "missing": 0,
                "duplicates": 0,
                "conflicts": 0,
                "logical_requests": 2,
                "physical_attempts": 2,
                "artifact_writes": 2,
                "raw_audit_writes": 2,
                "fact_writes": 0,
                "publication_writes": 0,
            },
            "candidate": {
                "manifest_sha256": candidate.manifest_sha256,
                "universe_sha256": candidate.universe_sha256,
                "coverage_count": candidate.coverage_count,
                "review_status": "pending_independent_review",
            },
            "candidate_manifest": candidate_payload,
        },
    }


def _canonical_sha256(payload: object) -> str:
    """Hash the canonical JSON bytes also consumed by the application port."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _persist_reviews(
    report: dict[str, object],
    *,
    environment: Literal["isolated", "production"] = "isolated",
    owner_expires_at: datetime | None = None,
) -> tuple[FinancialCapacityGovernanceRecordModel, ...]:
    """Persist review rows and separately authenticated approval events."""

    candidate = _candidate()
    report_sha256 = _canonical_sha256(report)
    records: list[FinancialCapacityGovernanceRecordModel] = []
    for role, approver, suffix in (
        ("data_owner", "financial-data-owner", "owner"),
        ("independent_reviewer", "independent-financial-reviewer", "reviewer"),
    ):
        payload: dict[str, object] = {
            "schema_version": "data-center.financial-scope-manifest-review.v1",
            "candidate_sha": candidate.binding.candidate_sha,
            "manifest_sha256": candidate.manifest_sha256,
            "universe_sha256": candidate.universe_sha256,
            "provider_identity_sha256": candidate.binding.provider_identity_sha256,
            "contract_sha256": candidate.binding.contract_sha256,
            "deployment_region": candidate.binding.deployment_region,
            "approval_id": f"scope-review-{suffix}-{report_sha256[:12]}",
            "approved_by": approver,
            "recorded_by": "financial-scope-operator",
            "event_id": f"scope-review-event-{suffix}-{report_sha256[:12]}",
            "approval_receipt_sha256": ("4" if suffix == "owner" else "5") * 64,
            "role": role,
            "environment": environment,
            "report_sha256": report_sha256,
            "approved_at": (_NOW - timedelta(minutes=20)).isoformat(),
            "expires_at": (
                owner_expires_at.isoformat()
                if suffix == "owner" and owner_expires_at is not None
                else (_NOW + timedelta(days=1)).isoformat()
            ),
        }
        record = FinancialCapacityGovernanceRecordModel._default_manager.create(
            approval_id=str(payload["approval_id"]),
            stage=FinancialCapacityGovernanceRecordModel.SCOPE_MANIFEST_REVIEW,
            record=payload,
            created_by=str(payload["recorded_by"]),
        )
        FinancialCapacityOwnerApprovalEventModel._default_manager.create(
            governance_record=record,
            event_id=str(payload["event_id"]),
            approved_by=approver,
            approved_at=datetime.fromisoformat(str(payload["approved_at"])),
            approval_receipt_sha256=str(payload["approval_receipt_sha256"]),
            record_sha256=_canonical_sha256(payload),
        )
        records.append(record)
    return tuple(records)


def _capacity_binding(
    *, environment: Literal["isolated", "production"] = "isolated"
) -> FinancialCapacityBinding:
    """Return the matching existing policy-v3 capacity binding."""

    scope = _scope_binding()
    return FinancialCapacityBinding(
        environment=environment,
        candidate_sha=scope.candidate_sha,
        provider_id=scope.provider_id,
        provider_name=scope.provider_name,
        provider_source="akshare",
        provider_identity_sha256=scope.provider_identity_sha256,
        contract_id=scope.contract_id,
        contract_version=scope.contract_version,
        contract_sha256=scope.contract_sha256,
        parser_id=scope.parser_id,
        parser_sha256=scope.parser_sha256,
        deployment_region=scope.deployment_region,
        publication_policy_version="3",
        publication_policy_sha256="6" * 64,
        isolation_attestation_sha256=("7" * 64 if environment == "isolated" else ""),
    )


def _pointer_services() -> tuple[
    DjangoFinancialScopeManifestCurrentPointerSource,
    DjangoFinancialScopeManifestReviewSource,
]:
    """Bind the real PostgreSQL/SQLite adapters used in runtime composition."""

    return (
        DjangoFinancialScopeManifestCurrentPointerSource(),
        DjangoFinancialScopeManifestReviewSource(),
    )


@pytest.mark.django_db
def test_pointer_command_persists_real_dual_approval_and_consumer_reloads_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI installation and capacity consumption use persisted owner/reviewer events."""

    report = _report()
    _persist_reviews(report)
    report_path = tmp_path / "financial-scope-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_version": "3.4.0",
                "source_commit": report["candidate_sha"],
            }
        ),
        encoding="utf-8",
    )
    user_model = get_user_model()
    actor = user_model._default_manager.create_superuser(
        username="scope-current-pointer-admin",
        email="scope-current-pointer-admin@example.test",
        password="scope-current-pointer-password",
    )
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_scope_manifest_pointer.getpass",
        lambda _prompt: "scope-current-pointer-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "record_financial_scope_manifest_pointer",
            report_file=report_path,
            actor=actor.get_username(),
        )

    pointer_model = FinancialScopeManifestCurrentPointerModel._default_manager.get(
        environment="isolated"
    )
    assert pointer_model.revision == 1
    assert pointer_model.report_sha256 == _canonical_sha256(report)
    pointer_source, review_source = _pointer_services()
    resolved = resolve_current_financial_scope_capacity_input(
        pointer_source=pointer_source,
        review_source=review_source,
        binding=_capacity_binding(),
        environment="isolated",
        now=_NOW,
    )
    assert resolved.reviewed_manifest.candidate.manifest_sha256 == _candidate().manifest_sha256
    assert resolved.report_sha256 == pointer_model.report_sha256


@pytest.mark.django_db
def test_missing_or_revoked_review_and_production_report_fail_closed() -> None:
    """A missing pointer, expired event, revocation, or wrong environment cannot pass."""

    pointer_source, review_source = _pointer_services()
    with pytest.raises(FinancialScopeCapacityInputError) as missing:
        resolve_current_financial_scope_capacity_input(
            pointer_source=pointer_source,
            review_source=review_source,
            binding=_capacity_binding(),
            environment="isolated",
            now=_NOW,
        )
    assert missing.value.code == "FINANCIAL_CAPACITY_SCOPE_POINTER_MISSING"

    report = _report()
    expired_at = _NOW - timedelta(minutes=1)
    _persist_reviews(report, owner_expires_at=expired_at)
    install_financial_scope_manifest_pointer(
        pointer_source=pointer_source,
        review_source=review_source,
        report_payload=report,
        environment="isolated",
        updated_by="financial-scope-operator",
        now=_NOW - timedelta(minutes=10),
    )
    with pytest.raises(FinancialScopeCapacityInputError) as expired:
        resolve_current_financial_scope_capacity_input(
            pointer_source=pointer_source,
            review_source=review_source,
            binding=_capacity_binding(),
            environment="isolated",
            now=_NOW,
        )
    assert expired.value.code == "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"

    revoked_report = _report()
    revoked_report["finished_at"] = (_NOW - timedelta(minutes=34)).isoformat()
    revoked_rows = _persist_reviews(revoked_report)
    install_financial_scope_manifest_pointer(
        pointer_source=pointer_source,
        review_source=review_source,
        report_payload=revoked_report,
        environment="isolated",
        updated_by="financial-scope-operator",
        now=_NOW,
    )
    for record in revoked_rows:
        FinancialCapacityGovernanceRevocationModel._default_manager.create(
            governance_record=record,
            revoked_by="governance-admin",
        )
    with pytest.raises(FinancialScopeCapacityInputError) as revoked:
        resolve_current_financial_scope_capacity_input(
            pointer_source=pointer_source,
            review_source=review_source,
            binding=_capacity_binding(),
            environment="isolated",
            now=_NOW + timedelta(minutes=1),
        )
    assert revoked.value.code == "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"

    with pytest.raises(FinancialScopeCapacityInputError) as production:
        install_financial_scope_manifest_pointer(
            pointer_source=pointer_source,
            review_source=review_source,
            report_payload=report,
            environment="production",
            updated_by="financial-scope-operator",
            now=_NOW,
        )
    assert production.value.code == "FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH"


@pytest.mark.django_db
def test_production_pointer_revalidates_current_s6_report_with_production_reviews() -> None:
    """Production reviews bind an isolated S6 report to the current typed-data scope."""

    report = _report()
    owner, reviewer = _persist_reviews(report, environment="production")
    report_sha256 = _canonical_sha256(report)
    FinancialScopeManifestCurrentPointerModel._default_manager.create(
        environment="production",
        report_payload=report,
        report_sha256=report_sha256,
        owner_approval_id=owner.approval_id,
        owner_event_id=str(owner.record["event_id"]),
        reviewer_approval_id=reviewer.approval_id,
        reviewer_event_id=str(reviewer.record["event_id"]),
        revision=1,
        updated_by="financial-scope-production-operator",
    )
    pointer_source, review_source = _pointer_services()

    resolved = resolve_current_financial_scope_capacity_input(
        pointer_source=pointer_source,
        review_source=review_source,
        binding=_capacity_binding(environment="production"),
        environment="production",
        now=_NOW,
    )

    assert resolved.environment == "production"
    assert resolved.report_sha256 == report_sha256
    assert resolved.reviewed_manifest.owner_event_id == owner.record["event_id"]
    assert resolved.reviewed_manifest.reviewer_event_id == reviewer.record["event_id"]


@pytest.mark.django_db
def test_pointer_compare_and_swap_and_database_failure_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale revisions and injected SQL failures leave the previous pointer intact."""

    report = _report()
    _persist_reviews(report)
    pointer_source, review_source = _pointer_services()
    installed = install_financial_scope_manifest_pointer(
        pointer_source=pointer_source,
        review_source=review_source,
        report_payload=report,
        environment="isolated",
        updated_by="financial-scope-operator",
        now=_NOW,
    )
    assert installed.revision == 1
    with pytest.raises(FinancialScopeCapacityInputError) as stale:
        pointer_source.set_current(installed, expected_revision=0)
    assert stale.value.code == "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"

    original_save = FinancialScopeManifestCurrentPointerModel.save

    def save_then_fail(
        self: FinancialScopeManifestCurrentPointerModel, *args: object, **kwargs: object
    ) -> None:
        original_save(self, *args, **kwargs)
        raise DatabaseError("injected pointer write failure")

    monkeypatch.setattr(FinancialScopeManifestCurrentPointerModel, "save", save_then_fail)
    with pytest.raises(FinancialScopeCapacityInputError) as injected:
        pointer_source.set_current(installed, expected_revision=1)
    assert injected.value.code == "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"
    assert pointer_source.get_current(environment="isolated") == installed


def test_review_database_failure_maps_to_stable_approval_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A governance database outage cannot bypass or escape the business gate."""

    def fail_filter(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise DatabaseError("injected review query failure")

    monkeypatch.setattr(
        FinancialCapacityGovernanceRecordModel._default_manager,
        "filter",
        fail_filter,
    )
    with pytest.raises(FinancialScopeCapacityInputError) as caught:
        DjangoFinancialScopeManifestReviewSource().get(
            candidate=_candidate(),
            environment="isolated",
            report_sha256=_canonical_sha256(_report()),
            now=_NOW,
        )
    assert caught.value.code == "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"


def test_scope_report_cannot_become_typed_fact_or_capacity_slice() -> None:
    """Raw discovery evidence selects the scope but never supplies announcement facts."""

    candidate = _candidate()
    report = _report()
    report_sha256 = _canonical_sha256(report)
    owner = FinancialScopeManifestReview(
        candidate_sha=candidate.binding.candidate_sha,
        manifest_sha256=candidate.manifest_sha256,
        universe_sha256=candidate.universe_sha256,
        provider_identity_sha256=candidate.binding.provider_identity_sha256,
        contract_sha256=candidate.binding.contract_sha256,
        deployment_region=candidate.binding.deployment_region,
        approval_id="owner-approval",
        approved_by="financial-data-owner",
        recorded_by="financial-scope-operator",
        event_id="owner-event",
        receipt_sha256="7" * 64,
        role="data_owner",
        environment="isolated",
        report_sha256=report_sha256,
        approved_at=_NOW - timedelta(minutes=20),
        expires_at=_NOW + timedelta(days=1),
    )
    reviewer = replace(
        owner,
        approval_id="reviewer-approval",
        approved_by="independent-financial-reviewer",
        event_id="reviewer-event",
        receipt_sha256="8" * 64,
        role="independent_reviewer",
    )
    reviewed = candidate.approve(
        owner=owner,
        reviewer=reviewer,
        environment="isolated",
        report_sha256=report_sha256,
        now=_NOW,
    )
    scope_input = FinancialScopeCapacityInput(
        reviewed_manifest=reviewed,
        environment="isolated",
        report_sha256=report_sha256,
    )
    active_sha = _canonical_sha256(list(_ASSET_CODES))
    matching_snapshot = FinancialCapacityManifestSnapshot.build(
        slices=(FinancialPublicationSlice(_ASSET_CODES[0], date(2026, 8, 30)),),
        active_universe_sha256=active_sha,
        typed_source_snapshot_sha256="9" * 64,
    )
    validate_capacity_scope_input(
        scope_input=scope_input,
        active_asset_codes=_ASSET_CODES,
        snapshot=matching_snapshot,
        typed_source_record_ids={
            _ASSET_CODES[0]: candidate.items[0].native_row_ids[0],
        },
    )
    with pytest.raises(FinancialScopeCapacityInputError) as wrong_source:
        validate_capacity_scope_input(
            scope_input=scope_input,
            active_asset_codes=_ASSET_CODES,
            snapshot=matching_snapshot,
            typed_source_record_ids={_ASSET_CODES[0]: "unrelated-native-row"},
        )
    assert wrong_source.value.code == "FINANCIAL_CAPACITY_SCOPE_TYPED_FACT_MISMATCH"

    wrong_date_snapshot = FinancialCapacityManifestSnapshot.build(
        slices=(FinancialPublicationSlice(_ASSET_CODES[0], date(2026, 8, 31)),),
        active_universe_sha256=active_sha,
        typed_source_snapshot_sha256="9" * 64,
    )
    with pytest.raises(FinancialScopeCapacityInputError) as wrong_date:
        validate_capacity_scope_input(
            scope_input=scope_input,
            active_asset_codes=_ASSET_CODES,
            snapshot=wrong_date_snapshot,
            typed_source_record_ids={
                _ASSET_CODES[0]: candidate.items[0].native_row_ids[0],
            },
        )
    assert wrong_date.value.code == "FINANCIAL_CAPACITY_SCOPE_TYPED_FACT_MISMATCH"

    contaminated = json.loads(json.dumps(report))
    contaminated["result"]["counts"]["fact_writes"] = 1
    with pytest.raises(FinancialScopeCapacityInputError) as raw_fact:
        prepare_financial_scope_manifest_pointer(
            report_payload=contaminated,
            environment="isolated",
            review_source=DjangoFinancialScopeManifestReviewSource(),
            updated_by="financial-scope-operator",
            now=_NOW,
        )
    assert raw_fact.value.code == "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"


@pytest.mark.django_db
def test_reviewed_scope_enters_existing_capacity_source_but_raw_audit_is_not_a_fact() -> None:
    """The public capacity source still blocks before checkpoint creation without typed facts."""

    from apps.data_center.infrastructure.financial_publication_capacity_runtime import (
        DjangoFinancialCapacityManifestSource,
    )

    report = _report()
    _persist_reviews(report)
    AssetMasterModel._default_manager.create(
        code=_ASSET_CODES[0],
        name="Test security",
        short_name="Test",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    pointer_source, review_source = _pointer_services()
    install_financial_scope_manifest_pointer(
        pointer_source=pointer_source,
        review_source=review_source,
        report_payload=report,
        environment="isolated",
        updated_by="financial-scope-operator",
        now=_NOW,
    )

    with pytest.raises(
        FinancialCapacityWorkflowError,
        match="typed announcement scope is incomplete",
    ):
        DjangoFinancialCapacityManifestSource().freeze(
            stage="capacity_rehearsal",
            environment="isolated",
            binding=_capacity_binding(),
        )

    assert FinancialFactModel._default_manager.count() == 0
    assert FinancialPublicationCapacityWorkflowModel._default_manager.count() == 0
