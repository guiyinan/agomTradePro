"""
Use Cases for AI Prompt Management.

Orchestration layer that coordinates components from Domain and Infrastructure layers.
"""

import logging
import time
import uuid
from dataclasses import replace
from datetime import date
from typing import Any

from apps.ai_provider.application.chat_completion import AIClientFactoryProtocol
from apps.ai_provider.application.client_provider import get_ai_client_factory
from apps.regime.domain.services_v2 import RegimeType
from shared.numeric import safe_float

from ..domain.entities import (
    ChainConfig,
    ChainExecutionMode,
    ChainExecutionResult,
    ChainStep,
    PlaceholderDef,
    PlaceholderType,
    PromptExecutionResult,
)
from ..domain.services import ChainExecutor, OutputParser, TemplateRenderer
from .dtos import (
    ExecuteChainRequest,
    ExecuteChainResponse,
    ExecutePromptRequest,
    ExecutePromptResponse,
    GenerateReportRequest,
    GenerateReportResponse,
    GenerateSignalRequest,
    GenerateSignalResponse,
)
from .repository_provider import (
    DjangoChainRepository,
    DjangoExecutionLogRepository,
    DjangoPromptRepository,
    FunctionExecutor,
    MacroDataAdapter,
    RegimeDataAdapter,
)

logger = logging.getLogger(__name__)


