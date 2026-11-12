"""Pure owner-consent preparation tests with explicit source and grant fixtures."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain import simulated_corporate_action_write_grant as grant_domain
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
)
from apps.account.simulated_corporate_action_policy_scope_composition import (
    ConfiguredSimulatedActionWritePolicy,
)
from apps.simulated_trading import corporate_action_consent_composition as consent
from core.exceptions import AuthorizationError

_NOW = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
_PHYSICAL_ID = 41
_OWNER_ID = 7
_CANONICAL_ID = "canonical-simulated-41"
_TERMS_SHA256 = "6ee0ad13d2e0b9cff885bfdf9d1e0e2ccb837c0943bf2cab6cf90d8410031165"
_ALL_CAPABILITIES = tuple(sorted(Capability, key=lambda item: item.value))
_ASSESS = (Capability.TAX_ASSESS,)
V1_SCHEMA = grant_domain.SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
V2_SCHEMA = grant_domain.SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA


@pytest.mark.parametrize("known_terms", [True, False])
def test_withdrawal_receipt_preserves_exact_scope_without_requiring_known_terms(
    monkeypatch: pytest.MonkeyPatch, known_terms: bool
) -> None:
    grant = _grant(
        _binding(_v2_policy(), _Source()),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=(
            SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2 if known_terms else "obsolete-terms"
        ),
        terms_sha256=_TERMS_SHA256,
    )
    monkeypatch.setattr(
        consent, "restore_simulated_action_withdrawal_token", lambda *a, **kw: grant.selector
    )
    monkeypatch.setattr(
        consent, "read_exact_simulated_action_withdrawal_metadata", lambda **kw: grant
    )
    revoked: list[object] = []
    monkeypatch.setattr(
        consent,
        "revoke_authenticated_simulated_corporate_action_grant",
        lambda *a, **kw: revoked.append(kw["selector"]),
    )
    payload = consent.withdraw_owner_simulated_action_consent(
        _request(), account_id=_PHYSICAL_ID, withdrawal_token="original", confirmed=True
    )
    assert revoked == [grant.selector]
    assert payload["consent_status"] == "revoked"
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert payload["grant_schema"] == V2_SCHEMA
    assert bool(payload["terms_text"]) is known_terms
    assert payload["must_not_execute"] is True


@dataclass(frozen=True)
class _Source:
    account_id: str = _CANONICAL_ID
    source_id: str = "account-source-1"
    source_version: str = "1"
    content_hash: str = "a" * 64
    account_namespace: str = "account"
    row_user_id: int = _OWNER_ID
    row_created_at: datetime = datetime(2026, 11, 1, tzinfo=UTC)
    row_updated_at: datetime = datetime(2026, 11, 2, tzinfo=UTC)
    raw_account_type: str = "simulated"
    observed_at: datetime = datetime(2026, 11, 3, tzinfo=UTC)
    valid_until: datetime = datetime(2027, 1, 1, tzinfo=UTC)
    underlying_unified_account_namespace: str = "simulated-account-row"
    underlying_unified_account_id: int = _PHYSICAL_ID

    def is_current_at(self, as_of: datetime) -> bool:
        """Provide the fake source's explicit finite current interval."""
        return self.observed_at <= as_of < self.valid_until


@dataclass
class _Harness:
    policy: ConfiguredSimulatedActionWritePolicy
    source: _Source
    grant: grant_domain.SimulatedCorporateActionWriteGrant | None
    commands: list[SimulatedCorporateActionGrantConsent]
    policy_schema_requests: list[str | None]


def _policy(
    *,
    schema: str = V1_SCHEMA,
    capabilities: tuple[Capability, ...] | None = None,
    terms_version: str | None = None,
    terms_sha256: str | None = None,
    tenant_id: str = "tenant-1",
    owner_id: str = "owner-1",
    policy_id: str = "policy-1",
    policy_version: str = "1",
) -> ConfiguredSimulatedActionWritePolicy:
    """Build one exact V1 or V2 test policy without enabling runtime configuration."""
    return ConfiguredSimulatedActionWritePolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        canonical_account_id=_CANONICAL_ID,
        owner_user_id=_OWNER_ID,
        tenant_id=tenant_id,
        owner_id=owner_id,
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=5),
        maximum_grant_seconds=3600,
        content_hash="b" * 64,
        grant_schema=schema,
        capabilities=capabilities,
        terms_version=terms_version,
        terms_sha256=terms_sha256,
    )


