"""
Terminal Interface API Views.

RESTful API视图定义。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
import logging

from ..infrastructure.models import TerminalCommandORM
from ..infrastructure.repositories import get_terminal_command_repository
from ..application.use_cases import (
    ExecuteCommandUseCase,
    ExecuteCommandRequest,
    ListCommandsUseCase,
    CreateCommandUseCase,
    CreateCommandRequest,
    UpdateCommandUseCase,
    UpdateCommandRequest,
    DeleteCommandUseCase,
)
from ..application.services import CommandExecutionService
from .serializers import (
    TerminalCommandSerializer,
    TerminalCommandCreateSerializer,
    TerminalCommandUpdateSerializer,
    ExecuteCommandSerializer,
    ExecuteCommandResponseSerializer,
    AvailableCommandSerializer,
)


logger = logging.getLogger(__name__)


class TerminalCommandViewSet(viewsets.ModelViewSet):
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
    
    queryset = TerminalCommandORM._default_manager.all()
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TerminalCommandCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TerminalCommandUpdateSerializer
        return TerminalCommandSerializer
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """
        执行指定命令
        
        POST /api/terminal/commands/{id}/execute/
        {
            "params": {"key": "value"},
            "session_id": "xxx",
            "provider_name": "openai",
            "model_name": "gpt-4"
        }
        """
        command = self.get_object()
        
        serializer = ExecuteCommandSerializer(data={
            'name': command.name,
            **request.data
        })
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        # 构建用例
        repository = get_terminal_command_repository()
        execution_service = CommandExecutionService()
        use_case = ExecuteCommandUseCase(repository, execution_service)
        
        # 执行
        request_obj = ExecuteCommandRequest(
            command_name=data['name'],
            params=data.get('params', {}),
            session_id=data.get('session_id'),
            provider_name=data.get('provider_name'),
            model_name=data.get('model_name'),
        )
        response_obj = use_case.execute(request_obj)
        
        # 序列化响应
        response_serializer = ExecuteCommandResponseSerializer({
            'success': response_obj.success,
            'output': response_obj.output,
            'metadata': response_obj.metadata,
            'error': response_obj.error,
            'command': response_obj.command.to_dict() if response_obj.command else None,
        })
        
        return Response(response_serializer.data)
    
    @action(detail=False, methods=['post'])
    def execute_by_name(self, request):
        """
        按名称执行命令
        
        POST /api/terminal/commands/execute_by_name/
        {
            "name": "analyze",
            "params": {"symbol": "AAPL"},
            "session_id": "xxx"
        }
        """
        serializer = ExecuteCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        # 构建用例
        repository = get_terminal_command_repository()
        execution_service = CommandExecutionService()
        use_case = ExecuteCommandUseCase(repository, execution_service)
        
        # 执行
        request_obj = ExecuteCommandRequest(
            command_name=data['name'],
            params=data.get('params', {}),
            session_id=data.get('session_id'),
            provider_name=data.get('provider_name'),
            model_name=data.get('model_name'),
        )
        response_obj = use_case.execute(request_obj)
        
        # 序列化响应
        response_serializer = ExecuteCommandResponseSerializer({
            'success': response_obj.success,
            'output': response_obj.output,
            'metadata': response_obj.metadata,
            'error': response_obj.error,
            'command': response_obj.command.to_dict() if response_obj.command else None,
        })
        
        return Response(response_serializer.data)
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        """
        获取可用命令列表（简化版）
        
        GET /api/terminal/commands/available/
        """
        repository = get_terminal_command_repository()
        commands = repository.get_all_active()
        
        data = [{
            'name': cmd.name,
            'description': cmd.description,
            'type': cmd.command_type.value,
            'category': cmd.category,
            'parameters': [p.to_dict() for p in cmd.parameters],
            'is_active': cmd.is_active,
        } for cmd in commands]
        
        serializer = AvailableCommandSerializer(data, many=True)
        return Response({
            'success': True,
            'count': len(data),
            'commands': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """
        按分类获取命令
        
        GET /api/terminal/commands/by_category/
        """
        repository = get_terminal_command_repository()
        
        # 获取所有命令并按分类分组
        commands = repository.get_all_active()
        
        categories = {}
        for cmd in commands:
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
            'categories': categories
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
