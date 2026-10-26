"""Pure Application tests for policy publication, reads, overlap, and revocation."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
    M1RiskPolicyIdempotencyConflictError,
    M1RiskPolicyIdempotencyContext,
    M1RiskPolicyNotFoundError,
    M1RiskPolicyOperation,
    M1RiskPolicySourceCorruptError,
    M1RiskPolicyValidationError,
    PublishM1RiskPolicyRevisionUseCase,
    RevokeM1RiskPolicyRevisionUseCase,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RiskApplicability,
    RiskQualificationState,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    build_m1_risk_policy_idempotency_context,
)

KNOWN_AT = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
START = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
END = datetime(2026, 12, 31, 0, 0, tzinfo=UTC)


def _idempotency(
    *,
    actor_user_id: int = 79,
    operation: M1RiskPolicyOperation = "publish",
    key: str = "owner-submit-1",
    request_body: str = "same explicit owner payload",
) -> M1RiskPolicyIdempotencyContext:
    """Build a typed transport identity for a pure Application test."""

    identity = hashlib.sha256(f"901:{actor_user_id}:{operation}:{key}".encode()).hexdigest()
    request_hash = hashlib.sha256(request_body.encode("utf-8")).hexdigest()
    return M1RiskPolicyIdempotencyContext(
        account_id=901,
        actor_user_id=actor_user_id,
        operation=operation,
        identity_sha256=identity,
        request_sha256=request_hash,
    )


def _source() -> M1RiskSourceSnapshot:
    """Return one exact current manual-account source snapshot."""

    return M1RiskSourceSnapshot(
        account_id=901,
        account_owner_user_id=79,
        account_type="simulated",
        account_is_active=True,
        account_max_single_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=Decimal("8"),
        strategy_selection_state="confirmed_unconfigured",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )


def _command() -> M1RiskPolicyPublishCommand:
    """Return a typed, explicit owner command with tighter known limits."""

    return M1RiskPolicyPublishCommand(
        account_id=901,
        actor_user_id=79,
        effective_from=START,
        effective_until=END,
        reason="Owner-approved M1 policy.",
        max_single_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("7")),
        source_snapshot=_source(),
    )


def _revision(
    *,
    source: M1RiskSourceSnapshot | None = None,
    start: datetime = START,
    end: datetime = END,
    revoked_at: datetime | None = None,
    revoked_by_user_id: int | None = None,
    revocation_reason: str | None = None,
) -> M1RiskPolicyRevision:
    """Return the exact immutable policy fixture consumed by reader tests."""

    selected_source = source or _source()
    revocation_state = (
        "unknown"
        if revoked_at is not None and revoked_by_user_id is None
        else ("revoked" if revoked_at is not None else "not_revoked")
    )
    return M1RiskPolicyRevision(
        risk_policy_version="7b5eaf53-990a-4ceb-b0ef-8b7fe13bad85",
        account_id=selected_source.account_id,
        actor_user_id=79,
        effective_from=start,
        effective_until=end,
        known_at=KNOWN_AT,
        reason="Owner-approved M1 policy.",
        max_single_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("7")),
        source_snapshot=selected_source,
        revocation_state=revocation_state,
        revoked_at=revoked_at,
        revoked_by_user_id=revoked_by_user_id,
        revocation_reason=revocation_reason,
    )


class InMemoryM1RiskPolicyRepository:
    """Minimal typed fake for tests that exercise Application orchestration only."""

    def __init__(self, revisions: tuple[M1RiskPolicyRevision, ...] = ()) -> None:
        """Keep immutable revisions in memory and capture revocation commands."""

        self.revisions = list(revisions)
        self.created_commands: list[M1RiskPolicyPublishCommand] = []
        self.revocations: list[tuple[int, str, int, str]] = []
        self.idempotency_results: dict[str, M1RiskPolicyRevision] = {}
        self.idempotency_request_hashes: dict[str, str] = {}

    def find_revision_by_idempotency(
        self,
        *,
        context: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision | None:
        """Replay only an exact prior body for this test identity."""

        prior_hash = self.idempotency_request_hashes.get(context.identity_sha256)
        if prior_hash is not None and prior_hash != context.request_sha256:
            raise M1RiskPolicyIdempotencyConflictError("changed body")
        return self.idempotency_results.get(context.identity_sha256)

    def create_revision(
        self,
        command: M1RiskPolicyPublishCommand,
        *,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Return one new immutable owner decision without inventing source values."""

        self.created_commands.append(command)
        revision = _revision(source=command.source_snapshot)
        self.revisions.append(revision)
        self.idempotency_results[idempotency.identity_sha256] = revision
        self.idempotency_request_hashes[idempotency.identity_sha256] = idempotency.request_sha256
        return revision

    def list_revisions(self, *, account_id: int) -> tuple[M1RiskPolicyRevision, ...]:
        """Return only revisions scoped to the requested account identity."""

        return tuple(item for item in self.revisions if item.account_id == account_id)

    def revoke_revision(
        self,
        *,
        account_id: int,
        risk_policy_version: str,
        actor_user_id: int,
        reason: str,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Append an in-memory audit state while leaving the stored revision intact."""

        self.revocations.append((account_id, risk_policy_version, actor_user_id, reason))
        for revision in self.revisions:
            if (
                revision.account_id == account_id
                and revision.risk_policy_version == risk_policy_version
            ):
                return replace(
                    revision,
                    revocation_state="revoked",
                    revoked_at=START + timedelta(days=1),
                    revoked_by_user_id=actor_user_id,
                    revocation_reason=reason,
                )
        raise M1RiskPolicyNotFoundError("version not found")


def test_publish_use_case_preserves_owner_command_and_rejects_widening() -> None:
    """Publishing is a typed explicit decision, not a fill-in of legacy NULLs."""

    repository = InMemoryM1RiskPolicyRepository()
    use_case = PublishM1RiskPolicyRevisionUseCase(repository)

    revision = use_case.execute(command=_command(), idempotency=_idempotency())

    assert revision.actor_user_id == 79
    assert revision.risk_policy_version == "7b5eaf53-990a-4ceb-b0ef-8b7fe13bad85"
    assert revision.source_snapshot.account_stop_loss_pct == Decimal("8")
    assert repository.created_commands == [_command()]


def test_publish_use_case_rejects_known_limit_widening() -> None:
    """The Application never stores a new cap looser than a known current cap."""

    repository = InMemoryM1RiskPolicyRepository()
    command = replace(
        _command(),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("96")),
    )

    try:
        PublishM1RiskPolicyRevisionUseCase(repository).execute(
            command=command,
            idempotency=_idempotency(request_body="widened total cap"),
        )
    except M1RiskPolicyValidationError as exc:
        assert exc.reason_codes == ("M1_POLICY_WIDENS_MAX_TOTAL_POSITION_LIMIT",)
    else:
        raise AssertionError("widened risk limit should be rejected")
    assert repository.created_commands == []


def test_publish_use_case_rejects_retry_identity_from_another_owner_scope() -> None:
    """A valid digest cannot be attached to another account/actor/operation command."""

    repository = InMemoryM1RiskPolicyRepository()
    command = replace(_command(), actor_user_id=80)

    try:
        PublishM1RiskPolicyRevisionUseCase(repository).execute(
            command=command,
            idempotency=_idempotency(actor_user_id=79),
        )
    except M1RiskPolicyValidationError as exc:
        assert exc.reason_codes == ("M1_RISK_POLICY_IDEMPOTENCY_SCOPE_MISMATCH",)
    else:
        raise AssertionError("retry identity from another actor must be rejected")
    assert repository.created_commands == []


def test_transport_idempotency_scope_binds_owner_account_operation_and_body() -> None:
    """One header key cannot alias another owner, account, operation, or payload."""

    body = {"reason": "The owner reviewed this M1 policy."}
    original = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=79,
        operation="publish",
        idempotency_key="same-key",
        request_payload=body,
    )
    other_owner = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=80,
        operation="publish",
        idempotency_key="same-key",
        request_payload=body,
    )
    other_account = build_m1_risk_policy_idempotency_context(
        account_id=902,
        actor_user_id=79,
        operation="publish",
        idempotency_key="same-key",
        request_payload=body,
    )
    other_operation = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=79,
        operation="revoke",
        idempotency_key="same-key",
        request_payload=body,
    )
    changed_body = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=79,
        operation="publish",
        idempotency_key="same-key",
        request_payload={"reason": "Changed owner request."},
    )
    revoke_one_target = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=79,
        operation="revoke",
        idempotency_key="same-key",
        request_payload=body,
        resource_id="version-one",
    )
    revoke_other_target = build_m1_risk_policy_idempotency_context(
        account_id=901,
        actor_user_id=79,
        operation="revoke",
        idempotency_key="same-key",
        request_payload=body,
        resource_id="version-two",
    )

    assert other_owner.identity_sha256 != original.identity_sha256
    assert other_account.identity_sha256 != original.identity_sha256
    assert other_operation.identity_sha256 != original.identity_sha256
    assert changed_body.identity_sha256 == original.identity_sha256
    assert changed_body.request_sha256 != original.request_sha256
    assert revoke_other_target.identity_sha256 == revoke_one_target.identity_sha256
    assert revoke_other_target.request_sha256 != revoke_one_target.request_sha256


def test_publish_use_case_replays_exact_commit_and_rejects_changed_payload() -> None:
    """A matching retry returns its original version before consulting mutable inputs."""

    repository = InMemoryM1RiskPolicyRepository()
    use_case = PublishM1RiskPolicyRevisionUseCase(repository)
    context = _idempotency()
    first = use_case.execute(command=_command(), idempotency=context)
    retry = use_case.execute(
        command=replace(
            _command(),
            source_snapshot=replace(
                _source(),
                account_max_total_position_pct=Decimal("94"),
            ),
        ),
        idempotency=context,
    )

    assert retry == first
    assert len(repository.created_commands) == 1
    try:
        use_case.execute(
            command=_command(),
            idempotency=_idempotency(request_body="changed request body"),
        )
    except M1RiskPolicyIdempotencyConflictError:
        pass
    else:
        raise AssertionError("reusing one idempotency identity with a new body must conflict")


def test_reader_returns_expired_and_changed_source_states() -> None:
    """A missing effective interval or changed input never qualifies for BUY."""

    expired = _revision(end=START + timedelta(hours=1))
    expired_reader = GetM1RiskPolicyQualificationUseCase(InMemoryM1RiskPolicyRepository((expired,)))
    expired_result = expired_reader.execute(
        account_id=901,
        as_of=START + timedelta(hours=1),
        current_source=_source(),
    )
    changed_reader = GetM1RiskPolicyQualificationUseCase(
        InMemoryM1RiskPolicyRepository((_revision(),))
    )
    changed_result = changed_reader.execute(
        account_id=901,
        as_of=START + timedelta(minutes=1),
        current_source=replace(_source(), account_max_single_position_pct=Decimal("18")),
    )

    assert expired_result.state is RiskQualificationState.NOT_EFFECTIVE
    assert changed_result.state is RiskQualificationState.SOURCE_CHANGED
    assert expired_result.ready_for_buy is False
    assert changed_result.ready_for_buy is False


def test_reader_rejects_ambiguous_overlapping_revisions() -> None:
    """Concurrent/legacy overlaps fail closed rather than choosing one silently."""

    repository = InMemoryM1RiskPolicyRepository(
        (
            _revision(),
            replace(_revision(), risk_policy_version="another-policy-version"),
        )
    )
    result = GetM1RiskPolicyQualificationUseCase(repository).execute(
        account_id=901,
        as_of=START + timedelta(days=1),
        current_source=_source(),
    )

    assert result.state is RiskQualificationState.UNKNOWN
    assert result.reason_codes == ("M1_RISK_POLICY_ACTIVE_REVISION_AMBIGUOUS",)


def test_reader_uses_new_revision_after_real_revocation_boundary() -> None:
    """A replaced revision is excluded after its explicit owner revocation event."""

    revocation_at = START + timedelta(days=2)
    old = _revision(
        revoked_at=revocation_at,
        revoked_by_user_id=79,
        revocation_reason="Owner replaced this M1 policy.",
    )
    new = replace(
        _revision(start=revocation_at),
        risk_policy_version="new-owner-published-version",
    )
    result = GetM1RiskPolicyQualificationUseCase(
        InMemoryM1RiskPolicyRepository((old, new))
    ).execute(
        account_id=901,
        as_of=revocation_at,
        current_source=_source(),
    )

    assert result.state is RiskQualificationState.QUALIFIED
    assert result.revision is not None
    assert result.revision.risk_policy_version == "new-owner-published-version"


def test_unknown_revocation_does_not_hide_overlapping_revision() -> None:
    """A broken revoke audit keeps ambiguity fail-closed instead of choosing a new row."""

    old = replace(
        _revision(),
        revocation_state="unknown",
        revoked_at=None,
        revoked_by_user_id=None,
        revocation_reason=None,
    )
    new = replace(_revision(), risk_policy_version="new-owner-published-version")
    result = GetM1RiskPolicyQualificationUseCase(
        InMemoryM1RiskPolicyRepository((old, new))
    ).execute(
        account_id=901,
        as_of=START + timedelta(days=1),
        current_source=_source(),
    )

    assert result.state is RiskQualificationState.UNKNOWN
    assert result.reason_codes == ("M1_RISK_POLICY_ACTIVE_REVISION_AMBIGUOUS",)


def test_corrupt_persisted_falsification_source_is_unknown_not_ready() -> None:
    """A source JSON/column disagreement cannot be converted to a default policy."""

    class CorruptRepository(InMemoryM1RiskPolicyRepository):
        """Simulate the typed repository's explicit stored-source corruption result."""

        def list_revisions(
            self,
            *,
            account_id: int,
        ) -> tuple[M1RiskPolicyRevision, ...]:
            """Reject rather than reading an inconsistent persisted risk predicate."""

            raise M1RiskPolicySourceCorruptError("condition columns and rules disagree")

    result = GetM1RiskPolicyQualificationUseCase(CorruptRepository()).execute(
        account_id=901,
        as_of=START,
        current_source=_source(),
    )

    assert result.state is RiskQualificationState.UNKNOWN
    assert result.reason_codes == ("M1_RISK_POLICY_VERSION_SOURCE_CORRUPT",)
    assert result.ready_for_buy is False


def test_revocation_use_case_keeps_reason_and_real_actor() -> None:
    """The revoke operation records actor/reason separately from the revision."""

    original = _revision()
    repository = InMemoryM1RiskPolicyRepository((original,))
    revoked = RevokeM1RiskPolicyRevisionUseCase(repository).execute(
        account_id=901,
        risk_policy_version=original.risk_policy_version,
        actor_user_id=80,
        reason="Owner replaced the current risk decision.",
        idempotency=_idempotency(
            actor_user_id=80,
            operation="revoke",
            key="revoke-1",
            request_body="owner reason",
        ),
    )

    assert revoked.revoked_by_user_id == 80
    assert revoked.revocation_reason == "Owner replaced the current risk decision."
    assert repository.revocations == [
        (901, original.risk_policy_version, 80, "Owner replaced the current risk decision.")
    ]
    assert repository.revisions == [original]


def test_revocation_use_case_rejects_missing_reason_and_unknown_version() -> None:
    """A revocation needs both owner intent and a persisted exact target version."""

    repository = InMemoryM1RiskPolicyRepository((_revision(),))
    use_case = RevokeM1RiskPolicyRevisionUseCase(repository)
    try:
        use_case.execute(
            account_id=901,
            risk_policy_version="7b5eaf53-990a-4ceb-b0ef-8b7fe13bad85",
            actor_user_id=80,
            reason="  ",
            idempotency=_idempotency(
                actor_user_id=80,
                operation="revoke",
                key="revoke-blank",
                request_body="blank reason",
            ),
        )
    except M1RiskPolicyValidationError as exc:
        assert exc.reason_codes == ("M1_RISK_POLICY_REVOCATION_REASON_REQUIRED",)
    else:
        raise AssertionError("blank revocation reason should be rejected")
    try:
        use_case.execute(
            account_id=901,
            risk_policy_version="missing-version",
            actor_user_id=80,
            reason="The owner confirmed the target does not exist.",
            idempotency=_idempotency(
                actor_user_id=80,
                operation="revoke",
                key="revoke-missing",
                request_body="missing version",
            ),
        )
    except M1RiskPolicyNotFoundError:
        pass
    else:
        raise AssertionError("unknown revision should not create an audit event")