def _binding(
    policy: ConfiguredSimulatedActionWritePolicy, source: _Source
) -> grant_domain.SimulatedCorporateActionWriteGrantBinding:
    """Bind the fixtures to the same canonical owner account and exact sources."""
    return grant_domain.SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id=_CANONICAL_ID,
        owner_user_id=_OWNER_ID,
        tenant_id=policy.tenant_id,
        owner_id=policy.owner_id,
        account_source_id=source.source_id,
        account_source_version=source.source_version,
        account_source_content_hash=source.content_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.content_hash,
    )


def _grant(
    binding: grant_domain.SimulatedCorporateActionWriteGrantBinding,
    *,
    schema: str,
    capabilities: tuple[Capability, ...] | None = None,
    terms_version: str | None = None,
    terms_sha256: str | None = None,
    grant_id: str = "grant-1",
    grant_version: str = "1",
) -> grant_domain.SimulatedCorporateActionWriteGrant:
    """Build a real sealed-domain-shaped grant for the selected current head."""
    return grant_domain.SimulatedCorporateActionWriteGrant(
        grant_id=grant_id,
        grant_version=grant_version,
        binding=binding,
        consent_evidence_id="consent-evidence-1",
        consent_evidence_version="1",
        consent_evidence_hash="c" * 64,
        issuer_evidence_id="issuer-evidence-1",
        issuer_evidence_version="1",
        issuer_evidence_hash="d" * 64,
        consented_at=_NOW - timedelta(minutes=3),
        issued_at=_NOW - timedelta(minutes=2),
        recorded_at=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(hours=1),
        permission=(
            grant_domain.SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
            if schema == V2_SCHEMA
            else grant_domain.SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
        ),
        schema=schema,
        capabilities=capabilities,
        terms_version=terms_version,
        terms_sha256=terms_sha256,
    )


