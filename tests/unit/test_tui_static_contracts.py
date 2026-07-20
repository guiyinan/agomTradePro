"""Tests for the declarative TUI source contract guard."""

from scripts.check_tui_static_contracts import (
    check_tui_static_contracts,
    evaluate_contract_rules,
)


def test_published_tui_static_contracts_are_satisfied() -> None:
    """Published workbench assets must satisfy every migrated source rule."""

    assert check_tui_static_contracts() == []


def test_tui_static_contract_guard_reports_required_and_forbidden_failures() -> None:
    """The scanner must fail closed for both supported relation types."""

    violations = evaluate_contract_rules(
        {"sample": "present forbidden"},
        [
            {
                "id": "sample:required",
                "source": "sample",
                "relation": "contains",
                "value": "missing",
            },
            {
                "id": "sample:forbidden",
                "source": "sample",
                "relation": "not_contains",
                "value": "forbidden",
            },
        ],
    )

    assert [(item.rule_id, item.message) for item in violations] == [
        ("sample:required", "required text is missing"),
        ("sample:forbidden", "forbidden text is present"),
    ]
