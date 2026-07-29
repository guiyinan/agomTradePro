"""Prompt context and execution-evidence boundary invariants."""

from __future__ import annotations

from typing import Any

import pytest

from apps.prompt.application.context_builders import ContextBundleBuilder, MacroContextProvider
from apps.prompt.domain.context_entities import ContextSection
from apps.prompt.domain.entities import (
    ChainExecutionMode,
    ChainExecutionResult,
    PromptCategory,
    PromptExecutionResult,
    PromptTemplate,
)
from apps.prompt.infrastructure.fixtures.templates import load_predefined_templates
from apps.prompt.infrastructure.repositories import PromptRepositoryError


class _ExplodingProvider:
    domain_name = "macro"

    def build_summary(self, params: dict[str, Any]) -> Any:
        raise RuntimeError("database-password=private")

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        raise RuntimeError("database-password=private")

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        raise RuntimeError("database-password=private")


def test_context_builder_redacts_provider_exception_body(caplog: pytest.LogCaptureFixture) -> None:
    """Provider failures publish stable context and exception-class-only logs."""

    builder = ContextBundleBuilder()
    builder.register_provider(_ExplodingProvider())

    bundle = builder.build(["macro"])

    assert bundle.sections["macro"].summary == "macro 数据构建失败"
    assert "RuntimeError" in caplog.text
    assert "database-password" not in caplog.text


@pytest.mark.parametrize(
    ("scope", "params", "policy"),
    (
        ([], {}, "summary_plus_raw"),
        (["macro", "macro"], {}, "summary_plus_raw"),
        (["../secret"], {}, "summary_plus_raw"),
        (["macro"], {"x" * 129: 1}, "summary_plus_raw"),
        (["macro"], {"nested": {"api_token": "private"}}, "summary_plus_raw"),
        (["macro"], {"value": float("nan")}, "summary_plus_raw"),
        (["macro"], {}, "unbounded"),
    ),
)
def test_context_builder_rejects_invalid_dynamic_contracts(
    scope: list[str], params: dict[str, Any], policy: str
) -> None:
    """Dynamic runtime callers cannot bypass context bounds."""

    with pytest.raises(ValueError):
        ContextBundleBuilder().build(scope, params=params, policy=policy)


def test_macro_context_provider_does_not_log_adapter_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Recoverable adapter errors never disclose their message body."""

    class _Adapter:
        def get_macro_summary(self, **_kwargs: object) -> object:
            raise RuntimeError("api-token=private")

    assert MacroContextProvider(_Adapter()).build_summary({}) == "宏观数据获取失败"
    assert "RuntimeError" in caplog.text
    assert "api-token" not in caplog.text


@pytest.mark.parametrize(
    "kwargs",
    (
        {"temperature": float("nan")},
        {"temperature": True},
        {"max_tokens": True},
        {"max_tokens": 1_000_001},
    ),
)
def test_prompt_template_rejects_nonfinite_or_ambiguous_limits(
    kwargs: dict[str, object],
) -> None:
    """Template runtime settings remain finite and bounded."""

    values: dict[str, object] = {
        "id": None,
        "name": "bounded",
        "category": PromptCategory.CHAT,
        "version": "1",
        "template_content": "hello",
        "placeholders": [],
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        PromptTemplate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    (
        {"prompt_tokens": -1},
        {"total_tokens": 1},
        {"estimated_cost": float("inf")},
        {"response_time_ms": True},
    ),
)
def test_prompt_execution_result_rejects_invalid_accounting(
    overrides: dict[str, object],
) -> None:
    """Execution accounting evidence cannot contain ambiguous or non-finite values."""

    values: dict[str, object] = {
        "success": True,
        "content": "ok",
        "provider_used": "provider",
        "model_used": "model",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
        "estimated_cost": 0.1,
        "response_time_ms": 10,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        PromptExecutionResult(**values)  # type: ignore[arg-type]


def test_chain_execution_result_rejects_nonfinite_cost() -> None:
    """Aggregate evidence applies the same finite accounting contract."""

    with pytest.raises(ValueError, match="total_cost"):
        ChainExecutionResult(
            success=True,
            chain_name="chain",
            execution_mode=ChainExecutionMode.SERIAL,
            step_results={},
            total_cost=float("nan"),
        )


def test_fixture_loader_redacts_repository_exception_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Legacy fixture loading logs only repository exception classes."""

    class _Repository:
        def get_template_by_name(self, name: str) -> PromptTemplate | None:
            raise PromptRepositoryError("database-password=private")

        def create_template(self, template: PromptTemplate) -> PromptTemplate:
            return template

    assert load_predefined_templates(_Repository()) == 0
    assert "PromptRepositoryError" in caplog.text
    assert "database-password" not in caplog.text
