from core.integration.realtime_polling import execute_realtime_price_polling


class _FakePricePollingUseCase:
    def execute_price_polling(self):
        return {"total_assets": 2, "success_count": 2, "failed_count": 0}


def test_execute_realtime_price_polling_uses_realtime_use_case(monkeypatch):
    monkeypatch.setattr(
        "core.integration.realtime_polling.PricePollingUseCase",
        lambda: _FakePricePollingUseCase(),
    )

    assert execute_realtime_price_polling()["success_count"] == 2
