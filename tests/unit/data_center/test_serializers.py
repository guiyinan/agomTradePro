from apps.data_center.interface.serializers import (
    CapitalFlowQuerySerializer,
    ProviderConfigListSerializer,
)


def test_provider_config_list_masks_nested_credentials() -> None:
    serializer = ProviderConfigListSerializer()
    provider = {
        "api_key": "top-level-key",
        "api_secret": "top-level-secret",
        "extra_config": {
            "region": "cn",
            "credentials": {
                "token": "nested-token",
                "endpoint": "https://example.test",
            },
        },
    }

    assert serializer.get_has_api_key(provider) is True
    assert serializer.get_has_api_secret(provider) is True
    assert serializer.get_extra_config(provider) == {
        "region": "cn",
        "credentials": {"endpoint": "https://example.test"},
    }


def test_capital_flow_query_rejects_unknown_parameters() -> None:
    serializer = CapitalFlowQuerySerializer(data={"asset_code": "000001.SZ", "period": "5d"})

    assert not serializer.is_valid()
    assert "Unknown query parameters: period" in str(serializer.errors)


def test_capital_flow_query_rejects_inverted_date_range() -> None:
    serializer = CapitalFlowQuerySerializer(
        data={
            "asset_code": "000001.SZ",
            "start": "2026-07-20",
            "end": "2026-07-01",
        }
    )

    assert not serializer.is_valid()
    assert "start must be on or before end" in str(serializer.errors)
