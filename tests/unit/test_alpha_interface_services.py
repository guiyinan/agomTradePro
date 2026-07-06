from types import SimpleNamespace

from apps.alpha.application.interface_services import (
    resolve_requested_alpha_user,
    upload_alpha_scores,
)


def test_resolve_requested_alpha_user_uses_account_service(monkeypatch):
    requested_user = object()

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.find_user_by_id",
        lambda user_id: requested_user if user_id == 7 else None,
    )

    assert resolve_requested_alpha_user(actor=object(), requested_user_id=7) is requested_user


def test_upload_alpha_scores_uses_cache_repository(monkeypatch):
    cache_entry = object()
    seen: dict[str, object] = {}

    class FakeRepository:
        def upsert_qlib_cache(self, **kwargs):
            seen.update(kwargs)
            return cache_entry, True

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.get_alpha_score_cache_repository",
        lambda: FakeRepository(),
    )

    result = upload_alpha_scores(
        write_user=SimpleNamespace(id=3),
        universe_id="csi300",
        asof_date="2026-07-05",
        intended_trade_date="2026-07-06",
        model_id="model-1",
        model_artifact_hash="hash-1",
        scores=[{"code": "000001.SZ", "score": 0.8}],
    )

    assert result == (cache_entry, True)
    assert seen["universe_id"] == "csi300"
    assert seen["model_id"] == "model-1"