def _install_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: ConfiguredSimulatedActionWritePolicy,
    grant: grant_domain.SimulatedCorporateActionWriteGrant | None = None,
    source: _Source = _Source(),
    role_eligible: bool = True,
    physical_updated_at: datetime | None = None,
) -> _Harness:
    """Replace database/runtime edges with fixed, same-owner unit fakes."""
    harness = _Harness(policy, source, grant, [], [])
    row = SimpleNamespace(
        created_at=source.row_created_at,
        updated_at=physical_updated_at or source.row_updated_at,
        is_active=True,
    )

    class _Query:
        def using(self, using: str) -> _Query:
            return self

        def select_for_update(self) -> _Query:
            return self

        def filter(self, **filters: object) -> _Query:
            assert filters == {
                "pk": _PHYSICAL_ID,
                "user_id": _OWNER_ID,
                "account_type": "simulated",
            }
            return self

        def first(self) -> object:
            return row

    class _SourceRepository:
        def __init__(self, *, using: str) -> None:
            assert using == consent.DEFAULT_DB_ALIAS

        def lock_current_sources_for_read(self) -> None:
            return None

        def get_physical_account_heads(
            self, *, underlying_unified_account_id: int, as_of: datetime
        ) -> tuple[object, ...]:
            assert underlying_unified_account_id == _PHYSICAL_ID and as_of == _NOW
            return (SimpleNamespace(source=harness.source),)

        def get_exact_by_hash(
            self,
            *,
            source_id: str,
            source_version: str,
            expected_content_hash: str,
            as_of: datetime,
        ) -> object:
            if grant is not None:
                assert (source_id, source_version, expected_content_hash) == (
                    grant.binding.account_source_id,
                    grant.binding.account_source_version,
                    grant.binding.account_source_content_hash,
                )
            return SimpleNamespace(
                source=SimpleNamespace(
                    account_namespace="account",
                    account_id=_CANONICAL_ID,
                    underlying_unified_account_namespace="simulated-account-row",
                    underlying_unified_account_id=_PHYSICAL_ID,
                    row_user_id=_OWNER_ID,
                    row_created_at=row.created_at,
                )
            )

    class _Eligibility:
        def __enter__(self) -> None:
            if not role_eligible:
                raise AuthorizationError("fixture read-only role")
            return None

        def __exit__(self, *args: object) -> None:
            return None

    def _policy_reader(**kwargs: object) -> ConfiguredSimulatedActionWritePolicy:
        requested = kwargs.get("expected_grant_schema", harness.policy.grant_schema)
        assert requested is None or type(requested) is str
        harness.policy_schema_requests.append(requested)
        if requested is not None and harness.policy.grant_schema != requested:
            raise ValueError("fixture policy schema differs from requested schema")
        return harness.policy

    def _token_builder(command: SimulatedCorporateActionGrantConsent, *, as_of: datetime) -> str:
        assert as_of == _NOW
        harness.commands.append(command)
        return "consent-token-for-test"

    monkeypatch.setattr(
        consent, "connections", {consent.DEFAULT_DB_ALIAS: SimpleNamespace(vendor="postgresql")}
    )
    monkeypatch.setattr(consent.transaction, "atomic", lambda *, using: nullcontext())
    monkeypatch.setattr(consent.timezone, "now", lambda: _NOW)
    monkeypatch.setattr(
        consent,
        "SimulatedAccountModel",
        SimpleNamespace(_base_manager=_Query()),
    )
    monkeypatch.setattr(consent, "DjangoSimulatedAccountRowSourceV2Repository", _SourceRepository)
    monkeypatch.setattr(
        consent, "get_simulated_execution_runtime_environment", lambda: "development"
    )
    monkeypatch.setattr(
        consent, "locked_simulated_action_trading_eligibility", lambda **kwargs: _Eligibility()
    )
    monkeypatch.setattr(consent, "read_current_simulated_action_write_policy", _policy_reader)
    monkeypatch.setattr(
        consent, "read_current_simulated_action_consent_metadata", lambda **kwargs: grant
    )
    monkeypatch.setattr(
        consent,
        "prepare_simulated_action_withdrawal_token",
        lambda active, *, physical_account_id: f"withdraw:{active.content_hash}",
    )
    monkeypatch.setattr(consent, "prepare_simulated_action_consent_token", _token_builder)
    return harness


def _request() -> SimpleNamespace:
    """Supply only the identity fields used before authenticated issuer confirmation."""
    return SimpleNamespace(user=SimpleNamespace(pk=_OWNER_ID, is_authenticated=True))


def _prepare(
    *,
    grant_schema: str | None = None,
    requested_capabilities: tuple[Capability, ...] | None = None,
) -> consent.SimulatedActionConsentPayload:
    """Call the public read-only preparation boundary for the test account."""
    if grant_schema is None:
        if requested_capabilities is None:
            return consent.prepare_owner_simulated_action_consent(
                _request(), account_id=_PHYSICAL_ID
            )
        return consent.prepare_owner_simulated_action_consent(
            _request(),
            account_id=_PHYSICAL_ID,
            requested_capabilities=requested_capabilities,
        )
    return consent.prepare_owner_simulated_action_consent(
        _request(),
        account_id=_PHYSICAL_ID,
        grant_schema=grant_schema,
        requested_capabilities=requested_capabilities,
    )


def _prepare_discovered(
    requested_capabilities: tuple[Capability, ...] | None,
) -> consent.SimulatedActionConsentPayload:
    """Let the unique current policy select V1 or V2 after an explicit choice."""
    return consent.prepare_owner_simulated_action_consent(
        _request(),
        account_id=_PHYSICAL_ID,
        grant_schema=None,
        requested_capabilities=requested_capabilities,
    )


