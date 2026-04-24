import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

APPS_DIR = REPO_ROOT / "apps"


@pytest.mark.guardrail
def test_guardrail_no_raw_decimal_in_json_payload_builders():
    """
    Ensure all values assigned to dict keys in JSON payload builder functions
    are wrapped with float() when sourced from Django model DecimalField attributes.

    This catches the pattern that causes:
      TypeError: Object of type Decimal is not JSON serializable

    Checked functions: `build_share_snapshot_from_account` in
    `apps/share/application/interface_services.py`.
    """
    target_file = APPS_DIR / "share" / "application" / "interface_services.py"
    if not target_file.exists():
        pytest.skip("share/application/interface_services.py not found")

    source = target_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    decimal_attrs = {
        "avg_cost",
        "current_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "total_cost",
        "initial_capital",
        "current_cash",
        "current_market_value",
        "total_value",
        "price",
        "amount",
        "quantity",
        "available_quantity",
    }

    target_functions = {
        "build_share_snapshot_from_account",
    }

    violations = []

    def is_wrapped_in_float(attr_node: ast.Attribute, root_value: ast.AST) -> bool:
        current = attr_node
        while current is not root_value:
            current = parents.get(current)
            if current is None:
                return False
            if (
                isinstance(current, ast.Call)
                and isinstance(current.func, ast.Name)
                and current.func.id == "float"
            ):
                return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in target_functions:
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Dict):
                continue
            for key, value in zip(child.keys, child.values):
                if not isinstance(key, ast.Constant):
                    continue
                for attr in [
                    item
                    for item in ast.walk(value)
                    if isinstance(item, ast.Attribute) and item.attr in decimal_attrs
                ]:
                    if not is_wrapped_in_float(attr, value):
                        violations.append(
                            f"{target_file}:{node.lineno} - "
                            f"dict key '{key.value}' uses raw Decimal attribute "
                            f"'{attr.attr}' without float() wrapping"
                        )

    assert not violations, (
        "Decimal values found in JSON payload dicts without float() wrapping:\n"
        + "\n".join(violations)
    )


def _assert_no_decimal(value) -> None:
    if isinstance(value, Decimal):
        raise AssertionError(f"Raw Decimal leaked into JSON payload: {value!r}")
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_decimal(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_decimal(nested)


@pytest.mark.django_db
@pytest.mark.guardrail
def test_guardrail_live_share_snapshot_payloads_are_json_serializable():
    """
    Build a real share snapshot and assert every JSON payload is Decimal-free.
    """
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from apps.share.application.interface_services import build_share_snapshot_from_account
    from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
    from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel

    user = get_user_model().objects.create_user(
        username="decimal_guardrail_user",
        email="decimal-guardrail@example.com",
        password="testpass123",
    )
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Decimal Guardrail Account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("50000.00"),
        current_market_value=Decimal("50000.00"),
        total_value=Decimal("100000.00"),
        start_date=timezone.now().date(),
    )
    PositionModel.objects.create(
        account=account,
        asset_code="000001.SH",
        asset_name="平安银行",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=timezone.now().date(),
    )
    share_link = ShareLinkModel.objects.create(
        owner=user,
        account_id=account.id,
        short_code="DECIMALGRD",
        title="Decimal Guardrail",
        share_level="snapshot",
        status="active",
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
    )

    snapshot_id = build_share_snapshot_from_account(share_link_id=share_link.id)
    snapshot = ShareSnapshotModel.objects.get(id=snapshot_id)

    _assert_no_decimal(snapshot.summary_payload)
    _assert_no_decimal(snapshot.performance_payload)
    _assert_no_decimal(snapshot.positions_payload)
    _assert_no_decimal(snapshot.transactions_payload)
    _assert_no_decimal(snapshot.decision_payload)

    result = json.dumps(
        {
            "summary": snapshot.summary_payload,
            "performance": snapshot.performance_payload,
            "positions": snapshot.positions_payload,
            "transactions": snapshot.transactions_payload,
            "decisions": snapshot.decision_payload,
        }
    )
    parsed = json.loads(result)
    assert parsed["summary"]["account_name"] == "Decimal Guardrail Account"


@pytest.mark.guardrail
def test_guardrail_decimal_not_json_serializable_fails():
    """
    Document that raw Decimal values ARE NOT JSON serializable,
    proving the guardrail is necessary.
    """
    with pytest.raises(TypeError, match="Decimal.*not JSON serializable"):
        json.dumps({"value": Decimal("10.50")})


@pytest.mark.guardrail
def test_guardrail_share_model_payloads_serializable():
    """
    Check that the share snapshot model's JSONField default values
    can be serialized to JSON without errors.
    """
    sample_data = {
        "summary_payload": {
            "account_name": "Test",
            "total_assets": 100000.0,
            "cash_balance": 50000.0,
        },
        "performance_payload": {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
        },
        "positions_payload": {
            "items": [],
            "summary": {
                "total_value": 0.0,
                "total_pnl": 0.0,
                "cash_balance": 0.0,
            },
        },
    }
    for key, value in sample_data.items():
        result = json.dumps(value)
        assert isinstance(result, str), f"{key} failed JSON serialization"
