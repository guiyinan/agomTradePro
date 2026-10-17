"""HTTP contracts for transaction-fee availability after the account cutover."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.urls import path, re_path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.account.interface.serializers import TransactionCreateSerializer
from apps.account.interface.transaction_api_views import TransactionViewSet
from tests.support.runtime_config import configure_account_runtime

pytestmark = pytest.mark.django_db

FEE_FIELDS = ("commission", "slippage", "stamp_duty", "transfer_fee")


@pytest.fixture
def auth_user(db: object) -> AbstractBaseUser:
    """Create an approved owner with the same authority shape as API edge tests."""

    configure_account_runtime()
    user = get_user_model().objects.create_user(
        username="fee_availability_api_user",
        password="testpass123",
        email="fee-availability@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Fee Availability API User",
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
            "rbac_role": "owner",
        },
    )
    return user


@pytest.fixture
def owned_portfolio(auth_user: AbstractBaseUser) -> PortfolioModel:
    """Create a real portfolio for serializer and HTTP calls."""

    return PortfolioModel.objects.create(user=auth_user, name="Fee availability")


def _transaction_payload(portfolio_id: int, **overrides: object) -> dict[str, object]:
    """Build a valid ordinary transaction request before applying one test case."""

    return {
        "portfolio": portfolio_id,
        "action": "buy",
        "asset_code": "600000.SH",
        "shares": 10,
        "price": "9.5000",
        "traded_at": timezone.now().isoformat(),
        **overrides,
    }


def _create_position(portfolio: PortfolioModel, asset_code: str) -> PositionModel:
    """Create a real owned position for cross-owner and mismatch requests."""

    return PositionModel.objects.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=10,
        avg_cost=Decimal("9.0000"),
        current_price=Decimal("9.5000"),
        market_value=Decimal("95.00"),
        unrealized_pnl=Decimal("5.00"),
        unrealized_pnl_pct=5.0,
    )


def _create_transaction(
    portfolio: PortfolioModel,
    *,
    traded_at: datetime,
    asset_code: str = "600000.SH",
    **fields: object,
) -> TransactionModel:
    """Insert a real transaction row with explicit test-owned values."""

    return TransactionModel.objects.create(
        portfolio=portfolio,
        action="buy",
        asset_code=asset_code,
        shares=10,
        price=Decimal("9.5000"),
        notional=Decimal("95.00"),
        traded_at=traded_at,
        **fields,
    )


def _schema_component(schema: dict[str, Any], schema_node: Any) -> dict[str, Any]:
    """Resolve one generated OpenAPI component reference for assertions."""
    assert isinstance(schema_node, dict)
    reference = schema_node.get("$ref")
    assert isinstance(reference, str)
    components = schema.get("components")
    assert isinstance(components, dict)
    schemas = components.get("schemas")
    assert isinstance(schemas, dict)
    component = schemas.get(reference.rsplit("/", 1)[-1])
    assert isinstance(component, dict)
    return component


@pytest.mark.parametrize("fee_field", FEE_FIELDS)
@pytest.mark.parametrize(
    ("input_kind", "input_value", "is_valid", "expected"),
    [
        ("missing", None, True, None),
        ("null", None, True, None),
        ("blank", "", True, None),
        ("explicit_zero", "0.00", True, Decimal("0.00")),
    ],
)
def test_create_serializer_uses_is_valid_for_each_fee_input_state(
    owned_portfolio: PortfolioModel,
    fee_field: str,
    input_kind: str,
    input_value: object,
    is_valid: bool,
    expected: Decimal | None,
) -> None:
    """Omitted/null/blank fees stay unknown, while explicit zero remains known."""

    payload = _transaction_payload(owned_portfolio.id)
    if input_kind != "missing":
        payload[fee_field] = input_value

    serializer = TransactionCreateSerializer(data=payload)

    assert serializer.is_valid() is is_valid
    if not is_valid:
        assert fee_field in serializer.errors
        return

    assert serializer.validated_data[fee_field] == expected
    assert all(
        serializer.validated_data[other_field] is None
        for other_field in FEE_FIELDS
        if other_field != fee_field
    )


def test_create_serializer_does_not_accept_client_fee_availability_flags(
    owned_portfolio: PortfolioModel,
) -> None:
    """Availability comes from fee values, not client-supplied *_known fields."""

    payload = _transaction_payload(
        owned_portfolio.id,
        commission="0.00",
        slippage=None,
        stamp_duty="1.20",
        transfer_fee="0.00",
        commission_known=False,
        slippage_known=True,
        stamp_duty_known=False,
        transfer_fee_known=False,
    )
    serializer = TransactionCreateSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["commission"] == Decimal("0.00")
    assert serializer.validated_data["slippage"] is None
    assert serializer.validated_data["stamp_duty"] == Decimal("1.20")
    assert serializer.validated_data["transfer_fee"] == Decimal("0.00")
    assert all(f"{field}_known" not in serializer.validated_data for field in FEE_FIELDS)


def test_create_returns_fee_availability_without_changing_response_shape(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """A real POST preserves the create response while deriving known flags server-side."""

    response = authenticated_client.post(
        "/api/account/transactions/",
        _transaction_payload(
            owned_portfolio.id,
            commission="0.00",
            slippage="",
            stamp_duty="2.50",
            transfer_fee="0.00",
            commission_known=False,
            slippage_known=True,
            stamp_duty_known=False,
            transfer_fee_known=False,
            notes="fee availability",
        ),
        format="json",
    )

    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert "id" not in payload
    assert "notional" not in payload
    assert payload["portfolio"] == owned_portfolio.id
    assert payload["position"] is None
    assert payload["action"] == "buy"
    assert payload["asset_code"] == "600000.SH"
    assert payload["shares"] == 10.0
    assert payload["price"] == "9.5000"
    assert payload["notes"] == "fee availability"
    assert payload["traded_at"]
    assert {
        "commission": (payload["commission"], payload["commission_known"]),
        "slippage": (payload["slippage"], payload["slippage_known"]),
        "stamp_duty": (payload["stamp_duty"], payload["stamp_duty_known"]),
        "transfer_fee": (payload["transfer_fee"], payload["transfer_fee_known"]),
    } == {
        "commission": ("0.00", True),
        "slippage": (None, False),
        "stamp_duty": ("2.50", True),
        "transfer_fee": ("0.00", True),
    }

    record = TransactionModel.objects.get(portfolio=owned_portfolio)
    assert record.commission == Decimal("0.00")
    assert record.commission_known is True
    assert record.slippage == Decimal("0.00")
    assert record.slippage_known is False
    assert record.stamp_duty == Decimal("2.50")
    assert record.stamp_duty_known is True
    assert record.transfer_fee == Decimal("0.00")
    assert record.transfer_fee_known is True


@pytest.mark.parametrize(
    ("format_name", "fee_field"),
    [("json", "slippage"), ("multipart", "stamp_duty")],
)
def test_http_blank_fee_is_unknown_for_json_and_form_requests(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
    format_name: str,
    fee_field: str,
) -> None:
    """JSON and HTML-form blank inputs preserve the unavailable-fee state."""

    response = authenticated_client.post(
        "/api/account/transactions/",
        _transaction_payload(owned_portfolio.id, **{fee_field: ""}),
        format=format_name,
    )

    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload[fee_field] is None
    assert payload[f"{fee_field}_known"] is False
    record = TransactionModel.objects.get(portfolio=owned_portfolio)
    assert getattr(record, fee_field) == Decimal("0.00")
    assert getattr(record, f"{fee_field}_known") is False


def test_create_rejects_negative_fee_with_400(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """A negative actual-fee input fails before a transaction is written."""

    response = authenticated_client.post(
        "/api/account/transactions/",
        _transaction_payload(owned_portfolio.id, commission="-0.01"),
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert not TransactionModel.objects.filter(portfolio=owned_portfolio).exists()


def test_unknown_legacy_fee_amounts_are_hidden_by_the_detail_api(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """Unknown legacy raw amounts remain stored but are not presented as actual fees."""

    record = _create_transaction(
        owned_portfolio,
        traded_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("7.50"),
        commission_known=None,
        slippage=Decimal("2.25"),
        slippage_known=False,
        stamp_duty=Decimal("0.00"),
        stamp_duty_known=True,
        transfer_fee=Decimal("1.20"),
        transfer_fee_known=True,
    )

    response = authenticated_client.get(f"/api/account/transactions/{record.id}/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["commission"] is None
    assert payload["commission_known"] is None
    assert payload["slippage"] is None
    assert payload["slippage_known"] is False
    assert payload["stamp_duty"] == "0.00"
    assert payload["stamp_duty_known"] is True
    assert payload["transfer_fee"] == "1.20"
    assert payload["transfer_fee_known"] is True

    record.refresh_from_db()
    assert record.commission == Decimal("7.50")
    assert record.slippage == Decimal("2.25")


def test_list_and_detail_hide_foreign_transactions_and_return_not_found(
    authenticated_client: APIClient,
    auth_user: AbstractBaseUser,
    owned_portfolio: PortfolioModel,
) -> None:
    """The owner-scoped API returns own rows and masks foreign or missing details."""

    own_record = _create_transaction(owned_portfolio, traded_at=timezone.now())
    foreign_user = get_user_model().objects.create_user(
        username="fee_availability_foreign_user",
        password="testpass123",
    )
    foreign_portfolio = PortfolioModel.objects.create(
        user=foreign_user,
        name="Foreign fee availability",
    )
    foreign_record = _create_transaction(
        foreign_portfolio,
        traded_at=timezone.now() - timedelta(minutes=1),
    )

    list_response = authenticated_client.get("/api/account/transactions/")
    own_detail = authenticated_client.get(f"/api/account/transactions/{own_record.id}/")
    foreign_detail = authenticated_client.get(f"/api/account/transactions/{foreign_record.id}/")
    missing_detail = authenticated_client.get("/api/account/transactions/99999999/")
    zero_detail = authenticated_client.get("/api/account/transactions/0/")

    assert list_response.status_code == 200
    assert list_response["Content-Type"].startswith("application/json")
    listing = list_response.json()
    assert listing["count"] == 1
    assert [row["id"] for row in listing["results"]] == [own_record.id]
    assert own_detail.status_code == 200
    assert own_detail["Content-Type"].startswith("application/json")
    assert foreign_detail.status_code == 404
    assert foreign_detail["Content-Type"].startswith("application/json")
    assert missing_detail.status_code == 404
    assert missing_detail["Content-Type"].startswith("application/json")
    assert zero_detail.status_code == 404
    assert zero_detail["Content-Type"].startswith("application/json")


def test_list_keeps_twenty_item_pages_default_order_and_last_page(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """The page-number contract defaults to 20 and keeps descending traded-time order."""

    newest = timezone.now()
    for index in range(21):
        _create_transaction(
            owned_portfolio,
            traded_at=newest - timedelta(minutes=index),
            asset_code=f"PAGE{index:03d}",
        )

    first_response = authenticated_client.get("/api/account/transactions/?ordering=traded_at")
    last_response = authenticated_client.get("/api/account/transactions/?page=last")

    assert first_response.status_code == 200
    assert first_response["Content-Type"].startswith("application/json")
    first_page = first_response.json()
    assert first_page["count"] == 21
    assert len(first_page["results"]) == 20
    assert first_page["results"][0]["asset_code"] == "PAGE000"
    assert first_page["results"][-1]["asset_code"] == "PAGE019"
    assert first_page["next"]

    assert last_response.status_code == 200
    assert last_response["Content-Type"].startswith("application/json")
    last_page = last_response.json()
    assert last_page["count"] == 21
    assert len(last_page["results"]) == 1
    assert last_page["results"][0]["asset_code"] == "PAGE020"


def test_foreign_existing_position_is_forbidden(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """A real position owned by another user cannot be attached to this user's trade."""

    foreign_user = get_user_model().objects.create_user(
        username="fee_availability_position_owner",
        password="testpass123",
    )
    foreign_portfolio = PortfolioModel.objects.create(
        user=foreign_user,
        name="Foreign position portfolio",
    )
    foreign_position = _create_position(foreign_portfolio, "600000.SH")

    response = authenticated_client.post(
        "/api/account/transactions/",
        _transaction_payload(
            owned_portfolio.id,
            position=foreign_position.id,
            commission="1.00",
        ),
        format="json",
    )

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert not TransactionModel.objects.filter(portfolio=owned_portfolio).exists()


