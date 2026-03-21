"""
初始化RSS源配置

运行: agomtradepro/Scripts/python.exe scripts/init_rss_sources.py
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

from apps.policy.infrastructure.models import RSSSourceConfigModel

# 初始RSS源配置（使用RSSHub聚合服务）
INITIAL_RSS_SOURCES = [
    {
        'name': '国务院政府文件库',
        'url': 'https://rsshub.app/gov/zhengce/zhengceku/bmwj',
        'category': 'gov_docs',
        'is_active': True,
        'fetch_interval_hours': 12,
        'parser_type': 'feedparser',
        'extract_content': False,
    },
    {
        'name': '央行公告',
        'url': 'https://rsshub.app/pbc/gonggao',
        'category': 'central_bank',
        'is_active': True,
        'fetch_interval_hours': 6,
        'parser_type': 'feedparser',
        'extract_content': False,
    },
    {
        'name': '证监会公告',
        'url': 'https://rsshub.app/csrc/gonggao',
        'category': 'csrc',
        'is_active': True,
        'fetch_interval_hours': 6,
        'parser_type': 'feedparser',
        'extract_content': False,
    },
    {
        'name': '财政部文件',
        'url': 'https://rsshub.app/mof/zhengcefagui',
        'category': 'mof',
        'is_active': True,
        'fetch_interval_hours': 12,
        'parser_type': 'feedparser',
        'extract_content': False,
    },
]


def init_rss_sources():
    """初始化RSS源"""
    print("[初始化] RSS源配置\n")
    print("=" * 60)

    for source_data in INITIAL_RSS_SOURCES:
        name = source_data['name']
        url = source_data['url']

        # 检查是否已存在
        existing = RSSSourceConfigModel.objects.filter(name=name).first()
        if existing:
            print(f"[跳过] 已存在: {name}")
            print(f"   URL: {url}")
            print(f"   状态: {'启用' if existing.is_active else '禁用'}")
            print()
            continue

        # 创建新源
        source = RSSSourceConfigModel.objects.create(**source_data)
        print(f"[创建] RSS源: {source.name}")
        print(f"   URL: {source.url}")
        print(f"   分类: {source.get_category_display()}")
        print(f"   间隔: {source.fetch_interval_hours} 小时")
        print(f"   状态: {'启用' if source.is_active else '禁用'}")
        print()

    print("=" * 60)
    total = RSSSourceConfigModel.objects.count()
    print(f"\n[完成] 共有 {total} 个RSS源。")
    print("\n请在Admin界面验证并管理RSS源:")
    print("http://127.0.0.1:8000/admin/policy/rsssourceconfigmodel/")


if __name__ == '__main__':
    init_rss_sources()
