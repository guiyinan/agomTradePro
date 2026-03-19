"""
Terminal Governance Domain & Application Tests.

Tests for risk levels, permissions, confirmation tokens, and execution flow.
"""

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from apps.terminal.domain.entities import (
    CommandType,
    TerminalAuditEntry,
    TerminalCommand,
    TerminalMode,
    TerminalRiskLevel,
)
from apps.terminal.domain.services import (
    RISK_ROLE_MAP,
    TerminalPermissionService,
)


# ========== Domain: TerminalRiskLevel ==========

class TestTerminalRiskLevel:
    """TerminalRiskLevel enum tests."""

    def test_enum_values(self):
        assert TerminalRiskLevel.READ.value == 'read'
        assert TerminalRiskLevel.WRITE_LOW.value == 'write_low'
        assert TerminalRiskLevel.WRITE_HIGH.value == 'write_high'
        assert TerminalRiskLevel.ADMIN.value == 'admin'

    def test_string_enum(self):
        assert isinstance(TerminalRiskLevel.READ, str)
        assert TerminalRiskLevel.READ == 'read'

    def test_from_string(self):
        assert TerminalRiskLevel('read') == TerminalRiskLevel.READ
        assert TerminalRiskLevel('admin') == TerminalRiskLevel.ADMIN


class TestTerminalMode:
    """TerminalMode enum tests."""

    def test_enum_values(self):
        assert TerminalMode.READONLY.value == 'readonly'
        assert TerminalMode.CONFIRM_EACH.value == 'confirm_each'
        assert TerminalMode.AUTO_CONFIRM.value == 'auto_confirm'


# ========== Domain: TerminalCommand governance fields ==========

class TestTerminalCommandGovernance:
    """TerminalCommand entity governance field tests."""

    def test_default_governance_fields(self):
        cmd = TerminalCommand(
            id='1',
            name='test',
            description='test command',
            command_type=CommandType.API,
        )
        assert cmd.risk_level == TerminalRiskLevel.READ
        assert cmd.requires_mcp is True
        assert cmd.enabled_in_terminal is True

    def test_custom_governance_fields(self):
        cmd = TerminalCommand(
            id='2',
            name='admin_cmd',
            description='admin command',
            command_type=CommandType.API,
            risk_level=TerminalRiskLevel.ADMIN,
            requires_mcp=False,
            enabled_in_terminal=False,
        )
        assert cmd.risk_level == TerminalRiskLevel.ADMIN
        assert cmd.requires_mcp is False
        assert cmd.enabled_in_terminal is False

    def test_risk_level_string_coercion(self):
        cmd = TerminalCommand(
            id='3',
            name='test',
            description='test',
            command_type='api',
            risk_level='write_high',
        )
        assert cmd.risk_level == TerminalRiskLevel.WRITE_HIGH

    def test_to_dict_includes_governance(self):
        cmd = TerminalCommand(
            id='4',
            name='test',
            description='test',
            command_type=CommandType.API,
            risk_level=TerminalRiskLevel.WRITE_LOW,
            requires_mcp=False,
            enabled_in_terminal=True,
        )
        d = cmd.to_dict()
        assert d['risk_level'] == 'write_low'
        assert d['requires_mcp'] is False
        assert d['enabled_in_terminal'] is True

    def test_from_dict_includes_governance(self):
        data = {
            'id': '5',
            'name': 'test',
            'description': 'test',
            'type': 'api',
            'risk_level': 'admin',
            'requires_mcp': False,
            'enabled_in_terminal': False,
        }
        cmd = TerminalCommand.from_dict(data)
        assert cmd.risk_level == TerminalRiskLevel.ADMIN
        assert cmd.requires_mcp is False
        assert cmd.enabled_in_terminal is False


# ========== Domain: TerminalAuditEntry ==========

class TestTerminalAuditEntry:
    """TerminalAuditEntry dataclass tests."""

    def test_default_values(self):
        entry = TerminalAuditEntry(
            user_id=1,
            username='admin',
            session_id='abc123',
            command_name='test_cmd',
            risk_level='read',
            mode='confirm_each',
        )
        assert entry.confirmation_status == 'not_required'
        assert entry.result_status == 'pending'
        assert entry.duration_ms == 0
        assert entry.error_message == ''


