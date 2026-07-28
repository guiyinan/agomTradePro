"""Safety regressions for the shared Operational Readiness monitor summary."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.operational_readiness.application import monitor_service as service


@pytest.mark.parametrize(
    ("function_name", "provider_name"),
    [
        ("build_personal_readiness_status", "build_personal_readiness_status"),
        ("get_ai_capability_surface_status_payload", "get_ai_capability_surface_status_payload"),
        ("get_terminal_surface_status_payload", "get_terminal_surface_status_payload"),
        ("get_active_stock_fact_coverage_payload", "get_active_stock_fact_coverage_payload"),
    ],
)
def test_dynamic_payload_providers_reject_non_object_results(
    monkeypatch,
    function_name: str,
    provider_name: str,
) -> None:
    provider = SimpleNamespace(**{provider_name: lambda **_kwargs: ["bad", "shape"]})
    monkeypatch.setattr(service, "import_module", lambda _module_name: provider)

    with pytest.raises(TypeError, match="non-object payload"):
        getattr(service, function_name)()


@pytest.mark.parametrize(
    "value",
    ["2026-07-28", datetime(2026, 7, 28, tzinfo=UTC), None],
)
def test_default_target_date_provider_requires_plain_date(monkeypatch, value: object) -> None:
    provider = SimpleNamespace(resolve_default_readiness_target_date=lambda: value)
    monkeypatch.setattr(service, "import_module", lambda _module_name: provider)

    with pytest.raises(TypeError, match="invalid value"):
        service.resolve_default_readiness_target_date()


def test_default_target_date_provider_accepts_plain_date(monkeypatch) -> None:
    expected = date(2026, 7, 28)
    provider = SimpleNamespace(resolve_default_readiness_target_date=lambda: expected)
    monkeypatch.setattr(service, "import_module", lambda _module_name: provider)

    assert service.resolve_default_readiness_target_date() == expected


def test_corrupted_strict_cache_is_ignored(monkeypatch) -> None:
    class FakeCache:
        def get(self, _key: str) -> dict[str, object]:
            return {"status": "accepted", "window": {"accepted": True}}

        def set(self, *_args: object, **_kwargs: object) -> None:
            return None

    build_calls: list[dict[str, object]] = []
    monkeypatch.setattr(service, "cache", FakeCache())
    monkeypatch.setattr(service, "_get_data_coverage", service._empty_data_coverage)
    monkeypatch.setattr(service, "_get_operator_surfaces", service._empty_operator_surfaces)
    monkeypatch.setattr(service, "resolve_default_readiness_target_date", lambda: date(2026, 7, 28))

    def build_status(**kwargs: object) -> dict[str, object]:
        build_calls.append(kwargs)
        return _minimal_status_payload()

    monkeypatch.setattr(service, "build_personal_readiness_status", build_status)

    summary = service.get_personal_readiness_monitor_summary(strict_runtime=True)

    assert len(build_calls) == 1
    assert summary["status"] == "in_progress"
    assert summary["window"]["accepted"] is False


@pytest.mark.parametrize(
    ("helper_name", "dependency_name", "error_code"),
    [
        (
            "_get_ai_capability_surface",
            "get_ai_capability_surface_status_payload",
            "ai_capability_status_unavailable",
        ),
        (
            "_get_terminal_surface",
            "get_terminal_surface_status_payload",
            "terminal_status_unavailable",
        ),
        (
            "_get_data_coverage",
            "get_active_stock_fact_coverage_payload",
            "data_coverage_unavailable",
        ),
    ],
)
def test_dependency_failures_are_redacted(
    monkeypatch,
    caplog,
    helper_name: str,
    dependency_name: str,
    error_code: str,
) -> None:
    def fail_dependency() -> dict[str, object]:
        raise RuntimeError("postgresql://user:secret-password@host/db")

    monkeypatch.setattr(service, dependency_name, fail_dependency)

    payload = getattr(service, helper_name)()

    assert payload["status"] == "error"
    assert payload["error"] == error_code
    assert "secret-password" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"


def test_malformed_nested_sequences_do_not_become_false_positive_flags(monkeypatch) -> None:
    monkeypatch.setattr(service, "_get_data_coverage", service._empty_data_coverage)
    monkeypatch.setattr(service, "_get_operator_surfaces", service._empty_operator_surfaces)
    payload = _minimal_status_payload()
    payload["monitor_gate"] = {"ok": "false"}
    payload["acceptance_gate"] = {"accepted": "false"}
    payload["scheduler_runtime"] = {
        "required": "false",
        "missing_queues": "alpha,default",
    }
    payload["current_decision_data"] = {
        "must_not_use_for_decision": "false",
        "blocked_reasons": "secret detail",
    }
    payload["validation"] = "broken section"

    summary = service._summarize_personal_readiness_payload(payload)

    assert summary["monitor_gate"]["ok"] is False
    assert summary["window"]["accepted"] is False
    assert summary["daily_state"]["code"] == "needs_attention"
    assert summary["scheduler_runtime"]["required"] is False
    assert summary["scheduler_runtime"]["missing_queues"] == []
    assert summary["decision_data"]["must_not_use_for_decision"] is False
    assert summary["decision_data"]["blocked_reasons"] == []


def _minimal_status_payload() -> dict[str, object]:
    return {
        "status": "in_progress",
        "status_date": "2026-07-28",
        "latest_closed_date": "2026-07-28",
        "expected_latest_date": "2026-07-28",
        "validation": {
            "accepted_days": 1,
            "required_days": 20,
            "remaining_days": 19,
            "latest_target_date": "2026-07-28",
            "blocking_issues": [],
            "accepted_dates": ["2026-07-28"],
        },
        "latest_evidence": {"status": "ok", "target_date": "2026-07-28"},
        "acceptance_gate": {"accepted": False},
        "schedule_expectation": {"due_status": "pending"},
        "monitor_gate": {"ok": True},
        "next_action": {"action": "wait_for_post_close"},
        "scheduler_runtime": {"required": False, "status": "not_checked"},
        "current_decision_data": {"status": "blocked"},
    }
