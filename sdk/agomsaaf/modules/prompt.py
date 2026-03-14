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