# ========== Domain: TerminalPermissionService ==========

class TestTerminalPermissionService:
    """TerminalPermissionService role→risk_level matrix tests."""

    @pytest.fixture
    def service(self):
        return TerminalPermissionService()

    # --- can_execute: all role x risk_level combinations ---

    @pytest.mark.parametrize("role,risk_level,expected", [
        # READ - everyone can read
        ("admin", TerminalRiskLevel.READ, True),
        ("owner", TerminalRiskLevel.READ, True),
        ("analyst", TerminalRiskLevel.READ, True),
        ("investment_manager", TerminalRiskLevel.READ, True),
        ("trader", TerminalRiskLevel.READ, True),
        ("risk", TerminalRiskLevel.READ, True),
        ("read_only", TerminalRiskLevel.READ, True),
        # WRITE_LOW
        ("admin", TerminalRiskLevel.WRITE_LOW, True),
        ("owner", TerminalRiskLevel.WRITE_LOW, True),
        ("investment_manager", TerminalRiskLevel.WRITE_LOW, True),
        ("trader", TerminalRiskLevel.WRITE_LOW, True),
        ("analyst", TerminalRiskLevel.WRITE_LOW, False),
        ("risk", TerminalRiskLevel.WRITE_LOW, False),
        ("read_only", TerminalRiskLevel.WRITE_LOW, False),
        # WRITE_HIGH
        ("admin", TerminalRiskLevel.WRITE_HIGH, True),
        ("owner", TerminalRiskLevel.WRITE_HIGH, True),
        ("investment_manager", TerminalRiskLevel.WRITE_HIGH, True),
        ("trader", TerminalRiskLevel.WRITE_HIGH, False),
        ("analyst", TerminalRiskLevel.WRITE_HIGH, False),
        ("risk", TerminalRiskLevel.WRITE_HIGH, False),
        ("read_only", TerminalRiskLevel.WRITE_HIGH, False),
        # ADMIN
        ("admin", TerminalRiskLevel.ADMIN, True),
        ("owner", TerminalRiskLevel.ADMIN, False),
        ("analyst", TerminalRiskLevel.ADMIN, False),
        ("investment_manager", TerminalRiskLevel.ADMIN, False),
        ("trader", TerminalRiskLevel.ADMIN, False),
        ("risk", TerminalRiskLevel.ADMIN, False),
        ("read_only", TerminalRiskLevel.ADMIN, False),
    ])
    def test_can_execute(self, service, role, risk_level, expected):
        assert service.can_execute(role, risk_level) is expected

    # --- get_max_risk_level ---

    def test_admin_max_risk(self, service):
        assert service.get_max_risk_level("admin") == TerminalRiskLevel.ADMIN

    def test_owner_max_risk(self, service):
        assert service.get_max_risk_level("owner") == TerminalRiskLevel.WRITE_HIGH

    def test_trader_max_risk(self, service):
        assert service.get_max_risk_level("trader") == TerminalRiskLevel.WRITE_LOW

    def test_read_only_max_risk(self, service):
        assert service.get_max_risk_level("read_only") == TerminalRiskLevel.READ

    def test_analyst_max_risk(self, service):
        assert service.get_max_risk_level("analyst") == TerminalRiskLevel.READ

    # --- filter_commands_for_role ---

    def _make_cmd(self, name, risk_level=TerminalRiskLevel.READ,
                  requires_mcp=True, enabled=True):
        return TerminalCommand(
            id=name,
            name=name,
            description=f'{name} desc',
            command_type=CommandType.API,
            risk_level=risk_level,
            requires_mcp=requires_mcp,
            enabled_in_terminal=enabled,
        )

    def test_filter_hides_disabled(self, service):
        cmds = [
            self._make_cmd('a', enabled=True),
            self._make_cmd('b', enabled=False),
        ]
        result = service.filter_commands_for_role(cmds, 'admin', True)
        assert len(result) == 1
        assert result[0].name == 'a'

    def test_filter_hides_mcp_when_disabled(self, service):
        cmds = [
            self._make_cmd('a', requires_mcp=True),
            self._make_cmd('b', requires_mcp=False),
        ]
        result = service.filter_commands_for_role(cmds, 'admin', mcp_enabled=False)
        assert len(result) == 1
        assert result[0].name == 'b'

    def test_filter_hides_admin_from_non_admin(self, service):
        cmds = [
            self._make_cmd('a', risk_level=TerminalRiskLevel.READ),
            self._make_cmd('b', risk_level=TerminalRiskLevel.ADMIN),
        ]
        result = service.filter_commands_for_role(cmds, 'analyst', True)
        assert len(result) == 1
        assert result[0].name == 'a'

    def test_filter_shows_all_to_admin(self, service):
        cmds = [
            self._make_cmd('a', risk_level=TerminalRiskLevel.READ),
            self._make_cmd('b', risk_level=TerminalRiskLevel.ADMIN),
        ]
        result = service.filter_commands_for_role(cmds, 'admin', True)
        assert len(result) == 2

    # --- get_available_modes ---

    def test_modes_mcp_disabled(self, service):
        modes = service.get_available_modes('admin', mcp_enabled=False)
        assert modes == ['readonly']

    def test_modes_admin(self, service):
        modes = service.get_available_modes('admin', mcp_enabled=True)
        assert 'auto_confirm' in modes
        assert 'confirm_each' in modes
        assert 'readonly' in modes

    def test_modes_all_roles_get_all_modes_when_mcp_enabled(self, service):
        """All roles get all three modes when MCP is enabled (per task book)."""
        for role in ['admin', 'owner', 'analyst', 'trader', 'read_only']:
            modes = service.get_available_modes(role, mcp_enabled=True)
            assert 'readonly' in modes
            assert 'confirm_each' in modes
            assert 'auto_confirm' in modes, f"{role} should have auto_confirm"


