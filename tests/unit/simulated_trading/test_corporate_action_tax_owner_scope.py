from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import TracebackType

import pytest

from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
from apps.simulated_trading import (
    corporate_action_tax_liability_owner_scope_composition as liability_owner_scope,
)
from apps.simulated_trading import corporate_action_tax_owner_scope_composition as owner_scope
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentExactReplayEvidence,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    AuditedTaxAssessmentScopeVerifierPort,
    TaxAssessmentAuditOrigin,
)
from apps.simulated_trading.corporate_action_tax_liability_owner_scope_composition import (
    DjangoTaxLiabilityOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    DjangoTaxAssessmentOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _request,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment
from tests.unit.simulated_trading.test_corporate_action_window_audit_composition import (
    _evidence,
)

_NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
_TERMS_SHA = "d" * 64


def _szse_assessment() -> CorporateActionTaxAssessment:
    """Build a synthetic SZSE assessment aligned with the official-window contract."""
    base = _assessment()
    asset_code = "000001.SZ"
    history = base.history
    ownership = replace(
        history.record_date_ownership_proof,
        asset_code=asset_code,
        security_id=asset_code,
    )
    days = tuple(
        replace(row, asset_code=asset_code, security_id=asset_code)
        for row in history.settlement_days
    )
    history = replace(
        history,
        asset_code=asset_code,
        security_id=asset_code,
        record_date_ownership_proof=ownership,
        settlement_days=days,
    )
    action = replace(
        base.action,
        asset_code=asset_code,
        security_id=asset_code,
        source_namespace="exchange_official_disclosure",
        source_record_id="synthetic-szse-record-1",
        source_event_id="synthetic-szse-event-1",
        source_revision_id="synthetic-szse-revision-1",
        source_revision_sha256="c" * 64,
        source_payload_sha256="d" * 64,
        effective_date=date(2026, 11, 2),
    )
    return _assessment(action=action, history=history)


def _window_proof(
    assessment: CorporateActionTaxAssessment,
    *,
    canonical_account_id: str,
    environment: str,
    checked_at: datetime,
) -> CorporateActionTaxWindowProof:
    """Build synthetic current-window originals at one exact scope and clock."""
    action = assessment.action
    request = replace(
        _request(),
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        asset_code=action.asset_code,
        security_id=action.security_id,
        source_namespace=action.source_namespace,
        source_record_id=action.source_record_id,
        source_event_id=action.source_event_id,
        source_revision_id=action.source_revision_id,
        source_payload_sha256=action.source_payload_sha256,
        source_observed_at=checked_at - timedelta(seconds=10),
        qualified_at=checked_at - timedelta(seconds=2),
        posted_at=checked_at - timedelta(seconds=1),
        record_date=action.record_date,
        ownership_snapshot_as_of_date=action.record_date,
        ownership_snapshot_observed_at=checked_at - timedelta(seconds=20),
        effective_date=action.effective_date,
    )
    original = _evidence()
    provenance = replace(
        original.policy_provenance,
        runtime_environment=environment,
        known_at=checked_at - timedelta(days=2),
        effective_at=checked_at - timedelta(days=1),
    )
    window = replace(
        original,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        asset_code=action.asset_code,
        security_id=action.security_id,
        source_record_id=action.source_record_id,
        source_revision_id=action.source_revision_id,
        source_payload_sha256=action.source_payload_sha256,
        source_observed_at=request.source_observed_at,
        original_first_observed_at=checked_at - timedelta(seconds=9),
        original_listing_verified_at=checked_at - timedelta(seconds=8),
        original_proof_recorded_at=checked_at - timedelta(seconds=7),
        checked_at=checked_at,
        expires_at=checked_at + timedelta(seconds=60),
        runtime_environment=environment,
        selected_event_sha256=action.source_revision_sha256,
        policy_provenance=provenance,
    )
    return CorporateActionTaxWindowProof(
        assessment.semantic_sha256,
        canonical_account_id,
        request,
        window,
    )


def _ordered_capabilities(
    *values: Capability,
) -> tuple[Capability, ...]:
    return tuple(sorted(values, key=lambda value: value.value))


def _binding(assessment: CorporateActionTaxAssessment) -> SimulatedCorporateActionWriteGrantBinding:
    return SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id="canonical-simulated-account-17",
        owner_user_id=assessment.owner_user_id,
        tenant_id="synthetic-tenant-v1",
        owner_id=f"synthetic-owner-{assessment.owner_user_id}",
        account_source_id="synthetic-account-source",
        account_source_version="source-v1",
        account_source_content_hash="a" * 64,
        policy_id="synthetic-write-policy",
        policy_version="policy-v1",
        policy_content_hash="b" * 64,
    )


