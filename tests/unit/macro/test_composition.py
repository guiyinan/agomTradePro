from apps.data_center.application.dtos import MacroSeriesRequest, MacroSeriesResponse
from apps.macro.composition import _PublishedMacroSeriesQuery


class _Delegate:
    def __init__(self) -> None:
        self.requests: list[MacroSeriesRequest] = []

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        self.requests.append(request)
        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn="M2",
            period_type="M",
            data_source="data_center_fact",
            freshness_status="fresh",
            decision_grade="decision_safe",
            must_not_use_for_decision=False,
        )


def test_published_macro_series_query_binds_publication_members(monkeypatch) -> None:
    delegate = _Delegate()
    monkeypatch.setattr(
        "apps.macro.composition.get_current_publication_freshness_gate",
        lambda dataset_key, publication_key: {
            "publication_id": "pub-1",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
        },
    )
    monkeypatch.setattr(
        "apps.macro.composition.get_publication_member_fact_pks",
        lambda publication_id, *, dataset_key, expected_fact_table: ["42"],
    )

    result = _PublishedMacroSeriesQuery(delegate).execute(
        MacroSeriesRequest(indicator_code="CN_M2", limit=12)
    )

    assert result.decision_grade == "decision_safe"
    assert delegate.requests[0].fact_pks == ["42"]


def test_published_macro_series_query_blocks_without_publication(monkeypatch) -> None:
    delegate = _Delegate()
    monkeypatch.setattr(
        "apps.macro.composition.get_current_publication_freshness_gate",
        lambda dataset_key, publication_key: None,
    )

    result = _PublishedMacroSeriesQuery(delegate).execute(
        MacroSeriesRequest(indicator_code="CN_M2", limit=12)
    )

    assert result.data == []
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "canonical_publication_missing"
    assert delegate.requests == []
