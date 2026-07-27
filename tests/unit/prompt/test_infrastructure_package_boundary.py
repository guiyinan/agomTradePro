"""Prompt infrastructure package boundary regressions."""

from __future__ import annotations

import apps.prompt.infrastructure as prompt_infrastructure
from apps.prompt.infrastructure import adapters as prompt_adapters
from apps.prompt.interface import serializers as prompt_serializers


def test_infrastructure_package_does_not_expose_interface_serializers() -> None:
    assert prompt_infrastructure.__all__ == ()
    assert not hasattr(prompt_infrastructure, "PromptTemplateCreateSerializer")
    assert not hasattr(prompt_infrastructure, "ChainConfigCreateSerializer")


def test_interface_remains_the_canonical_serializer_entrypoint() -> None:
    assert prompt_serializers.PromptTemplateCreateSerializer.__module__ == (
        "apps.prompt.interface.serializers"
    )
    assert prompt_serializers.ChainConfigCreateSerializer.__module__ == (
        "apps.prompt.interface.serializers"
    )


def test_adapters_package_does_not_duplicate_prompt_fixtures() -> None:
    """Adapter discovery must not execute or expose bootstrap fixture definitions."""

    assert prompt_adapters.__all__ == ()
    assert not hasattr(prompt_adapters, "get_predefined_templates")
    assert not hasattr(prompt_adapters, "load_predefined_chains")
