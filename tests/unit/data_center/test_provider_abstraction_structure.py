"""Structure contracts for the canonical Data Center provider runtime."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_CENTER_INFRA = REPO_ROOT / "apps" / "data_center" / "infrastructure"
MACRO_INFRA = REPO_ROOT / "apps" / "macro" / "infrastructure"


def test_provider_runtime_has_one_registry_and_no_forwarding_layers() -> None:
    """Keep construction, lookup, routing, and health in one runtime owner."""
    assert (DATA_CENTER_INFRA / "provider_registry.py").is_file()
    assert (DATA_CENTER_INFRA / "market_gateway_protocol.py").is_file()
    assert not (DATA_CENTER_INFRA / "provider_factory.py").exists()
    assert not (DATA_CENTER_INFRA / "providers.py").exists()
    assert not (DATA_CENTER_INFRA / "gateway_protocols.py").exists()
    assert not (DATA_CENTER_INFRA / "registries" / "source_registry.py").exists()
    assert not (
        REPO_ROOT / "apps" / "data_center" / "application" / "registry_factory.py"
    ).exists()
    assert not (
        REPO_ROOT / "apps" / "data_center" / "application" / "repository_provider.py"
    ).exists()


def test_application_composition_does_not_recreate_provider_capabilities() -> None:
    """Capability declarations belong to real adapters, not DB-backed stubs."""
    provider_runtime = (
        REPO_ROOT / "apps" / "data_center" / "provider_runtime.py"
    ).read_text(encoding="utf-8")
    composition = (REPO_ROOT / "apps" / "data_center" / "composition.py").read_text(
        encoding="utf-8"
    )

    assert "class _DbProvider" not in provider_runtime
    assert "_SOURCE_TYPE_CAPABILITIES" not in provider_runtime
    assert "provider_factory" not in composition
    assert "infrastructure.providers" not in composition
    assert "source_registry" not in composition


def test_macro_legacy_adapter_and_compatibility_paths_are_retired() -> None:
    """Macro consumes Data Center and no longer owns provider implementations."""
    assert (DATA_CENTER_INFRA / "macro_sources" / "akshare_adapter.py").is_file()
    assert (DATA_CENTER_INFRA / "macro_sources" / "tushare_adapter.py").is_file()
    assert not (MACRO_INFRA / "adapters.py").exists()
    assert not list((MACRO_INFRA / "adapters").rglob("*.py"))
    assert not (MACRO_INFRA / "data_center_compat.py").exists()
    assert not (MACRO_INFRA / "providers.py").exists()
    assert not (MACRO_INFRA / "repositories.py").exists()


def test_provider_adapter_facade_stays_thin_and_implementations_stay_bounded() -> None:
    """Keep the public import surface stable without rebuilding a monolith."""
    facade = DATA_CENTER_INFRA / "provider_adapters.py"
    facade_text = facade.read_text(encoding="utf-8")
    assert len([line for line in facade_text.splitlines() if line.strip()]) <= 50
    assert "class " not in facade_text

    owner_names = (
        "_provider_adapter_base.py",
        "_provider_adapter_tushare.py",
        "_provider_adapter_akshare.py",
        "_provider_adapter_specialized.py",
    )
    for owner_name in owner_names:
        owner = DATA_CENTER_INFRA / owner_name
        assert owner.is_file()
        non_empty_lines = [
            line for line in owner.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        assert len(non_empty_lines) <= 1200, owner_name
