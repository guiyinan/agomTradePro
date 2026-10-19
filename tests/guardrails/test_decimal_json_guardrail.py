import ast
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = REPO_ROOT / "apps"

DECIMAL_ATTRIBUTES: frozenset[str] = frozenset(
    {
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
)


def _iter_unwrapped_decimal_output_attributes(
    expression: ast.AST,
    decimal_attributes: frozenset[str],
    *,
    converted_to_float: bool = False,
) -> Iterator[ast.Attribute]:
    """Yield Decimal attributes that can reach a JSON value without float()."""

    if isinstance(expression, ast.Dict):
        # Nested mappings are visited once by the enclosing FunctionDef scan.
        return
    if isinstance(expression, ast.IfExp):
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.body, decimal_attributes, converted_to_float=converted_to_float
        )
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.orelse, decimal_attributes, converted_to_float=converted_to_float
        )
        return
    if isinstance(expression, ast.Compare):
        # Comparisons emit bool; their Decimal operands are control data.
        return
    if isinstance(expression, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        # Only the emitted element is a value; iterables and filters are control data.
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.elt, decimal_attributes, converted_to_float=converted_to_float
        )
        return
    if isinstance(expression, ast.DictComp):
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.key, decimal_attributes, converted_to_float=converted_to_float
        )
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.value, decimal_attributes, converted_to_float=converted_to_float
        )
        return
    if isinstance(expression, ast.JoinedStr):
        # An f-string is a string payload, not a raw Decimal value.
        return
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        # `not decimal_value` emits bool; arithmetic unary operators still recurse.
        return
    if isinstance(expression, ast.Call):
        if isinstance(expression.func, ast.Name) and expression.func.id in {"all", "any"}:
            # These builtins emit bool even when a predicate tests Decimal values.
            return
        is_float_call = isinstance(expression.func, ast.Name) and expression.func.id == "float"
        child_conversion = converted_to_float or is_float_call
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.func, decimal_attributes, converted_to_float=converted_to_float
        )
        for argument in expression.args:
            yield from _iter_unwrapped_decimal_output_attributes(
                argument, decimal_attributes, converted_to_float=child_conversion
            )
        for keyword in expression.keywords:
            yield from _iter_unwrapped_decimal_output_attributes(
                keyword.value, decimal_attributes, converted_to_float=child_conversion
            )
        return
    if isinstance(expression, ast.Attribute):
        if expression.attr in decimal_attributes and not converted_to_float:
            yield expression
        yield from _iter_unwrapped_decimal_output_attributes(
            expression.value, decimal_attributes, converted_to_float=converted_to_float
        )
        return

    for child in ast.iter_child_nodes(expression):
        yield from _iter_unwrapped_decimal_output_attributes(
            child, decimal_attributes, converted_to_float=converted_to_float
        )


def _find_unwrapped_decimal_output_attributes(
    function_node: ast.FunctionDef,
    decimal_attributes: frozenset[str],
) -> list[tuple[ast.Constant, ast.Attribute]]:
    """Inspect every literal-key mapping value in a function for raw Decimal output."""

    violations: list[tuple[ast.Constant, ast.Attribute]] = []
    for child in ast.walk(function_node):
        if not isinstance(child, ast.Dict):
            continue
        for key, value in zip(child.keys, child.values, strict=True):
            if not isinstance(key, ast.Constant):
                continue
            for attribute in _iter_unwrapped_decimal_output_attributes(value, decimal_attributes):
                violations.append((key, attribute))
    return violations


def _function_from_source(source: str) -> ast.FunctionDef:
    """Parse one function from a small AST guardrail test snippet."""

    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(functions) == 1
    return functions[0]


def _violations_for_expression(expression: str) -> list[tuple[ast.Constant, ast.Attribute]]:
    """Return Decimal sinks in a synthetic dict payload expression."""

    function_node = _function_from_source(f"def build_payload():\n    return {expression}\n")
    return _find_unwrapped_decimal_output_attributes(function_node, DECIMAL_ATTRIBUTES)


@pytest.mark.guardrail
@pytest.mark.parametrize(
    ("expression", "expected_attribute"),
    [
        ('{"value": row.unrealized_pnl}', "unrealized_pnl"),
        (
            '{"value": row.unrealized_pnl if row.enabled else None}',
            "unrealized_pnl",
        ),
        (
            '{"value": float(row.unrealized_pnl) if row.enabled else row.unrealized_pnl}',
            "unrealized_pnl",
        ),
        (
            '{"outer": [{"value": row.unrealized_pnl}]}',
            "unrealized_pnl",
        ),
        (
            '{"values": [row.unrealized_pnl for row in rows]}',
            "unrealized_pnl",
        ),
        ('{"value": row.unrealized_pnl or None}', "unrealized_pnl"),
    ],
    ids=[
        "direct",
        "if-body",
        "else-branch",
        "nested-dict-list",
        "comprehension-elt",
        "boolop-value",
    ],
)
def test_guardrail_ast_finder_rejects_raw_decimal_output(
    expression: str, expected_attribute: str
) -> None:
    """Reject unconverted Decimal values at direct and nested output positions."""

    violations = _violations_for_expression(expression)

    assert [attribute.attr for _, attribute in violations] == [expected_attribute]


