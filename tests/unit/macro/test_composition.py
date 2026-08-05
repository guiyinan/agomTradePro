from apps.data_center.application.dtos import MacroSeriesRequest, MacroSeriesResponse
from apps.macro.composition import _PublishedMacroSeriesQuery


def test_published_macro_series_query_uses_public_port(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_public_port(indicator_code: str, **kwargs: object) -> MacroSeriesResponse:
        calls.append({"indicator_code": indicator_code, **kwargs})
        return MacroSeriesResponse(
            indicator_code=indicator_code,
            name_cn="M2",
            period_type="M",
            data_source="data_center_fact",
            freshness_status="fresh",
            decision_grade="decision_safe",
            must_not_use_for_decision=False,
        )

    monkeypatch.setattr(
        "apps.macro.composition.get_published_macro_series_response",
        fake_public_port,
    )

    result = _PublishedMacroSeriesQuery().execute(
        MacroSeriesRequest(indicator_code="CN_M2", limit=12)
    )

    assert result.decision_grade == "decision_safe"
    assert calls == [
        {
            "indicator_code": "CN_M2",
            "publication_key": "CN_M2",
            "start": None,
            "end": None,
            "limit": 12,
            "source": None,
        }
    ]


def test_published_macro_series_query_blocks_without_publication(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.macro.composition.get_published_macro_series_response",
        lambda indicator_code, **_kwargs: MacroSeriesResponse(
            indicator_code=indicator_code,
            name_cn=indicator_code,
            period_type="",
            data_source="data_center_publication",
            freshness_status="missing",
            decision_grade="blocked",
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_missing",
        ),
    )

    result = _PublishedMacroSeriesQuery().execute(
        MacroSeriesRequest(indicator_code="CN_M2", limit=12)
    )

    assert result.data == []
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "canonical_publication_missing"
