"""
Terminal Interface API Views.

RESTful API视图定义。
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.rbac import get_user_role
from apps.ai_capability.application.facade import CapabilityRoutingFacade

from ..application.repository_provider import (
    get_terminal_audit_repository,
    get_terminal_command_repository,
)
from ..application.services import AnswerChainSettingsService, CommandExecutionService
from ..application.use_cases import (
    CreateCommandRequest,
    CreateCommandUseCase,
    DeleteCommandUseCase,
    ExecuteCommandRequest,
    ExecuteCommandUseCase,
    ListCommandsUseCase,
    UpdateCommandRequest,
    UpdateCommandUseCase,
)
from ..domain.entities import TerminalMode, TerminalRiskLevel
from ..domain.services import TerminalPermissionService
from .permissions import IsStaffOrAdmin
from .serializers import (
    AvailableCommandSerializer,
    ConfirmExecuteSerializer,
    ExecuteCommandResponseSerializer,
    ExecuteCommandSerializer,
    TerminalAuditEntrySerializer,
    TerminalCapabilitiesSerializer,
    TerminalChatRequestSerializer,
    TerminalChatResponseSerializer,
    TerminalCommandCreateSerializer,
    TerminalCommandSerializer,
    TerminalCommandUpdateSerializer,
)

logger = logging.getLogger(__name__)


def _get_mcp_enabled(user) -> bool:
    """获取用户 MCP 启用状态"""
    profile = getattr(user, 'account_profile', None)
    return getattr(profile, 'mcp_enabled', False) if profile else False


def _get_answer_chain_config(user) -> dict:
    return AnswerChainSettingsService.get_config(user)


def _normalize_prompt_template_id(value):
    if value in (None, ''):
        return None
    return str(value)


def _command_to_payload(command) -> dict:
    """Serialize a terminal command entity into API response payload."""

    payload = command.to_dict()
    prompt_template = payload.pop('prompt_template_id', None)
    payload['command_type'] = payload['type']
    payload['prompt_template'] = int(prompt_template) if str(prompt_template).isdigit() else prompt_template
    payload['param_count'] = len(payload.get('parameters') or [])
    payload['created_at'] = command.created_at
    payload['updated_at'] = command.updated_at
    return payload


class TerminalCommandViewSet(viewsets.ViewSet):
    """
    终端命令管理 API

    list: 获取所有命令
    retrieve: 获取单个命令详情
    create: 创建新命令
    update: 更新命令
    destroy: 删除命令
    execute: 执行命令
    available: 获取可用命令列表（简化版）
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        """list/retrieve/CRUD 需要 staff 权限，execute/available/capabilities 仅需认证"""
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'list', 'retrieve'):
            return [IsStaffOrAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return TerminalCommandCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TerminalCommandUpdateSerializer
        return TerminalCommandSerializer

    def _get_command(self, command_id: str):
        repository = get_terminal_command_repository()
        command = repository.get_by_id(command_id)
        if not command:
            raise NotFound(detail=f"Command with id '{command_id}' not found")
        return command

    def _build_command_payload(self, command):
        serializer = TerminalCommandSerializer(_command_to_payload(command))
        return serializer.data

    def _build_execute_request(self, data, request) -> ExecuteCommandRequest:
        """构建执行请求 DTO"""
        user_role = get_user_role(request.user)
        mcp_enabled = _get_mcp_enabled(request.user)
        return ExecuteCommandRequest(
            command_name=data['name'],
            params=data.get('params', {}),
            session_id=data.get('session_id'),
            provider_name=data.get('provider_name'),
            model_name=data.get('model_name'),
            user_id=request.user.id,
            username=request.user.username,
            user_role=user_role,
            mcp_enabled=mcp_enabled,
            terminal_mode=data.get('mode', 'confirm_each'),
            confirmation_token=data.get('confirmation_token') or None,
        )

    def _serialize_response(self, response_obj) -> Response:
        """序列化执行响应"""
        response_data = {
            'success': response_obj.success,
            'output': response_obj.output,
            'metadata': response_obj.metadata,
            'error': response_obj.error,
            'command': response_obj.command.to_dict() if response_obj.command else None,
            'confirmation_required': response_obj.confirmation_required,
            'confirmation_token': response_obj.confirmation_token,
            'confirmation_prompt': response_obj.confirmation_prompt,
            'command_summary': response_obj.command_summary,
            'risk_level': response_obj.risk_level,
        }
        response_serializer = ExecuteCommandResponseSerializer(response_data)
        return Response(response_serializer.data)

    def list(self, request):
        """获取所有命令（包含非激活命令）。"""

        repository = get_terminal_command_repository()
        commands = ListCommandsUseCase(repository).execute(include_inactive=True)
        serializer = TerminalCommandSerializer(
            [_command_to_payload(command) for command in commands],
            many=True,
        )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """获取单个命令详情。"""

        command = self._get_command(pk)
        return Response(self._build_command_payload(command))

    def create(self, request):
        """创建新命令。"""

        serializer = TerminalCommandCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = CreateCommandUseCase(get_terminal_command_repository())
        request_obj = CreateCommandRequest(
            name=data['name'],
            description=data.get('description', ''),
            command_type=data['command_type'],
            prompt_template_id=_normalize_prompt_template_id(data.get('prompt_template')),
            system_prompt=data.get('system_prompt') or None,
            user_prompt_template=data.get('user_prompt_template', ''),
            api_endpoint=data.get('api_endpoint') or None,
            api_method=data.get('api_method', 'GET'),
            response_jq_filter=data.get('response_jq_filter') or None,
            parameters=data.get('parameters', []),
            timeout=data.get('timeout', 60),
            provider_name=data.get('provider_name') or None,
            model_name=data.get('model_name') or None,
            risk_level=data.get('risk_level', TerminalRiskLevel.READ.value),
            requires_mcp=data.get('requires_mcp', True),
            enabled_in_terminal=data.get('enabled_in_terminal', True),
            category=data.get('category', 'general'),
            tags=data.get('tags', []),
            is_active=data.get('is_active', True),
        )

        try:
            result = use_case.execute(request_obj)
        except DjangoValidationError as exc:
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)

        if not result.success:
            return Response({'error': result.error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            self._build_command_payload(result.command),
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
        """全量更新命令。"""

        return self._update_command(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        """部分更新命令。"""

        return self._update_command(request, pk, partial=True)

    def _update_command(self, request, pk=None, *, partial: bool):
        self._get_command(pk)

        serializer = TerminalCommandUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        use_case = UpdateCommandUseCase(get_terminal_command_repository())
        request_obj = UpdateCommandRequest(
            command_id=str(pk),
            name=data.get('name'),
            description=data.get('description'),
            command_type=data.get('command_type'),
            prompt_template_id=_normalize_prompt_template_id(data.get('prompt_template'))
            if 'prompt_template' in data else None,
            system_prompt=(data.get('system_prompt') or None) if 'system_prompt' in data else None,
            user_prompt_template=data.get('user_prompt_template'),
            api_endpoint=(data.get('api_endpoint') or None) if 'api_endpoint' in data else None,
            api_method=data.get('api_method'),
            response_jq_filter=(data.get('response_jq_filter') or None)
            if 'response_jq_filter' in data else None,
            parameters=data.get('parameters'),
            timeout=data.get('timeout'),
            provider_name=(data.get('provider_name') or None) if 'provider_name' in data else None,
            model_name=(data.get('model_name') or None) if 'model_name' in data else None,
            risk_level=data.get('risk_level'),
            requires_mcp=data.get('requires_mcp'),
            enabled_in_terminal=data.get('enabled_in_terminal'),
            category=data.get('category'),
            tags=data.get('tags'),
            is_active=data.get('is_active'),
        )

        try:
            result = use_case.execute(request_obj)
        except DjangoValidationError as exc:
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)

        if not result.success:
            status_code = status.HTTP_404_NOT_FOUND if 'not found' in (result.error or '').lower() else status.HTTP_400_BAD_REQUEST
            return Response({'error': result.error}, status=status_code)
        return Response(self._build_command_payload(result.command))

    def destroy(self, request, pk=None):
        """删除命令。"""

        self._get_command(pk)
        DeleteCommandUseCase(get_terminal_command_repository()).execute(str(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """
        执行指定命令

        POST /api/terminal/commands/{id}/execute/
        """
        command = self._get_command(pk)

        serializer = ExecuteCommandSerializer(data={
            'name': command.name,
            **request.data
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        repository = get_terminal_command_repository()
        audit_repository = get_terminal_audit_repository()
        execution_service = CommandExecutionService()
        use_case = ExecuteCommandUseCase(repository, execution_service, audit_repository)

        request_obj = self._build_execute_request(data, request)
        response_obj = use_case.execute(request_obj)
        return self._serialize_response(response_obj)

    @action(detail=False, methods=['post'])
    def execute_by_name(self, request):
        """
        按名称执行命令

        POST /api/terminal/commands/execute_by_name/
        """
        serializer = ExecuteCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        repository = get_terminal_command_repository()
        audit_repository = get_terminal_audit_repository()
        execution_service = CommandExecutionService()
        use_case = ExecuteCommandUseCase(repository, execution_service, audit_repository)

        request_obj = self._build_execute_request(data, request)
        response_obj = use_case.execute(request_obj)
        return self._serialize_response(response_obj)

    @action(detail=False, methods=['post'])
    def confirm_execute(self, request):
        """
        确认并执行命令

        POST /api/terminal/commands/confirm_execute/
        """
        serializer = ConfirmExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        repository = get_terminal_command_repository()
        audit_repository = get_terminal_audit_repository()
        execution_service = CommandExecutionService()
        use_case = ExecuteCommandUseCase(repository, execution_service, audit_repository)

        request_obj = self._build_execute_request(
            {
                'name': data['name'],
                'params': data.get('params', {}),
                'session_id': data.get('session_id'),
                'mode': data.get('mode', 'confirm_each'),
                'confirmation_token': data['confirmation_token'],
            },
            request,
        )
        response_obj = use_case.execute(request_obj)
        return self._serialize_response(response_obj)

    @action(detail=False, methods=['get'])
    def available(self, request):
        """
        获取可用命令列表（根据角色和 MCP 状态过滤）

        GET /api/terminal/commands/available/
        """
        repository = get_terminal_command_repository()
        commands = repository.get_all_active()

        user_role = get_user_role(request.user)
        mcp_enabled = _get_mcp_enabled(request.user)

        permission_service = TerminalPermissionService()
        filtered = permission_service.filter_commands_for_role(
            commands, user_role, mcp_enabled,
        )

        data = [{
            'name': cmd.name,
            'description': cmd.description,
            'type': cmd.command_type.value,
            'category': cmd.category,
            'parameters': [p.to_dict() for p in cmd.parameters],
            'is_active': cmd.is_active,
            'risk_level': cmd.risk_level.value,
            'requires_mcp': cmd.requires_mcp,
            'confirmation_required': cmd.risk_level != TerminalRiskLevel.READ,
            'terminal_enabled': cmd.enabled_in_terminal,
        } for cmd in filtered]

        serializer = AvailableCommandSerializer(data, many=True)
        return Response({
            'success': True,
            'count': len(data),
            'commands': serializer.data,
        })

    @action(detail=False, methods=['get'])
    def capabilities(self, request):
        """
        获取终端能力信息

        GET /api/terminal/commands/capabilities/
        """
        user_role = get_user_role(request.user)
        mcp_enabled = _get_mcp_enabled(request.user)

        permission_service = TerminalPermissionService()
        available_modes = permission_service.get_available_modes(user_role, mcp_enabled)
        max_risk = permission_service.get_max_risk_level(user_role)
        answer_chain_config = _get_answer_chain_config(request.user)

        reason = None
        if not mcp_enabled:
            reason = "MCP access disabled for your account"

        data = {
            'mcp_enabled': mcp_enabled,
            'role': user_role,
            'available_modes': available_modes,
            'current_mode': available_modes[0] if len(available_modes) == 1 else 'confirm_each',
            'max_risk_level': max_risk.value,
            'reason_if_locked': reason,
            'answer_chain_enabled': answer_chain_config['enabled'],
            'answer_chain_visibility': answer_chain_config['visibility'],
        }

        serializer = TerminalCapabilitiesSerializer(data)
        return Response({'success': True, **serializer.data})

    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """
        按分类获取命令（根据角色和 MCP 状态过滤）

        GET /api/terminal/commands/by_category/
        """
        repository = get_terminal_command_repository()
        commands = repository.get_all_active()

        user_role = get_user_role(request.user)
        mcp_enabled = _get_mcp_enabled(request.user)

        permission_service = TerminalPermissionService()
        filtered = permission_service.filter_commands_for_role(
            commands, user_role, mcp_enabled,
        )

        categories = {}
        for cmd in filtered:
            if cmd.category not in categories:
                categories[cmd.category] = []
            categories[cmd.category].append({
                'name': cmd.name,
                'description': cmd.description,
                'type': cmd.command_type.value,
                'parameters': [p.to_dict() for p in cmd.parameters],
            })

        return Response({
            'success': True,
            'categories': categories,
        })


class TerminalSessionView(APIView):
    """终端会话管理"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        创建新会话

        POST /api/terminal/session/
        """
        import uuid
        session_id = str(uuid.uuid4())[:8]

        return Response({
            'success': True,
            'session_id': session_id,
            'username': request.user.username,
        })


class TerminalChatView(APIView):
    """Terminal 自然语言聊天入口，先做意图路由，再决定是否走系统查询。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TerminalChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        provider_ref = data.get('provider_ref', data.get('provider_name'))
        router = CapabilityRoutingFacade()
        user_role = get_user_role(request.user)
        mcp_enabled = _get_mcp_enabled(request.user)

        try:
            answer_chain_config = _get_answer_chain_config(request.user)
            routed = router.route(
                message=data['message'],
                entrypoint='terminal',
                session_id=data.get('session_id'),
                user_id=request.user.id,
                user_is_admin=answer_chain_config['is_admin'],
                mcp_enabled=mcp_enabled,
                provider_name=provider_ref,
                model=data.get('model'),
                context={
                    **(data.get('context', {}) or {}),
                    'username': request.user.username,
                    'user_role': user_role,
                    'terminal_mode': 'confirm_each',
                },
                answer_chain_enabled=answer_chain_config['enabled'],
            )
            response_data = {
                'reply': routed.get('reply', ''),
                'session_id': routed.get('session_id', ''),
                'metadata': {
                    **(routed.get('metadata', {}) or {}),
                    'decision': routed.get('decision'),
                    'selected_capability_key': routed.get('selected_capability_key'),
                },
                'route_confirmation_required': routed.get('requires_confirmation', False),
                'selected_capability_key': routed.get('selected_capability_key'),
                'suggested_command': routed.get('suggested_command'),
                'suggested_intent': routed.get('suggested_intent'),
                'suggestion_prompt': routed.get('suggestion_prompt'),
                'missing_params': routed.get('missing_params') or [],
            }
            if answer_chain_config['enabled'] and routed.get('answer_chain'):
                response_data['metadata']['answer_chain'] = routed['answer_chain']
        except Exception as e:
            logger.error("Terminal chat routing failed: %s", e)
            return Response(
                {'error': f'AI 调用异常: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_serializer = TerminalChatResponseSerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class TerminalAuditView(APIView):
    """终端审计日志 API（仅 staff）"""

    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        """
        获取终端审计日志

        GET /api/terminal/audit/?username=&command=&status=&limit=50
        """
        repository = get_terminal_audit_repository()
        username = request.query_params.get('username')
        command_name = request.query_params.get('command')
        result_status = request.query_params.get('status')
        limit = min(int(request.query_params.get('limit', 50)), 200)

        entries = repository.get_recent(
            limit=limit,
            username=username,
            command_name=command_name,
            result_status=result_status,
        )

        serializer = TerminalAuditEntrySerializer(
            [e.__dict__ for e in entries],
            many=True,
        )
        return Response({
            'success': True,
            'count': len(entries),
            'entries': serializer.data,
        })