def _grant(
    assessment: CorporateActionTaxAssessment,
    *,
    schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    capabilities: tuple[Capability, ...] | None = (Capability.TAX_ASSESS,),
    valid_until: datetime = _NOW + timedelta(minutes=7),
    terms_version: str | None = "synthetic-terms-v2",
    terms_sha256: str | None = _TERMS_SHA,
) -> SimulatedCorporateActionWriteGrant:
    is_v2 = schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    is_v3 = schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    is_versioned = is_v2 or is_v3
    return SimulatedCorporateActionWriteGrant(
        grant_id="synthetic-current-grant",
        grant_version="grant-v2",
        binding=_binding(assessment),
        consent_evidence_id="synthetic-consent",
        consent_evidence_version="v2",
        consent_evidence_hash="c" * 64,
        issuer_evidence_id="synthetic-issuer",
        issuer_evidence_version="v2",
        issuer_evidence_hash="e" * 64,
        consented_at=_NOW - timedelta(minutes=2),
        issued_at=_NOW - timedelta(minutes=1),
        recorded_at=_NOW - timedelta(minutes=1),
        valid_until=valid_until,
        permission=(
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
            if is_v2
            else (
                SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
                if is_v3
                else SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
            )
        ),
        service_actor_id=SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
        schema=schema,
        capabilities=capabilities if is_versioned else None,
        terms_version=terms_version if is_versioned else None,
        terms_sha256=terms_sha256 if is_versioned else None,
    )


def _locked_scope(
    assessment: CorporateActionTaxAssessment,
    grant: SimulatedCorporateActionWriteGrant,
    *,
    grant_schema: str | None = None,
    capabilities: tuple[Capability, ...] | None = None,
    terms_version: str | None = None,
    terms_sha256: str | None = None,
    physical_account_id: int | None = None,
    valid_until: datetime = _NOW + timedelta(minutes=9),
) -> LockedSimulatedCorporateActionWriteScope:
    selected_schema = grant.schema if grant_schema is None else grant_schema
    selected_capabilities = capabilities
    if (
        selected_capabilities is None
        and selected_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    ):
        selected_capabilities = _ordered_capabilities(
            Capability.CASH_STAGE_WRITE, Capability.TAX_ASSESS
        )
    elif (
        selected_capabilities is None
        and selected_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    ):
        selected_capabilities = (Capability.TAX_ASSESS,)
    return LockedSimulatedCorporateActionWriteScope(
        physical_account_id=(
            assessment.account_id if physical_account_id is None else physical_account_id
        ),
        binding=grant.binding,
        valid_until=valid_until,
        grant_schema=selected_schema,
        capabilities=selected_capabilities,
        terms_version=grant.terms_version if terms_version is None else terms_version,
        terms_sha256=grant.terms_sha256 if terms_sha256 is None else terms_sha256,
    )


def _qualification(
    assessment: CorporateActionTaxAssessment,
    *,
    grant: SimulatedCorporateActionWriteGrant,
    environment: str = "development",
    valid_until: datetime = _NOW + timedelta(minutes=5),
    qualification_id: str = "synthetic-qualification-v1",
    qualification_sha256: str = "f" * 64,
) -> CurrentTaxAssessmentQualification:
    return CurrentTaxAssessmentQualification(
        assessment_semantic_sha256=assessment.semantic_sha256,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        canonical_account_id=grant.binding.account_id,
        environment=environment,
        qualification_id=qualification_id,
        qualification_sha256=qualification_sha256,
        runtime_profile_id="synthetic-runtime-profile",
        runtime_profile_content_sha256="1" * 64,
        runtime_snapshot_id="synthetic-runtime-snapshot",
        runtime_snapshot_sha256="2" * 64,
        valid_until=valid_until,
    )