# ========== Application: ConfirmationTokenService ==========

@pytest.mark.django_db
class TestConfirmationTokenService:
    """ConfirmationTokenService tests."""

    @pytest.fixture
    def token_service(self):
        from apps.terminal.application.confirmation import ConfirmationTokenService
        return ConfirmationTokenService()

    def test_create_and_validate_success(self, token_service):
        token, details = token_service.create_token(
            user_id=1,
            command_name='test_cmd',
            params={'symbol': '000001'},
            risk_level='write_high',
            mode='confirm_each',
        )
        assert token
        assert details['command_name'] == 'test_cmd'

        valid, error = token_service.validate_token(
            token=token,
            user_id=1,
            command_name='test_cmd',
            params={'symbol': '000001'},
            risk_level='write_high',
            mode='confirm_each',
        )
        assert valid is True
        assert error == ''

    def test_reuse_rejected(self, token_service):
        token, _ = token_service.create_token(1, 'cmd', {}, 'read', 'confirm_each')

        # First use succeeds
        valid, _ = token_service.validate_token(token, 1, 'cmd', {}, 'read', 'confirm_each')
        assert valid is True

        # Second use fails
        valid, error = token_service.validate_token(token, 1, 'cmd', {}, 'read', 'confirm_each')
        assert valid is False
        assert 'already used' in error

    def test_wrong_user_rejected(self, token_service):
        token, _ = token_service.create_token(1, 'cmd', {}, 'read', 'confirm_each')
        valid, error = token_service.validate_token(token, 999, 'cmd', {}, 'read', 'confirm_each')
        assert valid is False
        assert 'user mismatch' in error.lower()

    def test_wrong_command_rejected(self, token_service):
        token, _ = token_service.create_token(1, 'cmd_a', {}, 'read', 'confirm_each')
        valid, error = token_service.validate_token(token, 1, 'cmd_b', {}, 'read', 'confirm_each')
        assert valid is False
        assert 'command mismatch' in error.lower()

    def test_wrong_params_rejected(self, token_service):
        token, _ = token_service.create_token(1, 'cmd', {'a': 1}, 'read', 'confirm_each')
        valid, error = token_service.validate_token(token, 1, 'cmd', {'a': 2}, 'read', 'confirm_each')
        assert valid is False
        assert 'params mismatch' in error.lower()

    def test_expired_rejected(self, token_service):
        token, _ = token_service.create_token(1, 'cmd', {}, 'read', 'confirm_each')

        # Manually unsign with expired max_age
        with patch.object(
            token_service._signer, 'unsign',
            side_effect=__import__('django.core.signing', fromlist=['SignatureExpired']).SignatureExpired('expired'),
        ):
            valid, error = token_service.validate_token(token, 1, 'cmd', {}, 'read', 'confirm_each')
            assert valid is False
            assert 'expired' in error.lower()


