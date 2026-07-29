"""Setup-wizard persistence boundary contracts."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.setup_wizard.domain.entities import AIProviderConfigDTO, WizardStep
from apps.setup_wizard.infrastructure.models import SetupStateModel
from apps.setup_wizard.infrastructure.repositories import AIProviderRepository


def test_setup_state_rejects_inconsistent_completion_evidence() -> None:
    """Completion cannot be persisted without matching step evidence and time."""
    state = SetupStateModel(
        is_completed=True,
        current_step=WizardStep.WELCOME.value,
        completed_steps=[],
    )

    with pytest.raises(ValidationError):
        state.full_clean()


def test_ai_provider_repository_fails_closed_without_encryption(monkeypatch) -> None:
    """A credential must never fall back to the deprecated plaintext field."""
    monkeypatch.setattr("shared.infrastructure.crypto.get_encryption_service", lambda: None)
    credential = "secret-value-that-must-not-leak"

    with pytest.raises(ValueError, match="encryption is unavailable") as exc_info:
        AIProviderRepository().save_config(
            AIProviderConfigDTO(
                name="test-provider",
                provider_type="openai",
                base_url="https://example.com",
                api_key=credential,
            )
        )

    assert credential not in str(exc_info.value)
