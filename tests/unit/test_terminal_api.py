"""
Terminal API Tests.

Tests for terminal governance API endpoints, permissions, and contracts.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.terminal.infrastructure.models import TerminalAuditLogORM, TerminalCommandORM


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        username='staff_test', password='test123', is_staff=True,
    )
    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.create_user(
        username='regular_test', password='test123', is_staff=False,
    )
    return user


@pytest.fixture
def sample_command(db):
    return TerminalCommandORM.objects.create(
        name='test_read_cmd',
        description='A read-only test command',
        command_type='api',
        api_endpoint='/api/test/',
        risk_level='read',
        requires_mcp=True,
        enabled_in_terminal=True,
        is_active=True,
    )


@pytest.fixture
def write_command(db):
    return TerminalCommandORM.objects.create(
        name='test_write_cmd',
        description='A write test command',
        command_type='api',
        api_endpoint='/api/test/write/',
        risk_level='write_high',
        requires_mcp=True,
        enabled_in_terminal=True,
        is_active=True,
    )


# ========== CRUD Permission Tests ==========

@pytest.mark.django_db
class TestCRUDPermissions:
    """Non-staff cannot create/update/delete commands; staff can."""

    def test_non_staff_cannot_create(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)
        resp = api_client.post('/api/terminal/commands/', {
            'name': 'new_cmd',
            'description': 'test',
            'command_type': 'api',
            'api_endpoint': '/test/',
        }, format='json')
        assert resp.status_code == 403

    def test_staff_can_create(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/commands/', {
            'name': 'new_cmd',
            'description': 'test',
            'command_type': 'api',
            'api_endpoint': '/test/',
        }, format='json')
        assert resp.status_code == 201

    def test_non_staff_cannot_delete(self, api_client, regular_user, sample_command):
        api_client.force_authenticate(user=regular_user)
        resp = api_client.delete(f'/api/terminal/commands/{sample_command.pk}/')
        assert resp.status_code == 403

    def test_staff_can_delete(self, api_client, staff_user, sample_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.delete(f'/api/terminal/commands/{sample_command.pk}/')
        assert resp.status_code == 204

    def test_non_staff_cannot_update(self, api_client, regular_user, sample_command):
        api_client.force_authenticate(user=regular_user)
        resp = api_client.patch(
            f'/api/terminal/commands/{sample_command.pk}/',
            {'description': 'updated'},
            format='json',
        )
        assert resp.status_code == 403

    def test_staff_can_update(self, api_client, staff_user, sample_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.patch(
            f'/api/terminal/commands/{sample_command.pk}/',
            {'description': 'updated'},
            format='json',
        )
        assert resp.status_code == 200

    def test_non_staff_cannot_list(self, api_client, regular_user, sample_command):
        """Non-staff users cannot list full command definitions."""
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get('/api/terminal/commands/')
        assert resp.status_code == 403

    def test_non_staff_cannot_retrieve(self, api_client, regular_user, sample_command):
        """Non-staff users cannot retrieve individual command details."""
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get(f'/api/terminal/commands/{sample_command.pk}/')
        assert resp.status_code == 403

    def test_staff_can_list(self, api_client, staff_user, sample_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/')
        assert resp.status_code == 200

    def test_staff_can_retrieve(self, api_client, staff_user, sample_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get(f'/api/terminal/commands/{sample_command.pk}/')
        assert resp.status_code == 200


# ========== Available Endpoint Tests ==========

@pytest.mark.django_db
class TestAvailableEndpoint:
    """Tests for /api/terminal/commands/available/"""

    def test_returns_risk_level(self, api_client, staff_user, sample_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/available/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        cmds = data['commands']
        if cmds:
            assert 'risk_level' in cmds[0]

    def test_unauthenticated_denied(self, api_client):
        resp = api_client.get('/api/terminal/commands/available/')
        assert resp.status_code in (401, 403)

    def test_filters_by_role(self, api_client, regular_user, db):
        # Create an admin-only command
        TerminalCommandORM.objects.create(
            name='admin_only_cmd',
            description='admin only',
            command_type='api',
            api_endpoint='/test/',
            risk_level='admin',
            requires_mcp=True,
            enabled_in_terminal=True,
            is_active=True,
        )
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get('/api/terminal/commands/available/')
        data = resp.json()
        cmd_names = [c['name'] for c in data['commands']]
        assert 'admin_only_cmd' not in cmd_names


# ========== Capabilities Endpoint Tests ==========

@pytest.mark.django_db
class TestCapabilitiesEndpoint:
    """Tests for /api/terminal/commands/capabilities/"""

    def test_returns_role_and_modes(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/capabilities/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert 'role' in data
        assert 'available_modes' in data
        assert 'mcp_enabled' in data
        assert 'max_risk_level' in data


# ========== Execute Endpoint Tests ==========

@pytest.mark.django_db
class TestExecuteEndpoint:
    """Tests for /api/terminal/commands/execute_by_name/"""

    @patch('apps.terminal.application.services.CommandExecutionService.execute_api_command')
    def test_read_command_succeeds(self, mock_exec, api_client, staff_user, sample_command):
        mock_exec.return_value = {'output': 'test output', 'metadata': {}}
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'test_read_cmd',
            'params': {},
            'mode': 'auto_confirm',
        }, format='json')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True

    def test_write_returns_confirmation(self, api_client, staff_user, write_command):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'test_write_cmd',
            'params': {},
            'mode': 'confirm_each',
        }, format='json')
        assert resp.status_code == 200
        data = resp.json()
        assert data['confirmation_required'] is True
        assert data['confirmation_token'] is not None

    @patch('apps.terminal.application.services.CommandExecutionService.execute_api_command')
    def test_confirm_execute_with_valid_token(self, mock_exec, api_client, staff_user, write_command):
        mock_exec.return_value = {'output': 'done', 'metadata': {}}
        api_client.force_authenticate(user=staff_user)

        # Step 1: Get confirmation token
        resp1 = api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'test_write_cmd',
            'params': {},
            'mode': 'confirm_each',
        }, format='json')
        token = resp1.json()['confirmation_token']

        # Step 2: Confirm
        resp2 = api_client.post('/api/terminal/commands/confirm_execute/', {
            'name': 'test_write_cmd',
            'params': {},
            'confirmation_token': token,
            'mode': 'confirm_each',
        }, format='json')
        assert resp2.status_code == 200
        data = resp2.json()
        assert data['success'] is True


# ========== Audit Tests ==========

@pytest.mark.django_db
class TestAuditEndpoint:
    """Tests for audit logging and /api/terminal/audit/"""

    @patch('apps.terminal.application.services.CommandExecutionService.execute_api_command')
    def test_audit_entry_created_on_execute(self, mock_exec, api_client, staff_user, sample_command):
        mock_exec.return_value = {'output': 'ok', 'metadata': {}}
        api_client.force_authenticate(user=staff_user)

        api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'test_read_cmd',
            'params': {},
            'mode': 'auto_confirm',
        }, format='json')

        assert TerminalAuditLogORM.objects.count() >= 1

    def test_audit_endpoint_staff_only(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get('/api/terminal/audit/')
        assert resp.status_code == 403

    def test_audit_endpoint_accessible_by_staff(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/audit/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert 'entries' in data

    @patch('apps.terminal.application.services.CommandExecutionService.execute_api_command')
    def test_audit_records_actual_username_not_id(self, mock_exec, api_client, staff_user, sample_command):
        """Audit entry must contain the actual username, not str(user_id)."""
        mock_exec.return_value = {'output': 'ok', 'metadata': {}}
        api_client.force_authenticate(user=staff_user)

        api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'test_read_cmd',
            'params': {},
            'mode': 'auto_confirm',
        }, format='json')

        log = TerminalAuditLogORM.objects.latest('created_at')
        assert log.username == staff_user.username
        assert log.username != str(staff_user.id)


# ========== Route Contract Tests ==========

@pytest.mark.django_db
class TestRouteContracts:
    """Verify all new endpoints exist and return correct status codes."""

    def test_commands_list(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/')
        assert resp.status_code == 200

    def test_available(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/available/')
        assert resp.status_code == 200

    def test_capabilities(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/commands/capabilities/')
        assert resp.status_code == 200

    def test_execute_by_name(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/commands/execute_by_name/', {
            'name': 'nonexistent',
        }, format='json')
        assert resp.status_code == 200  # returns success=false with error

    def test_confirm_execute(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/commands/confirm_execute/', {
            'name': 'nonexistent',
            'confirmation_token': 'invalid',
        }, format='json')
        assert resp.status_code == 200

    def test_audit(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.get('/api/terminal/audit/')
        assert resp.status_code == 200

    def test_session(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post('/api/terminal/session/')
        assert resp.status_code == 200


# ========== Model Tests ==========

@pytest.mark.django_db
class TestOrmModels:
    """Test ORM model governance fields and audit model."""

    def test_command_default_governance_fields(self):
        cmd = TerminalCommandORM.objects.create(
            name='test_defaults',
            command_type='api',
            api_endpoint='/test/',
        )
        assert cmd.risk_level == 'read'
        assert cmd.requires_mcp is True
        assert cmd.enabled_in_terminal is True

    def test_command_to_entity_maps_governance(self):
        cmd = TerminalCommandORM.objects.create(
            name='test_entity',
            command_type='api',
            api_endpoint='/test/',
            risk_level='write_high',
            requires_mcp=False,
            enabled_in_terminal=False,
        )
        entity = cmd.to_entity()
        from apps.terminal.domain.entities import TerminalRiskLevel
        assert entity.risk_level == TerminalRiskLevel.WRITE_HIGH
        assert entity.requires_mcp is False
        assert entity.enabled_in_terminal is False

    def test_audit_log_creation(self):
        log = TerminalAuditLogORM.objects.create(
            username='test_user',
            session_id='abc123',
            command_name='test_cmd',
            risk_level='read',
            mode='confirm_each',
            result_status='success',
        )
        assert log.pk is not None
        entity = log.to_entity()
        assert entity.username == 'test_user'
        assert entity.result_status == 'success'


# ========== Config Page Permission Tests ==========

@pytest.mark.django_db
class TestConfigPagePermissions:
    """Config page must require staff/admin, not just login."""

    def test_config_page_denied_for_non_staff(self, client, regular_user):
        client.force_login(regular_user)
        resp = client.get('/terminal/config/')
        assert resp.status_code == 403

    def test_config_page_allowed_for_staff(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.get('/terminal/config/')
        assert resp.status_code == 200

    def test_config_page_denied_for_anonymous(self, client):
        resp = client.get('/terminal/config/')
        # Should redirect to login
        assert resp.status_code == 302


# ========== by_category Filtering Tests ==========

@pytest.mark.django_db
class TestByCategoryFiltering:
    """by_category must filter by role/MCP like available endpoint."""

    def test_by_category_hides_admin_commands_from_regular(self, api_client, regular_user, db):
        TerminalCommandORM.objects.create(
            name='admin_only_bc',
            description='admin only',
            command_type='api',
            api_endpoint='/test/',
            risk_level='admin',
            requires_mcp=True,
            enabled_in_terminal=True,
            is_active=True,
            category='admin_cat',
        )
        api_client.force_authenticate(user=regular_user)
        resp = api_client.get('/api/terminal/commands/by_category/')
        data = resp.json()
        all_cmd_names = []
        for cmds in data.get('categories', {}).values():
            all_cmd_names.extend(c['name'] for c in cmds)
        assert 'admin_only_bc' not in all_cmd_names