# ========== Application: ExecuteCommandUseCase governance ==========

@pytest.mark.django_db
class TestExecuteCommandGovernance:
    """ExecuteCommandUseCase governance flow tests."""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def mock_execution_service(self):
        svc = MagicMock()
        svc.execute_api_command.return_value = {'output': 'ok', 'metadata': {}}
        svc.execute_prompt_command.return_value = {'output': 'ok', 'metadata': {}}
        return svc

    @pytest.fixture
    def mock_audit_repo(self):
        return MagicMock()

    def _make_cmd(self, risk_level=TerminalRiskLevel.READ, requires_mcp=True, enabled=True):
        return TerminalCommand(
            id='1',
            name='test_cmd',
            description='test',
            command_type=CommandType.API,
            risk_level=risk_level,
            requires_mcp=requires_mcp,
            enabled_in_terminal=enabled,
        )

    def test_mcp_blocked(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(requires_mcp=True)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=False,
            terminal_mode='confirm_each',
        )
        resp = use_case.execute(req)
        assert resp.success is False
        assert 'MCP' in resp.error

    def test_role_blocked(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.ADMIN)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_analyst',
            user_role='analyst',
            mcp_enabled=True,
            terminal_mode='confirm_each',
        )
        resp = use_case.execute(req)
        assert resp.success is False
        assert 'role' in resp.error.lower()

    def test_readonly_blocks_writes(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.WRITE_LOW)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=True,
            terminal_mode='readonly',
        )
        resp = use_case.execute(req)
        assert resp.success is False
        assert 'read-only' in resp.error.lower()

    def test_confirm_each_returns_token_for_write(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.WRITE_HIGH)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=True,
            terminal_mode='confirm_each',
        )
        resp = use_case.execute(req)
        assert resp.success is False
        assert resp.confirmation_required is True
        assert resp.confirmation_token is not None

    def test_auto_confirm_executes_directly(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.WRITE_LOW)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=True,
            terminal_mode='auto_confirm',
        )
        resp = use_case.execute(req)
        assert resp.success is True

    def test_read_command_always_succeeds(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.READ)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_readonly',
            user_role='read_only',
            mcp_enabled=True,
            terminal_mode='confirm_each',
        )
        resp = use_case.execute(req)
        assert resp.success is True

    def test_disabled_command_blocked(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(enabled=False)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=True,
            terminal_mode='auto_confirm',
        )
        resp = use_case.execute(req)
        assert resp.success is False
        assert 'not available' in resp.error.lower()

    def test_audit_logged_on_success(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.READ)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            username='test_admin',
            user_role='admin',
            mcp_enabled=True,
            terminal_mode='auto_confirm',
        )
        use_case.execute(req)
        mock_audit_repo.save.assert_called_once()
        entry = mock_audit_repo.save.call_args[0][0]
        assert entry.result_status == 'success'

    def test_audit_logged_on_block(self, mock_repo, mock_execution_service, mock_audit_repo):
        from apps.terminal.application.use_cases import ExecuteCommandUseCase, ExecuteCommandRequest

        cmd = self._make_cmd(risk_level=TerminalRiskLevel.ADMIN)
        mock_repo.get_by_name.return_value = cmd

        use_case = ExecuteCommandUseCase(mock_repo, mock_execution_service, mock_audit_repo)
        req = ExecuteCommandRequest(
            command_name='test_cmd',
            user_id=1,
            user_role='analyst',
            mcp_enabled=True,
            terminal_mode='auto_confirm',
        )
        use_case.execute(req)
        mock_audit_repo.save.assert_called_once()
        entry = mock_audit_repo.save.call_args[0][0]
        assert entry.result_status == 'blocked'