def _replay_evidence(
    assessment: CorporateActionTaxAssessment,
    *,
    grant: SimulatedCorporateActionWriteGrant,
    proof: CorporateActionTaxWindowProof | None = None,
) -> TaxAssessmentExactReplayEvidence:
    """Build immutable original-row/Audit references for controlled replay tests."""
    digest = "a" * 64
    return TaxAssessmentExactReplayEvidence(
        assessment_revision_id=assessment.assessment_revision_id,
        idempotency_key=assessment.calculation.idempotency_key,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
        recorded_at=(
            proof.evidence.checked_at + timedelta(seconds=1)
            if proof is not None
            else _NOW - timedelta(seconds=30)
        ),
        audit_scope=AuditScopeRef(grant.binding.tenant_id, grant.binding.owner_id),
        audit_event_id="synthetic-assessment-audit-event",
        audit_content_sha256=digest,
        outbox_id="synthetic-assessment-outbox-row",
        outbox_payload_sha256=digest,
        official_window_proof=proof,
    )


class _ReplayProbe:
    """Controlled complete-replay result source for owner-scope behavior tests."""

    def __init__(self, results: tuple[object, ...]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def find_exact_replay(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        audit_scope: AuditScopeRef,
        as_of: datetime,
    ) -> TaxAssessmentExactReplayEvidence | None:
        self.calls.append(
            {
                "assessment": assessment,
                "actor_user_id": actor_user_id,
                "audit_scope": audit_scope,
                "as_of": as_of,
            }
        )
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


class _QualificationProvider:
    def __init__(self, results: tuple[object, ...]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def read_current(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
        using: str,
        as_of: datetime,
    ) -> CurrentTaxAssessmentQualification:
        self.calls.append(
            {
                "assessment": assessment,
                "canonical_account_id": canonical_account_id,
                "environment": environment,
                "using": using,
                "as_of": as_of,
            }
        )
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def execute(self, statement: str) -> None:
        assert statement == "SHOW transaction_isolation"

    def fetchone(self) -> tuple[str, ...]:
        return ("read committed",)


class _PostgreSQLConnection:
    vendor = "postgresql"
    in_atomic_block = True

    def get_autocommit(self) -> bool:
        return False

    def cursor(self) -> _Cursor:
        return _Cursor()


class _Connections:
    def __getitem__(self, using: str) -> _PostgreSQLConnection:
        assert using
        return _PostgreSQLConnection()


def _harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    assessment: CorporateActionTaxAssessment | None = None,
    grant: SimulatedCorporateActionWriteGrant | None = None,
    locked_scope: LockedSimulatedCorporateActionWriteScope | None = None,
    qualification_results: tuple[object, ...] | None = None,
    grant_results: tuple[object, ...] | None = None,
    audit_results: tuple[SystemAuditAuthorityLease | object, ...] | None = None,
    clock_values: tuple[datetime, ...] = (_NOW,),
    expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
) -> tuple[DjangoTaxAssessmentOwnerScopeVerifier, CorporateActionTaxAssessment, dict[str, object]]:
    selected_assessment = _assessment() if assessment is None else assessment
    selected_grant = _grant(selected_assessment) if grant is None else grant
    selected_scope = (
        _locked_scope(selected_assessment, selected_grant) if locked_scope is None else locked_scope
    )
    selected_qualification = _qualification(selected_assessment, grant=selected_grant)
    qualification_provider = _QualificationProvider(
        (selected_qualification,) if qualification_results is None else qualification_results
    )
    grant_responses = (selected_grant, selected_grant) if grant_results is None else grant_results
    audit_responses = (
        (
            SystemAuditAuthorityLease(
                mode="required",
                outbox_enabled=True,
                valid_until=_NOW + timedelta(minutes=8),
            ),
        )
        if audit_results is None
        else audit_results
    )
    calls: dict[str, object] = {
        "eligibility": [],
        "scope": [],
        "grant": [],
        "audit": [],
        "selected_grant": selected_grant,
    }

    @contextmanager
    def eligibility(*, user_id: int, using: str) -> Iterator[None]:
        cast_list = calls["eligibility"]
        assert isinstance(cast_list, list)
        cast_list.append((user_id, using))
        yield

    @contextmanager
    def lock_scope(
        locker: DjangoSimulatedCorporateActionWriteScopeLocker,
        *,
        physical_account_id: int,
        owner_user_id: int,
        expected_binding: SimulatedCorporateActionWriteGrantBinding,
        request: object,
        expected_grant_schema: str,
    ) -> Iterator[LockedSimulatedCorporateActionWriteScope]:
        assert locker.database_alias == "default"
        calls["scope"].append(
            {
                "physical_account_id": physical_account_id,
                "owner_user_id": owner_user_id,
                "expected_binding": expected_binding,
                "request": request,
                "expected_grant_schema": expected_grant_schema,
            }
        )
        yield selected_scope

    def current_grant(*, selector: object, using: str, required_capability: Capability) -> object:
        assert selector == selected_grant.selector
        assert using == "default"
        assert required_capability is Capability.TAX_ASSESS
        calls["grant"].append((selector, using, required_capability))
        result = grant_responses[min(len(calls["grant"]) - 1, len(grant_responses) - 1)]

        @contextmanager
        def active_grant() -> Iterator[SimulatedCorporateActionWriteGrant]:
            if isinstance(result, BaseException):
                raise result
            yield result  # type: ignore[misc]

        return active_grant()

    def audit_readiness(*, environment: str, using: str) -> object:
        assert environment == "development"
        assert using == "default"
        calls["audit"].append((environment, using))
        return audit_responses[min(len(calls["audit"]) - 1, len(audit_responses) - 1)]

    clock_iter = iter(clock_values)

    def now() -> datetime:
        try:
            return next(clock_iter)
        except StopIteration:
            return clock_values[-1]

    monkeypatch.setattr(owner_scope, "connections", _Connections())
    monkeypatch.setattr(owner_scope, "locked_simulated_action_trading_eligibility", eligibility)
    monkeypatch.setattr(
        owner_scope, "locked_current_simulated_corporate_action_write_grant", current_grant
    )
    monkeypatch.setattr(owner_scope, "read_system_audit_runtime_readiness", audit_readiness)
    monkeypatch.setattr(owner_scope.timezone, "now", now)
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteScopeLocker, "lock_owned_scope", lock_scope
    )
    verifier = DjangoTaxAssessmentOwnerScopeVerifier(
        selector=selected_grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default", runtime_environment="development"
        ),
        qualification_provider=qualification_provider,
        using="default",
        environment="development",
        expected_grant_schema=expected_grant_schema,
    )
    calls["qualification_provider"] = qualification_provider
    return verifier, selected_assessment, calls