def test_position_from_another_owned_portfolio_is_a_bad_request(
    authenticated_client: APIClient,
    auth_user: AbstractBaseUser,
    owned_portfolio: PortfolioModel,
) -> None:
    """A real same-owner position from another portfolio is a relationship mismatch."""

    other_portfolio = PortfolioModel.objects.create(
        user=auth_user,
        name="Second owned portfolio",
    )
    other_position = _create_position(other_portfolio, "600000.SH")

    response = authenticated_client.post(
        "/api/account/transactions/",
        _transaction_payload(
            owned_portfolio.id,
            position=other_position.id,
            commission="1.00",
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert not TransactionModel.objects.filter(portfolio=owned_portfolio).exists()


@pytest.mark.parametrize(
    ("reference_field", "reference_id"),
    [("portfolio", 99999999), ("position", 99999999)],
)
def test_missing_portfolio_or_position_id_returns_400(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
    reference_field: str,
    reference_id: int,
) -> None:
    """Positive IDs that do not resolve retain the ModelSerializer 400 contract."""

    payload = _transaction_payload(owned_portfolio.id, commission="1.00")
    payload[reference_field] = reference_id

    response = authenticated_client.post(
        "/api/account/transactions/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert not TransactionModel.objects.filter(portfolio=owned_portfolio).exists()


def test_transaction_create_openapi_separates_fee_request_from_server_flags() -> None:
    """The POST schema exposes nullable fees and read-only server availability."""

    schema = SchemaGenerator(
        patterns=[
            path(
                "api/account/transactions/",
                TransactionViewSet.as_view({"post": "create"}),
            )
        ]
    ).get_schema(public=True)

    assert schema is not None
    schema_dict = cast(dict[str, Any], schema)
    path_item = cast(
        dict[str, Any],
        schema_dict["paths"]["/api/account/transactions/"],
    )
    assert "post" in path_item

    operation = cast(dict[str, Any], path_item["post"])
    request_body = cast(dict[str, Any], operation["requestBody"])
    request_content = cast(dict[str, Any], request_body["content"])
    request_json = cast(dict[str, Any], request_content["application/json"])
    request_component = _schema_component(schema_dict, request_json["schema"])
    request_properties = cast(
        dict[str, dict[str, Any]],
        request_component["properties"],
    )
    request_required = cast(list[str], request_component.get("required", []))

    fee_fields = ("commission", "slippage", "stamp_duty", "transfer_fee")
    known_fields = tuple(f"{field}_known" for field in fee_fields)
    for fee_field in fee_fields:
        assert request_properties[fee_field]["nullable"] is True
        assert fee_field not in request_required
    assert not set(known_fields).intersection(request_properties)

    responses = cast(dict[str, Any], operation["responses"])
    created = cast(dict[str, Any], responses["201"])
    response_content = cast(dict[str, Any], created["content"])
    response_json = cast(dict[str, Any], response_content["application/json"])
    response_component = _schema_component(schema_dict, response_json["schema"])
    response_properties = cast(
        dict[str, dict[str, Any]],
        response_component["properties"],
    )
    for fee_field in fee_fields:
        assert response_properties[fee_field]["nullable"] is True
    for known_field in known_fields:
        assert response_properties[known_field]["readOnly"] is True
        assert response_properties[known_field]["nullable"] is True


def test_transaction_detail_openapi_preserves_integer_path_parameter() -> None:
    """The transaction detail ID remains a required integer path parameter."""

    schema = SchemaGenerator(
        patterns=[
            re_path(
                r"^api/account/transactions/(?P<id>[^/.]+)/$",
                TransactionViewSet.as_view({"get": "retrieve"}),
            )
        ]
    ).get_schema(public=True)

    assert schema is not None
    schema_dict = cast(dict[str, Any], schema)
    path_item = cast(
        dict[str, Any],
        schema_dict["paths"]["/api/account/transactions/{id}/"],
    )
    operation = cast(dict[str, Any], path_item["get"])
    parameters = cast(list[dict[str, Any]], operation["parameters"])
    id_parameters = [
        parameter
        for parameter in parameters
        if parameter.get("in") == "path" and parameter.get("name") == "id"
    ]

    assert len(id_parameters) == 1
    id_parameter = id_parameters[0]
    assert id_parameter.get("required") is True
    parameter_schema = cast(dict[str, Any], id_parameter["schema"])
    assert parameter_schema.get("type") == "integer"


def test_transaction_read_openapi_preserves_legacy_non_fee_metadata() -> None:
    """Keep the original read contract for every non-fee transaction field."""

    schema = SchemaGenerator(
        patterns=[
            re_path(
                r"^api/account/transactions/(?P<id>[^/.]+)/$",
                TransactionViewSet.as_view({"get": "retrieve"}),
            )
        ]
    ).get_schema(public=True)

    assert schema is not None
    schema_dict = cast(dict[str, Any], schema)
    path_item = cast(
        dict[str, Any],
        schema_dict["paths"]["/api/account/transactions/{id}/"],
    )
    operation = cast(dict[str, Any], path_item["get"])
    responses = cast(dict[str, Any], operation["responses"])
    response = cast(dict[str, Any], responses["200"])
    content = cast(dict[str, Any], response["content"])
    response_json = cast(dict[str, Any], content["application/json"])
    component = _schema_component(schema_dict, response_json["schema"])
    properties = cast(dict[str, dict[str, Any]], component["properties"])

    expected_non_fee_properties = {
        "id": {"type": "integer", "readOnly": True},
        "portfolio": {"type": "integer", "title": "投资组合"},
        "portfolio_name": {"type": "string", "readOnly": True},
        "position": {
            "type": "integer",
            "nullable": True,
            "title": "关联持仓",
        },
        "asset_code": {"type": "string", "readOnly": True},
        "shares": {
            "type": "number",
            "format": "double",
            "title": "交易数量",
        },
        "price": {
            "type": "string",
            "format": "decimal",
            "pattern": r"^-?\d{0,16}(?:\.\d{0,4})?$",
            "title": "成交价格",
        },
        "notional": {
            "type": "string",
            "format": "decimal",
            "pattern": r"^-?\d{0,18}(?:\.\d{0,2})?$",
            "title": "成交金额",
        },
        "broker_name": {
            "type": "string",
            "title": "券商名称",
            "maxLength": 64,
        },
        "external_trade_id": {
            "type": "string",
            "title": "外部成交编号",
            "maxLength": 128,
        },
        "broker_trade_key": {
            "type": "string",
            "nullable": True,
            "title": "券商成交去重键",
            "maxLength": 64,
        },
        "import_batch": {
            "type": "integer",
            "nullable": True,
            "title": "导入批次",
        },
        "notes": {"type": "string", "title": "备注"},
        "traded_at": {
            "type": "string",
            "format": "date-time",
            "title": "交易时间",
        },
        "created_at": {
            "type": "string",
            "format": "date-time",
            "readOnly": True,
            "title": "创建时间",
        },
    }
    fee_fields = set(FEE_FIELDS)
    known_fields = {f"{field}_known" for field in FEE_FIELDS}
    non_fee_names = set(properties) - fee_fields - known_fields
    assert non_fee_names == set(expected_non_fee_properties) | {"action"}
    for field_name, expected_metadata in expected_non_fee_properties.items():
        assert properties[field_name] == expected_metadata

    action_schema = properties["action"]
    assert action_schema.get("title") == "交易方向"
    action_reference = cast(list[dict[str, Any]], action_schema["allOf"])[0]
    action_component = _schema_component(schema_dict, action_reference)
    assert action_component.get("enum") == ["buy", "sell"]

    required = set(cast(list[str], component.get("required", [])))
    assert required - fee_fields - known_fields == {
        "action",
        "notional",
        "portfolio",
        "price",
        "shares",
        "traded_at",
    }


def test_transactions_remain_append_only_over_http(
    authenticated_client: APIClient,
    owned_portfolio: PortfolioModel,
) -> None:
    """Fee availability does not add PATCH or DELETE to the transaction API."""

    record = _create_transaction(
        owned_portfolio,
        traded_at=timezone.now(),
        notes="original",
    )

    patch_response = authenticated_client.patch(
        f"/api/account/transactions/{record.id}/",
        {"notes": "rewritten"},
        format="json",
    )
    delete_response = authenticated_client.delete(f"/api/account/transactions/{record.id}/")

    assert patch_response.status_code == 405
    assert patch_response["Content-Type"].startswith("application/json")
    assert delete_response.status_code == 405
    assert delete_response["Content-Type"].startswith("application/json")
    record.refresh_from_db()
    assert record.notes == "original"


@pytest.mark.parametrize(
    "transaction_id",
    ["²", "9" * 5000],
    ids=["unicode-digit-not-an-integer", "oversized-decimal"],
)
def test_unparseable_transaction_detail_id_returns_json_not_found(
    authenticated_client: APIClient,
    transaction_id: str,
) -> None:
    """Malformed numeric identifiers retain the detail endpoint's 404 contract."""
    response = authenticated_client.get(f"/api/account/transactions/{transaction_id}/")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
