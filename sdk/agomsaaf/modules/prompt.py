"""AgomSAAF SDK - Prompt 模块。"""

from typing import Any

from .base import BaseModule


class PromptModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/prompt")

    def list_templates(self) -> list[dict[str, Any]]:
        response = self._get("templates/")
        return response.get("results", response) if isinstance(response, dict) else response

    def get_template(self, template_id: int) -> dict[str, Any]:
        return self._get(f"templates/{template_id}/")

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("templates/", json=payload)

    def update_template(self, template_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"templates/{template_id}/", json=payload)

    def delete_template(self, template_id: int) -> None:
        self._delete(f"templates/{template_id}/")

    def list_chains(self) -> list[dict[str, Any]]:
        response = self._get("chains/")
        return response.get("results", response) if isinstance(response, dict) else response

    def create_chain(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("chains/", json=payload)

    def list_logs(self) -> list[dict[str, Any]]:
        response = self._get("logs/")
        return response.get("results", response) if isinstance(response, dict) else response

    def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("reports/generate", json=payload)

    def generate_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("signals/generate", json=payload)

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("chat", json=payload)

    def chat_providers(self) -> dict[str, Any]:
        return self._get("chat/providers")

    def chat_models(self) -> dict[str, Any]:
        return self._get("chat/models")

    # ==================== Agent Runtime ====================

    def agent_execute(
        self,
        task_type: str,
        user_input: str,
        provider_ref: Any = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context_scope: list[str] | None = None,
        context_params: dict[str, Any] | None = None,
        tool_names: list[str] | None = None,
        response_schema: dict[str, Any] | None = None,
        max_rounds: int = 4,
        session_id: str | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an Agent Runtime task.

        Sends a task to the unified Agent Runtime which handles
        context building, tool calling loops, and trace logging.

        Args:
            task_type: Task type (chat/analysis/signal/report/strategy)
            user_input: User input or task description
            provider_ref: AI provider reference (name or ID)
            model: Model name override
            temperature: Temperature override
            max_tokens: Max tokens override
            context_scope: Context domains to include (macro/regime/portfolio/signals/asset_pool)
            context_params: Parameters for context building
            tool_names: Whitelist of allowed tools
            response_schema: JSON Schema for structured output
            max_rounds: Max tool calling rounds (default 4)
            session_id: Session ID for continuity
            system_prompt: System prompt override
            metadata: Additional metadata

        Returns:
            Dict with success, final_answer, tool_calls, turn_count, tokens, etc.

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.prompt.agent_execute(
            ...     task_type="chat",
            ...     user_input="当前宏观环境如何？",
            ...     context_scope=["macro", "regime"],
            ...     tool_names=["get_macro_summary", "get_regime_status"],
            ... )
            >>> print(result["final_answer"])
        """
        body: dict[str, Any] = {
            "task_type": task_type,
            "user_input": user_input,
            "max_rounds": max_rounds,
        }
        if provider_ref is not None:
            body["provider_ref"] = provider_ref
        if model is not None:
            body["model"] = model
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if context_scope is not None:
            body["context_scope"] = context_scope
        if context_params is not None:
            body["context_params"] = context_params
        if tool_names is not None:
            body["tool_names"] = tool_names
        if response_schema is not None:
            body["response_schema"] = response_schema
        if session_id is not None:
            body["session_id"] = session_id
        if system_prompt is not None:
            body["system_prompt"] = system_prompt
        if metadata is not None:
            body["metadata"] = metadata
        return self._post("agent/execute", json=body)
