from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.application.simulated_corporate_action_write_lease import (
    RequireSimulatedCorporateActionWriteLease,
    SimulatedCorporateActionWriteLeaseUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_lease import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SimulatedCorporateActionWriteLease,
    SimulatedCorporateActionWriteLeaseBinding,
    SimulatedCorporateActionWriteLeaseRevocationState,
    SimulatedCorporateActionWriteLeaseSelector,
)

_RECORDED_AT = datetime(2026, 11, 11, 2, 0, tzinfo=UTC)
_VALID_UNTIL = _RECORDED_AT + timedelta(seconds=30)


def _binding(**changes: object) -> SimulatedCorporateActionWriteLeaseBinding:
    values: dict[str, object] = {
        "permission": SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
        "service_actor_id": SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
        "account_namespace": "simulated_trading",
        "account_id": "simulated-account:73",
        "owner_user_id": 41,
        "tenant_id": "tenant:41",
        "owner_id": "owner:41",
        "account_source_id": "account-owner-source:73",
        "account_source_version": "v1",
        "account_source_content_hash": "a" * 64,
        "policy_id": "single-owner-policy:73",
        "policy_version": "v1",
        "policy_content_hash": "b" * 64,
    }
    values.update(changes)
    return SimulatedCorporateActionWriteLeaseBinding(**values)  # type: ignore[arg-type]


def _selector(**changes: object) -> SimulatedCorporateActionWriteLeaseSelector:
    values: dict[str, object] = {
        "lease_id": "corporate-action-write:73",
        "lease_version": "v1",
        "source_id": "owner-write-authority:73",
        "source_version": "v1",
        "source_content_hash": "c" * 64,
        "binding": _binding(),
    }
    values.update(changes)
    return SimulatedCorporateActionWriteLeaseSelector(**values)  # type: ignore[arg-type]


def _lease(
    *,
    selector: SimulatedCorporateActionWriteLeaseSelector | None = None,
    revocation_state: SimulatedCorporateActionWriteLeaseRevocationState = (
        SimulatedCorporateActionWriteLeaseRevocationState.ACTIVE
    ),
    **changes: object,
) -> SimulatedCorporateActionWriteLease:
    values: dict[str, object] = {
        "selector": selector or _selector(),
        "recorded_at": _RECORDED_AT,
        "valid_until": _VALID_UNTIL,
        "revocation_state": revocation_state,
        "revocation_source_id": None,
        "revocation_source_version": None,
        "revocation_source_content_hash": None,
        "revocation_recorded_at": None,
    }
    if revocation_state is SimulatedCorporateActionWriteLeaseRevocationState.REVOKED:
        values.update(
            {
                "revocation_source_id": "owner-write-revocation:73",
                "revocation_source_version": "v1",
                "revocation_source_content_hash": "d" * 64,
                "revocation_recorded_at": _RECORDED_AT + timedelta(seconds=1),
            }
        )
    values.update(changes)
    return SimulatedCorporateActionWriteLease(**values)  # type: ignore[arg-type]