class ExecutePromptUseCase:
    """
    执行单个Prompt的用例

    负责加载模板、解析占位符、渲染模板、调用AI、记录日志。
    """

    def __init__(
        self,
        prompt_repository: DjangoPromptRepository,
        execution_log_repository: DjangoExecutionLogRepository,
        ai_client_factory: AIClientFactoryProtocol,
        macro_adapter: MacroDataAdapter,
        regime_adapter: RegimeDataAdapter,
    ):
        self.prompt_repository = prompt_repository
        self.execution_log_repository = execution_log_repository
        self.ai_client_factory = ai_client_factory
        self.macro_adapter = macro_adapter
        self.regime_adapter = regime_adapter
        self.renderer = TemplateRenderer()

    def execute(self, request: ExecutePromptRequest) -> ExecutePromptResponse:
        """
        执行Prompt模板

        流程：
        1. 加载模板
        2. 解析占位符，从数据库获取数据
        3. 渲染模板
        4. 调用AI API
        5. 记录日志
        6. 返回结果
        """
        execution_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            # 1. 加载模板
            template = self.prompt_repository.get_template_by_id(request.template_id)
            if not template:
                raise ValueError(f"Template not found: {request.template_id}")

            # 2. 解析占位符
            resolved_values = self._resolve_placeholders(
                template.placeholders, request.placeholder_values
            )

            # 3. 渲染模板
            # 合并用户提供的值和解析的值
            all_values = {**request.placeholder_values, **resolved_values}
            rendered_prompt = self.renderer.render_simple(template.template_content, all_values)

            # 4. 调用AI
            ai_client = self.ai_client_factory.get_client(
                self._resolve_provider_ref(request),
                user=self._resolve_user_ref(request),
            )
            ai_response = ai_client.chat_completion(
                messages=[
                    {"role": "system", "content": template.system_prompt or ""},
                    {"role": "user", "content": rendered_prompt},
                ],
                model=request.model,
                temperature=(
                    request.temperature if request.temperature is not None else template.temperature
                ),
                max_tokens=(
                    request.max_tokens if request.max_tokens is not None else template.max_tokens
                ),
            )

            # 计算执行时间
            response_time_ms = int((time.time() - start_time) * 1000)

            # 构建结果
            result = PromptExecutionResult(
                success=(ai_response.get("status") == "success"),
                content=ai_response.get("content", ""),
                provider_used=ai_response.get("provider_used", ""),
                model_used=ai_response.get("model", ""),
                prompt_tokens=ai_response.get("prompt_tokens", 0),
                completion_tokens=ai_response.get("completion_tokens", 0),
                total_tokens=ai_response.get("total_tokens", 0),
                estimated_cost=ai_response.get("estimated_cost", 0.0),
                response_time_ms=response_time_ms,
                error_message=ai_response.get("error_message"),
            )

            # 解析结构化输出
            if result.success:
                parsed = OutputParser.extract_json(result.content)
                result = PromptExecutionResult(**{**result.__dict__, "parsed_output": parsed})

            # 5. 记录日志
            self._log_execution(
                execution_id=execution_id,
                template_id=request.template_id,
                placeholder_values=all_values,
                rendered_prompt=rendered_prompt,
                result=result,
            )

            # 6. 更新模板最后使用时间
            self.prompt_repository.update_last_used(request.template_id)

            return ExecutePromptResponse(
                success=result.success,
                content=result.content,
                provider_used=result.provider_used,
                model_used=result.model_used,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                estimated_cost=result.estimated_cost,
                response_time_ms=result.response_time_ms,
                error_message=result.error_message,
                parsed_output=result.parsed_output,
                template_name=template.name,
            )

        except Exception as e:
            # 记录错误
            response_time_ms = int((time.time() - start_time) * 1000)
            self._log_error(execution_id, request.template_id, str(e), response_time_ms)
            raise

    @staticmethod
    def _resolve_provider_ref(request: Any) -> Any:
        """Support both provider_ref and the legacy provider_name field."""
        if isinstance(request, dict):
            provider_ref = request.get("provider_ref")
            return provider_ref if provider_ref is not None else request.get("provider_name")
        provider_ref = getattr(request, "provider_ref", None)
        return provider_ref if provider_ref is not None else getattr(request, "provider_name", None)

    @staticmethod
    def _resolve_user_ref(request: Any) -> Any:
        """Extract requesting user/user_id for user-aware provider routing."""
        if isinstance(request, dict):
            return request.get("user_id")
        return getattr(request, "user_id", None)

    def _resolve_placeholders(
        self, placeholders: list[PlaceholderDef], user_values: dict[str, Any]
    ) -> dict[str, Any]:
        """解析占位符"""
        resolved: dict[str, Any] = {}

        for ph in placeholders:
            # 优先使用用户提供的值
            if ph.name in user_values:
                resolved[ph.name] = user_values[ph.name]
                continue

            # 根据类型解析
            if ph.type == PlaceholderType.FUNCTION:
                resolved[ph.name] = self._execute_function(ph)
            else:
                resolved[ph.name] = self._fetch_data(ph)

        return resolved

    def _fetch_data(self, placeholder: PlaceholderDef) -> Any:
        """获取数据"""
        # 尝试从宏观数据获取
        value = self.macro_adapter.resolve_placeholder(placeholder.name)
        if value is not None:
            return value

        # 尝试从Regime获取
        value = self.regime_adapter.resolve_placeholder(placeholder.name)
        if value is not None:
            return value

        # 返回默认值
        return placeholder.default_value

    def _execute_function(self, placeholder: PlaceholderDef) -> Any:
        """执行函数占位符"""
        if not placeholder.function_name:
            return placeholder.default_value

        # 使用FunctionExecutor
        executor = FunctionExecutor(self.macro_adapter)
        return executor.execute_function(
            placeholder.function_name, placeholder.function_params or {}
        )

    def _log_execution(
        self,
        execution_id: str,
        template_id: int,
        placeholder_values: dict[str, Any],
        rendered_prompt: str,
        result: PromptExecutionResult,
    ) -> None:
        """记录执行日志"""
        log_data = {
            "execution_id": execution_id,
            "template_id": template_id,
            "placeholder_values": placeholder_values,
            "rendered_prompt": rendered_prompt,
            "ai_response": result.content,
            "parsed_output": result.parsed_output,
            "response_time_ms": result.response_time_ms,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "estimated_cost": result.estimated_cost,
            "provider_used": result.provider_used,
            "model_used": result.model_used,
            "status": "success" if result.success else "error",
            "error_message": result.error_message,
        }
        self.execution_log_repository.create_log(log_data)

    def _log_error(
        self,
        execution_id: str,
        template_id: int,
        error: str,
        response_time_ms: int,
    ) -> None:
        """记录错误日志"""
        log_data = {
            "execution_id": execution_id,
            "template_id": template_id,
            "placeholder_values": {},
            "rendered_prompt": "",
            "ai_response": "",
            "response_time_ms": response_time_ms,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0,
            "status": "error",
            "error_message": error,
        }
        self.execution_log_repository.create_log(log_data)


