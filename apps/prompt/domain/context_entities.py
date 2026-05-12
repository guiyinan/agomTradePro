"""
Context Bundle Domain Entities.

定义上下文构建的核心数据结构。
遵循项目架构约束：Domain 层只使用 Python 标准库。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContextDomain(Enum):
    """上下文域枚举"""
    MACRO = "macro"
    REGIME = "regime"
    PORTFOLIO = "portfolio"
    SIGNALS = "signals"
    ASSET_POOL = "asset_pool"


class ContextPolicy(Enum):
    """上下文注入策略"""
    SUMMARY_ONLY = "summary_only"                    # 首轮只给摘要
    SUMMARY_PLUS_SELECTED_RAW = "summary_plus_raw"   # 摘要 + 少量关键字段
    TOOL_ONLY = "tool_only"                          # 不注入，全部通过工具查


@dataclass(frozen=True)
class ContextSection:
    """单个上下文域的数据段（值对象）

    Attributes:
        name: 域名称
        summary: 摘要文本/dict，用于注入首轮 prompt
        raw_data: 完整原始数据，供工具查询和审计
        references: 数据来源引用信息
        generated_at: 生成时间
    """
    name: str
    summary: Any
    raw_data: Any
    references: dict[str, Any] = field(default_factory=dict)
    generated_at: str | None = None


@dataclass
class ContextBundle:
    """上下文包（聚合所有域的上下文数据）

    Attributes:
        sections: 各域的上下文段
        scope: 本次使用的域列表
        policy: 上下文注入策略
        generated_at: 生成时间
    """
    sections: dict[str, ContextSection] = field(default_factory=dict)
    scope: list[str] = field(default_factory=list)
    policy: str = ContextPolicy.SUMMARY_PLUS_SELECTED_RAW.value
    generated_at: str | None = None

    def add_section(self, section: ContextSection) -> None:
        """添加一个上下文段。"""
        self.sections[section.name] = section

    def get_section(self, name: str) -> ContextSection | None:
        """获取指定域的上下文段。"""
        return self.sections.get(name)

    def build_summary_text(self) -> str:
        """构建所有域的摘要文本，用于注入 system prompt。"""
        parts: list[str] = []
        for name, section in self.sections.items():
            summary = section.summary
            if isinstance(summary, dict):
                import json
                summary_str = json.dumps(summary, ensure_ascii=False, indent=2)
            elif isinstance(summary, str):
                summary_str = summary
            else:
                summary_str = str(summary) if summary else ""
            if summary_str:
                parts.append(f"## {name.upper()}\n{summary_str}")
        return "\n\n".join(parts)

    def get_used_domains(self) -> list[str]:
        """返回已构建的域列表。"""
        return list(self.sections.keys())