def test_owner_tax_assessment_requires_explicit_v2_tax_capability_and_yields_exact_audit_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier, assessment, calls = _harness(monkeypatch)
    assert isinstance(verifier, AuditedTaxAssessmentScopeVerifierPort)

    with verifier.locked_current_scope(
        assessment,
        actor_user_id=assessment.owner_user_id,
        using="default",
    ) as lease:
        origin = verifier.get_locked_audit_origin()
        assert type(origin) is TaxAssessmentAuditOrigin
        assert lease.authority_grant_id == "synthetic-current-grant"
        assert lease.permission == Capability.TAX_ASSESS.value
        assert lease.valid_until == _NOW + timedelta(minutes=5)
        assert origin.lease is lease
        assert origin.scope == AuditScopeRef(
            "synthetic-tenant-v1", f"synthetic-owner-{assessment.owner_user_id}"
        )
        selected_grant = calls["selected_grant"]
        assert type(selected_grant) is SimulatedCorporateActionWriteGrant
        assert origin.grant_content_sha256 == selected_grant.content_hash
        assert origin.write_policy is AuditWritePolicy.TRANSACTIONAL_OUTBOX
        provider = calls["qualification_provider"]
        assert isinstance(provider, _QualificationProvider)
        other_verifier = DjangoTaxAssessmentOwnerScopeVerifier(
            selector=selected_grant.selector,
            scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                database_alias="default", runtime_environment="development"
            ),
            qualification_provider=provider,
            using="default",
            environment="development",
        )
        with pytest.raises(BusinessLogicError):
            other_verifier.get_locked_audit_origin()
        with pytest.raises(BusinessLogicError):
            with verifier.locked_current_scope(
                assessment,
                actor_user_id=assessment.owner_user_id,
                using="default",
            ):
                pass

    scope_calls = calls["scope"]
    assert isinstance(scope_calls, list)
    assert scope_calls[0]["request"] is None
    assert (
        scope_calls[0]["expected_grant_schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    )
    grant_calls = calls["grant"]
    audit_calls = calls["audit"]
    assert isinstance(grant_calls, list) and len(grant_calls) == 2
    assert isinstance(audit_calls, list) and len(audit_calls) == 2
    provider = calls["qualification_provider"]
    assert isinstance(provider, _QualificationProvider)
    assert len(provider.calls) == 2
    with pytest.raises(BusinessLogicError):
        verifier.get_locked_audit_origin()


def test_complete_exact_replay_skips_current_qualification_but_rechecks_live_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _szse_assessment()
    grant = _grant(assessment)
    proof = _window_proof(
        assessment,
        canonical_account_id=grant.binding.account_id,
        environment="development",
        checked_at=_NOW - timedelta(seconds=2),
    )
    evidence = _replay_evidence(assessment, grant=grant, proof=proof)
    verifier, _, calls = _harness(monkeypatch, assessment=assessment, grant=grant)
    probe = _ReplayProbe((evidence, evidence))

    with verifier.locked_current_scope(
        assessment,
        actor_user_id=assessment.owner_user_id,
        using="default",
        replay_probe=probe,
    ) as lease:
        origin = verifier.get_locked_audit_origin()
        assert origin.write_mode == "exact_retry_only"
        assert origin.replay_evidence == evidence
        assert lease.valid_until == _NOW + timedelta(minutes=7)

    provider = calls["qualification_provider"]
    assert isinstance(provider, _QualificationProvider)
    assert provider.calls == []
    assert len(probe.calls) == 2
    assert len(calls["grant"]) == 2
    assert len(calls["audit"]) == 2


def test_exact_replay_rechecks_original_evidence_and_current_grant_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _szse_assessment()
    grant = _grant(assessment)
    proof = _window_proof(
        assessment,
        canonical_account_id=grant.binding.account_id,
        environment="development",
        checked_at=_NOW - timedelta(seconds=2),
    )
    evidence = _replay_evidence(assessment, grant=grant, proof=proof)
    changed = replace(
        evidence,
        audit_content_sha256="b" * 64,
        outbox_payload_sha256="b" * 64,
    )
    verifier, _, calls = _harness(monkeypatch, assessment=assessment, grant=grant)
    probe = _ReplayProbe((evidence, changed))

    with pytest.raises(BusinessLogicError, match="changed before transaction exit"):
        with verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
            replay_probe=probe,
        ):
            verifier.get_locked_audit_origin()

    provider = calls["qualification_provider"]
    assert isinstance(provider, _QualificationProvider)
    assert provider.calls == []
    assert len(probe.calls) == 2

    verifier2, _, calls2 = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        grant_results=(grant, BusinessLogicError("current grant was revoked")),
    )
    with pytest.raises(BusinessLogicError, match="revoked"):
        with verifier2.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
            replay_probe=_ReplayProbe((evidence, evidence)),
        ):
            verifier2.get_locked_audit_origin()
    provider2 = calls2["qualification_provider"]
    assert isinstance(provider2, _QualificationProvider)
    assert provider2.calls == []


