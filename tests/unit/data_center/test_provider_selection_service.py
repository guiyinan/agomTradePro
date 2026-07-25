from types import SimpleNamespace

from apps.data_center.application import interface_services


def test_active_provider_selection_preserves_database_name(monkeypatch) -> None:
    repository = SimpleNamespace(
        get_active_by_type=lambda source_type: (
            [SimpleNamespace(id=7, name="akshare-main")] if source_type == "akshare" else []
        )
    )
    monkeypatch.setattr(
        interface_services,
        "_make_provider_repo",
        lambda: repository,
    )

    assert interface_services.get_active_provider_selection_by_source("akshare") == (
        7,
        "akshare-main",
    )
    assert interface_services.get_active_provider_id_by_source("akshare") == 7
    assert interface_services.get_active_provider_selection_by_source("wind") is None
