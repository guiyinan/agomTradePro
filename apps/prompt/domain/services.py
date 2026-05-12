"""
Domain Services for AI Prompt Management.

This file contains pure business logic using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


class PlaceholderResolverProtocol(Protocol):
    """占位符解析器协议"""

    def resolve(self, placeholder: str, context: dict[str, Any]) -> Any:
        """解析单个占位符"""
        ...


class TemplateRenderer:
    """模板渲染器（Domain层纯实现）

    注意：实际渲染在Infrastructure层使用Jinja2完成。
    这里只定义接口和基础逻辑。
    """

    def __init__(self):
        self.resolvers: dict[str, PlaceholderResolverProtocol] = {}

    def register_resolver(self, prefix: str, resolver: PlaceholderResolverProtocol):
        """注册解析器"""
        self.resolvers[prefix] = resolver

    def render_simple(
        self,
        template: str,
        context: dict[str, Any]
    ) -> str:
        """简单模板渲染（仅支持{{var}}替换）

        这是Domain层的纯实现，用于简单场景。
        复杂模板请在Infrastructure层使用Jinja2。
        """
        result = template
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))
        return result

    def extract_placeholders(self, template: str) -> list[str]:
        """从模板中提取占位符

        Returns:
            占位符名称列表，如 ["PMI", "CPI", "MACRO_DATA"]
        """
        pattern = r'\{\{([^{}]+)\}\}'
        matches = re.findall(pattern, template)
        return [m.strip() for m in matches]


class OutputParser:
    """输出解析器

    从AI响应中提取结构化数据。
    """

    @staticmethod
    def extract_json(response: str) -> dict[str, Any] | None:
        """从AI响应中提取JSON

        支持以下格式：
        1. ```json...``` 代码块
        2. 纯JSON字符串

        Returns:
            解析后的字典，失败返回None
        """
        # 尝试提取代码块
        pattern = r'```json\s*(.*?)\s*```'
        match = re.search(pattern, response, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return None

    @staticmethod
    def extract_table(response: str) -> list[list[str]]:
        """从AI响应中提取表格

        支持Markdown表格格式：
        | Header1 | Header2 |
        |---------|---------|
        | Value1  | Value2  |

        Returns:
            二维列表，第一行为表头
        """
        lines = response.strip().split('\n')
        table_data = []
        in_table = False

        for line in lines:
            line = line.strip()
            if not line.startswith('|'):
                if in_table:
                    break
                continue

            if not in_table:
                in_table = True

            # 移除首尾的 |
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            # 跳过分隔行
            if not all(cell.startswith('-') if cell else False for cell in cells):
                table_data.append(cells)

        return table_data

    @staticmethod
    def extract_code_blocks(response: str, language: str = "") -> list[str]:
        """提取指定语言的代码块

        Args:
            response: AI响应内容
            language: 语言标识（如"python", "json"），空字符串表示所有语言

        Returns:
            代码块内容列表
        """
        if language:
            pattern = f'```{language}\\s*(.*?)\\s*```'
        else:
            pattern = r'```(?:\w+)?\s*(.*?)\s*```'

        matches = re.findall(pattern, response, re.DOTALL)
        return [m.strip() for m in matches]

    @staticmethod
    def parse_function_calls(response: str) -> list[dict[str, Any]]:
        """解析AI返回的函数调用

        支持OpenAI Function Calling格式：
        <tool_call>
        {"name": "function_name", "arguments": {...}}
        </tool_call>

        Returns:
            函数调用列表，格式：[{"name": str, "arguments": dict}]
        """
        pattern = r'<tool_call>\s*(.*?)\s*</tool_call>'
        matches = re.findall(pattern, response, re.DOTALL)

        function_calls = []
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, dict) and "name" in data:
                    function_calls.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {})
                    })
            except json.JSONDecodeError:
                continue

        return function_calls


class ChainExecutionPlan:
    """链式执行计划"""

    @dataclass(frozen=True)
    class ExecutionStep:
        """执行步骤"""
        step_id: str
        template_id: str
        order: int
        parallel_group: str | None = None
        dependencies: list[str] = None  # 依赖的step_id列表

    def __init__(self):
        self.steps: list[ChainExecutionPlan.ExecutionStep] = []

    def add_step(self, step: "ChainExecutionPlan.ExecutionStep"):
        """添加执行步骤"""
        self.steps.append(step)

    def get_parallel_groups(self) -> dict[str, list["ExecutionStep"]]:
        """获取并行分组

        Returns:
            分组字典，key为parallel_group，value为该组的步骤列表
            无分组的步骤key为None
        """
        groups: dict[str, list[ChainExecutionPlan.ExecutionStep]] = {}
        for step in self.steps:
            group = step.parallel_group or "__serial__"
            if group not in groups:
                groups[group] = []
            groups[group].append(step)
        return groups


class ChainExecutor:
    """链式执行器（Domain层编排逻辑）

    负责构建执行计划，实际执行在Application层完成。
    """

    def __init__(self):
        self._plan: ChainExecutionPlan | None = None

    def build_execution_plan(
        self,
        steps: list["ChainStep"],
        execution_mode: "ChainExecutionMode"
    ) -> ChainExecutionPlan:
        """构建执行计划

        Args:
            steps: 链式步骤列表
            execution_mode: 执行模式

        Returns:
            执行计划
        """
        self._plan = ChainExecutionPlan()

        if execution_mode == ChainExecutionMode.SERIAL:
            self._build_serial_plan(steps)
        elif execution_mode == ChainExecutionMode.PARALLEL:
            self._build_parallel_plan(steps)
        elif execution_mode == ChainExecutionMode.TOOL_CALLING:
            self._build_tool_calling_plan(steps)
        else:  # HYBRID
            self._build_hybrid_plan(steps)

        return self._plan

    def _build_serial_plan(self, steps: list["ChainStep"]):
        """构建串行执行计划"""
        # 按order排序
        sorted_steps = sorted(steps, key=lambda s: s.order)

        # 每个步骤依赖前一个步骤
        for i, step in enumerate(sorted_steps):
            dependencies = []
            if i > 0:
                dependencies = [sorted_steps[i - 1].step_id]

            exec_step = ChainExecutionPlan.ExecutionStep(
                step_id=step.step_id,
                template_id=step.template_id,
                order=step.order,
                parallel_group=None,
                dependencies=dependencies
            )
            self._plan.add_step(exec_step)

    def _build_parallel_plan(self, steps: list["ChainStep"]):
        """构建并行执行计划"""
        # 按parallel_group分组
        groups: dict[str, list[ChainStep]] = {}
        for step in steps:
            group = step.parallel_group or f"group_{step.order}"
            if group not in groups:
                groups[group] = []
            groups[group].append(step)

        # 按order排序分组
        sorted_groups = sorted(
            groups.items(),
            key=lambda x: min(s.order for s in x[1])
        )

        # 构建执行计划
        prev_group_steps: list[str] = []
        for group_name, group_steps in sorted_groups:
            group_steps_sorted = sorted(group_steps, key=lambda s: s.order)
            for step in group_steps_sorted:
                exec_step = ChainExecutionPlan.ExecutionStep(
                    step_id=step.step_id,
                    template_id=step.template_id,
                    order=step.order,
                    parallel_group=group_name,
                    dependencies=prev_group_steps.copy()
                )
                self._plan.add_step(exec_step)
            prev_group_steps = [s.step_id for s in group_steps_sorted]

    def _build_tool_calling_plan(self, steps: list["ChainStep"]):
        """构建工具调用执行计划"""
        # 工具调用模式通常是单步执行
        for step in sorted(steps, key=lambda s: s.order):
            exec_step = ChainExecutionPlan.ExecutionStep(
                step_id=step.step_id,
                template_id=step.template_id,
                order=step.order,
                parallel_group=None,
                dependencies=[]
            )
            self._plan.add_step(exec_step)

    def _build_hybrid_plan(self, steps: list["ChainStep"]):
        """构建混合执行计划"""
        # 混合模式：根据parallel_group决定是否并行
        self._build_parallel_plan(steps)


# 导入ChainStep和ChainExecutionMode（避免循环导入）
# 这些在运行时会从entities.py导入
from .entities import ChainExecutionMode, ChainStep  # noqa: E402
