"""
Application Layer - Services for RSS Processing

RSS相关的业务服务，包括档位匹配等。
"""

import logging
from typing import TypedDict

from django.utils import timezone

from ..domain.entities import PolicyLevel, PolicyLevelKeywordRule, RSSItem

logger = logging.getLogger(__name__)
KeywordWeight = tuple[PolicyLevel, int]


class LevelMatchDetails(TypedDict):
    """Per-level keyword evidence."""

    score: int
    keywords: list[str]


class PolicyMatchDetails(TypedDict):
    """Explainable policy-level match result."""

    score: int
    matched_keywords: list[str]
    all_scores: dict[str, int]


class PolicyLevelMatcher:
    """
    政策档位匹配器

    根据关键词规则从RSS条目标题中提取政策档位
    """

    def __init__(self, keyword_rules: list[PolicyLevelKeywordRule]) -> None:
        """
        初始化匹配器

        Args:
            keyword_rules: 关键词规则列表
        """
        self.keyword_rules = keyword_rules
        # 构建关键词到档位的映射（提高匹配效率）
        self._keyword_map = self._build_keyword_map()

    def _build_keyword_map(self) -> dict[str, list[KeywordWeight]]:
        """
        构建关键词映射

        Returns:
            Dict[str, List[tuple]]: {关键词: [(档位, 权重), ...]}
        """
        keyword_map: dict[str, list[KeywordWeight]] = {}
        for rule in self.keyword_rules:
            if rule.level not in {PolicyLevel.P1, PolicyLevel.P2, PolicyLevel.P3}:
                raise ValueError("keyword rule level must be P1, P2, or P3")
            if isinstance(rule.weight, bool) or rule.weight <= 0:
                raise ValueError("keyword rule weight must be a positive integer")
            seen_keywords: set[str] = set()
            for keyword in rule.keywords:
                normalized = keyword.strip().casefold()
                if not normalized:
                    raise ValueError("keyword rule cannot contain blank keywords")
                if normalized in seen_keywords:
                    continue
                seen_keywords.add(normalized)
                keyword_map.setdefault(normalized, []).append((rule.level, rule.weight))

        return keyword_map

    def match(self, item: RSSItem) -> PolicyLevel | None:
        """
        匹配RSS条目的档位

        Args:
            item: RSS条目

        Returns:
            Optional[PolicyLevel]: 匹配到的档位，None表示未匹配到
        """
        title = item.title.casefold()

        # 统计各档位的得分
        level_scores: dict[PolicyLevel, int] = {
            PolicyLevel.P1: 0,
            PolicyLevel.P2: 0,
            PolicyLevel.P3: 0,
        }

        # 遍历关键词
        for keyword, level_weight_list in self._keyword_map.items():
            if keyword in title:
                # 关键词匹配，累加得分
                for level, weight in level_weight_list:
                    level_scores[level] += weight

        # 获取最高分的档位
        severity = {PolicyLevel.P1: 1, PolicyLevel.P2: 2, PolicyLevel.P3: 3}
        matched_level, max_score = max(
            level_scores.items(),
            key=lambda item: (item[1], severity[item[0]]),
        )

        # 只有得分大于0时才返回档位
        if max_score > 0:
            logger.debug(
                "Matched policy level %s for RSS item (score=%s)",
                matched_level.value,
                max_score,
            )
            return matched_level

        logger.debug("No policy level matched for RSS item")
        return None

    def match_with_details(
        self,
        item: RSSItem,
    ) -> tuple[PolicyLevel | None, PolicyMatchDetails]:
        """
        匹配RSS条目的档位（带详细信息）

        Args:
            item: RSS条目

        Returns:
            tuple[Optional[PolicyLevel], Dict]: (档位, 详细信息)
        """
        title = item.title.casefold()

        # 统计各档位的得分和匹配的关键词
        level_scores: dict[PolicyLevel, LevelMatchDetails] = {
            PolicyLevel.P1: {"score": 0, "keywords": []},
            PolicyLevel.P2: {"score": 0, "keywords": []},
            PolicyLevel.P3: {"score": 0, "keywords": []},
        }

        # 遍历关键词
        for keyword, level_weight_list in self._keyword_map.items():
            if keyword in title:
                # 关键词匹配
                for level, weight in level_weight_list:
                    level_scores[level]["score"] += weight
                    if keyword not in level_scores[level]["keywords"]:
                        level_scores[level]["keywords"].append(keyword)

        # 获取最高分的档位
        severity = {PolicyLevel.P1: 1, PolicyLevel.P2: 2, PolicyLevel.P3: 3}
        matched_level, matched = max(
            level_scores.items(),
            key=lambda item: (item[1]["score"], severity[item[0]]),
        )
        max_score = matched["score"]
        matched_keywords = matched["keywords"]

        details: PolicyMatchDetails = {
            "score": max_score,
            "matched_keywords": matched_keywords,
            "all_scores": {
                level.value: details["score"] for level, details in level_scores.items()
            },
        }

        return (matched_level if max_score > 0 else None), details


def extract_policy_level_from_title(
    title: str,
    keyword_rules: list[PolicyLevelKeywordRule] | None = None,
) -> PolicyLevel | None:
    """
    从标题提取政策档位（便捷函数）

    Args:
        title: RSS条目标题
        keyword_rules: 关键词规则列表（可选，None使用默认规则）

    Returns:
        Optional[PolicyLevel]: 提取到的档位
    """
    if keyword_rules is None:
        # 使用默认规则
        from ..domain.rules import DEFAULT_KEYWORD_RULES

        keyword_rules = DEFAULT_KEYWORD_RULES

    matcher = PolicyLevelMatcher(keyword_rules)

    # 创建临时RSSItem
    item = RSSItem(title=title, link="", pub_date=timezone.now(), source="extractor")

    return matcher.match(item)
