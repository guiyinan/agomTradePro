"""Production R7 composition exposes no owner-controlled write capability."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import signature

import pytest

from apps.research.application.r7_research_result_lifecycle import (
    ApplyR7ResultLifecycleCommand,
    R7ResultLifecycleAuthorizationRef,
    R7ResultLifecycleUnavailable,
)
from apps.research.application.r7_research_result_persistence import (
    R7ResearchResultUnavailable,
    RegisterR7ResearchResultCommand,
)
from apps.research.application.r7_sample_policy import (
    R7SamplePolicyUnavailable,
    RegisterR7SamplePolicyCommand,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
)
from apps.research.r7_research_result_composition import (
    _build_django_r7_research_result_owner_runtime,
    build_django_r7_research_result_runtime,
)
from apps.research.r7_research_result_lifecycle_composition import (
    build_django_r7_result_lifecycle_runtime,
)
from apps.research.r7_sample_policy_composition import (
    build_django_r7_sample_policy_runtime,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _retained_attribute_names(root: object) -> frozenset[str]:
    names: set[str] = set()
    seen: set[int] = set()

    def visit(value: object) -> None:
        if isinstance(value, (str, bytes, int, float, bool, type(None), datetime)):
            return
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        attributes = dict(vars(value)) if hasattr(value, "__dict__") else {}
        for owner_type in type(value).__mro__:
            slots = getattr(owner_type, "__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if name not in {"__dict__", "__weakref__"} and hasattr(value, name):
                    attributes[name] = getattr(value, name)
        for name, nested in attributes.items():
            names.add(name)
            visit(nested)

    visit(root)
    return frozenset(names)


def _sample_policy_command() -> RegisterR7SamplePolicyCommand:
    return RegisterR7SamplePolicyCommand(
        policy_id="r7-policy",
        policy_version="policy-v1",
        authorization_id="r7-policy-authorization",
        authorization_version="authorization-v1",
        as_of=NOW,
    )


def _result_command() -> RegisterR7ResearchResultCommand:
    return RegisterR7ResearchResultCommand(
        result_id="r7-result",
        result_version="result-v1",
        policy_id="r7-policy",
        policy_version="policy-v1",
        as_of=NOW,
    )


def _lifecycle_command() -> ApplyR7ResultLifecycleCommand:
    return ApplyR7ResultLifecycleCommand(
        result_ref=R7ResearchResultRef("r7-result", "result-v1", "a" * 64),
        action=R7ResultLifecycleAction.PROMOTE,
        authorization_ref=R7ResultLifecycleAuthorizationRef(
            "r7-lifecycle-authorization",
            "authorization-v1",
        ),
    )


def test_public_builders_accept_no_owner_provider_or_clock() -> None:
    for builder in (
        build_django_r7_sample_policy_runtime,
        build_django_r7_research_result_runtime,
        build_django_r7_result_lifecycle_runtime,
    ):
        assert tuple(signature(builder).parameters) == ("using",)


def test_private_result_owner_runtime_composes_only_canonical_exact_readers() -> None:
    runtime = _build_django_r7_research_result_owner_runtime(using="owners")

    writer = runtime.register._writer
    evidence_provider = writer._evidence_provider
    source = evidence_provider._source
    assert type(source._forecast_provider).__name__ == (
        "SignalForecastCalibrationSampleProvider"
    )
    assert type(source._historical_analogy_provider).__name__ == (
        "DjangoR7HistoricalAnalogyProvider"
    )
    assert type(source._path_study_provider).__name__ == "DjangoR7PathStudyProvider"
    assert {
        runtime.repository.unit_of_work_key,
        writer._policy_provider.unit_of_work_key,
        writer._store.unit_of_work_key,
        source.unit_of_work_key,
    } == {"django:owners"}
    assert tuple(signature(_build_django_r7_research_result_owner_runtime).parameters) == (
        "using",
    )


@pytest.mark.parametrize(
    ("runtime", "attribute", "command", "error"),
    (
        (
            build_django_r7_sample_policy_runtime(),
            "register",
            _sample_policy_command(),
            R7SamplePolicyUnavailable,
        ),
        (
            build_django_r7_research_result_runtime(),
            "register",
            _result_command(),
            R7ResearchResultUnavailable,
        ),
        (
            build_django_r7_result_lifecycle_runtime(),
            "apply",
            _lifecycle_command(),
            R7ResultLifecycleUnavailable,
        ),
    ),
)
def test_production_write_facades_are_inert_and_retain_no_capabilities(
    runtime: object,
    attribute: str,
    command: object,
    error: type[Exception],
) -> None:
    facade = getattr(runtime, attribute)
    assert not hasattr(runtime, "__dict__")
    assert not hasattr(facade, "__dict__")
    assert type(facade).__slots__ == ()
    assert facade.execute.__func__.__closure__ is None
    assert not any(
        forbidden in name.lower()
        for name in _retained_attribute_names(runtime)
        for forbidden in ("writer", "store", "token")
    )
    with pytest.raises(error, match="owner"):
        facade.execute(command)


@pytest.mark.parametrize(
    ("runtime", "attribute", "command", "error"),
    (
        (
            build_django_r7_sample_policy_runtime(),
            "register",
            _sample_policy_command(),
            R7SamplePolicyUnavailable,
        ),
        (
            build_django_r7_research_result_runtime(),
            "register",
            _result_command(),
            R7ResearchResultUnavailable,
        ),
        (
            build_django_r7_result_lifecycle_runtime(),
            "apply",
            _lifecycle_command(),
            R7ResultLifecycleUnavailable,
        ),
    ),
)
def test_malformed_commands_are_stably_unavailable(
    runtime: object,
    attribute: str,
    command: object,
    error: type[Exception],
) -> None:
    object.__setattr__(command, next(iter(command.__dataclass_fields__)), None)
    with pytest.raises(error, match="command"):
        getattr(runtime, attribute).execute(command)
