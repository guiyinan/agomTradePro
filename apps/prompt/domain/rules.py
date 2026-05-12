"""
Validation Rules for AI Prompt Management.

This file contains pure validation logic using only Python standard library.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: list[str]
    warnings: list[str]

    @staticmethod
    def success() -> "ValidationResult":
        """创建成功的验证结果"""
        return ValidationResult(is_valid=True, errors=[], warnings=[])

    @staticmethod
    def failure(errors: list[str], warnings: list[str] | None = None) -> "ValidationResult":
        """创建失败的验证结果"""
        return ValidationResult(
            is_valid=False,
            errors=errors,
            warnings=warnings or []
        )

    def add_error(self, error: str) -> "ValidationResult":
        """添加错误并返回新结果"""
        return ValidationResult(
            is_valid=False,
            errors=self.errors + [error],
            warnings=self.warnings.copy()
        )

    def add_warning(self, warning: str) -> "ValidationResult":
        """添加警告并返回新结果"""
        return ValidationResult(
            is_valid=self.is_valid,
            errors=self.errors.copy(),
            warnings=self.warnings + [warning]
        )


def validate_template_content(content: str) -> ValidationResult:
    """验证模板内容

    检查：
    1. 占位符格式正确性
    2. 模板语法正确性
    3. 内容长度

    Args:
        content: 模板内容

    Returns:
        验证结果
    """
    errors = []
    warnings = []

    # 长度检查
    if len(content) < 10:
        errors.append("模板内容过短，至少需要10个字符")

    # 检查占位符格式
    open_braces = content.count('{{')
    close_braces = content.count('}}')
    if open_braces != close_braces:
        errors.append(f"占位符数量不匹配：{{ {open_braces} 个，}} {close_braces} 个")

    # 检查模板语法
    open_if = content.count('{%')
    close_if = content.count('%}')
    if open_if != close_if:
        errors.append(f"模板语法数量不匹配：{{% {open_if} 个，%}} {close_if} 个")

    # 检查未闭合的占位符
    unclosed_placeholders = re.findall(r'\{\{[^}]*$', content, re.MULTILINE)
    if unclosed_placeholders:
        errors.append(f"发现未闭合的占位符：{unclosed_placeholders}")

    # 警告：未使用占位符
    if '{{' not in content and '{%' not in content:
        warnings.append("模板未使用任何占位符或模板语法")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def validate_placeholder_name(name: str) -> ValidationResult:
    """验证占位符名称

    规则：
    1. 只能包含字母、数字、下划线
    2. 不能以数字开头
    3. 长度在1-50之间

    Args:
        name: 占位符名称

    Returns:
        验证结果
    """
    errors = []

    if not name:
        errors.append("占位符名称不能为空")

    if len(name) > 50:
        errors.append("占位符名称长度不能超过50个字符")

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        errors.append(
            "占位符名称只能包含字母、数字、下划线，且不能以数字开头"
        )

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=[]
    )


def validate_chain_steps(
    steps: list,
    execution_mode: str
) -> ValidationResult:
    """验证链式步骤配置

    检查：
    1. 步骤列表不为空
    2. order唯一性
    3. 循环依赖
    4. 并行组配置一致性

    Args:
        steps: 步骤列表
        execution_mode: 执行模式

    Returns:
        验证结果
    """
    errors = []
    warnings = []

    # 检查步骤列表
    if not steps:
        errors.append("步骤列表不能为空")
        return ValidationResult(is_valid=False, errors=errors, warnings=[])

    # 检查order唯一性
    orders = [s.order for s in steps]
    if len(orders) != len(set(orders)):
        errors.append("步骤order必须唯一")
        duplicate_orders = [o for o in orders if orders.count(o) > 1]
        errors.append(f"重复的order值：{set(duplicate_orders)}")

    # 检查循环依赖
    cycle = _detect_cycle(steps)
    if cycle:
        errors.append(f"检测到循环依赖：{' -> '.join(cycle)}")

    # 检查并行组配置
    parallel_groups = [s.parallel_group for s in steps if s.parallel_group]
    if parallel_groups and execution_mode == "serial":
        warnings.append(
            "串行模式下配置了parallel_group，将被忽略"
        )

    # 检查工具调用配置
    tool_calling_steps = [s for s in steps if s.enable_tool_calling]
    if tool_calling_steps and execution_mode != "tool" and execution_mode != "hybrid":
        warnings.append(
            "非工具调用模式下配置了enable_tool_calling，将被忽略"
        )

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def _detect_cycle(steps: list) -> list[str] | None:
    """检测步骤依赖中的循环

    Args:
        steps: 步骤列表

    Returns:
        循环路径，如果没有循环返回None
    """
    # 构建依赖图
    graph = {}
    step_map = {s.step_id: s for s in steps}

    for step in steps:
        graph[step.step_id] = []

    for step in steps:
        for _key, value in step.input_mapping.items():
            # 解析依赖：step1.output.xxx -> step1
            if isinstance(value, str) and '.output.' in value:
                parts = value.split('.')
                if parts[0] in step_map:
                    graph[step.step_id].append(parts[0])

    # DFS检测环
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # 找到环
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]

        path.pop()
        rec_stack.remove(node)
        return False

    for node in graph:
        if node not in visited:
            if dfs(node):
                cycle_start = path.index(path[-1])
                return path[cycle_start:]

    return None


def validate_temperature(value: float) -> ValidationResult:
    """验证温度参数

    Args:
        value: 温度值

    Returns:
        验证结果
    """
    errors = []

    if not (0 <= value <= 2):
        errors.append(f"temperature必须在0-2之间，当前值：{value}")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=[]
    )


def validate_function_params(params: dict) -> ValidationResult:
    """验证函数调用参数

    Args:
        params: 参数字典

    Returns:
        验证结果
    """
    errors = []
    warnings = []

    if not isinstance(params, dict):
        errors.append("函数参数必须是字典类型")
        return ValidationResult(is_valid=False, errors=errors, warnings=[])

    # 检查参数名格式
    for key in params.keys():
        result = validate_placeholder_name(key)
        if not result.is_valid:
            errors.extend([f"函数参数 {key}: {e}" for e in result.errors])

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def validate_prompt_category(category: str) -> ValidationResult:
    """验证Prompt分类

    Args:
        category: 分类字符串

    Returns:
        验证结果
    """
    valid_categories = ["report", "signal", "analysis", "chat"]

    if category not in valid_categories:
        return ValidationResult(
            is_valid=False,
            errors=[f"无效的分类：{category}，有效值：{valid_categories}"],
            warnings=[]
        )

    return ValidationResult.success()