def _v2_policy(
    *,
    capabilities: tuple[Capability, ...] = _ALL_CAPABILITIES,
    tenant_id: str = "tenant-1",
    owner_id: str = "owner-1",
    policy_id: str = "policy-1",
    policy_version: str = "1",
) -> ConfiguredSimulatedActionWritePolicy:
    """Build a typed current V2 policy with the pinned terms identity."""
    return _policy(
        schema=V2_SCHEMA,
        capabilities=capabilities,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
        tenant_id=tenant_id,
        owner_id=owner_id,
        policy_id=policy_id,
        policy_version=policy_version,
    )


def test_v2_prepare_api_requires_explicit_subset_and_returns_full_pinned_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _v2_policy()
    harness = _install_harness(monkeypatch, policy=policy)

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["outcome"] == "success"
    assert payload["consent_status"] == "awaiting_confirmation"
    assert payload["consent_token"] == "consent-token-for-test"
    assert payload["grant_schema"] == V2_SCHEMA
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert payload["capability_labels"] == ["模拟税额评估"]
    assert payload["terms_version"] == SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
    assert payload["terms_sha256"] == _TERMS_SHA256
    assert "来源、持仓历史和适用政策核验" in payload["terms_text"]
    assert "余额不足时显示待扣" in payload["terms_text"]
    assert "现金分红模拟权益与模拟到账" in payload["terms_text"]
    assert all(capability.value not in payload["terms_text"] for capability in Capability)
    assert len(harness.commands) == 1
    command = harness.commands[0]
    assert command.grant_schema == V2_SCHEMA
    assert command.capabilities == _ASSESS
    assert command.terms_version == SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
    assert command.terms_sha256 == _TERMS_SHA256
    assert command.expected_predecessor_content_hash is None
    assert harness.policy_schema_requests == [V2_SCHEMA]


def test_v1_default_remains_legacy_and_rejects_explicit_capability_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _install_harness(monkeypatch, policy=_policy())

    payload = consent.prepare_owner_simulated_action_consent(_request(), account_id=_PHYSICAL_ID)

    assert payload["summary"].startswith("确认后，服务可在有效期内")
    assert payload["consent_token"] == "consent-token-for-test"
    assert payload["grant_schema"] is None
    assert payload["selected_capabilities"] == []
    assert payload["terms_text"] == ""
    assert harness.commands[0].grant_schema == V1_SCHEMA
    assert harness.commands[0].capabilities is None
    assert harness.commands[0].terms_version is None

    second = _install_harness(monkeypatch, policy=_policy())
    rejected = _prepare(requested_capabilities=_ASSESS)
    assert rejected["outcome"] == "blocked"
    assert rejected["consent_token"] is None
    assert second.commands == []


def test_exact_active_v1_keeps_legacy_summary_without_preparing_a_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()
    source = _Source()
    active = _grant(_binding(policy, source), schema=V1_SCHEMA)
    harness = _install_harness(monkeypatch, policy=policy, grant=active)

    payload = consent.prepare_owner_simulated_action_consent(_request(), account_id=_PHYSICAL_ID)

    assert payload["outcome"] == "success"
    assert payload["summary"] == "已有有限期的现金分红模拟入账授权，可随时撤销。"
    assert payload["consent_status"] == "active"
    assert payload["grant_schema"] is None
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{active.content_hash}"
    assert harness.commands == []


def test_v2_requires_explicit_canonical_capabilities_and_policy_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _install_harness(monkeypatch, policy=_v2_policy())
    missing = _prepare(grant_schema=V2_SCHEMA)
    assert missing["outcome"] == "blocked"
    assert missing["consent_token"] is None
    assert first.commands == []

    second = _install_harness(
        monkeypatch,
        policy=_v2_policy(capabilities=(Capability.TAX_ASSESS,)),
    )
    not_allowed = _prepare(
        grant_schema=V2_SCHEMA, requested_capabilities=(Capability.TAX_WITHHOLD,)
    )
    assert not_allowed["outcome"] == "blocked"
    assert not_allowed["blocking_reason"] == "simulated_action_consent_capability_not_permitted"
    assert not_allowed["consent_token"] is None
    assert second.commands == []


def test_discovery_requires_an_explicit_nonempty_capability_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _install_harness(monkeypatch, policy=_policy())

    payload = _prepare_discovered(None)

    assert payload["outcome"] == "blocked"
    assert payload["blocking_reason"] == "simulated_action_consent_selection_invalid"
    assert payload["consent_token"] is None
    assert harness.commands == []
    assert harness.policy_schema_requests == []


