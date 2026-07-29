from datetime import date
from types import SimpleNamespace

import pytest

from apps.alpha.application.interface_services import (
    get_factor_exposure_payload,
    preview_alpha_score_upload,
    resolve_requested_alpha_user,
    upload_alpha_scores,
)


def _score(**overrides):
    payload = {
        "code": "000001.sz",
        "score": 0.8,
        "rank": 1,
        "factors": {"momentum": 0.7},
        "confidence": 0.9,
        "source": "local_qlib",
    }
    payload.update(overrides)
    return payload


def test_resolve_requested_alpha_user_uses_account_service(monkeypatch):
    requested_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.find_user_by_id",
        lambda user_id: requested_user if user_id == 7 else None,
    )

    assert (
        resolve_requested_alpha_user(actor=SimpleNamespace(id=1), requested_user_id=7)
        is requested_user
    )


def test_upload_alpha_scores_uses_cache_repository(monkeypatch):
    cache_entry = SimpleNamespace(pk=11)
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
        asof_date=date(2026, 7, 5),
        intended_trade_date=date(2026, 7, 6),
        model_id="model-1",
        model_artifact_hash="hash-1",
        scores=[_score()],
    )

    assert result == (cache_entry, True)
    assert seen["universe_id"] == "csi300"
    assert seen["model_id"] == "model-1"
    assert seen["scores"][0]["code"] == "000001.SZ"


def test_upload_normalizes_rank_order_and_detaches_caller_scores(monkeypatch):
    seen: dict[str, object] = {}

    class FakeRepository:
        def upsert_qlib_cache(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(pk=12), True

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.get_alpha_score_cache_repository",
        lambda: FakeRepository(),
    )
    scores = [
        _score(code="000002.SZ", rank=2),
        _score(code="000001.sz", rank=1),
    ]

    upload_alpha_scores(
        write_user=SimpleNamespace(id=3),
        universe_id="csi300",
        asof_date=date(2026, 7, 5),
        intended_trade_date=date(2026, 7, 6),
        model_id="model-1",
        model_artifact_hash="hash-1",
        scores=scores,
    )
    scores[1]["factors"]["momentum"] = 999

    persisted = seen["scores"]
    assert [item["code"] for item in persisted] == ["000001.SZ", "000002.SZ"]
    assert persisted[0]["factors"] == {"momentum": 0.7}


@pytest.mark.parametrize(
    "override",
    [
        {"asof_date": "2026-07-05"},
        {"write_user": SimpleNamespace(id=True)},
        {"scores": [_score(score=float("nan"))]},
        {"scores": [_score(code="A", rank=1), _score(code="a", rank=2)]},
        {"scores": [_score(code="A", rank=1), _score(code="B", rank=1)]},
    ],
)
def test_upload_rejects_invalid_direct_calls_before_repository(monkeypatch, override):
    called = False

    class FakeRepository:
        def upsert_qlib_cache(self, **kwargs):
            nonlocal called
            called = True
            return SimpleNamespace(pk=1), True

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.get_alpha_score_cache_repository",
        lambda: FakeRepository(),
    )
    values = {
        "write_user": SimpleNamespace(id=3),
        "universe_id": "csi300",
        "asof_date": date(2026, 7, 5),
        "intended_trade_date": date(2026, 7, 6),
        "model_id": "model-1",
        "model_artifact_hash": "hash-1",
        "scores": [_score()],
    }
    values.update(override)

    with pytest.raises(ValueError):
        upload_alpha_scores(**values)

    assert called is False


def test_preview_rejects_dynamic_repository_evidence(monkeypatch):
    class FakeRepository:
        def get_upload_target(self, **kwargs):
            return {"id": True, "score_count": -1}

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.get_alpha_score_cache_repository",
        lambda: FakeRepository(),
    )

    with pytest.raises(RuntimeError, match="alpha_upload_target_invalid"):
        preview_alpha_score_upload(
            write_user=SimpleNamespace(id=3),
            universe_id="csi300",
            asof_date=date(2026, 7, 5),
            intended_trade_date=date(2026, 7, 6),
            model_id="model-1",
            model_artifact_hash="hash-1",
            scores=[_score()],
        )


def test_factor_exposure_is_normalized_and_nonfinite_values_fail_closed(monkeypatch):
    class GoodService:
        def get_factor_exposure(self, **kwargs):
            return {"momentum": 0.5}

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.AlphaService",
        GoodService,
    )
    payload = get_factor_exposure_payload(
        stock_code="000001.sz",
        trade_date=date(2026, 7, 5),
        provider="simple",
    )
    assert payload["stock_code"] == "000001.SZ"
    assert payload["factors"] == {"momentum": 0.5}

    class BrokenService:
        def get_factor_exposure(self, **kwargs):
            return {"momentum": float("nan")}

    monkeypatch.setattr(
        "apps.alpha.application.interface_services.AlphaService",
        BrokenService,
    )
    with pytest.raises(RuntimeError, match="alpha_factor_exposure_invalid"):
        get_factor_exposure_payload(
            stock_code="000001.SZ",
            trade_date=date(2026, 7, 5),
            provider="simple",
        )