def test_legacy_exact_replay_without_window_proof_runs_current_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    evidence = _replay_evidence(assessment, grant=grant)
    verifier, _, calls = _harness(monkeypatch, assessment=assessment, grant=grant)

    with verifier.locked_current_scope(
        assessment,
        actor_user_id=assessment.owner_user_id,
        using="default",
        replay_probe=_ReplayProbe((evidence, evidence)),
    ) as lease:
        origin = verifier.get_locked_audit_origin()
        assert origin.write_mode == "append"
        assert origin.replay_evidence is None
        assert lease.valid_until == _NOW + timedelta(minutes=5)

    provider = calls["qualification_provider"]
    assert isinstance(provider, _QualificationProvider)
    assert len(provider.calls) == 2


def test_owner_tax_assessment_uses_explicit_v3_scope_and_tax_assess_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    capabilities = (Capability.TAX_ASSESS,)
    grant = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=capabilities,
    )
    verifier, _, calls = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        locked_scope=_locked_scope(assessment, grant, capabilities=capabilities),
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )

    with verifier.locked_current_scope(
        assessment,
        actor_user_id=assessment.owner_user_id,
        using="default",
    ) as lease:
        assert lease.permission == Capability.TAX_ASSESS.value
        assert verifier.get_locked_audit_origin().grant_content_sha256 == grant.content_hash

    scope_calls = calls["scope"]
    assert isinstance(scope_calls, list)
    assert (
        scope_calls[0]["expected_grant_schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    )
    grant_calls = calls["grant"]
    assert isinstance(grant_calls, list) and len(grant_calls) == 2


def test_owner_tax_assessment_does_not_infer_v3_selection_or_tax_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    v3_share_only = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=(Capability.SHARE_STAGE_WRITE,),
    )
    verifier, _, calls = _harness(
        monkeypatch,
        assessment=assessment,
        grant=v3_share_only,
        locked_scope=_locked_scope(
            assessment, v3_share_only, capabilities=(Capability.SHARE_STAGE_WRITE,)
        ),
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
        ):
            pass
    assert calls["grant"] == []

    v2 = _grant(assessment)
    v3_selected_verifier, _, v2_calls = _harness(
        monkeypatch,
        assessment=assessment,
        grant=v2,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    with pytest.raises(BusinessLogicError):
        with v3_selected_verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
        ):
            pass
    assert v2_calls["grant"] == []

    v3 = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=(Capability.TAX_ASSESS,),
    )
    wrong_terms_scope = _locked_scope(
        assessment,
        v3,
        capabilities=(Capability.TAX_ASSESS,),
        terms_sha256="f" * 64,
    )
    terms_verifier, _, terms_calls = _harness(
        monkeypatch,
        assessment=assessment,
        grant=v3,
        locked_scope=wrong_terms_scope,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    with pytest.raises(BusinessLogicError):
        with terms_verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
        ):
            pass
    term_grant_calls = terms_calls["grant"]
    qualification_provider = terms_calls["qualification_provider"]
    assert isinstance(term_grant_calls, list) and len(term_grant_calls) == 1
    assert isinstance(qualification_provider, _QualificationProvider)
    assert qualification_provider.calls == []


