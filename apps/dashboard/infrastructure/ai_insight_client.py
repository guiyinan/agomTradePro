"""AI insight client for dashboard application services."""

from typing import Any

import requests


class DashboardAIInsightError(RuntimeError):
    """Raised when dashboard AI insight generation fails."""


def _build_ai_api_url(base_url: str) -> str:
    """Build a chat completion endpoint URL from a provider base URL."""
    normalized = (base_url or "").rstrip("/")
    if normalized.endswith("/chat/completions") or normalized.endswith("/responses"):
        return normalized
    return f"{normalized}/chat/completions"


class DashboardAIInsightClient:
    """Generate dashboard investment insights using the configured AI provider."""

    def generate_insights(self, *, provider: dict[str, Any], prompt: str) -> list[str]:
        api_url = _build_ai_api_url(str(provider["base_url"]))
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider['api_key']}",
        }
        payload = {
            "model": provider["default_model"],
            "messages": [
                {
                    "role": "system",
                    "content": "你是 AgomTradePro 投资助手，给出简洁具体的投资建议。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 500,
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=10)
            status_code = getattr(response, "status_code", None)
            if status_code != 200:
                raise DashboardAIInsightError(f"AI provider returned status {status_code}")
            data = response.json()
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            raise DashboardAIInsightError(str(exc)) from exc

        if provider["provider_type"] in ["openai", "deepseek", "qwen"]:
            content = data["choices"][0]["message"]["content"]
        else:
            content = str(data)

        insights: list[str] = []
        for line in (line.strip() for line in content.split("\n") if line.strip()):
            normalized = line.lstrip("0123456789.-*•、 ")
            normalized = normalized.lstrip("【").rstrip("】")
            if 5 < len(normalized) < 100:
                insights.append(normalized)
            if len(insights) >= 5:
                break
        return insights
