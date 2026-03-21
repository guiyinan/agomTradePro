"""
初始化政策档位关键词规则

运行: agomtradepro/Scripts/python.exe scripts/init_policy_keywords.py
"""

import os
import sys
import django

# 设置UTF-8编码输出（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.policy.infrastructure.models import PolicyLevelKeywordModel

# 初始关键词规则配置
INITIAL_KEYWORD_RULES = [
    {
        'level': 'P3',
        'keywords': ['熔断', '紧急', '救市', '危机', '恐慌', '系统性风险'],
        'weight': 1,
        'category': None,  # 适用于所有分类
        'is_active': True,
    },
    {
        'level': 'P2',
        'keywords': ['降息', '降准', '加息', '加准', '刺激', '干预', '调整',
                     '降存款', '降贷款', 'MLF', '逆回购', '中期借贷'],
        'weight': 1,
        'category': None,
        'is_active': True,
    },
    {
        'level': 'P1',
        'keywords': ['酝酿', '研究', '考虑', '拟', '或将', '讨论',
                     '适时', '酌情', '有望', '可能'],
        'weight': 1,
        'category': None,
        'is_active': True,
    },
    # 央行特定关键词
    {
        'level': 'P2',
        'keywords': ['准备金', '利率', '流动性', '公开市场操作'],
        'weight': 2,  # 央行相关权重更高
        'category': 'central_bank',
        'is_active': True,
    },
    # 证监会特定关键词
    {
        'level': 'P2',
        'keywords': ['IPO', '再融资', '减持', '退市', '停牌'],
        'weight': 2,
        'category': 'csrc',
        'is_active': True,
    },
]


def init_policy_keywords():
    """初始化关键词规则"""
    print("[初始化] 政策档位关键词规则\n")
    print("=" * 60)

    for rule_data in INITIAL_KEYWORD_RULES:
        level = rule_data['level']
        keywords = rule_data['keywords']
        category = rule_data.get('category')
        weight = rule_data.get('weight', 1)

        # 检查是否已存在相似的规则
        existing = PolicyLevelKeywordModel.objects.filter(
            level=level,
            category=category
        ).first()

        if existing:
            print(f"[跳过] 已存在: {level} 档位规则")
            print(f"   关键词: {', '.join(existing.keywords[:5])}")
            print(f"   分类: {category or '通用'}")
            print(f"   权重: {existing.weight}")
            print()
            continue

        # 创建新规则
        rule = PolicyLevelKeywordModel.objects.create(**rule_data)
        print(f"[创建] 关键词规则: {rule.level} 档位")
        print(f"   关键词: {', '.join(keywords[:5])}{' ...' if len(keywords) > 5 else ''}")
        print(f"   权重: {rule.weight}")
        print(f"   分类: {category or '通用（所有RSS源）'}")
        print()

    print("=" * 60)
    total = PolicyLevelKeywordModel.objects.count()
    print(f"\n[完成] 共有 {total} 个关键词规则。")
    print("\n请在Admin界面验证并管理关键词规则:")
    print("http://127.0.0.1:8000/admin/policy/policylevelkeywordmodel/")


if __name__ == '__main__':
    init_policy_keywords()
