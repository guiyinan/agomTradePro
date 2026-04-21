from apps.macro.application.use_cases import build_sync_macro_data_use_case


def test_build_sync_macro_data_use_case_uses_default_adapter(monkeypatch):
    fake_repository = object()
    fake_adapter = object()

    monkeypatch.setattr(
        "apps.macro.infrastructure.repositories.DjangoMacroRepository",
        lambda: fake_repository,
    )
    monkeypatch.setattr(
        "apps.macro.infrastructure.adapters.create_default_adapter",
        lambda: fake_adapter,
    )

    use_case = build_sync_macro_data_use_case()

    assert use_case.repository is fake_repository
    assert use_case.adapters == {"default": fake_adapter}


def test_build_sync_macro_data_use_case_uses_explicit_akshare_adapter(monkeypatch):
    fake_repository = object()
    fake_adapter = object()

    monkeypatch.setattr(
        "apps.macro.infrastructure.repositories.DjangoMacroRepository",
        lambda: fake_repository,
    )
    monkeypatch.setattr(
        "apps.macro.infrastructure.adapters.AKShareAdapter",
        lambda: fake_adapter,
    )

    use_case = build_sync_macro_data_use_case("akshare")

    assert use_case.repository is fake_repository
    assert use_case.adapters == {"akshare": fake_adapter}