@pytest.mark.guardrail
@pytest.mark.parametrize(
    "expression",
    [
        '{"value": float(row.unrealized_pnl)}',
        '{"value": float(row.unrealized_pnl) if row.unrealized_pnl is not None else None}',
        '{"value": None if row.unrealized_pnl is None else float(row.unrealized_pnl)}',
        '{"has_value": any(row.unrealized_pnl for row in rows)}',
        '{"value": float(row.unrealized_pnl) if any(row.unrealized_pnl is not None for row in rows) else None}',
        '{"values": [float(row.unrealized_pnl) for row in rows if row.unrealized_pnl is not None]}',
        '{"outer": [{"value": float(row.market_value) if row.market_value is not None else None}]}',
    ],
    ids=[
        "float-output",
        "is-not-none-condition",
        "is-none-condition",
        "any-bool-output",
        "any-condition",
        "comprehension-filter",
        "nested-float-and-none",
    ],
)
def test_guardrail_ast_finder_allows_conditions_and_converted_output(
    expression: str,
) -> None:
    """Ignore control-only Decimal reads while checking emitted values."""

    assert _violations_for_expression(expression) == []


@pytest.mark.guardrail
def test_guardrail_no_raw_decimal_in_json_payload_builders() -> None:
    """Reject raw Decimal attributes in the production share snapshot payload."""

    target_file = APPS_DIR / "share" / "application" / "interface_services.py"
    if not target_file.exists():
        pytest.skip("share/application/interface_services.py not found")

    tree = ast.parse(target_file.read_text(encoding="utf-8"))
    target_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_share_snapshot_from_account"
    ]
    assert len(target_functions) == 1

    violations = _find_unwrapped_decimal_output_attributes(target_functions[0], DECIMAL_ATTRIBUTES)
    details = [
        f"{target_file}:{attribute.lineno} - dict key {key.value!r} "
        f"uses raw Decimal attribute {attribute.attr!r} without float() wrapping"
        for key, attribute in violations
    ]

    assert (
        not details
    ), "Decimal values found in JSON payload dicts without float() wrapping:\n" + "\n".join(details)


def _assert_no_decimal(value: object) -> None:
    """Recursively reject raw Decimal objects in JSON-shaped values."""

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
@pytest.mark.parametrize(
    "valuation_known",
    [True, False],
    ids=["known-valuation", "unknown-valuation"],
)
def test_guardrail_live_share_snapshot_payloads_are_json_serializable(
    valuation_known: bool,
) -> None:
    """Serialize real known and unknown-valuation share snapshot payloads."""

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from apps.share.application.interface_services import build_share_snapshot_from_account
    from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
    from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel

    user = get_user_model().objects.create_user(
        username=f"decimal_guardrail_user_{int(valuation_known)}",
        email=f"decimal-guardrail-{int(valuation_known)}@example.com",
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
        cost_basis_known=True,
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        valuation_known=valuation_known,
        unrealized_pnl=Decimal("50.00"),
        unrealized_pnl_pct=5.0,
        first_buy_date=timezone.now().date(),
    )
    share_link = ShareLinkModel.objects.create(
        owner=user,
        account_id=account.id,
        short_code=f"DECIMAL{int(valuation_known)}",
        title="Decimal Guardrail",
        share_level="snapshot",
        status="active",
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
    )

    snapshot_id = build_share_snapshot_from_account(share_link_id=share_link.id)
    assert snapshot_id is not None
    snapshot = ShareSnapshotModel.objects.get(id=snapshot_id)

    _assert_no_decimal(snapshot.summary_payload)
    _assert_no_decimal(snapshot.performance_payload)
    _assert_no_decimal(snapshot.positions_payload)
    _assert_no_decimal(snapshot.transactions_payload)
    _assert_no_decimal(snapshot.decision_payload)

    serialized = json.dumps(
        {
            "summary": snapshot.summary_payload,
            "performance": snapshot.performance_payload,
            "positions": snapshot.positions_payload,
            "transactions": snapshot.transactions_payload,
            "decisions": snapshot.decision_payload,
        }
    )
    parsed = json.loads(serialized)
    assert parsed["summary"]["account_name"] == "Decimal Guardrail Account"
    assert parsed["summary"]["cash_known"] is True
    assert parsed["summary"]["cash_reconciliation_status"] == "simulated_ledger"
    assert parsed["summary"]["cash_balance"] == 50000.0

    position = parsed["positions"]["items"][0]
    assert position["cost_basis_known"] is True
    assert position["avg_cost"] == 10.0
    assert position["valuation_known"] is valuation_known
    assert position["current_price"] == (10.5 if valuation_known else None)
    assert position["market_value"] == (1050.0 if valuation_known else None)
    assert position["pnl"] == (50.0 if valuation_known else None)
    assert position["return_pct"] == (5.0 if valuation_known else None)

    position_summary = parsed["positions"]["summary"]
    assert position_summary["total_value"] == (50000.0 if valuation_known else None)
    assert position_summary["total_pnl"] == (50.0 if valuation_known else None)
    assert position_summary["total_pnl_known"] is valuation_known
    assert parsed["summary"]["total_assets"] == (100000.0 if valuation_known else None)
    assert parsed["summary"]["valuation_known"] is valuation_known
    assert parsed["performance"]["valuation_known"] is valuation_known
    if not valuation_known:
        assert position_summary["asset_allocation"] == []


@pytest.mark.guardrail
def test_guardrail_decimal_not_json_serializable_fails() -> None:
    """Document that JSON encoding rejects a raw Decimal object."""

    with pytest.raises(TypeError, match="Decimal.*not JSON serializable"):
        json.dumps({"value": Decimal("10.50")})


@pytest.mark.guardrail
def test_guardrail_share_model_payloads_serializable() -> None:
    """Check that share snapshot JSONField-style defaults serialize."""

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