class ExecuteChainUseCase:
    """
    执行链式Prompt的用例

    根据execution_mode决定执行策略。
    """

    def __init__(
        self, chain_repository: DjangoChainRepository, prompt_use_case: ExecutePromptUseCase
    ):
        self.chain_repository = chain_repository
        self.prompt_use_case = prompt_use_case
        self.executor = ChainExecutor()

    def execute(self, request: ExecuteChainRequest) -> ExecuteChainResponse:
        """
        执行链式Prompt

        根据execution_mode决定执行策略：
        - SERIAL: 依次执行
        - PARALLEL: 并行执行+汇总
        - TOOL_CALLING: 工具调用模式
        """
        start_time = time.time()

        try:
            # 加载链配置
            chain = self.chain_repository.get_chain_by_id(request.chain_id)
            if not chain:
                raise ValueError(f"Chain not found: {request.chain_id}")

            # 根据模式执行
            if chain.execution_mode == ChainExecutionMode.SERIAL:
                chain_result = self._execute_serial(chain, request)
            elif chain.execution_mode == ChainExecutionMode.PARALLEL:
                chain_result = self._execute_parallel(chain, request)
            elif chain.execution_mode == ChainExecutionMode.TOOL_CALLING:
                chain_result = self._execute_tool_calling(chain, request)
            else:  # HYBRID
                chain_result = self._execute_hybrid(chain, request)

            # 计算总时间
            total_time_ms = int((time.time() - start_time) * 1000)
            chain_result = replace(chain_result, total_time_ms=total_time_ms)

            return ExecuteChainResponse(
                success=chain_result.success,
                chain_name=chain_result.chain_name,
                execution_mode=chain_result.execution_mode.value,
                step_results=self._serialize_step_results(chain_result.step_results),
                final_output=chain_result.final_output,
                total_tokens=chain_result.total_tokens,
                total_cost=chain_result.total_cost,
                total_time_ms=chain_result.total_time_ms,
                error_message=chain_result.error_message,
            )

        except Exception:
            logger.exception("Prompt chain execution failed")
            return ExecuteChainResponse(
                success=False,
                chain_name="",
                execution_mode="",
                step_results={},
                final_output=None,
                total_tokens=0,
                total_cost=0.0,
                total_time_ms=int((time.time() - start_time) * 1000),
                error_message="chain_execution_failed",
            )

    def execute_named(
        self,
        *,
        chain_name: str,
        placeholder_values: dict[str, Any],
        provider_ref: Any | None = None,
        model: str | None = None,
        user_id: int | None = None,
    ) -> ExecuteChainResponse:
        """Resolve an active chain by its configured name and execute it."""

        chain = self.chain_repository.get_chain_by_name(chain_name)
        if chain is None or not chain.is_active or chain.id is None:
            return ExecuteChainResponse(
                success=False,
                chain_name=chain_name,
                execution_mode="",
                step_results={},
                final_output=None,
                total_tokens=0,
                total_cost=0.0,
                total_time_ms=0,
                error_message="chain_unavailable",
            )
        try:
            chain_id = int(chain.id)
        except (TypeError, ValueError):
            logger.error("Prompt chain %s has an invalid persisted ID", chain_name)
            return ExecuteChainResponse(
                success=False,
                chain_name=chain_name,
                execution_mode="",
                step_results={},
                final_output=None,
                total_tokens=0,
                total_cost=0.0,
                total_time_ms=0,
                error_message="chain_unavailable",
            )
        return self.execute(
            ExecuteChainRequest(
                chain_id=chain_id,
                placeholder_values=placeholder_values,
                provider_ref=provider_ref,
                model=model,
                user_id=user_id,
            )
        )

    @staticmethod
    def _to_domain_result(response: ExecutePromptResponse) -> PromptExecutionResult:
        """Convert the Application response into the Domain chain result type."""

        return PromptExecutionResult(
            success=response.success,
            content=response.content,
            provider_used=response.provider_used,
            model_used=response.model_used,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            estimated_cost=response.estimated_cost,
            response_time_ms=response.response_time_ms,
            error_message=response.error_message,
            parsed_output=response.parsed_output,
        )

    def _execute_serial(
        self, chain: ChainConfig, request: ExecuteChainRequest
    ) -> ChainExecutionResult:
        """串行执行"""
        step_results: dict[str, PromptExecutionResult] = {}
        accumulated_output: dict[str, Any] = {}

        for step in sorted(chain.steps, key=lambda s: s.order):
            # 构建步骤上下文
            step_context = self._build_step_context(
                step, request.placeholder_values, accumulated_output
            )

            # 执行步骤
            step_request = ExecutePromptRequest(
                template_id=int(step.template_id),
                placeholder_values=step_context,
                provider_ref=self.prompt_use_case._resolve_provider_ref(request),
                user_id=self.prompt_use_case._resolve_user_ref(request),
            )
            step_response = self.prompt_use_case.execute(step_request)
            domain_result = self._to_domain_result(step_response)

            step_results[step.step_id] = domain_result

            # 保存输出
            if step_response.success:
                accumulated_output[step.step_id] = step_response.parsed_output or {
                    "content": step_response.content
                }

        return ChainExecutionResult(
            success=all(r.success for r in step_results.values()),
            chain_name=chain.name,
            execution_mode=chain.execution_mode,
            step_results=step_results,
            final_output=(self._resolve_final_output(chain, accumulated_output)),
            total_tokens=sum(r.total_tokens for r in step_results.values()),
            total_cost=sum(r.estimated_cost for r in step_results.values()),
            total_time_ms=sum(r.response_time_ms for r in step_results.values()),
        )

    def _execute_parallel(
        self, chain: ChainConfig, request: ExecuteChainRequest
    ) -> ChainExecutionResult:
        """并行执行 - 按 parallel_group 分组，组内并行（concurrent.futures），组间串行。"""
        from collections import defaultdict
        from concurrent.futures import ThreadPoolExecutor, as_completed

        step_results: dict[str, PromptExecutionResult] = {}
        accumulated_output: dict[str, Any] = {}

        # 按 parallel_group 和 order 分组
        groups: dict[str | None, list[ChainStep]] = defaultdict(list)
        for step in sorted(chain.steps, key=lambda s: s.order):
            groups[step.parallel_group].append(step)

        # 按 order 排序组
        sorted_groups = sorted(groups.items(), key=lambda g: min(s.order for s in g[1]))

        for group_key, steps in sorted_groups:
            if group_key is None or len(steps) == 1:
                # 非并行步骤或单步骤组：串行执行
                for step in steps:
                    step_context = self._build_step_context(
                        step, request.placeholder_values, accumulated_output
                    )
                    step_request = ExecutePromptRequest(
                        template_id=int(step.template_id),
                        placeholder_values=step_context,
                        provider_ref=self.prompt_use_case._resolve_provider_ref(request),
                        user_id=self.prompt_use_case._resolve_user_ref(request),
                    )
                    step_response = self.prompt_use_case.execute(step_request)
                    step_results[step.step_id] = self._to_domain_result(step_response)
                    if step_response.success:
                        accumulated_output[step.step_id] = step_response.parsed_output or {
                            "content": step_response.content
                        }
            else:
                # 并行组：使用线程池并行执行
                def _run_step(s: ChainStep) -> tuple[str, ExecutePromptResponse]:
                    ctx = self._build_step_context(
                        s, request.placeholder_values, accumulated_output
                    )
                    req = ExecutePromptRequest(
                        template_id=int(s.template_id),
                        placeholder_values=ctx,
                        provider_ref=self.prompt_use_case._resolve_provider_ref(request),
                        user_id=self.prompt_use_case._resolve_user_ref(request),
                    )
                    return s.step_id, self.prompt_use_case.execute(req)

                with ThreadPoolExecutor() as executor:
                    futures = {executor.submit(_run_step, step): step for step in steps}
                    for future in as_completed(futures):
                        step_id, step_response = future.result()
                        step_results[step_id] = self._to_domain_result(step_response)
                        if step_response.success:
                            accumulated_output[step_id] = step_response.parsed_output or {
                                "content": step_response.content
                            }

        return ChainExecutionResult(
            success=all(r.success for r in step_results.values()),
            chain_name=chain.name,
            execution_mode=chain.execution_mode,
            step_results=step_results,
            final_output=self._resolve_final_output(chain, accumulated_output),
            total_tokens=sum(r.total_tokens for r in step_results.values()),
            total_cost=sum(r.estimated_cost for r in step_results.values()),
            total_time_ms=sum(r.response_time_ms for r in step_results.values()),
        )

    def _execute_tool_calling(
        self, chain: ChainConfig, request: ExecuteChainRequest
    ) -> ChainExecutionResult:
        """工具调用模式 - 使用 AgentRuntime 执行真正的 tool calling。"""
        from ..domain.agent_entities import AgentExecutionRequest
        from .runtime_provider import build_terminal_agent_runtime

        step_results: dict[str, PromptExecutionResult] = {}
        accumulated_output: dict[str, Any] = {}

        for step in sorted(chain.steps, key=lambda s: s.order):
            if step.enable_tool_calling and step.available_tools:
                # 使用 AgentRuntime 执行工具调用步骤
                step_context = self._build_step_context(
                    step, request.placeholder_values, accumulated_output
                )

                # 加载模板以获取 system prompt
                template = None
                try:
                    template = self.prompt_use_case.prompt_repository.get_template_by_id(
                        int(step.template_id)
                    )
                except Exception:
                    pass

                runtime = build_terminal_agent_runtime(get_ai_client_factory())

                # 构建用户输入
                user_input = step_context.get("user_input", "")
                if not user_input and template:
                    from ..domain.services import TemplateRenderer

                    renderer = TemplateRenderer()
                    user_input = renderer.render_simple(template.template_content, step_context)

                agent_request = AgentExecutionRequest(
                    task_type="tool_calling",
                    user_input=user_input,
                    provider_ref=self.prompt_use_case._resolve_provider_ref(request),
                    tool_names=step.available_tools,
                    system_prompt=template.system_prompt if template else None,
                    max_rounds=4,
                )

                agent_response = runtime.execute(agent_request)

                # 转为 ExecutePromptResponse 兼容格式
                from .dtos import ExecutePromptResponse

                step_response = ExecutePromptResponse(
                    success=agent_response.success,
                    content=agent_response.final_answer or "",
                    provider_used=agent_response.provider_used or "",
                    model_used=agent_response.model_used or "",
                    prompt_tokens=agent_response.prompt_tokens,
                    completion_tokens=agent_response.completion_tokens,
                    total_tokens=agent_response.total_tokens,
                    estimated_cost=agent_response.estimated_cost,
                    response_time_ms=agent_response.response_time_ms,
                    error_message=agent_response.error_message,
                    parsed_output=agent_response.structured_output,
                    template_name=template.name if template else step.step_name,
                )
            else:
                # 非工具调用步骤：普通执行
                step_context = self._build_step_context(
                    step, request.placeholder_values, accumulated_output
                )
                step_request = ExecutePromptRequest(
                    template_id=int(step.template_id),
                    placeholder_values=step_context,
                    provider_ref=self.prompt_use_case._resolve_provider_ref(request),
                    user_id=self.prompt_use_case._resolve_user_ref(request),
                )
                step_response = self.prompt_use_case.execute(step_request)

            step_results[step.step_id] = self._to_domain_result(step_response)
            if step_response.success:
                accumulated_output[step.step_id] = step_response.parsed_output or {
                    "content": step_response.content
                }

        return ChainExecutionResult(
            success=all(r.success for r in step_results.values()),
            chain_name=chain.name,
            execution_mode=chain.execution_mode,
            step_results=step_results,
            final_output=self._resolve_final_output(chain, accumulated_output),
            total_tokens=sum(r.total_tokens for r in step_results.values()),
            total_cost=sum(r.estimated_cost for r in step_results.values()),
            total_time_ms=sum(r.response_time_ms for r in step_results.values()),
        )

    def _execute_hybrid(
        self, chain: ChainConfig, request: ExecuteChainRequest
    ) -> ChainExecutionResult:
        """混合模式 - 按步骤配置决定是否走工具调用。

        步骤中 enable_tool_calling=True 的走 AgentRuntime，
        其余走普通串行执行。逻辑与 _execute_tool_calling 相同。
        """
        return self._execute_tool_calling(chain, request)

    @staticmethod
    def _resolve_final_output(
        chain: ChainConfig,
        accumulated_output: dict[str, Any],
    ) -> str | None:
        """
        Resolve final output by chain order, not completion order.

        This keeps parallel execution deterministic even when steps in the
        last parallel group finish in different orders.
        """
        if not accumulated_output:
            return None

        sorted_steps = sorted(chain.steps, key=lambda s: (s.order, s.step_id))
        for step in reversed(sorted_steps):
            step_output = accumulated_output.get(step.step_id)
            if not step_output:
                continue
            if isinstance(step_output, dict):
                content = step_output.get("content")
                if content is not None:
                    return str(content)
            return str(step_output)
        return None

    def _build_step_context(
        self,
        step: ChainStep,
        base_values: dict[str, Any],
        accumulated_output: dict[str, Any],
    ) -> dict[str, Any]:
        """构建步骤上下文"""
        context = base_values.copy()

        # 解析input_mapping
        for key, value_ref in step.input_mapping.items():
            if isinstance(value_ref, str) and value_ref.startswith("step"):
                parts = value_ref.split(".")
                if len(parts) >= 3:
                    step_id = parts[0]
                    if step_id in accumulated_output:
                        context[key] = accumulated_output[step_id]

        return context

    def _serialize_step_results(
        self, step_results: dict[str, PromptExecutionResult]
    ) -> dict[str, dict[str, Any]]:
        """序列化步骤结果"""
        return {
            step_id: {
                "success": r.success,
                "content": r.content,
                "total_tokens": r.total_tokens,
                "estimated_cost": r.estimated_cost,
                "response_time_ms": r.response_time_ms,
                "error_message": r.error_message,
                "parsed_output": r.parsed_output,
            }
            for step_id, r in step_results.items()
        }


