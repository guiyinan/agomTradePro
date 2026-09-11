"""Adversarial clock regressions independent of the integration implementation."""

from dataclasses import replace
from datetime import timedelta

from apps.research.application.evidence_scope import EvidenceScopeCorruption
from core.integration.owner_tenant_evidence_scope_v2 import (
    OwnerTenantAuthorityV2EvidenceReadFacade,
)
from tests.unit.account.test_owner_tenant_authority_v2_application import _selector, _World
from tests.unit.research.test_evidence_contracts import _spec


def test_intermediate_clock_rollback_cannot_escape_as_success():
    world = _World()
    service = world.service()
    decision = service.issue(world.issue_command())
    selector = _selector(decision)
    current = service.get_current(selector)
    assert current is not None
    now = current.observed_at
    spec = replace(
        _spec(),
        activated_at=now - timedelta(hours=1),
        valid_until=now + timedelta(hours=1),
        content_hash="",
    )

    class Clock:
        def __init__(self):
            self.times = iter(now + timedelta(seconds=value) for value in (0, 5, 1, 2, 3))

        def now(self):
            return next(self.times)

    class Authority:
        unit_of_work_key = "django:owner-test"

        def with_current(self, command, operation):
            assert command == selector
            return operation(current)

    class Evidence:
        unit_of_work_key = "django:owner-test"

        def get_operator_spec(self, **kwargs):
            return spec

    reader = OwnerTenantAuthorityV2EvidenceReadFacade(
        authority_reader=Authority(),
        evidence_reader=Evidence(),
        authority_command=selector,
        server_bound_artifacts=frozenset({spec.artifact_ref}),
        scope_ttl=timedelta(minutes=1),
        using="owner-test",
        clock=Clock(),
    )
    try:
        result = reader.get_operator_spec(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            expected_content_hash=spec.content_hash,
            evidence_as_of=now - timedelta(seconds=1),
        )
    except EvidenceScopeCorruption:
        result = None
    assert result is None, "a 5 -> 1 second server-clock rollback must never return evidence"