class _LeaseProvider:
    def __init__(self, lease: object | None) -> None:
        self.lease = lease
        self.calls: list[tuple[SimulatedCorporateActionWriteLeaseSelector, datetime]] = []

    def get_current_lease(
        self,
        *,
        selector: SimulatedCorporateActionWriteLeaseSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteLease | None:
        self.calls.append((selector, as_of))
        return cast(SimulatedCorporateActionWriteLease | None, self.lease)


def test_application_returns_only_exact_provider_lease_in_half_open_window() -> None:
    selector = _selector()
    lease = _lease(selector=selector)
    provider = _LeaseProvider(lease)
    use_case = RequireSimulatedCorporateActionWriteLease(provider)

    accepted = use_case.execute(selector, as_of=_RECORDED_AT)
    accepted_before_expiry = use_case.execute(
        selector,
        as_of=_VALID_UNTIL - timedelta(microseconds=1),
    )

    assert accepted is lease
    assert accepted_before_expiry is lease
    assert provider.calls == [
        (selector, _RECORDED_AT),
        (selector, _VALID_UNTIL - timedelta(microseconds=1)),
    ]
    assert selector.binding.permission != "evidence_read"
    assert selector.binding.service_actor_id == "simulated-trading"


@pytest.mark.parametrize(
    "as_of",
    [
        _RECORDED_AT - timedelta(microseconds=1),
        _VALID_UNTIL,
    ],
)
def test_application_blocks_before_recorded_at_and_at_expiry(as_of: datetime) -> None:
    use_case = RequireSimulatedCorporateActionWriteLease(_LeaseProvider(_lease()))

    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        use_case.execute(_selector(), as_of=as_of)


def test_application_blocks_absent_provider_and_missing_lease() -> None:
    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        RequireSimulatedCorporateActionWriteLease(None)

    use_case = RequireSimulatedCorporateActionWriteLease(_LeaseProvider(None))
    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        use_case.execute(_selector(), as_of=_RECORDED_AT)


def test_application_blocks_revoked_lease() -> None:
    revoked = _lease(revocation_state=SimulatedCorporateActionWriteLeaseRevocationState.REVOKED)

    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        RequireSimulatedCorporateActionWriteLease(_LeaseProvider(revoked)).execute(
            _selector(), as_of=_RECORDED_AT + timedelta(seconds=2)
        )


@pytest.mark.parametrize(
    "binding_changes",
    [
        {"account_namespace": "real_trading"},
        {"account_id": "simulated-account:74"},
        {"owner_user_id": 42},
        {"tenant_id": "tenant:42"},
        {"owner_id": "owner:42"},
        {"account_source_id": "account-owner-source:other"},
        {"account_source_version": "v2"},
        {"account_source_content_hash": "e" * 64},
        {"policy_id": "single-owner-policy:other"},
        {"policy_version": "v2"},
        {"policy_content_hash": "f" * 64},
    ],
)
def test_application_blocks_account_owner_scope_or_lineage_drift(
    binding_changes: dict[str, object],
) -> None:
    lease = _lease()
    selector = replace(lease.selector, binding=_binding(**binding_changes))

    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        RequireSimulatedCorporateActionWriteLease(_LeaseProvider(lease)).execute(
            selector, as_of=_RECORDED_AT
        )


@pytest.mark.parametrize(
    "source_changes",
    [
        {"source_id": "owner-write-authority:other"},
        {"source_version": "v2"},
        {"source_content_hash": "9" * 64},
    ],
)
def test_application_blocks_changed_authority_source(
    source_changes: dict[str, object],
) -> None:
    lease = _lease()
    selector = replace(lease.selector, **source_changes)

    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        RequireSimulatedCorporateActionWriteLease(_LeaseProvider(lease)).execute(
            selector, as_of=_RECORDED_AT
        )


def test_application_blocks_provider_type_substitution_and_forged_content_hash() -> None:
    use_case = RequireSimulatedCorporateActionWriteLease(_LeaseProvider(object()))
    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        use_case.execute(_selector(), as_of=_RECORDED_AT)

    forged = _lease()
    object.__setattr__(forged, "content_hash", "0" * 64)
    with pytest.raises(SimulatedCorporateActionWriteLeaseUnavailable):
        RequireSimulatedCorporateActionWriteLease(_LeaseProvider(forged)).execute(
            _selector(), as_of=_RECORDED_AT
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("permission", "evidence_read"),
        ("service_actor_id", "untrusted-service"),
        ("account_source_content_hash", "not-a-digest"),
        ("policy_content_hash", "not-a-digest"),
    ],
)
def test_binding_rejects_wrong_permission_actor_or_incomplete_lineage(
    field: str,
    value: str,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _binding(**{field: value})


def test_lease_revocation_state_requires_exact_revocation_provenance() -> None:
    with pytest.raises(ValueError):
        _lease(
            revocation_state=SimulatedCorporateActionWriteLeaseRevocationState.REVOKED,
            revocation_source_content_hash=None,
        )

    with pytest.raises(ValueError):
        _lease(
            revocation_source_id="owner-write-revocation:73",
            revocation_source_version="v1",
            revocation_source_content_hash="d" * 64,
            revocation_recorded_at=_RECORDED_AT,
        )