class GenerateReportUseCase:
    """
    生成投资分析报告的用例
    """

    def __init__(self, chain_use_case: ExecuteChainUseCase):
        self.chain_use_case = chain_use_case

    def execute(self, request: GenerateReportRequest) -> GenerateReportResponse:
        """
        生成投资分析报告

        流程：
        1. 准备数据上下文
        2. 执行报告生成链
        3. 返回报告
        """
        # 构建初始上下文
        placeholder_values = {
            "as_of_date": request.as_of_date.isoformat(),
            "include_regime": request.include_regime,
            "include_policy": request.include_policy,
            "include_macro": request.include_macro,
        }

        if request.indicators:
            placeholder_values["indicators"] = request.indicators

        chain_result = self.chain_use_case.execute_named(
            chain_name="investment_report_chain",
            placeholder_values=placeholder_values,
            provider_ref=request.provider_ref or request.provider_name,
            model=request.model,
            user_id=getattr(request, "user_id", None),
        )

        return GenerateReportResponse(
            report=chain_result.final_output or "报告生成失败",
            metadata={
                "generated_at": date.today().isoformat(),
                "tokens_used": chain_result.total_tokens,
                "cost": chain_result.total_cost,
                "time_ms": chain_result.total_time_ms,
            },
        )


class GenerateSignalUseCase:
    """
    生成投资信号的用例（AI分析+证伪逻辑）
    """

    def __init__(self, chain_use_case: ExecuteChainUseCase):
        self.chain_use_case = chain_use_case

    def execute(self, request: GenerateSignalRequest) -> GenerateSignalResponse:
        """
        AI自动生成投资信号

        流程：
        1. 调用信号生成链
        2. 解析AI输出
        3. 返回信号数据
        """
        placeholder_values = {"asset_code": request.asset_code, **request.analysis_context}

        chain_result = self.chain_use_case.execute_named(
            chain_name="signal_validation_chain",
            placeholder_values=placeholder_values,
            provider_ref=request.provider_ref or request.provider_name,
            user_id=request.user_id,
        )
        if not chain_result.success:
            return self._failed_signal(request.asset_code, "signal_chain_failed")

        parsed_output: dict[str, Any] | None = None
        for step_result in chain_result.step_results.values():
            candidate = step_result.get("parsed_output")
            if isinstance(candidate, dict):
                parsed_output = candidate
                break
        if parsed_output is None:
            return self._failed_signal(request.asset_code, "signal_output_invalid")

        direction = str(parsed_output.get("direction") or "").strip().upper()
        logic_desc = str(parsed_output.get("logic_desc") or "").strip()
        invalidation_logic = str(parsed_output.get("invalidation_logic") or "").strip()
        invalidation_threshold = safe_float(parsed_output.get("invalidation_threshold"))
        confidence = safe_float(parsed_output.get("confidence"))
        regime_lookup = {regime.value.casefold(): regime.value for regime in RegimeType}
        target_regime = regime_lookup.get(
            str(parsed_output.get("target_regime") or "").strip().casefold()
        )
        invalidation_placeholder = invalidation_logic.casefold() in {
            "",
            "none",
            "n/a",
            "待完善",
            "无",
        }

        if (
            direction not in {"LONG", "SHORT", "NEUTRAL"}
            or not logic_desc
            or invalidation_placeholder
            or invalidation_threshold is None
            or confidence is None
            or not 0 <= confidence <= 1
            or target_regime is None
        ):
            return self._failed_signal(request.asset_code, "signal_output_invalid")

        return GenerateSignalResponse(
            asset_code=request.asset_code,
            direction=direction,
            logic_desc=logic_desc,
            invalidation_logic=invalidation_logic,
            invalidation_threshold=invalidation_threshold,
            target_regime=target_regime,
            confidence=confidence,
            success=True,
            must_not_use_for_decision=False,
            error_code=None,
        )

    @staticmethod
    def _failed_signal(asset_code: str, error_code: str) -> GenerateSignalResponse:
        """Return a non-actionable signal response without fabricated values."""

        return GenerateSignalResponse(
            asset_code=asset_code,
            direction="",
            logic_desc="",
            invalidation_logic="",
            invalidation_threshold=None,
            target_regime="",
            confidence=0.0,
            success=False,
            must_not_use_for_decision=True,
            error_code=error_code,
        )
