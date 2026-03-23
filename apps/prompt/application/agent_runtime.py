"""
Agent Runtime - 统一 AI 执行引擎。

核心职责：
- 构造 messages + tools schema
- 调用 AI provider
- 解析 tool calls → 执行工具 → 结果回灌
- 控制回合次数和终止条件
- 记录完整 trace
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ..domain.agent_entities import (
    AgentExecutionRequest,
    AgentExecutionResponse,
    AgentTurnResult,
    ToolCallRecord,
)
from ..domain.context_entities import ContextBundle
from ..infrastructure.adapters.function_registry import FunctionRegistry

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    统一 Agent 执行引擎。

    接收 AgentExecutionRequest，执行多轮工具调用闭环，
    返回 AgentExecutionResponse。
    """

    def __init__(
        self,
        ai_client_factory,
        tool_registry: FunctionRegistry | None = None,
        context_builder: Any | None = None,
        execution_logger: Any | None = None,
    ):
        """
        Args:
            ai_client_factory: AIClientFactory 实例
            tool_registry: 工具注册表（FunctionRegistry）
            context_builder: 上下文构建器（ContextBundleBuilder）
            execution_logger: 执行日志记录器
        """
        self.ai_client_factory = ai_client_factory
        self.tool_registry = tool_registry or FunctionRegistry()
        self.context_builder = context_builder
        self.execution_logger = execution_logger

    def execute(self, request: AgentExecutionRequest) -> AgentExecutionResponse:
        """
        执行 Agent 任务。

        标准流程：
        1. 根据 scope 构建 ContextBundle
        2. 生成 messages 和 tools schema
        3. 多轮推理闭环
        4. 返回结果和 trace

        Args:
            request: Agent 执行请求

        Returns:
            Agent 执行响应
        """
        execution_id = str(uuid.uuid4())
        start_time = time.time()
        all_tool_calls: list[ToolCallRecord] = []
        all_turns: list[AgentTurnResult] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0

        try:
            # 1. 构建上下文
            context_bundle = self._build_context(request)
            used_context = context_bundle.get_used_domains() if context_bundle else []

            # 2. 构建初始 messages
            messages = self._build_messages(request, context_bundle)

            # 3. 获取 tools schema（仅对白名单工具）
            tools_schema = self._get_tools_schema(request.tool_names)

            # 4. 获取 AI client
            ai_client = self.ai_client_factory.get_client(request.provider_ref)

            # 5. 多轮推理循环
            provider_used = None
            model_used = None

            for turn_number in range(1, request.max_rounds + 1):
                # 调用模型
                ai_response = ai_client.chat_completion(
                    messages=messages,
                    model=request.model,
                    temperature=request.temperature or 0.7,
                    max_tokens=request.max_tokens,
                    tools=tools_schema if tools_schema else None,
                    tool_choice="auto" if tools_schema else None,
                )

                provider_used = ai_response.get("provider_used", provider_used)
                model_used = ai_response.get("model", model_used)

                # 累计 token
                turn_prompt_tokens = ai_response.get("prompt_tokens", 0)
                turn_completion_tokens = ai_response.get("completion_tokens", 0)
                total_prompt_tokens += turn_prompt_tokens
                total_completion_tokens += turn_completion_tokens

                # 检查 AI 调用是否成功
                if ai_response.get("status") != "success":
                    error_msg = ai_response.get("error_message", "AI provider call failed")
                    all_turns.append(AgentTurnResult(
                        turn_number=turn_number,
                        has_tool_calls=False,
                        tool_calls=[],
                        content=None,
                        prompt_tokens=turn_prompt_tokens,
                        completion_tokens=turn_completion_tokens,
                        finish_reason="error",
                    ))
                    return self._build_error_response(
                        error_msg, execution_id, start_time,
                        all_tool_calls, all_turns,
                        total_prompt_tokens, total_completion_tokens,
                        provider_used, model_used, used_context,
                    )

                # 检查是否有 tool_calls
                tool_calls_data = ai_response.get("tool_calls")
                content = ai_response.get("content", "")
                finish_reason = ai_response.get("finish_reason")

                if tool_calls_data:
                    # 执行工具调用
                    turn_tool_records = self._execute_tool_calls(tool_calls_data)
                    all_tool_calls.extend(turn_tool_records)

                    all_turns.append(AgentTurnResult(
                        turn_number=turn_number,
                        has_tool_calls=True,
                        tool_calls=turn_tool_records,
                        content=content,
                        prompt_tokens=turn_prompt_tokens,
                        completion_tokens=turn_completion_tokens,
                        finish_reason=finish_reason,
                    ))

                    # 将工具结果回灌到 messages
                    messages = self._append_tool_results(
                        messages, content, tool_calls_data, turn_tool_records,
                    )
                    # 继续下一轮
                    continue

                # 没有 tool_calls，得到最终答案
                all_turns.append(AgentTurnResult(
                    turn_number=turn_number,
                    has_tool_calls=False,
                    tool_calls=[],
                    content=content,
                    prompt_tokens=turn_prompt_tokens,
                    completion_tokens=turn_completion_tokens,
                    finish_reason=finish_reason,
                ))
                break

            # 构建最终响应
            final_content = all_turns[-1].content if all_turns else ""
            total_tokens = total_prompt_tokens + total_completion_tokens
            response_time_ms = int((time.time() - start_time) * 1000)

            # 检查是否因 max_rounds 耗尽而退出（最后一轮仍有 tool_calls）
            max_rounds_exhausted = (
                all_turns
                and all_turns[-1].has_tool_calls
                and len(all_turns) >= request.max_rounds
            )

            if max_rounds_exhausted:
                logger.warning(
                    "AgentRuntime max_rounds (%d) exhausted, "
                    "last turn still has tool_calls",
                    request.max_rounds,
                )
                return self._build_error_response(
                    f"Max rounds ({request.max_rounds}) exhausted without final answer",
                    execution_id, start_time,
                    all_tool_calls, all_turns,
                    total_prompt_tokens, total_completion_tokens,
                    provider_used, model_used, used_context,
                )

            # 尝试解析结构化输出
            structured_output = None
            if request.response_schema and final_content:
                structured_output = self._parse_structured_output(final_content)

            response = AgentExecutionResponse(
                success=True,
                final_answer=final_content,
                structured_output=structured_output,
                used_context=used_context,
                tool_calls=all_tool_calls if all_tool_calls else None,
                turns=all_turns,
                turn_count=len(all_turns),
                provider_used=provider_used,
                model_used=model_used,
                total_tokens=total_tokens,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                estimated_cost=0.0,
                response_time_ms=response_time_ms,
                execution_id=execution_id,
            )

            # 记录执行日志
            self._log_execution(request, response)

            return response

        except Exception as exc:
            logger.error("AgentRuntime execution failed: %s", exc, exc_info=True)
            return self._build_error_response(
                str(exc), execution_id, start_time,
                all_tool_calls, all_turns,
                total_prompt_tokens, total_completion_tokens,
                None, None, [],
            )

    def _build_context(self, request: AgentExecutionRequest) -> ContextBundle | None:
        """根据 scope 构建 ContextBundle。"""
        if not self.context_builder:
            return None
        if not request.context_scope:
            return None
        return self.context_builder.build(
            scope=request.context_scope,
            params=request.context_params or {},
        )

    def _build_messages(
        self,
        request: AgentExecutionRequest,
        context_bundle: ContextBundle | None,
    ) -> list[dict[str, str]]:
        """构建首轮 messages。"""
        messages: list[dict[str, str]] = []

        # System prompt
        system_parts: list[str] = []
        if request.system_prompt:
            system_parts.append(request.system_prompt)

        # 注入上下文摘要
        if context_bundle:
            summary_text = context_bundle.build_summary_text()
            if summary_text:
                system_parts.append(
                    "以下是系统实时数据摘要，你可以使用工具查询更多详细数据：\n\n"
                    + summary_text
                )

        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        # User message
        messages.append({"role": "user", "content": request.user_input})

        return messages

    def _get_tools_schema(
        self, tool_names: list[str] | None
    ) -> list[dict[str, Any]] | None:
        """获取指定工具的 OpenAI Function Calling schema。"""
        if not tool_names:
            return None

        all_tools = self.tool_registry.to_openai_format()
        if not all_tools:
            return None

        # 按白名单过滤
        available_names = set(self.tool_registry.get_tool_names())
        requested = set(tool_names)
        filtered = [
            t for t in all_tools
            if t.get("function", {}).get("name") in (requested & available_names)
        ]
        return filtered if filtered else None

    def _execute_tool_calls(
        self, tool_calls_data: list[dict[str, Any]]
    ) -> list[ToolCallRecord]:
        """执行一组工具调用，返回记录列表。"""
        records: list[ToolCallRecord] = []

        for tc in tool_calls_data:
            tool_name = tc.get("tool_name", "")
            arguments_raw = tc.get("arguments", "{}")
            call_start = time.time()

            # 解析参数
            try:
                if isinstance(arguments_raw, str):
                    arguments = json.loads(arguments_raw)
                else:
                    arguments = arguments_raw
            except json.JSONDecodeError:
                records.append(ToolCallRecord(
                    tool_name=tool_name,
                    arguments={"raw": arguments_raw},
                    success=False,
                    result=None,
                    error_message=f"Invalid JSON arguments: {arguments_raw}",
                    duration_ms=int((time.time() - call_start) * 1000),
                ))
                continue

            # 校验工具是否存在
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                records.append(ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    success=False,
                    result=None,
                    error_message=f"Tool not found: {tool_name}",
                    duration_ms=int((time.time() - call_start) * 1000),
                ))
                continue

            # 执行工具
            try:
                result = self.tool_registry.execute(tool_name, arguments)
                duration_ms = int((time.time() - call_start) * 1000)

                # 检查是否返回了错误 dict
                if isinstance(result, dict) and "error" in result:
                    records.append(ToolCallRecord(
                        tool_name=tool_name,
                        arguments=arguments,
                        success=False,
                        result=result,
                        error_message=result["error"],
                        duration_ms=duration_ms,
                    ))
                else:
                    records.append(ToolCallRecord(
                        tool_name=tool_name,
                        arguments=arguments,
                        success=True,
                        result=result,
                        duration_ms=duration_ms,
                    ))
            except Exception as exc:
                records.append(ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    success=False,
                    result=None,
                    error_message=str(exc),
                    duration_ms=int((time.time() - call_start) * 1000),
                ))

        return records

    def _append_tool_results(
        self,
        messages: list[dict[str, str]],
        assistant_content: str | None,
        tool_calls_data: list[dict[str, Any]],
        tool_records: list[ToolCallRecord],
    ) -> list[dict[str, str]]:
        """将工具执行结果添加到 messages 以继续推理。"""
        new_messages = list(messages)

        # 添加 assistant 消息（含 tool_calls）
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if assistant_content:
            assistant_msg["content"] = assistant_content
        else:
            assistant_msg["content"] = ""

        # 构建 tool_calls 引用
        tc_list = []
        for tc in tool_calls_data:
            tc_list.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("tool_name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            })
        if tc_list:
            assistant_msg["tool_calls"] = tc_list
        new_messages.append(assistant_msg)

        # 添加每个工具的结果
        for tc, record in zip(tool_calls_data, tool_records):
            result_content = self._serialize_tool_result(record)
            new_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_content,
            })

        return new_messages

    @staticmethod
    def _serialize_tool_result(record: ToolCallRecord) -> str:
        """将工具调用结果序列化为 JSON 字符串。"""
        if not record.success:
            return json.dumps(
                {"error": record.error_message or "Tool execution failed"},
                ensure_ascii=False,
            )
        result = record.result
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result) if result is not None else ""

    @staticmethod
    def _parse_structured_output(content: str) -> dict[str, Any] | None:
        """尝试从文本中解析 JSON 结构化输出。"""
        if not content:
            return None
        content = content.strip()
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 尝试提取 ```json ... ``` 代码块
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        return None

    def _build_error_response(
        self,
        error_msg: str,
        execution_id: str,
        start_time: float,
        tool_calls: list[ToolCallRecord],
        turns: list[AgentTurnResult],
        prompt_tokens: int,
        completion_tokens: int,
        provider_used: str | None,
        model_used: str | None,
        used_context: list[str],
    ) -> AgentExecutionResponse:
        """构建错误响应。"""
        return AgentExecutionResponse(
            success=False,
            final_answer=None,
            used_context=used_context,
            tool_calls=tool_calls if tool_calls else None,
            turns=turns if turns else None,
            turn_count=len(turns),
            provider_used=provider_used,
            model_used=model_used,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            response_time_ms=int((time.time() - start_time) * 1000),
            error_message=error_msg,
            execution_id=execution_id,
        )

    def _log_execution(
        self,
        request: AgentExecutionRequest,
        response: AgentExecutionResponse,
    ) -> None:
        """记录执行日志。"""
        if not self.execution_logger:
            return
        try:
            self.execution_logger.log_agent_execution(request, response)
        except Exception as exc:
            logger.warning("Failed to log agent execution: %s", exc)
