"""
Terminal Domain Services.

纯领域逻辑，无 Django 依赖。
"""

from .entities import TerminalCommand, TerminalMode, TerminalRiskLevel

# 风险等级 → 允许角色 映射
RISK_ROLE_MAP: dict[TerminalRiskLevel, set[str]] = {
    TerminalRiskLevel.READ: {
        "admin", "owner", "analyst", "investment_manager",
        "trader", "risk", "read_only",
    },
    TerminalRiskLevel.WRITE_LOW: {
        "admin", "owner", "investment_manager", "trader",
    },
    TerminalRiskLevel.WRITE_HIGH: {
        "admin", "owner", "investment_manager",
    },
    TerminalRiskLevel.ADMIN: {
        "admin",
    },
}


class TerminalPermissionService:
    """终端权限服务 - 纯领域逻辑"""

    @staticmethod
    def can_execute(role: str, risk_level: TerminalRiskLevel) -> bool:
        """检查角色是否可执行指定风险等级的命令"""
        allowed_roles = RISK_ROLE_MAP.get(risk_level, set())
        return role in allowed_roles

    @staticmethod
    def get_max_risk_level(role: str) -> TerminalRiskLevel:
        """获取角色允许的最高风险等级"""
        for level in reversed(list(TerminalRiskLevel)):
            if role in RISK_ROLE_MAP.get(level, set()):
                return level
        return TerminalRiskLevel.READ

    @staticmethod
    def filter_commands_for_role(
        commands: list[TerminalCommand],
        role: str,
        mcp_enabled: bool,
    ) -> list[TerminalCommand]:
        """根据角色和 MCP 状态过滤可用命令"""
        result = []
        for cmd in commands:
            if not cmd.enabled_in_terminal:
                continue
            if cmd.requires_mcp and not mcp_enabled:
                continue
            allowed_roles = RISK_ROLE_MAP.get(cmd.risk_level, set())
            if role in allowed_roles:
                result.append(cmd)
        return result

    @staticmethod
    def get_available_modes(role: str, mcp_enabled: bool) -> list[str]:
        """获取角色可用的终端模式"""
        if not mcp_enabled:
            return [TerminalMode.READONLY.value]
        return [
            TerminalMode.READONLY.value,
            TerminalMode.CONFIRM_EACH.value,
            TerminalMode.AUTO_CONFIRM.value,
        ]
