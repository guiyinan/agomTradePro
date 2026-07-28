"""Terminal permission boundary tests."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser, Group, User
from rest_framework.views import APIView

from apps.terminal.interface.permissions import IsStaffOrAdmin, IsStaffOrOperator


def _request_for(user):
    return SimpleNamespace(user=user)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("is_staff", "is_superuser", "expected"),
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
    ],
)
def test_staff_permission_uses_authenticated_django_flags(
    is_staff,
    is_superuser,
    expected,
):
    user = User.objects.create_user(
        username=f"permission-{is_staff}-{is_superuser}",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )

    assert IsStaffOrAdmin().has_permission(_request_for(user), APIView()) is expected


@pytest.mark.django_db
def test_operator_permission_accepts_only_operator_group_member():
    operator = User.objects.create_user(username="terminal-operator")
    regular = User.objects.create_user(username="terminal-regular")
    operator.groups.add(Group.objects.create(name="operator"))

    permission = IsStaffOrOperator()

    assert permission.has_permission(_request_for(operator), APIView()) is True
    assert permission.has_permission(_request_for(regular), APIView()) is False


def test_terminal_permissions_reject_anonymous_user():
    request = _request_for(AnonymousUser())

    assert IsStaffOrAdmin().has_permission(request, APIView()) is False
    assert IsStaffOrOperator().has_permission(request, APIView()) is False


def test_truthy_string_staff_flag_does_not_grant_access():
    groups = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: False))
    user = SimpleNamespace(
        is_authenticated=True,
        is_staff="false",
        is_superuser=False,
        groups=groups,
    )

    assert IsStaffOrAdmin().has_permission(_request_for(user), APIView()) is False
    assert IsStaffOrOperator().has_permission(_request_for(user), APIView()) is False


def test_truthy_string_group_result_does_not_grant_operator_access():
    groups = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: "false"))
    user = SimpleNamespace(
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        groups=groups,
    )

    assert IsStaffOrOperator().has_permission(_request_for(user), APIView()) is False
