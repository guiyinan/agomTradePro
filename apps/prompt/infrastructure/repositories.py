"""
Repositories for AI Prompt Management.

Infrastructure layer implementation using Django ORM.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..domain.entities import (
    ChainConfig,
    ChainExecutionMode,
    ChainStep,
    PlaceholderDef,
    PlaceholderType,
    PromptCategory,
    PromptTemplate,
)
from .models import ChainConfigORM, PromptExecutionLogORM, PromptTemplateORM


class PromptRepositoryError(Exception):
    """Prompt仓储异常"""
    pass


class ChainRepositoryError(Exception):
    """链配置仓储异常"""
    pass


class DjangoPromptRepository:
    """
    Django ORM实现的Prompt模板仓储

    提供Prompt模板的增删改查操作。
    """

    def __init__(self):
        self._model = PromptTemplateORM

    def get_template_by_id(self, template_id: int) -> PromptTemplate | None:
        """根据ID获取模板

        Args:
            template_id: 模板ID

        Returns:
            PromptTemplate实体，不存在返回None
        """
        try:
            orm_obj = self._model.objects.get(id=template_id, is_active=True)
            return self._orm_to_entity(orm_obj)
        except self._model.DoesNotExist:
            return None

    def get_template_by_name(self, name: str) -> PromptTemplate | None:
        """根据名称获取模板

        Args:
            name: 模板名称

        Returns:
            PromptTemplate实体，不存在返回None
        """
        try:
            orm_obj = self._model.objects.get(name=name, is_active=True)
            return self._orm_to_entity(orm_obj)
        except self._model.DoesNotExist:
            return None

    def list_templates(
        self,
        category: str | None = None,
        is_active: bool = True
    ) -> list[PromptTemplate]:
        """列出模板

        Args:
            category: 分类过滤
            is_active: 是否激活

        Returns:
            PromptTemplate实体列表
        """
        queryset = self._model.objects.filter(is_active=is_active)
        if category:
            queryset = queryset.filter(category=category)
        return [self._orm_to_entity(obj) for obj in queryset]

    def create_template(self, template: PromptTemplate) -> PromptTemplate:
        """创建模板

        Args:
            template: 模板实体

        Returns:
            创建后的模板实体
        """
        # 转换为ORM格式
        placeholders_data = [
            {
                "name": p.name,
                "type": p.type.value,
                "description": p.description,
                "default_value": p.default_value,
                "required": p.required,
                "function_name": p.function_name,
                "function_params": p.function_params,
            }
            for p in template.placeholders
        ]

        orm_obj = self._model.objects.create(
            name=template.name,
            category=template.category.value,
            version=template.version,
            template_content=template.template_content,
            system_prompt=template.system_prompt or "",
            placeholders=placeholders_data,
            temperature=template.temperature,
            max_tokens=template.max_tokens,
            description=template.description,
            is_active=template.is_active
        )

        return self._orm_to_entity(orm_obj)

    def update_template(
        self,
        template_id: int,
        template: PromptTemplate
    ) -> PromptTemplate | None:
        """更新模板

        Args:
            template_id: 模板ID
            template: 新的模板实体

        Returns:
            更新后的模板实体，不存在返回None
        """
        try:
            orm_obj = self._model.objects.get(id=template_id)
        except self._model.DoesNotExist:
            return None

        # 转换占位符
        placeholders_data = [
            {
                "name": p.name,
                "type": p.type.value,
                "description": p.description,
                "default_value": p.default_value,
                "required": p.required,
                "function_name": p.function_name,
                "function_params": p.function_params,
            }
            for p in template.placeholders
        ]

        orm_obj.name = template.name
        orm_obj.category = template.category.value
        orm_obj.version = template.version
        orm_obj.template_content = template.template_content
        orm_obj.system_prompt = template.system_prompt or ""
        orm_obj.placeholders = placeholders_data
        orm_obj.temperature = template.temperature
        orm_obj.max_tokens = template.max_tokens
        orm_obj.description = template.description
        orm_obj.is_active = template.is_active
        orm_obj.save()

        return self._orm_to_entity(orm_obj)

    def update_last_used(self, template_id: int):
        """更新最后使用时间

        Args:
            template_id: 模板ID
        """
        self._model.objects.filter(id=template_id).update(
            last_used_at=timezone.now()
        )

    @staticmethod
    def _orm_to_entity(orm: PromptTemplateORM) -> PromptTemplate:
        """ORM转实体

        Args:
            orm: ORM对象

        Returns:
            PromptTemplate实体
        """
        # 转换占位符
        placeholders = [
            PlaceholderDef(
                name=p["name"],
                type=PlaceholderType(p["type"]),
                description=p["description"],
                default_value=p.get("default_value"),
                required=p.get("required", True),
                function_name=p.get("function_name"),
                function_params=p.get("function_params"),
            )
            for p in orm.placeholders
        ]

        return PromptTemplate(
            id=str(orm.id),
            name=orm.name,
            category=PromptCategory(orm.category),
            version=orm.version,
            template_content=orm.template_content,
            placeholders=placeholders,
            system_prompt=orm.system_prompt or None,
            temperature=orm.temperature,
            max_tokens=orm.max_tokens,
            description=orm.description,
            is_active=orm.is_active,
            created_at=orm.created_at.date()
        )


class DjangoChainRepository:
    """
    Django ORM实现的链配置仓储

    提供链配置的增删改查操作。
    """

    def __init__(self):
        self._model = ChainConfigORM

    def get_chain_by_id(self, chain_id: int) -> ChainConfig | None:
        """根据ID获取链配置

        Args:
            chain_id: 链ID

        Returns:
            ChainConfig实体，不存在返回None
        """
        try:
            orm_obj = self._model.objects.get(id=chain_id, is_active=True)
            return self._orm_to_entity(orm_obj)
        except self._model.DoesNotExist:
            return None

    def get_chain_by_name(self, name: str) -> ChainConfig | None:
        """根据名称获取链配置

        Args:
            name: 链名称

        Returns:
            ChainConfig实体，不存在返回None
        """
        try:
            orm_obj = self._model.objects.get(name=name, is_active=True)
            return self._orm_to_entity(orm_obj)
        except self._model.DoesNotExist:
            return None

    def list_chains(
        self,
        category: str | None = None,
        is_active: bool = True
    ) -> list[ChainConfig]:
        """列出链配置

        Args:
            category: 分类过滤
            is_active: 是否激活

        Returns:
            ChainConfig实体列表
        """
        queryset = self._model.objects.filter(is_active=is_active)
        if category:
            queryset = queryset.filter(category=category)
        return [self._orm_to_entity(obj) for obj in queryset]

    def create_chain(self, chain: ChainConfig) -> ChainConfig:
        """创建链配置

        Args:
            chain: 链配置实体

        Returns:
            创建后的链配置实体
        """
        # 转换步骤数据
        steps_data = [
            {
                "step_id": s.step_id,
                "template_id": s.template_id,
                "step_name": s.step_name,
                "order": s.order,
                "input_mapping": s.input_mapping,
                "output_parser": s.output_parser,
                "parallel_group": s.parallel_group,
                "enable_tool_calling": s.enable_tool_calling,
                "available_tools": s.available_tools,
            }
            for s in chain.steps
        ]

        # 转换aggregate_step
        aggregate_data = None
        if chain.aggregate_step:
            aggregate_data = {
                "step_id": chain.aggregate_step.step_id,
                "template_id": chain.aggregate_step.template_id,
                "step_name": chain.aggregate_step.step_name,
                "order": chain.aggregate_step.order,
                "input_mapping": chain.aggregate_step.input_mapping,
                "output_parser": chain.aggregate_step.output_parser,
                "parallel_group": chain.aggregate_step.parallel_group,
                "enable_tool_calling": chain.aggregate_step.enable_tool_calling,
                "available_tools": chain.aggregate_step.available_tools,
            }

        orm_obj = self._model.objects.create(
            name=chain.name,
            category=chain.category.value,
            description=chain.description,
            steps=steps_data,
            execution_mode=chain.execution_mode.value,
            aggregate_step=aggregate_data,
            is_active=chain.is_active
        )

        return self._orm_to_entity(orm_obj)

    def update_chain(self, chain_id: int, chain: ChainConfig) -> ChainConfig | None:
        """更新链配置。"""
        try:
            orm_obj = self._model.objects.get(id=chain_id)
        except self._model.DoesNotExist:
            return None

        steps_data = [
            {
                "step_id": s.step_id,
                "template_id": s.template_id,
                "step_name": s.step_name,
                "order": s.order,
                "input_mapping": s.input_mapping,
                "output_parser": s.output_parser,
                "parallel_group": s.parallel_group,
                "enable_tool_calling": s.enable_tool_calling,
                "available_tools": s.available_tools,
            }
            for s in chain.steps
        ]

        aggregate_data = None
        if chain.aggregate_step:
            aggregate_data = {
                "step_id": chain.aggregate_step.step_id,
                "template_id": chain.aggregate_step.template_id,
                "step_name": chain.aggregate_step.step_name,
                "order": chain.aggregate_step.order,
                "input_mapping": chain.aggregate_step.input_mapping,
                "output_parser": chain.aggregate_step.output_parser,
                "parallel_group": chain.aggregate_step.parallel_group,
                "enable_tool_calling": chain.aggregate_step.enable_tool_calling,
                "available_tools": chain.aggregate_step.available_tools,
            }

        orm_obj.name = chain.name
        orm_obj.category = chain.category.value
        orm_obj.description = chain.description
        orm_obj.steps = steps_data
        orm_obj.execution_mode = chain.execution_mode.value
        orm_obj.aggregate_step = aggregate_data
        orm_obj.is_active = chain.is_active
        orm_obj.save()

        return self._orm_to_entity(orm_obj)

    @staticmethod
    def _orm_to_entity(orm: ChainConfigORM) -> ChainConfig:
        """ORM转实体

        Args:
            orm: ORM对象

        Returns:
            ChainConfig实体
        """
        # 转换步骤
        steps = [
            ChainStep(
                step_id=s["step_id"],
                template_id=s["template_id"],
                step_name=s["step_name"],
                order=s["order"],
                input_mapping=s["input_mapping"],
                output_parser=s.get("output_parser"),
                parallel_group=s.get("parallel_group"),
                enable_tool_calling=s.get("enable_tool_calling", False),
                available_tools=s.get("available_tools"),
            )
            for s in orm.steps
        ]

        # 转换aggregate_step
        aggregate_step = None
        if orm.aggregate_step:
            aggregate_step = ChainStep(
                step_id=orm.aggregate_step["step_id"],
                template_id=orm.aggregate_step["template_id"],
                step_name=orm.aggregate_step["step_name"],
                order=orm.aggregate_step["order"],
                input_mapping=orm.aggregate_step["input_mapping"],
                output_parser=orm.aggregate_step.get("output_parser"),
                parallel_group=orm.aggregate_step.get("parallel_group"),
                enable_tool_calling=orm.aggregate_step.get("enable_tool_calling", False),
                available_tools=orm.aggregate_step.get("available_tools"),
            )

        return ChainConfig(
            id=str(orm.id),
            name=orm.name,
            category=PromptCategory(orm.category),
            description=orm.description,
            steps=steps,
            execution_mode=ChainExecutionMode(orm.execution_mode),
            aggregate_step=aggregate_step,
            is_active=orm.is_active,
            created_at=orm.created_at.date()
        )


class DjangoExecutionLogRepository:
    """
    Django ORM实现的执行日志仓储

    提供执行日志的记录和查询。
    """

    def __init__(self):
        self._model = PromptExecutionLogORM

    def create_log(self, log_data: dict[str, Any]) -> PromptExecutionLogORM:
        """创建执行日志

        Args:
            log_data: 日志数据

        Returns:
            创建的日志ORM对象
        """
        return self._model.objects.create(**log_data)

    def get_logs_by_execution_id(self, execution_id: str) -> list[PromptExecutionLogORM]:
        """根据执行ID获取日志

        Args:
            execution_id: 执行ID

        Returns:
            日志ORM对象列表
        """
        return list(self._model.objects.filter(
            execution_id=execution_id
        ).order_by('created_at'))

    def get_logs_by_template(
        self,
        template_id: int,
        limit: int = 100
    ) -> list[PromptExecutionLogORM]:
        """根据模板ID获取日志

        Args:
            template_id: 模板ID
            limit: 限制数量

        Returns:
            日志ORM对象列表
        """
        return list(self._model.objects.filter(
            template_id=template_id
        ).order_by('-created_at')[:limit])

    def get_recent_logs(self, limit: int = 50) -> list[PromptExecutionLogORM]:
        """获取最近的日志

        Args:
            limit: 限制数量

        Returns:
            日志ORM对象列表
        """
        return list(self._model.objects.order_by('-created_at')[:limit])
