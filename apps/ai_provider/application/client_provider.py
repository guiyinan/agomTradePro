"""Application-side helpers for resolving AI client factories."""

from __future__ import annotations

from apps.ai_provider.application.repository_provider import (
    build_openai_compatible_adapter,
    get_ai_client_factory,
    get_ai_provider_repository,
)
