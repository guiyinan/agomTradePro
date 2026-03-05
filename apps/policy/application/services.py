"""
Application Layer - Services for RSS Processing

RSS相关的业务服务，包括档位匹配等。
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

from django.utils import timezone

from ..domain.entities import PolicyLevel, RSSItem, PolicyLevelKeywordRule

logger = logging.getLogger(__name__)


class PolicyLevelMatcher:
    """
    政策档位匹配器

    根据关键词规则从RSS条目标题中提取政策档位
    """

    def __init__(self, keyword_rules: List[PolicyLevelKeywordRule]):
        """
        初始化匹配器

        Args:
            keyword_rules: 关键词规则列表
        """
        self.keyword_rules = keyword_rules
        # 构建关键词到档位的映射（提高匹配效率）
        self._keyword_map = self._build_keyword_map()

    def _build_keyword_map(self) -> Dict[str, List[tuple]]:
        """
        构建关键词映射

        Returns:
            Dict[str, List[tuple]]: {关键词: [(档位, 权重), ...]}
        """
        keyword_map = {}
        for rule in self.keyword_rules:
            for keyword in rule.keywords:
                if keyword not in keyword_map:
                    keyword_map[keyword] = []
                keyword_map[keyword].append((rule.level, rule.weight))

        return keyword_map

    def match(self, item: RSSItem) -> Optional[PolicyLevel]:
        """
        匹配RSS条目的档位

        Args:
            item: RSS条目

        Returns:
            Optional[PolicyLevel]: 匹配到的档位，None表示未匹配到
        """
        title = item.title.lower()

        # 统计各档位的得分
        level_scores = {PolicyLevel.P1: 0, PolicyLevel.P2: 0, PolicyLevel.P3: 0}

        # 遍历关键词
        for keyword, level_weight_list in self._keyword_map.items():
            if keyword.lower() in title:
                # 关键词匹配，累加得分
                for level, weight in level_weight_list:
                    level_scores[level] += weight

        # 获取最高分的档位
        max_score = 0
        matched_level = None

        for level, score in level_scores.items():
            if score > max_score:
                max_score = score
                matched_level = level

        # 只有得分大于0时才返回档位
        if matched_level and max_score > 0:
            logger.debug(
                f"Matched policy level {matched_level.value} "
                f"for item '{item.title}' (score: {max_score})"
            )
            return matched_level

        logger.debug(f"No policy level matched for item: {item.title}")
        return None

    def match_with_details(
        self,
        item: RSSItem
    ) -> tuple[Optional[PolicyLevel], Dict[str, any]]:
        """
        匹配RSS条目的档位（带详细信息）

        Args:
            item: RSS条目

        Returns:
            tuple[Optional[PolicyLevel], Dict]: (档位, 详细信息)
        """
        title = item.title.lower()

        # 统计各档位的得分和匹配的关键词
        level_scores = {
            PolicyLevel.P1: {"score": 0, "keywords": []},
            PolicyLevel.P2: {"score": 0, "keywords": []},
            PolicyLevel.P3: {"score": 0, "keywords": []},
        }

        # 遍历关键词
        for keyword, level_weight_list in self._keyword_map.items():
            if keyword.lower() in title:
                # 关键词匹配
                for level, weight in level_weight_list:
                    level_scores[level]["score"] += weight
                    if keyword not in level_scores[level]["keywords"]:
                        level_scores[level]["keywords"].append(keyword)

        # 获取最高分的档位
        max_score = 0
        matched_level = None
        matched_keywords = []

        for level, details in level_scores.items():
            if details["score"] > max_score:
                max_score = details["score"]
                matched_level = level
                matched_keywords = details["keywords"]

        details = {
            "score": max_score,
            "matched_keywords": matched_keywords,
            "all_scores": {
                level.value: details["score"]
                for level, details in level_scores.items()
            }
        }

        return matched_level, details


def extract_policy_level_from_title(
    title: str,
    keyword_rules: Optional[List[PolicyLevelKeywordRule]] = None
) -> Optional[PolicyLevel]:
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
    item = RSSItem(
        title=title,
        link="",
        pub_date=timezone.now(),
        source="extractor"
    )

    return matcher.match(item)
