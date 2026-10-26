"""Protect the write-alias lookup used by M1 audit instance updates."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from apps.risk_center.infrastructure import models as risk_models
from apps.risk_center.infrastructure.models import RiskPolicyAuditModel


def _audit_row(
    *,
    target_type: str = RiskPolicyAuditModel.TARGET_POLICY,
    pk: int | None = None,
) -> RiskPolicyAuditModel:
    """Create one legacy audit instance without touching a database."""

    audit = RiskPolicyAuditModel(
        target_type=target_type,
        target_id="risk-policy-v1",
        action="publish",
    )
    audit.pk = pk
    return audit


def _target_type_expressions() -> tuple[object, ...]:
    """Return common ORM expressions that must never impersonate literals."""

    m1_target = RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
    return (
        models.Value(m1_target),
        models.F("target_type"),
        models.Case(
            models.When(pk=41, then=models.Value(m1_target)),
            default=models.Value(RiskPolicyAuditModel.TARGET_POLICY),
            output_field=models.CharField(max_length=32),
        ),
    )


def _route_exists_to_write_alias(
    monkeypatch: pytest.MonkeyPatch,
    *,
    has_m1_row_on_write_alias: bool = True,
) -> tuple[list[str], Mock, Mock]:
    """Record the alias used by preflight queries and model a separate read route."""

    observed_aliases: list[str] = []
    route_read = Mock(return_value="risk_read")
    route_write = Mock(return_value="risk_write")
    monkeypatch.setattr(risk_models.router, "db_for_read", route_read)
    monkeypatch.setattr(risk_models.router, "db_for_write", route_write)

    def exists(queryset: models.QuerySet[RiskPolicyAuditModel]) -> bool:
        alias = queryset.db
        observed_aliases.append(alias)
        return alias == "risk_write" and has_m1_row_on_write_alias

    monkeypatch.setattr(models.QuerySet, "exists", exists)
    return observed_aliases, route_read, route_write


def _stub_persisted_target_type(
    monkeypatch: pytest.MonkeyPatch,
    target_type: str,
) -> list[str]:
    """Stub a row lookup while recording the queryset's resolved database alias."""

    observed_aliases: list[str] = []

    def values(
        queryset: models.QuerySet[RiskPolicyAuditModel],
        *fields: str,
        **expressions: object,
    ) -> Mock:
        observed_aliases.append(queryset.db)
        result = Mock()
        result.first.return_value = {"target_type": target_type}
        return result

    monkeypatch.setattr(models.QuerySet, "values", values)
    return observed_aliases


