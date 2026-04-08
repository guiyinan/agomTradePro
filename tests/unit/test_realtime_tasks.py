from apps.realtime.application.tasks import poll_realtime_prices_task


def test_poll_realtime_prices_task_polls_full_watchlist_when_no_assets(mocker) -> None:
    """Periodic realtime polling should call the full polling workflow by default."""
    use_case = mocker.Mock()
    use_case.execute_price_polling.return_value = {"success": True, "total": 3}
    mocker.patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    )

    result = poll_realtime_prices_task(asset_codes=[])

    use_case.execute_price_polling.assert_called_once_with()
    use_case.get_latest_prices.assert_not_called()
    assert result == {"success": True, "total": 3}


def test_poll_realtime_prices_task_fetches_specific_assets_when_requested(mocker) -> None:
    """Explicit asset requests should use the latest-price query path instead of full polling."""
    use_case = mocker.Mock()
    use_case.get_latest_prices.return_value = [{"asset_code": "510300.SH", "price": 4.2}]
    mocker.patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase",
        return_value=use_case,
    )

    result = poll_realtime_prices_task(asset_codes=["510300.SH", ""])

    use_case.get_latest_prices.assert_called_once_with(["510300.SH"])
    use_case.execute_price_polling.assert_not_called()
    assert result == {
        "success": True,
        "asset_codes": ["510300.SH"],
        "prices": [{"asset_code": "510300.SH", "price": 4.2}],
    }