def test_tax_scope_verifiers_reject_v1_as_an_expected_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(BusinessLogicError):
        _harness(monkeypatch, expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA)


def test_v3_liability_grant_requires_matching_schema_and_tax_withhold_capability() -> None:
    assessment = _assessment()
    capabilities = (Capability.TAX_WITHHOLD,)
    grant = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=capabilities,
    )
    scope = _locked_scope(assessment, grant, capabilities=capabilities)

    liability_owner_scope._verify_grant(
        scope=scope,
        grant=grant,
        selector=grant.selector,
        assessment=assessment,
        as_of=_NOW,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    with pytest.raises(BusinessLogicError):
        liability_owner_scope._verify_grant(
            scope=scope,
            grant=grant,
            selector=grant.selector,
            assessment=assessment,
            as_of=_NOW,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        )

    v3_share_only = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=(Capability.SHARE_STAGE_WRITE,),
    )
    with pytest.raises(BusinessLogicError):
        liability_owner_scope._verify_grant(
            scope=_locked_scope(
                assessment, v3_share_only, capabilities=(Capability.SHARE_STAGE_WRITE,)
            ),
            grant=v3_share_only,
            selector=v3_share_only.selector,
            assessment=assessment,
            as_of=_NOW,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        )

    wrong_terms_scope = _locked_scope(
        assessment,
        grant,
        capabilities=capabilities,
        terms_sha256="f" * 64,
    )
    with pytest.raises(BusinessLogicError):
        liability_owner_scope._verify_grant(
            scope=wrong_terms_scope,
            grant=grant,
            selector=grant.selector,
            assessment=assessment,
            as_of=_NOW,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        )


@pytest.mark.parametrize(
    "expected_grant_schema",
    (
        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    ),
)
def test_tax_liability_verifier_passes_selected_schema_to_account_locker(
    monkeypatch: pytest.MonkeyPatch,
    expected_grant_schema: str,
) -> None:
    assessment = _assessment()
    selected_grant = _grant(assessment)
    provider = _QualificationProvider((_qualification(assessment, grant=selected_grant),))

    class _Audit:
        database_alias = "default"

    locker = DjangoSimulatedCorporateActionWriteScopeLocker(
        database_alias="default", runtime_environment="development"
    )
    if expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA:
        verifier = DjangoTaxLiabilityOwnerScopeVerifier(
            selector=selected_grant.selector,
            scope_locker=locker,
            qualification_provider=provider,
            audit=_Audit(),
            using="default",
            environment="development",
            expected_grant_schema=expected_grant_schema,
        )
    else:
        verifier = DjangoTaxLiabilityOwnerScopeVerifier(
            selector=selected_grant.selector,
            scope_locker=locker,
            qualification_provider=provider,
            audit=_Audit(),
            using="default",
            environment="development",
        )
    requested_schemas: list[str] = []

    class _StopAtScope(Exception):
        pass

    @contextmanager
    def eligibility(*, user_id: int, using: str) -> Iterator[None]:
        assert user_id == assessment.owner_user_id
        assert using == "default"
        yield

    def stop_at_scope(
        selected_locker: DjangoSimulatedCorporateActionWriteScopeLocker,
        **kwargs: object,
    ) -> object:
        assert selected_locker is locker
        requested_schemas.append(str(kwargs["expected_grant_schema"]))
        raise _StopAtScope

    monkeypatch.setattr(liability_owner_scope, "_require_outer_read_committed", lambda **_: None)
    monkeypatch.setattr(
        liability_owner_scope, "locked_simulated_action_trading_eligibility", eligibility
    )
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteScopeLocker, "lock_owned_scope", stop_at_scope
    )
    with pytest.raises(_StopAtScope):
        with verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
            operation_id="v3-selection-probe-v1",
            cash_action=None,
        ):
            pass

    assert requested_schemas == [expected_grant_schema]


