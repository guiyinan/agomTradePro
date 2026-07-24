"""Signal eligibility configuration initialization contracts."""

from types import SimpleNamespace
from typing import Any

import pytest

from apps.regime.domain import asset_eligibility
from apps.regime.domain.asset_eligibility import (
    DEFAULT_ELIGIBILITY_MATRIX,
    Eligibility,
    get_eligibility_matrix,
)
from apps.signal.infrastructure import config_init


class _Manager:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def filter(self, **kwargs: Any) -> list[SimpleNamespace]:
        assert kwargs == {"is_active": True}
        return self.rows


def _model(rows: list[SimpleNamespace]) -> type:
    return type("EligibilityConfigModel", (), {"_default_manager": _Manager(rows)})


def test_initialize_registers_validated_database_provider(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            asset_class="a_share_growth",
            regime="Recovery",
            eligibility="preferred",
        )
    ]
    registered: list[object] = []
    monkeypatch.setattr(config_init.django_apps, "get_model", lambda *args: _model(rows))
    monkeypatch.setattr(
        config_init,
        "set_eligibility_matrix_provider",
        registered.append,
    )

    config_init.initialize_domain_config()

    assert len(registered) == 1
    provider = registered[0]
    assert callable(provider)
    assert provider() == {"a_share_growth": {"Recovery": Eligibility.PREFERRED}}


@pytest.mark.parametrize(
    "row",
    [
        SimpleNamespace(
            asset_class="",
            regime="Recovery",
            eligibility="preferred",
        ),
        SimpleNamespace(
            asset_class="a_share_growth",
            regime="Unknown",
            eligibility="preferred",
        ),
        SimpleNamespace(
            asset_class="a_share_growth",
            regime="Recovery",
            eligibility="invalid",
        ),
    ],
)
def test_loader_rejects_malformed_database_rows(monkeypatch, row) -> None:
    monkeypatch.setattr(
        config_init.django_apps,
        "get_model",
        lambda *args: _model([row]),
    )

    with pytest.raises(ValueError, match="invalid"):
        config_init._load_eligibility_matrix_from_db()


def test_empty_database_matrix_falls_back_to_domain_default(monkeypatch) -> None:
    monkeypatch.setattr(
        config_init.django_apps,
        "get_model",
        lambda *args: _model([]),
    )
    monkeypatch.setattr(
        asset_eligibility,
        "_eligibility_matrix_provider",
        config_init._load_eligibility_matrix_from_db,
    )

    assert get_eligibility_matrix() == DEFAULT_ELIGIBILITY_MATRIX


def test_refresh_re_registers_provider_without_cache_backend_extensions(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        config_init,
        "initialize_domain_config",
        lambda: calls.append("initialized"),
    )

    config_init.refresh_domain_config()

    assert calls == ["initialized"]
