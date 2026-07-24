"""Behavior tests for Prompt validation rules."""

from typing import cast

import pytest

from apps.prompt.domain.entities import ChainStep
from apps.prompt.domain.rules import (
    ValidationResult,
    validate_chain_steps,
    validate_function_params,
    validate_placeholder_name,
    validate_prompt_category,
    validate_temperature,
    validate_template_content,
)


def _step(
    step_id: str,
    order: int,
    *,
    input_mapping: dict[str, str] | None = None,
    parallel_group: str | None = None,
    enable_tool_calling: bool = False,
) -> ChainStep:
    """Create a bounded ChainStep fixture."""
    return ChainStep(
        step_id=step_id,
        template_id=f"template-{step_id}",
        step_name=step_id,
        order=order,
        input_mapping=input_mapping or {},
        parallel_group=parallel_group,
        enable_tool_calling=enable_tool_calling,
    )


def test_validation_result_builders_are_immutable() -> None:
    """Adding errors or warnings returns a new result without mutating the original."""
    success = ValidationResult.success()
    warned = success.add_warning("review")
    failed = warned.add_error("invalid")
    explicit_failure = ValidationResult.failure(["bad"], ["careful"])

    assert success == ValidationResult(is_valid=True, errors=[], warnings=[])
    assert warned == ValidationResult(is_valid=True, errors=[], warnings=["review"])
    assert failed == ValidationResult(
        is_valid=False,
        errors=["invalid"],
        warnings=["review"],
    )
    assert explicit_failure.warnings == ["careful"]


@pytest.mark.parametrize(
    ("content", "expected_error", "expected_warning"),
    [
        ("short", "模板内容过短", "模板未使用任何占位符"),
        ("long enough {{ value", "占位符数量不匹配", None),
        ("long enough {% if value", "模板语法数量不匹配", None),
        ("long enough {{ value }", "占位符数量不匹配", None),
        ("long enough plain content", None, "模板未使用任何占位符"),
        ("long enough {{ value }}", None, None),
    ],
)
def test_template_content_reports_syntax_and_placeholder_boundaries(
    content: str,
    expected_error: str | None,
    expected_warning: str | None,
) -> None:
    """Template validation reports syntax failures and non-blocking warnings separately."""
    result = validate_template_content(content)

    if expected_error is None:
        assert result.is_valid
    else:
        assert not result.is_valid
        assert any(expected_error in error for error in result.errors)
    if expected_warning is None:
        assert not result.warnings
    else:
        assert any(expected_warning in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("name", "is_valid"),
    [
        ("valid_name_2", True),
        ("", False),
        ("2invalid", False),
        ("invalid-dash", False),
        ("x" * 51, False),
    ],
)
def test_placeholder_names_enforce_identifier_contract(name: str, is_valid: bool) -> None:
    """Placeholder names follow the documented identifier and length contract."""
    assert validate_placeholder_name(name).is_valid is is_valid


def test_chain_steps_reject_empty_duplicate_and_cyclic_graphs() -> None:
    """The chain validator rejects missing steps, duplicate order, and dependency cycles."""
    assert validate_chain_steps([], "serial").errors == ["步骤列表不能为空"]

    duplicate = validate_chain_steps([_step("one", 1), _step("two", 1)], "serial")
    assert any("order必须唯一" in error for error in duplicate.errors)
    assert any("重复的order值" in error for error in duplicate.errors)

    cyclic = validate_chain_steps(
        [
            _step("one", 1, input_mapping={"value": "two.output.value"}),
            _step("two", 2, input_mapping={"value": "one.output.value"}),
        ],
        "serial",
    )
    assert cyclic.errors == ["检测到循环依赖：one -> two -> one"]


def test_chain_steps_warn_when_execution_mode_ignores_configuration() -> None:
    """Ignored parallel and tool configuration remains visible to callers."""
    result = validate_chain_steps(
        [
            _step("one", 1, parallel_group="parallel"),
            _step("two", 2, enable_tool_calling=True),
        ],
        "serial",
    )

    assert result.is_valid
    assert result.warnings == [
        "串行模式下配置了parallel_group，将被忽略",
        "非工具调用模式下配置了enable_tool_calling，将被忽略",
    ]
    assert not validate_chain_steps([_step("tool", 1, enable_tool_calling=True)], "hybrid").warnings


@pytest.mark.parametrize(
    ("value", "is_valid"), [(0.0, True), (2.0, True), (-0.1, False), (2.1, False)]
)
def test_temperature_boundaries(value: float, is_valid: bool) -> None:
    """Temperature accepts the inclusive 0-2 interval only."""
    assert validate_temperature(value).is_valid is is_valid


def test_function_parameters_validate_container_and_each_name() -> None:
    """Function parameters must be a mapping whose keys are valid placeholders."""
    wrong_container = validate_function_params(cast(dict[str, object], ["not", "mapping"]))
    invalid_key = validate_function_params({"2bad": 1, "good": 2})

    assert wrong_container.errors == ["函数参数必须是字典类型"]
    assert not invalid_key.is_valid
    assert invalid_key.errors[0].startswith("函数参数 2bad:")
    assert validate_function_params({"good": 2}).is_valid


@pytest.mark.parametrize(
    ("category", "is_valid"),
    [("report", True), ("signal", True), ("analysis", True), ("chat", True), ("unknown", False)],
)
def test_prompt_categories_are_closed(category: str, is_valid: bool) -> None:
    """Unknown categories never silently map to a business category."""
    result = validate_prompt_category(category)

    assert result.is_valid is is_valid
    if not is_valid:
        assert result.errors == [
            "无效的分类：unknown，有效值：['report', 'signal', 'analysis', 'chat']"
        ]
