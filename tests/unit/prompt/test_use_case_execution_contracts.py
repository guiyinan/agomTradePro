"""Execution, fallback, and orchestration contracts for Prompt use cases."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.prompt.application.dtos import (
    ExecuteChainRequest,
    ExecutePromptRequest,
    ExecutePromptResponse,
    GenerateReportRequest,
    GenerateSignalRequest,
)
from apps.prompt.application.use_cases import (
    ExecuteChainUseCase,
    ExecutePromptUseCase,
    GenerateReportUseCase,
    GenerateSignalUseCase,
)
from apps.prompt.domain.agent_entities import AgentExecutionResponse
from apps.prompt.domain.entities import (
    ChainConfig,
    ChainExecutionMode,
    ChainExecutionResult,
    ChainStep,
    PlaceholderDef,
    PlaceholderType,
    PromptCategory,
    PromptTemplate,
)


def _prompt_response(
    content: str,
    *,
    success: bool = True,
    parsed_output: dict[str, object] | None = None,
    template_name: str = "template",
) -> ExecutePromptResponse:
    return ExecutePromptResponse(
        success=success,
        content=content,
        provider_used="provider",
        model_used="model",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        estimated_cost=0.25,
        response_time_ms=10,
        error_message=None if success else "failed",
        parsed_output=parsed_output,
        template_name=template_name,
    )


def _step(
    step_id: str,
    template_id: int,
    order: int,
    *,
    parallel_group: str | None = None,
    input_mapping: dict[str, str] | None = None,
) -> ChainStep:
    return ChainStep(
        step_id=step_id,
        template_id=str(template_id),
        step_name=step_id,
        order=order,
        input_mapping=input_mapping or {},
        parallel_group=parallel_group,
    )


def _chain(
    mode: ChainExecutionMode,
    steps: list[ChainStep],
    *,
    aggregate_step: ChainStep | None = None,
) -> ChainConfig:
    return ChainConfig(
        id="1",
        name=f"{mode.value}-chain",
        category=PromptCategory.DATA_ANALYSIS,
        description="contract",
        steps=steps,
        execution_mode=mode,
        aggregate_step=aggregate_step,
    )


def _chain_use_case(
    chain: ChainConfig | None,
    execute: object,
) -> tuple[ExecuteChainUseCase, Mock, Mock]:
    chain_repository = Mock()
    chain_repository.get_chain_by_id.return_value = chain
    prompt_use_case = Mock()
    prompt_use_case._resolve_provider_ref.side_effect = ExecutePromptUseCase._resolve_provider_ref
    prompt_use_case._resolve_user_ref.side_effect = ExecutePromptUseCase._resolve_user_ref
    prompt_use_case.execute.side_effect = execute
    return (
        ExecuteChainUseCase(chain_repository, prompt_use_case),
        chain_repository,
        prompt_use_case,
    )


def test_execute_prompt_resolves_user_macro_regime_and_function_values() -> None:
    placeholders = [
        PlaceholderDef("USER", PlaceholderType.SIMPLE, "user"),
        PlaceholderDef("PMI", PlaceholderType.STRUCTURED, "pmi", default_value=49),
        PlaceholderDef("REGIME", PlaceholderType.SIMPLE, "regime", default_value="MD"),
        PlaceholderDef(
            "TREND",
            PlaceholderType.FUNCTION,
            "trend",
            default_value="flat",
            function_name="trend",
            function_params={"period": 6},
        ),
        PlaceholderDef(
            "DEFAULT_FUNCTION",
            PlaceholderType.FUNCTION,
            "function without name",
            default_value="default-function",
        ),
    ]
    template = PromptTemplate(
        id="12",
        name="macro",
        category=PromptCategory.DATA_ANALYSIS,
        version="1.0",
        template_content=(
            "user={{USER}} pmi={{PMI}} regime={{REGIME}} "
            "trend={{TREND}} default={{DEFAULT_FUNCTION}}"
        ),
        placeholders=placeholders,
        system_prompt="system",
        temperature=0.3,
        max_tokens=400,
    )
    prompt_repository = Mock()
    prompt_repository.get_template_by_id.return_value = template
    log_repository = Mock()
    macro_adapter = Mock()
    macro_adapter.resolve_placeholder.side_effect = lambda name: (51.2 if name == "PMI" else None)
    regime_adapter = Mock()
    regime_adapter.resolve_placeholder.side_effect = lambda name: (
        "ME" if name == "REGIME" else None
    )
    client = Mock()
    client.chat_completion.return_value = {
        "status": "success",
        "content": '{"direction": "BUY"}',
        "provider_used": "provider",
        "model": "model",
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "estimated_cost": 0.12,
    }
    factory = Mock()
    factory.get_client.return_value = client
    function_executor = Mock()
    function_executor.execute_function.return_value = "up"

    with patch(
        "apps.prompt.application.use_cases.FunctionExecutor",
        return_value=function_executor,
    ):
        result = ExecutePromptUseCase(
            prompt_repository,
            log_repository,
            factory,
            macro_adapter,
            regime_adapter,
        ).execute(
            ExecutePromptRequest(
                template_id=12,
                placeholder_values={"USER": "alice"},
                provider_ref="primary",
                model="requested-model",
                temperature=0.8,
                max_tokens=123,
                user_id=7,
            )
        )

    assert result.success is True
    assert result.parsed_output == {"direction": "BUY"}
    assert result.template_name == "macro"
    factory.get_client.assert_called_once_with("primary", user=7)
    messages = client.chat_completion.call_args.kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "system"}
    assert "user=alice" in messages[1]["content"]
    assert "pmi=51.2" in messages[1]["content"]
    assert "regime=ME" in messages[1]["content"]
    assert "trend=up" in messages[1]["content"]
    assert "default=default-function" in messages[1]["content"]
    assert client.chat_completion.call_args.kwargs["temperature"] == 0.8
    assert client.chat_completion.call_args.kwargs["max_tokens"] == 123
    prompt_repository.update_last_used.assert_called_once_with(12)
    log_data = log_repository.create_log.call_args.args[0]
    assert log_data["status"] == "success"
    assert log_data["parsed_output"] == {"direction": "BUY"}
    function_executor.execute_function.assert_called_once_with("trend", {"period": 6})


def test_execute_prompt_uses_defaults_and_logs_provider_failure() -> None:
    template = PromptTemplate(
        id="13",
        name="fallback",
        category=PromptCategory.CHAT,
        version="1.0",
        template_content="{{VALUE}}",
        placeholders=[
            PlaceholderDef(
                "VALUE",
                PlaceholderType.SIMPLE,
                "value",
                default_value="unavailable",
            )
        ],
        temperature=0.0,
        max_tokens=50,
    )
    prompt_repository = Mock()
    prompt_repository.get_template_by_id.return_value = template
    log_repository = Mock()
    factory = Mock()
    client = Mock()
    client.chat_completion.return_value = {
        "status": "error",
        "error_message": "quota",
    }
    factory.get_client.return_value = client
    macro_adapter = Mock(resolve_placeholder=Mock(return_value=None))
    regime_adapter = Mock(resolve_placeholder=Mock(return_value=None))

    result = ExecutePromptUseCase(
        prompt_repository,
        log_repository,
        factory,
        macro_adapter,
        regime_adapter,
    ).execute(
        ExecutePromptRequest(
            template_id=13,
            placeholder_values={},
            provider_name="legacy",
        )
    )

    assert result.success is False
    assert result.error_message == "quota"
    factory.get_client.assert_called_once_with("legacy", user=None)
    assert client.chat_completion.call_args.kwargs["temperature"] == 0.0
    assert client.chat_completion.call_args.kwargs["max_tokens"] == 50
    assert log_repository.create_log.call_args.args[0]["status"] == "error"


def test_execute_prompt_missing_template_logs_error_and_reraises() -> None:
    prompt_repository = Mock()
    prompt_repository.get_template_by_id.return_value = None
    log_repository = Mock()
    use_case = ExecutePromptUseCase(
        prompt_repository,
        log_repository,
        Mock(),
        Mock(),
        Mock(),
    )

    with pytest.raises(ValueError, match="Template not found: 404"):
        use_case.execute(ExecutePromptRequest(template_id=404, placeholder_values={}))

    log = log_repository.create_log.call_args.args[0]
    assert log["template_id"] == 404
    assert log["status"] == "error"
    assert log["rendered_prompt"] == ""
    assert "Template not found" in log["error_message"]


def test_provider_and_user_resolution_support_dict_and_legacy_requests() -> None:
    assert (
        ExecutePromptUseCase._resolve_provider_ref(
            {"provider_ref": "preferred", "provider_name": "legacy"}
        )
        == "preferred"
    )
    assert ExecutePromptUseCase._resolve_provider_ref({"provider_name": "legacy"}) == "legacy"
    assert ExecutePromptUseCase._resolve_user_ref({"user_id": 12}) == 12
    assert (
        ExecutePromptUseCase._resolve_provider_ref(SimpleNamespace(provider_name="legacy"))
        == "legacy"
    )


def test_serial_chain_propagates_previous_output_and_aggregates_usage() -> None:
    chain = _chain(
        ChainExecutionMode.SERIAL,
        [
            _step("step1", 1, 1),
            _step(
                "step2",
                2,
                2,
                input_mapping={"prior": "step1.output.content"},
            ),
        ],
    )
    seen_requests: list[ExecutePromptRequest] = []

    def execute(request: ExecutePromptRequest) -> ExecutePromptResponse:
        seen_requests.append(request)
        return _prompt_response(f"content-{request.template_id}")

    use_case, repository, _prompt = _chain_use_case(chain, execute)

    result = use_case.execute(
        ExecuteChainRequest(
            chain_id=1,
            placeholder_values={"base": "value"},
            provider_ref="primary",
            user_id=9,
        )
    )

    repository.get_chain_by_id.assert_called_once_with(1)
    assert result.success is True
    assert result.final_output == "content-2"
    assert result.total_tokens == 10
    assert result.total_cost == 0.5
    assert result.step_results["step1"]["content"] == "content-1"
    assert seen_requests[1].placeholder_values["prior"] == {"content": "content-1"}
    assert all(request.provider_ref == "primary" for request in seen_requests)
    assert all(request.user_id == 9 for request in seen_requests)


def test_parallel_chain_runs_group_before_dependent_final_step() -> None:
    chain = _chain(
        ChainExecutionMode.PARALLEL,
        [
            _step("step1", 1, 1, parallel_group="analysis"),
            _step("step2", 2, 1, parallel_group="analysis"),
            _step(
                "step3",
                3,
                2,
                input_mapping={
                    "left_result": "step1.output.content",
                    "right_result": "step2.output.content",
                },
            ),
        ],
    )
    requests: dict[int, ExecutePromptRequest] = {}

    def execute(request: ExecutePromptRequest) -> ExecutePromptResponse:
        requests[request.template_id] = request
        return _prompt_response(f"content-{request.template_id}")

    use_case, _repository, _prompt = _chain_use_case(chain, execute)

    result = use_case.execute(
        ExecuteChainRequest(
            chain_id=1,
            placeholder_values={"base": "value"},
            provider_name="legacy",
            user_id=3,
        )
    )

    assert result.success is True
    assert result.final_output == "content-3"
    assert set(result.step_results) == {"step1", "step2", "step3"}
    assert requests[3].placeholder_values["left_result"] == {"content": "content-1"}
    assert requests[3].placeholder_values["right_result"] == {"content": "content-2"}
    assert requests[3].provider_ref == "legacy"


@pytest.mark.parametrize(
    "mode",
    [ChainExecutionMode.TOOL_CALLING, ChainExecutionMode.HYBRID],
)
def test_tool_and_hybrid_dispatch_return_stable_serialized_result(
    mode: ChainExecutionMode,
) -> None:
    chain = _chain(mode, [_step("tool", 1, 1)])
    use_case, _repository, _prompt = _chain_use_case(chain, Mock())
    chain_result = ChainExecutionResult(
        success=True,
        chain_name=chain.name,
        execution_mode=mode,
        step_results={"tool": _prompt_response("done")},
        final_output="done",
        total_tokens=5,
        total_cost=0.25,
        total_time_ms=10,
    )

    with patch.object(
        use_case,
        "_execute_tool_calling",
        return_value=chain_result,
    ) as tool_execution:
        result = use_case.execute(ExecuteChainRequest(chain_id=1, placeholder_values={}))

    tool_execution.assert_called_once()
    assert result.success is True
    assert result.execution_mode == mode.value
    assert result.final_output == "done"


def test_tool_calling_executes_runtime_and_plain_steps_with_safe_template_fallback() -> None:
    tool_step = ChainStep(
        step_id="step1",
        template_id="1",
        step_name="tool-step",
        order=1,
        input_mapping={},
        enable_tool_calling=True,
        available_tools=["market.lookup"],
    )
    plain_step = _step("step2", 2, 2)
    chain = _chain(ChainExecutionMode.TOOL_CALLING, [tool_step, plain_step])
    template = PromptTemplate(
        id="1",
        name="tool-template",
        category=PromptCategory.DATA_ANALYSIS,
        version="1.0",
        template_content="Analyze {{asset}}",
        placeholders=[],
        system_prompt="Use approved tools only",
    )
    prompt_use_case = Mock()
    prompt_use_case._resolve_provider_ref.side_effect = ExecutePromptUseCase._resolve_provider_ref
    prompt_use_case._resolve_user_ref.side_effect = ExecutePromptUseCase._resolve_user_ref
    prompt_use_case.prompt_repository.get_template_by_id.return_value = template
    prompt_use_case.execute.return_value = _prompt_response("plain-result")
    repository = Mock()
    repository.get_chain_by_id.return_value = chain
    runtime = Mock()
    runtime.execute.return_value = AgentExecutionResponse(
        success=True,
        final_answer="tool-result",
        structured_output={"content": "structured-tool-result"},
        provider_used="provider",
        model_used="model",
        total_tokens=6,
        prompt_tokens=4,
        completion_tokens=2,
        estimated_cost=0.4,
        response_time_ms=12,
    )
    use_case = ExecuteChainUseCase(repository, prompt_use_case)

    with (
        patch(
            "apps.prompt.application.runtime_provider.build_terminal_agent_runtime",
            return_value=runtime,
        ),
        patch(
            "apps.prompt.application.use_cases.get_ai_client_factory",
            return_value=Mock(),
        ),
    ):
        result = use_case.execute(
            ExecuteChainRequest(
                chain_id=1,
                placeholder_values={"asset": "000001.SZ"},
                provider_ref="primary",
                user_id=8,
            )
        )

    assert result.success is True
    assert result.final_output == "plain-result"
    assert result.total_tokens == 11
    agent_request = runtime.execute.call_args.args[0]
    assert agent_request.user_input == "Analyze 000001.SZ"
    assert agent_request.provider_ref == "primary"
    assert agent_request.tool_names == ["market.lookup"]
    assert agent_request.system_prompt == "Use approved tools only"
    assert result.step_results["step1"]["content"] == "tool-result"
    plain_request = prompt_use_case.execute.call_args.args[0]
    assert plain_request.template_id == 2
    assert plain_request.user_id == 8


def test_chain_missing_configuration_returns_explicit_failure_response() -> None:
    use_case, _repository, prompt = _chain_use_case(None, Mock())

    result = use_case.execute(ExecuteChainRequest(chain_id=404, placeholder_values={}))

    assert result.success is False
    assert result.chain_name == ""
    assert result.step_results == {}
    assert result.error_message == "chain_execution_failed"
    prompt.execute.assert_not_called()


def test_final_output_uses_chain_order_and_ignores_empty_results() -> None:
    chain = _chain(
        ChainExecutionMode.PARALLEL,
        [
            _step("first", 1, 1, parallel_group="group"),
            _step("second", 2, 1, parallel_group="group"),
        ],
    )

    assert ExecuteChainUseCase._resolve_final_output(chain, {}) is None
    assert (
        ExecuteChainUseCase._resolve_final_output(
            chain,
            {"first": {"content": "one"}, "second": {}},
        )
        == "one"
    )
    assert (
        ExecuteChainUseCase._resolve_final_output(
            chain,
            {"second": ["structured"]},
        )
        == "['structured']"
    )
    assert (
        ExecuteChainUseCase._resolve_final_output(
            chain,
            {"second": {"other": "value"}},
        )
        == "{'other': 'value'}"
    )


def test_report_and_signal_facades_forward_provider_user_and_safe_fallbacks() -> None:
    chain_use_case = Mock()
    chain_use_case.execute_named.side_effect = [
        SimpleNamespace(
            success=False,
            final_output=None,
            step_results={},
            total_tokens=8,
            total_cost=0.3,
            total_time_ms=20,
        ),
        SimpleNamespace(
            success=True,
            final_output="validated signal",
            step_results={
                "signal": {
                    "parsed_output": {
                        "direction": "LONG",
                        "logic_desc": "Momentum is strengthening",
                        "invalidation_logic": "Momentum turns negative",
                        "invalidation_threshold": -0.1,
                        "confidence": 0.8,
                        "target_regime": "Recovery",
                    }
                }
            },
            total_tokens=5,
            total_cost=0.2,
            total_time_ms=10,
        ),
    ]

    report = GenerateReportUseCase(chain_use_case).execute(
        GenerateReportRequest(
            as_of_date=date(2026, 7, 25),
            indicators=["PMI", "CPI"],
            provider_name="legacy",
            user_id=5,
        )
    )
    signal = GenerateSignalUseCase(chain_use_case).execute(
        GenerateSignalRequest(
            asset_code="000001.SZ",
            analysis_context={"score": 0.8},
            provider_ref="primary",
            user_id=6,
        )
    )

    assert report.report == "报告生成失败"
    assert report.metadata["tokens_used"] == 8
    report_request = chain_use_case.execute_named.call_args_list[0].kwargs
    assert report_request["chain_name"] == "investment_report_chain"
    assert report_request["placeholder_values"]["as_of_date"] == "2026-07-25"
    assert report_request["placeholder_values"]["indicators"] == ["PMI", "CPI"]
    assert report_request["provider_ref"] == "legacy"
    assert report_request["user_id"] == 5

    assert signal.asset_code == "000001.SZ"
    assert signal.success is True
    assert signal.direction == "LONG"
    assert signal.logic_desc == "Momentum is strengthening"
    assert signal.invalidation_logic == "Momentum turns negative"
    signal_request = chain_use_case.execute_named.call_args_list[1].kwargs
    assert signal_request["chain_name"] == "signal_validation_chain"
    assert signal_request["placeholder_values"] == {
        "asset_code": "000001.SZ",
        "score": 0.8,
    }
    assert signal_request["provider_ref"] == "primary"
    assert signal_request["user_id"] == 6