def test_discovery_v1_allows_only_explicit_cash_capability_as_legacy_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _install_harness(monkeypatch, policy=_policy())

    payload = _prepare_discovered((Capability.CASH_STAGE_WRITE,))

    assert payload["outcome"] == "success"
    assert payload["consent_status"] == "awaiting_confirmation"
    assert payload["consent_token"] == "consent-token-for-test"
    assert harness.policy_schema_requests == [None]
    assert len(harness.commands) == 1
    assert harness.commands[0].grant_schema == V1_SCHEMA
    assert harness.commands[0].capabilities is None
    assert harness.commands[0].terms_version is None
    assert harness.commands[0].terms_sha256 is None


def test_discovery_v1_rejects_any_tax_capability_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _install_harness(monkeypatch, policy=_policy())

    payload = _prepare_discovered(_ASSESS)

    assert payload["outcome"] == "blocked"
    assert payload["consent_token"] is None
    assert harness.commands == []


@pytest.mark.parametrize("selected", [(Capability.CASH_STAGE_WRITE,), _ASSESS])
def test_discovery_v2_uses_exact_explicit_selected_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    selected: tuple[Capability, ...],
) -> None:
    harness = _install_harness(monkeypatch, policy=_v2_policy())

    payload = _prepare_discovered(selected)

    assert payload["outcome"] == "success"
    assert payload["grant_schema"] == V2_SCHEMA
    assert payload["selected_capabilities"] == [item.value for item in selected]
    assert payload["terms_sha256"] == _TERMS_SHA256
    assert harness.policy_schema_requests == [None]
    assert len(harness.commands) == 1
    assert harness.commands[0].grant_schema == V2_SCHEMA
    assert harness.commands[0].capabilities == selected


@pytest.mark.parametrize(
    "requested",
    (
        (Capability.TAX_WITHHOLD, Capability.TAX_ASSESS),
        (Capability.TAX_ASSESS, Capability.TAX_ASSESS),
    ),
)
def test_v2_rejects_noncanonical_or_duplicate_capability_choice(
    monkeypatch: pytest.MonkeyPatch,
    requested: tuple[Capability, ...],
) -> None:
    harness = _install_harness(monkeypatch, policy=_v2_policy())

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=requested)

    assert payload["outcome"] == "blocked"
    assert payload["blocking_reason"] == "simulated_action_consent_selection_invalid"
    assert payload["consent_token"] is None
    assert harness.commands == []


def test_v1_to_v2_upgrade_reuses_grant_chain_and_exact_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_policy = _policy()
    old_source = _Source()
    prior = _grant(_binding(old_policy, old_source), schema=V1_SCHEMA)
    current_policy = _v2_policy()
    harness = _install_harness(monkeypatch, policy=current_policy, grant=prior)

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["outcome"] == "success"
    assert payload["withdrawal_token"] == f"withdraw:{prior.content_hash}"
    assert payload["consent_token"] == "consent-token-for-test"
    command = harness.commands[0]
    assert command.grant_id == prior.grant_id
    assert command.grant_version != prior.grant_version
    assert command.expected_predecessor_content_hash == prior.content_hash
    assert command.expected_binding == prior.binding
    assert "替换" in payload["summary"]