def test_tax_liability_verifier_rejects_v1_schema_selection() -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    provider = _QualificationProvider((_qualification(assessment, grant=grant),))

    class _Audit:
        database_alias = "default"

    with pytest.raises(BusinessLogicError):
        DjangoTaxLiabilityOwnerScopeVerifier(
            selector=grant.selector,
            scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                database_alias="default", runtime_environment="development"
            ),
            qualification_provider=provider,
            audit=_Audit(),
            using="default",
            environment="development",
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
        )


def test_grant_cannot_outlive_its_locked_owner_policy_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment, valid_until=_NOW + timedelta(minutes=7))
    locked_scope = _locked_scope(
        assessment,
        grant,
        valid_until=_NOW + timedelta(minutes=5),
    )
    verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        locked_scope=locked_scope,
    )

    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment,
            actor_user_id=assessment.owner_user_id,
            using="default",
        ):
            pass


def test_grant_service_namespace_is_distinct_from_canonical_account_identity() -> None:
    assessment = _assessment()
    binding = _binding(assessment)
    assert binding.account_namespace == "simulated"
    assert binding.account_id == "canonical-simulated-account-17"

    with pytest.raises(ValueError):
        replace(binding, account_namespace="account")


def test_legacy_v1_and_cash_only_v2_grants_cannot_qualify_tax_assessment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    v1 = _grant(
        assessment,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
        capabilities=None,
        terms_version=None,
        terms_sha256=None,
    )
    v1_verifier, _, v1_calls = _harness(
        monkeypatch,
        assessment=assessment,
        grant=v1,
        locked_scope=_locked_scope(
            assessment,
            v1,
            grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
            capabilities=None,
            terms_version=None,
            terms_sha256=None,
        ),
    )
    with pytest.raises(BusinessLogicError):
        with v1_verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass
    assert v1_calls["grant"] == []

    cash = _grant(assessment, capabilities=(Capability.CASH_STAGE_WRITE,))
    cash_verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=cash,
        locked_scope=_locked_scope(assessment, cash),
    )
    with pytest.raises(BusinessLogicError):
        with cash_verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass

    withholding = _grant(assessment, capabilities=(Capability.TAX_WITHHOLD,))
    withholding_verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=withholding,
        locked_scope=_locked_scope(
            assessment,
            withholding,
            capabilities=_ordered_capabilities(Capability.TAX_ASSESS, Capability.TAX_WITHHOLD),
        ),
    )
    with pytest.raises(BusinessLogicError):
        with withholding_verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass


@pytest.mark.parametrize("mismatch", ["owner", "alias", "terms", "physical"])
def test_wrong_owner_alias_terms_or_physical_scope_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    locked_scope = _locked_scope(
        assessment,
        grant,
        terms_version=("another-terms-v2" if mismatch == "terms" else None),
        physical_account_id=(assessment.account_id + 1 if mismatch == "physical" else None),
    )
    verifier, _, _ = _harness(
        monkeypatch, assessment=assessment, grant=grant, locked_scope=locked_scope
    )
    actor = assessment.owner_user_id + 1 if mismatch == "owner" else assessment.owner_user_id
    using = "other" if mismatch == "alias" else "default"

    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(assessment, actor_user_id=actor, using=using):
            pass


