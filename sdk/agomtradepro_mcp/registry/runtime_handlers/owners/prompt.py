"""prompt runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_list_prompt_templates() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    templates = client.prompt.list_templates()
    return {
        "templates": templates,
        "total_count": len(templates),
    }


def _fallback_list_prompt_chains() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    chains = client.prompt.list_chains()
    return {
        "chains": chains,
        "total_count": len(chains),
    }


def _internal_handler_prompt_create_template(
    name: str,
    category: str,
    template_content: str,
    version: str = "1.0",
    system_prompt: str | None = None,
    placeholders: list[dict[str, Any]] | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    description: str = "",
    is_active: bool = True,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_name = str(name or "").strip()
    normalized_category = str(category or "").strip().lower()
    normalized_content = str(template_content or "")
    if not normalized_name:
        raise ValueError("name must be a non-empty string")
    if normalized_category not in {"report", "signal", "analysis", "chat"}:
        raise ValueError("category must be one of: report, signal, analysis, chat")
    if not normalized_content.strip():
        raise ValueError("template_content must be a non-empty string")

    payload = {
        "name": normalized_name,
        "category": normalized_category,
        "version": str(version or "1.0").strip() or "1.0",
        "template_content": normalized_content,
        "system_prompt": system_prompt,
        "placeholders": list(placeholders or []),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "description": description,
        "is_active": is_active,
    }
    client = AgomTradeProClient()
    if preview_only:
        existing = client.prompt.list_templates(
            name=normalized_name,
            include_inactive=True,
        )
        if existing:
            raise ValueError(f"Prompt template name is already reserved: {normalized_name}")
        return {
            "success": True,
            "preview_only": True,
            "template_summary": {
                "name": normalized_name,
                "category": normalized_category,
                "version": payload["version"],
                "is_active": is_active,
                "placeholder_count": len(payload["placeholders"]),
                "template_content_length": len(normalized_content),
                "system_prompt_length": len(system_prompt or ""),
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "summary": {
                "name": normalized_name,
                "category": normalized_category,
                "duplicate_count": 0,
            },
            "message": "Preview generated. Confirm to create the prompt template.",
        }

    return client.prompt.create_template(payload)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_prompt_templates": _fallback_list_prompt_templates,
    "list_prompt_chains": _fallback_list_prompt_chains,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "prompt_create_template": _internal_handler_prompt_create_template,
}
