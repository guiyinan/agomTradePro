"""Strict persistence codec coverage for the R7 family lifecycle."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from copy import deepcopy
from datetime import timedelta

import pytest

from apps.research.application.r7_result_family_lifecycle import (
    R7FamilyLifecycleUnavailable,
    R7FamilyOwnerSourceGraph,
)
from apps.research.application.r7_result_family_lifecycle_persistence import (
    AuditR7FamilyLifecycle,
    GetExactR7FamilyAuthorization,
    GetExactR7FamilyEvent,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7LocalLifecycleStreamAttestation,
)
from apps.research.infrastructure.r7_result_family_lifecycle_codec import (
    R7FamilyLifecycleCodecError,
    decode_r7_family_lifecycle_authorization,
    decode_r7_family_lifecycle_event,
    encode_r7_family_lifecycle_authorization,
    encode_r7_family_lifecycle_event,
)
from tests.unit.research.test_r7_result_family_lifecycle import (
    _authorization,
    _event,
    _local_stream,
    _result,
)


def _root() -> tuple[object, object, R7FamilyOwnerSourceGraph]:
    result = _result("codec")
    stream = _local_stream(result)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id=f"r7-local-lifecycle-attestation:{result.result_id}",
        attestation_version="r7-local-lifecycle-attestation.v1",
        complete_local_lifecycle_stream=stream,
        recorded_at=stream[-1].recorded_at,
    )
    source = R7FamilyOwnerSourceGraph.from_owner_graph(
        result=result,
        local_lifecycle_stream=stream,
        local_lifecycle_attestation=attestation,
        evaluated_at=stream[-1].recorded_at,
    )
    evidence = source.evidence
    authorization = _authorization(
        family=evidence.family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    event = _event(
        previous_events=(),
        authorization=authorization,
        subject=evidence,
    )
    return authorization, event, source


def test_family_codec_round_trips_only_through_complete_source_graph() -> None:
    authorization, event, source = _root()

    restored_authorization = decode_r7_family_lifecycle_authorization(
        encode_r7_family_lifecycle_authorization(authorization)
    )
    restored_event = decode_r7_family_lifecycle_event(
        encode_r7_family_lifecycle_event(
            event,
            subject_source=source,
            rollback_target_source=None,
        ),
        previous_events=(),
    )

    assert restored_authorization == authorization
    assert restored_event == event


def test_family_codec_rejects_nested_owner_source_tamper() -> None:
    _, event, source = _root()
    payload = deepcopy(
        encode_r7_family_lifecycle_event(
            event,
            subject_source=source,
            rollback_target_source=None,
        )
    )
    subject = payload["subject_source"]
    assert isinstance(subject, dict)
    result = subject["result"]
    assert isinstance(result, dict)
    body = result["body"]
    assert isinstance(body, dict)
    body["result_id"] = "r7-family-result:substituted"

    with pytest.raises(R7FamilyLifecycleCodecError):
        decode_r7_family_lifecycle_event(payload, previous_events=())


class _SpoofCommand:
    def __post_init__(self) -> None:
        return None


class _NeverCalledQueryRepository:
    def __init__(self) -> None:
        self.calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        self.calls += 1
        return nullcontext()

    def get_exact_authorization(self, **kwargs: object) -> None:
        self.calls += 1
        return None

    def get_exact_event(self, **kwargs: object) -> None:
        self.calls += 1
        return None

    def audit_events(self, **kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("audit repository must not be called")


@pytest.mark.parametrize(
    "use_case_type",
    (GetExactR7FamilyAuthorization, GetExactR7FamilyEvent, AuditR7FamilyLifecycle),
)
def test_family_query_use_cases_reject_spoof_commands_without_repository_calls(
    use_case_type: type,
) -> None:
    repository = _NeverCalledQueryRepository()
    use_case = use_case_type(repository)

    with pytest.raises(R7FamilyLifecycleUnavailable):
        use_case.execute(_SpoofCommand())

    assert repository.calls == 0
