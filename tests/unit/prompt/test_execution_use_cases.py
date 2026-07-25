"""Prompt execution and chain orchestration contracts."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from apps.prompt.application.dtos import (
    ExecuteChainRequest,
    ExecutePromptRequest,
    ExecutePromptResponse,
    GenerateReportRequest,
)
from apps.prompt.application.use_cases import (
    ExecuteChainUseCase,
    ExecutePromptUseCase,
    GenerateReportUseCase,
)
from apps.prompt.domain.entities import (
    ChainConfig,
    ChainExecutionMode,
    ChainStep,
    PromptCategory,
    PromptTemplate,
)


def _prompt_response(*, parsed_output: dict[str, object] | None = None) -> ExecutePromptResponse:
    return ExecutePromptResponse(
        success=True,
        content="answer",
        provider_used="configured-provider",
        model_used="configured-model",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        estimated_cost=0.01,
        response_time_ms=8,
        error_message=None,
        parsed_output=parsed_output,
        template_name="test-template",
    )


def test_execute_prompt_preserves_zero_temperature_and_configured_model_default() -> None:
    template = PromptTemplate(
        id="1",
        name="test-template",
        category=PromptCategory.DATA_ANALYSIS,
        version="1.0",
        template_content="Analyze {{ value }}",
        placeholders=[],
        temperature=0.7,
        max_tokens=256,
    )
    prompt_repository = Mock()
    prompt_repository.get_template_by_id.return_value = template
    ai_client = Mock()
    ai_client.chat_completion.return_value = {
        "status": "success",
        "content": "answer",
        "provider_used": "configured-provider",
        "model": "configured-model",
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "estimated_cost": 0.01,
    }
    factory = Mock()
    factory.get_client.return_value = ai_client
    use_case = ExecutePromptUseCase(
        prompt_repository=prompt_repository,
        execution_log_repository=Mock(),
        ai_client_factory=factory,
        macro_adapter=Mock(resolve_placeholder=Mock(return_value=None)),
        regime_adapter=Mock(resolve_placeholder=Mock(return_value=None)),
    )

    result = use_case.execute(
        ExecutePromptRequest(
            template_id=1,
            placeholder_values={"value": "PMI"},
            temperature=0.0,
        )
    )

    assert result.success is True
    ai_client.chat_completion.assert_called_once()
    call = ai_client.chat_completion.call_args.kwargs
    assert call["model"] is None
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 256


def test_serial_chain_accepts_structured_final_output_without_content_key() -> None:
    chain = ChainConfig(
        id="7",
        name="structured-chain",
        category=PromptCategory.DATA_ANALYSIS,
        description="",
        steps=[
            ChainStep(
                step_id="step1",
                template_id="1",
                step_name="structured",
                order=1,
                input_mapping={},
            )
        ],
        execution_mode=ChainExecutionMode.SERIAL,
    )
    chain_repository = Mock()
    chain_repository.get_chain_by_id.return_value = chain
    prompt_use_case = Mock()
    prompt_use_case._resolve_provider_ref.return_value = None
    prompt_use_case._resolve_user_ref.return_value = None
    prompt_use_case.execute.return_value = _prompt_response(parsed_output={"score": 0.8})

    result = ExecuteChainUseCase(chain_repository, prompt_use_case).execute(
        ExecuteChainRequest(chain_id=7, placeholder_values={})
    )

    assert result.success is True
    assert result.final_output == "{'score': 0.8}"
    assert result.step_results["step1"]["total_tokens"] == 5


def test_chain_failure_does_not_expose_internal_exception_details() -> None:
    repository = Mock()
    repository.get_chain_by_id.side_effect = RuntimeError("postgresql://secret@internal-db")
    use_case = ExecuteChainUseCase(repository, Mock())

    result = use_case.execute(ExecuteChainRequest(chain_id=1, placeholder_values={}))

    assert result.success is False
    assert result.error_message == "chain_execution_failed"
    assert "secret@internal-db" not in str(result)


def test_generate_report_resolves_chain_by_configured_name() -> None:
    chain_use_case = Mock()
    chain_use_case.execute_named.return_value = SimpleNamespace(
        final_output="report",
        total_tokens=5,
        total_cost=0.01,
        total_time_ms=8,
    )

    result = GenerateReportUseCase(chain_use_case).execute(
        GenerateReportRequest(as_of_date=date(2026, 7, 26))
    )

    assert result.report == "report"
    chain_use_case.execute_named.assert_called_once()
    assert chain_use_case.execute_named.call_args.kwargs["chain_name"] == "investment_report_chain"
