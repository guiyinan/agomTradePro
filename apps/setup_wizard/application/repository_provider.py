"""Setup wizard repository providers for application consumers."""

from apps.setup_wizard.infrastructure.providers import (
    AdminRepository,
    AIProviderRepository,
    DataSourceRepository,
    SetupStateRepository,
)


def get_setup_state_repository() -> SetupStateRepository:
    """Return the setup state repository."""

    return SetupStateRepository()


def get_setup_admin_repository() -> AdminRepository:
    """Return the setup admin repository."""

    return AdminRepository()


def get_setup_ai_provider_repository() -> AIProviderRepository:
    """Return the setup AI provider repository."""

    return AIProviderRepository()


def get_setup_data_source_repository() -> DataSourceRepository:
    """Return the setup data source repository."""

    return DataSourceRepository()


def ensure_setup_security_keys(*, generate_secret_key: bool = True, generate_encryption_key: bool = True):
    """Ensure required setup-time security keys exist."""

    from apps.setup_wizard.infrastructure.encryption_setup import ensure_all_keys

    return ensure_all_keys(
        generate_secret_key=generate_secret_key,
        generate_encryption_key=generate_encryption_key,
    )