@pytest.mark.parametrize(
    "failure",
    [
        "expired_qualification",
        "missing_audit",
        "changed_qualification",
        "revoked_grant",
        "audit_lost_on_exit",
        "expired_before_exit",
    ],
)
def test_qualification_grant_audit_and_deadlines_are_rechecked_on_context_exit(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    qualification = _qualification(assessment, grant=grant)
    qualifications: tuple[object, ...] = (qualification, qualification)
    grants: tuple[object, ...] = (grant, grant)
    audits: tuple[SystemAuditAuthorityLease | object, ...] = (
        SystemAuditAuthorityLease(
            mode="required", outbox_enabled=True, valid_until=_NOW + timedelta(minutes=8)
        ),
    )
    clocks = (_NOW,)

    if failure == "expired_qualification":
        qualifications = (_qualification(assessment, grant=grant, valid_until=_NOW),)
    elif failure == "missing_audit":
        audits = (None,)
    elif failure == "changed_qualification":
        qualifications = (
            qualification,
            _qualification(
                assessment,
                grant=grant,
                qualification_id="changed-qualification-v2",
                qualification_sha256="9" * 64,
            ),
        )
    elif failure == "revoked_grant":
        grants = (grant, BusinessLogicError("grant was revoked"))
    elif failure == "audit_lost_on_exit":
        audits = (
            SystemAuditAuthorityLease(
                mode="required", outbox_enabled=True, valid_until=_NOW + timedelta(minutes=8)
            ),
            SystemAuditAuthorityLease(
                mode="off", outbox_enabled=False, valid_until=_NOW + timedelta(minutes=8)
            ),
        )
    elif failure == "expired_before_exit":
        qualification = _qualification(
            assessment, grant=grant, valid_until=_NOW + timedelta(minutes=15)
        )
        qualifications = (qualification, qualification)
        audits = (
            SystemAuditAuthorityLease(
                mode="required", outbox_enabled=True, valid_until=_NOW + timedelta(minutes=10)
            ),
        )
        clocks = (
            _NOW,
            _NOW,
            _NOW + timedelta(minutes=8),
            _NOW + timedelta(minutes=8),
            _NOW + timedelta(minutes=8),
        )

    verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        qualification_results=qualifications,
        grant_results=grants,
        audit_results=audits,
        clock_values=clocks,
    )
    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            assert verifier.get_locked_audit_origin().lease.authority_grant_id == grant.grant_id

    with pytest.raises(BusinessLogicError):
        verifier.get_locked_audit_origin()


def test_qualification_result_binds_complete_assessment_owner_and_runtime_scope() -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    qualification = _qualification(assessment, grant=grant)
    qualification.verify_for(
        assessment,
        canonical_account_id=grant.binding.account_id,
        environment="development",
        as_of=_NOW,
    )

    with pytest.raises(BusinessLogicError):
        qualification.verify_for(
            assessment,
            canonical_account_id="another-canonical-account",
            environment="development",
            as_of=_NOW,
        )
    with pytest.raises(BusinessLogicError):
        qualification.verify_for(
            assessment,
            canonical_account_id=grant.binding.account_id,
            environment="production",
            as_of=_NOW,
        )


@pytest.mark.parametrize(
    "mismatch",
    [
        "account_id",
        "owner_user_id",
        "assessment_semantic_sha256",
        "canonical_account_id",
        "environment",
    ],
)
def test_provider_must_return_typed_qualification_for_exact_assessment_scope(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    qualified = _qualification(assessment, grant=grant)
    values: dict[str, object] = {
        "account_id": assessment.account_id + 1,
        "owner_user_id": assessment.owner_user_id + 1,
        "assessment_semantic_sha256": "9" * 64,
        "canonical_account_id": "another-canonical-account",
        "environment": "production",
    }
    changed_qualification = replace(qualified, **{mismatch: values[mismatch]})
    verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        qualification_results=(changed_qualification,),
    )

    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass


def test_boolean_or_other_untyped_qualifier_cannot_authorize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        qualification_results=(True,),
    )

    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass


@pytest.mark.parametrize(
    "clock_values",
    [
        (_NOW.replace(tzinfo=None),),
        (_NOW, _NOW - timedelta(seconds=1)),
        (_NOW, _NOW, _NOW - timedelta(seconds=1)),
    ],
)
def test_scope_clock_must_be_aware_and_nondecreasing(
    monkeypatch: pytest.MonkeyPatch,
    clock_values: tuple[datetime, ...],
) -> None:
    assessment = _assessment()
    grant = _grant(assessment)
    verifier, _, _ = _harness(
        monkeypatch,
        assessment=assessment,
        grant=grant,
        clock_values=clock_values,
    )

    with pytest.raises(BusinessLogicError):
        with verifier.locked_current_scope(
            assessment, actor_user_id=assessment.owner_user_id, using="default"
        ):
            pass