@pytest.mark.parametrize(
    ("requested_using", "routed_alias", "expected_alias", "router_called"),
    (
        ("risk_audit", "default", "risk_audit", False),
        (None, "risk_audit", "risk_audit", True),
    ),
)
def test_existing_m1_audit_is_checked_on_the_write_alias(
    requested_using: str | None,
    routed_alias: str,
    expected_alias: str,
    router_called: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale default read must not let a non-default M1 audit row be rewritten."""

    audit = RiskPolicyAuditModel(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        target_id="risk-policy-v1",
        action="publish",
    )
    audit.pk = 41
    audit._state.adding = False

    observed_aliases = _stub_persisted_target_type(
        monkeypatch,
        RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
    )

    route_write = Mock(return_value=routed_alias)
    monkeypatch.setattr(risk_models.router, "db_for_write", route_write)
    base_save = Mock()
    monkeypatch.setattr(models.Model, "save", base_save)

    with pytest.raises(ValidationError, match="append-only"):
        audit.save(using=requested_using)

    assert observed_aliases == [expected_alias]
    base_save.assert_not_called()
    assert route_write.call_count == (1 if router_called else 0)


@pytest.mark.parametrize(
    ("requested_using", "routed_alias", "expected_alias", "router_called"),
    (("risk_audit", "default", "risk_audit", False), (None, "risk_audit", "risk_audit", True)),
)
def test_delete_rejects_existing_m1_audit_on_the_write_alias(
    requested_using: str | None,
    routed_alias: str,
    expected_alias: str,
    router_called: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutable instance label cannot redirect the persisted-row guard."""

    audit = RiskPolicyAuditModel(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        target_id="risk-policy-v1",
        action="publish",
    )
    audit.pk = 41
    audit._state.adding = False

    observed_aliases = _stub_persisted_target_type(
        monkeypatch,
        RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
    )

    route_write = Mock(return_value=routed_alias)
    monkeypatch.setattr(risk_models.router, "db_for_write", route_write)
    base_delete = Mock()
    monkeypatch.setattr(models.Model, "delete", base_delete)

    with pytest.raises(ValidationError, match="append-only"):
        audit.delete(using=requested_using)

    assert observed_aliases == [expected_alias]
    base_delete.assert_not_called()
    assert route_write.call_count == (1 if router_called else 0)


def test_delete_preserves_legacy_audit_rows_and_returns_django_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-M1 audit evidence retains ordinary deletion on its routed write DB."""

    audit = RiskPolicyAuditModel(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        target_id="legacy-policy-v1",
        action="delete",
    )
    audit.pk = 42
    audit._state.adding = False

    observed_aliases = _stub_persisted_target_type(
        monkeypatch,
        RiskPolicyAuditModel.TARGET_POLICY,
    )
    route_write = Mock(return_value="risk_audit")
    monkeypatch.setattr(risk_models.router, "db_for_write", route_write)
    expected_result = (1, {"risk_center.RiskPolicyAuditModel": 1})
    base_delete = Mock(return_value=expected_result)
    monkeypatch.setattr(models.Model, "delete", base_delete)

    result = audit.delete()

    assert observed_aliases == ["risk_audit"]
    base_delete.assert_called_once_with(using="risk_audit", keep_parents=False)
    assert result == expected_result


@pytest.mark.parametrize("expression", _target_type_expressions(), ids=("value", "f", "case"))
def test_queryset_update_rejects_expression_target_type(
    expression: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Target expressions cannot create or disguise M1 audit rows."""

    base_exists = Mock(return_value=False)
    monkeypatch.setattr(models.QuerySet, "exists", base_exists)
    base_update = Mock(return_value=1)
    monkeypatch.setattr(models.QuerySet, "update", base_update)

    with pytest.raises(ValidationError, match="literal"):
        RiskPolicyAuditModel.objects.filter(pk=41).update(target_type=expression)

    base_update.assert_not_called()


@pytest.mark.parametrize("expression", _target_type_expressions(), ids=("value", "f", "case"))
def test_model_save_rejects_expression_target_type(
    expression: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model insertion cannot use an expression to impersonate an M1 target."""

    audit = _audit_row()
    audit.target_type = cast(str, expression)
    base_save = Mock()
    monkeypatch.setattr(models.Model, "save", base_save)

    with pytest.raises(ValidationError, match="literal"):
        audit.save()

    base_save.assert_not_called()


@pytest.mark.parametrize("expression", _target_type_expressions(), ids=("value", "f", "case"))
def test_bulk_create_rejects_expression_target_type(
    expression: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk insertion cannot bypass the repository-only M1 audit path."""

    audit = _audit_row()
    audit.target_type = cast(str, expression)
    base_bulk_create = Mock()
    monkeypatch.setattr(models.QuerySet, "bulk_create", base_bulk_create)

    with pytest.raises(ValidationError, match="literal"):
        RiskPolicyAuditModel.objects.bulk_create([audit])

    base_bulk_create.assert_not_called()


@pytest.mark.parametrize("expression", _target_type_expressions(), ids=("value", "f", "case"))
def test_bulk_update_rejects_target_type_assignments(
    expression: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk target-type changes stay blocked because Django lowers them to CASE."""

    audit = _audit_row(pk=41)
    audit.target_type = cast(str, expression)
    base_exists = Mock(return_value=False)
    monkeypatch.setattr(models.QuerySet, "exists", base_exists)
    base_bulk_update = Mock(return_value=1)
    monkeypatch.setattr(models.QuerySet, "bulk_update", base_bulk_update)

    with pytest.raises(ValidationError, match="target_type"):
        RiskPolicyAuditModel.objects.bulk_update([audit], ["target_type"])

    base_bulk_update.assert_not_called()


def test_save_on_adding_instance_checks_explicit_primary_key_on_write_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An adding instance with an explicit pk cannot overwrite a persisted M1 row."""

    audit = _audit_row(pk=41)
    assert audit._state.adding is True
    observed_aliases = _stub_persisted_target_type(
        monkeypatch,
        RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
    )
    route_write = Mock(return_value="risk_write")
    monkeypatch.setattr(risk_models.router, "db_for_write", route_write)
    base_save = Mock()
    monkeypatch.setattr(models.Model, "save", base_save)

    with pytest.raises(ValidationError, match="append-only"):
        audit.save()

    route_write.assert_called_once()
    assert observed_aliases == ["risk_write"]
    base_save.assert_not_called()


def test_queryset_update_checks_existing_m1_rows_on_write_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct read router cannot hide M1 rows from an ordinary update."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(monkeypatch)
    base_update = Mock(return_value=1)
    monkeypatch.setattr(models.QuerySet, "update", base_update)

    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.filter(pk=41).update(reason="legacy edit")

    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_update.assert_not_called()


def test_queryset_delete_checks_existing_m1_rows_on_write_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct read router cannot hide M1 rows from a bulk delete."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(monkeypatch)
    base_delete = Mock(return_value=(1, {"risk_center.RiskPolicyAuditModel": 1}))
    monkeypatch.setattr(models.QuerySet, "delete", base_delete)

    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.filter(pk=41).delete()

    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_delete.assert_not_called()


def test_bulk_update_checks_existing_m1_rows_on_write_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk updates must inspect persisted identities on the write database."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(monkeypatch)
    base_bulk_update = Mock(return_value=1)
    monkeypatch.setattr(models.QuerySet, "bulk_update", base_bulk_update)

    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.bulk_update([_audit_row(pk=41)], ["reason"])

    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_bulk_update.assert_not_called()


def test_bulk_create_upsert_cannot_replace_m1_row_on_write_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy payload plus a conflicting M1 primary key cannot rewrite evidence."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(monkeypatch)
    base_bulk_create = Mock()
    monkeypatch.setattr(models.QuerySet, "bulk_create", base_bulk_create)

    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.bulk_create(
            [_audit_row(pk=41)],
            update_conflicts=True,
            update_fields=["reason"],
            unique_fields=["pk"],
        )

    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_bulk_create.assert_not_called()


def test_legacy_literal_update_and_delete_remain_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary legacy literals still use the write alias and reach Django."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(
        monkeypatch,
        has_m1_row_on_write_alias=False,
    )
    base_update = Mock(return_value=1)
    base_delete = Mock(return_value=(1, {"risk_center.RiskPolicyAuditModel": 1}))
    monkeypatch.setattr(models.QuerySet, "update", base_update)
    monkeypatch.setattr(models.QuerySet, "delete", base_delete)

    updated = RiskPolicyAuditModel.objects.filter(pk=41).update(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        reason="legacy edit",
    )
    deleted = RiskPolicyAuditModel.objects.filter(pk=42).delete()

    assert updated == 1
    assert deleted == (1, {"risk_center.RiskPolicyAuditModel": 1})
    assert observed_aliases == ["risk_write", "risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_update.assert_called_once_with(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        reason="legacy edit",
    )
    base_delete.assert_called_once()


def test_legacy_bulk_update_of_non_target_field_remains_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk updating a legacy non-target field remains supported on its writer."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(
        monkeypatch,
        has_m1_row_on_write_alias=False,
    )
    base_bulk_update = Mock(return_value=1)
    monkeypatch.setattr(models.QuerySet, "bulk_update", base_bulk_update)

    result = RiskPolicyAuditModel.objects.bulk_update([_audit_row(pk=41)], ["reason"])

    assert result == 1
    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_bulk_update.assert_called_once()


def test_legacy_conflict_upsert_remains_available_when_no_m1_row_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy upsert with a non-M1 pk retains normal Django behavior."""

    observed_aliases, route_read, route_write = _route_exists_to_write_alias(
        monkeypatch,
        has_m1_row_on_write_alias=False,
    )
    audit = _audit_row(pk=52)
    base_bulk_create = Mock(return_value=[audit])
    monkeypatch.setattr(models.QuerySet, "bulk_create", base_bulk_create)

    result = RiskPolicyAuditModel.objects.bulk_create(
        [audit],
        update_conflicts=True,
        update_fields=["reason"],
        unique_fields=["pk"],
    )

    assert result == [audit]
    assert observed_aliases == ["risk_write"]
    route_read.assert_not_called()
    route_write.assert_called()
    base_bulk_create.assert_called_once_with(
        [audit],
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=True,
        update_fields=["reason"],
        unique_fields=["pk"],
    )


__all__: tuple[str, ...] = ()