def test_v2_narrowing_and_refreshed_source_prepare_same_chain_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_policy = _v2_policy()
    old_source = _Source()
    prior = _grant(
        _binding(old_policy, old_source),
        schema=V2_SCHEMA,
        capabilities=_ALL_CAPABILITIES,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    current_source = _Source(
        source_id="account-source-2",
        source_version="2",
        content_hash="e" * 64,
    )
    current_policy = _v2_policy(policy_id="policy-2", policy_version="2")
    harness = _install_harness(
        monkeypatch,
        policy=current_policy,
        grant=prior,
        source=current_source,
    )

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["consent_token"] == "consent-token-for-test"
    command = harness.commands[0]
    assert command.grant_id == prior.grant_id
    assert command.grant_version != prior.grant_version
    assert command.expected_predecessor_content_hash == prior.content_hash
    assert command.expected_binding == _binding(current_policy, current_source)
    assert command.expected_binding != prior.binding


def test_exact_active_v2_returns_actual_selected_scope_without_new_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _v2_policy()
    source = _Source()
    active = _grant(
        _binding(policy, source),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    harness = _install_harness(monkeypatch, policy=policy, grant=active)

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["outcome"] == "success"
    assert payload["consent_status"] == "active"
    assert payload["grant_schema"] == V2_SCHEMA
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert payload["capability_labels"] == ["模拟税额评估"]
    assert payload["terms_sha256"] == _TERMS_SHA256
    assert "模拟税额评估" in payload["summary"]
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{active.content_hash}"
    assert harness.commands == []


def test_default_v1_read_of_active_v2_never_downgrades_and_shows_its_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _v2_policy()
    source = _Source()
    active = _grant(
        _binding(policy, source),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    harness = _install_harness(monkeypatch, policy=policy, grant=active)

    payload = consent.prepare_owner_simulated_action_consent(_request(), account_id=_PHYSICAL_ID)

    assert payload["outcome"] == "success"
    assert payload["grant_schema"] == V2_SCHEMA
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert "模拟税额评估" in payload["summary"]
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{active.content_hash}"
    assert harness.policy_schema_requests == [V2_SCHEMA]
    assert harness.commands == []


def test_default_v1_read_blocks_stale_v2_basis_without_losing_selected_scope_or_withdrawal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_policy = _v2_policy()
    old_source = _Source()
    active = _grant(
        _binding(old_policy, old_source),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    current_source = _Source(
        source_id="account-source-2",
        source_version="2",
        content_hash="e" * 64,
    )
    current_policy = _v2_policy(policy_id="policy-2", policy_version="2")
    harness = _install_harness(
        monkeypatch,
        policy=current_policy,
        grant=active,
        source=current_source,
    )

    payload = consent.prepare_owner_simulated_action_consent(_request(), account_id=_PHYSICAL_ID)

    assert payload["outcome"] == "blocked"
    assert payload["blocking_reason"] == "simulated_action_consent_basis_changed"
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert "模拟税额评估" in payload["summary"]
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{active.content_hash}"
    assert harness.policy_schema_requests == [V2_SCHEMA]
    assert harness.commands == []


@pytest.mark.parametrize("failure", ("read_only_role", "source_refresh"))
def test_existing_v2_withdrawal_survives_new_consent_eligibility_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    policy = _v2_policy()
    source = _Source()
    active = _grant(
        _binding(policy, source),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    harness = _install_harness(
        monkeypatch,
        policy=policy,
        grant=active,
        role_eligible=failure != "read_only_role",
        physical_updated_at=(
            source.row_updated_at + timedelta(seconds=1) if failure == "source_refresh" else None
        ),
    )

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["outcome"] == "blocked"
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert payload["capability_labels"] == ["模拟税额评估"]
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{active.content_hash}"
    assert harness.commands == []


def test_cross_tenant_successor_is_blocked_but_withdrawal_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_policy = _policy()
    prior = _grant(_binding(old_policy, _Source()), schema=V1_SCHEMA)
    harness = _install_harness(
        monkeypatch,
        policy=_v2_policy(tenant_id="another-tenant"),
        grant=prior,
    )

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=_ASSESS)

    assert payload["outcome"] == "blocked"
    assert payload["blocking_reason"] == "simulated_action_consent_chain_scope_changed"
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{prior.content_hash}"
    assert harness.commands == []


def test_policy_terms_mismatch_blocks_new_consent_and_retains_withdrawal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        schema=V2_SCHEMA,
        capabilities=_ALL_CAPABILITIES,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256="0" * 64,
    )
    prior_policy = _v2_policy()
    prior = _grant(
        _binding(prior_policy, _Source()),
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    harness = _install_harness(monkeypatch, policy=policy, grant=prior)

    payload = _prepare(grant_schema=V2_SCHEMA, requested_capabilities=(Capability.TAX_WITHHOLD,))

    assert payload["outcome"] == "blocked"
    assert payload["blocking_reason"] == "simulated_action_service_policy_unavailable"
    assert payload["consent_token"] is None
    assert payload["withdrawal_token"] == f"withdraw:{prior.content_hash}"
    assert harness.commands == []


def test_v2_confirmation_rechecks_terms_and_wraps_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _v2_policy()
    command = SimulatedCorporateActionGrantConsent(
        grant_id="grant-confirm",
        grant_version="confirm-v2",
        physical_account_id=_PHYSICAL_ID,
        expected_binding=_binding(policy, _Source()),
        valid_until=_NOW + timedelta(minutes=30),
        consent=True,
        grant_schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version="unknown-terms.v2",
        terms_sha256=_TERMS_SHA256,
    )
    issuer_calls: list[bool] = []
    monkeypatch.setattr(consent.timezone, "now", lambda: _NOW)
    monkeypatch.setattr(
        consent, "restore_simulated_action_consent_token", lambda *args, **kwargs: command
    )
    monkeypatch.setattr(
        consent, "get_simulated_execution_runtime_environment", lambda: "development"
    )
    monkeypatch.setattr(
        consent, "DjangoSimulatedCorporateActionWriteScopeLocker", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        consent,
        "issue_authenticated_simulated_corporate_action_grant",
        lambda *args, **kwargs: issuer_calls.append(True),
    )

    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        consent.confirm_owner_simulated_action_consent(
            _request(), account_id=_PHYSICAL_ID, consent_token="signed", confirmed=True
        )

    assert issuer_calls == []


@pytest.mark.parametrize("extra_minutes", [0, 30])
def test_successful_v2_confirmation_receipt_uses_actual_issued_scope(
    monkeypatch: pytest.MonkeyPatch,
    extra_minutes: int,
) -> None:
    policy = _v2_policy()
    binding = _binding(policy, _Source())
    command = SimulatedCorporateActionGrantConsent(
        grant_id="grant-confirm",
        grant_version="confirm-v2",
        physical_account_id=_PHYSICAL_ID,
        expected_binding=binding,
        valid_until=_NOW + timedelta(minutes=30),
        consent=True,
        grant_schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
    )
    issued = _grant(
        binding,
        schema=V2_SCHEMA,
        capabilities=_ASSESS,
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=_TERMS_SHA256,
        grant_id=command.grant_id,
        grant_version=command.grant_version,
    )
    issued = replace(
        issued,
        valid_until=command.valid_until + timedelta(minutes=extra_minutes),
        content_hash="",
    )
    monkeypatch.setattr(consent.timezone, "now", lambda: _NOW)
    monkeypatch.setattr(
        consent, "restore_simulated_action_consent_token", lambda *args, **kwargs: command
    )
    monkeypatch.setattr(
        consent, "get_simulated_execution_runtime_environment", lambda: "development"
    )
    monkeypatch.setattr(
        consent, "DjangoSimulatedCorporateActionWriteScopeLocker", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        consent,
        "issue_authenticated_simulated_corporate_action_grant",
        lambda *args, **kwargs: issued,
    )
    monkeypatch.setattr(
        consent,
        "prepare_simulated_action_withdrawal_token",
        lambda active, *, physical_account_id: f"withdraw:{active.content_hash}",
    )

    if extra_minutes:
        with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
            consent.confirm_owner_simulated_action_consent(
                _request(), account_id=_PHYSICAL_ID, consent_token="signed", confirmed=True
            )
        return

    payload = consent.confirm_owner_simulated_action_consent(
        _request(), account_id=_PHYSICAL_ID, consent_token="signed", confirmed=True
    )

    assert payload["grant_id"] == issued.grant_id
    assert payload["grant_version"] == issued.grant_version
    assert payload["grant_content_hash"] == issued.content_hash
    assert payload["grant_schema"] == V2_SCHEMA
    assert payload["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert payload["capability_labels"] == ["模拟税额评估"]
    assert payload["terms_sha256"] == _TERMS_SHA256
    assert "模拟税额评估" in payload["summary"]
