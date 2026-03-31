"""
AgomTradePro 系统页面遍历测试

使用无头浏览器遍历所有页面，检测错误并收集信息。
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import Browser, Page, async_playwright

# 添加项目根目录到 Python 路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

import django

django.setup()

from django.conf import settings
from django.test.utils import get_runner

# 定义要测试的页面列表
# 注意：只测试HTML页面视图，不测试POST-only API端点
PAGE_ROUTES = [
    # 公开页面
    {"url": "/", "name": "首页", "requires_auth": False},
    {"url": "/api/health/", "name": "健康检查", "requires_auth": False},
    {"url": "/docs/", "name": "文档列表", "requires_auth": False},

    # 认证页面
    {"url": "/account/login/", "name": "登录页面", "requires_auth": False},
    {"url": "/account/register/", "name": "注册页面", "requires_auth": False},

    # 需要登录的页面
    {"url": "/dashboard/", "name": "仪表盘", "requires_auth": True},
    {"url": "/account/profile/", "name": "用户资料", "requires_auth": True},
    {"url": "/account/settings/", "name": "账户设置", "requires_auth": True},
    {"url": "/account/capital-flow/", "name": "资金流水", "requires_auth": True},

    # 回测模块
    {"url": "/backtest/", "name": "回测列表", "requires_auth": True},
    {"url": "/backtest/create/", "name": "创建回测", "requires_auth": True},

    # 宏观模块
    {"url": "/macro/data/", "name": "宏观数据", "requires_auth": True},
    {"url": "/macro/datasources/", "name": "数据源配置", "requires_auth": True},
    {"url": "/macro/controller/", "name": "数据控制器", "requires_auth": True},

    # Regime 模块
    {"url": "/regime/dashboard/", "name": "Regime 仪表盘", "requires_auth": True},

    # Filter 模块
    {"url": "/filter/dashboard/", "name": "Filter 仪表盘", "requires_auth": True},

    # Signal 模块（只测试页面视图，不测试POST API）
    {"url": "/signal/manage/", "name": "信号管理", "requires_auth": True},
    # 注意: /signal/create/, /signal/eligibility/ 是POST API，不是页面

    # Policy 模块
    {"url": "/policy/events/", "name": "政策事件页面", "requires_auth": True},
    {"url": "/policy/rss/sources/", "name": "RSS 源管理", "requires_auth": True},
    {"url": "/policy/rss/reader/", "name": "RSS 阅读器", "requires_auth": True},
    {"url": "/policy/rss/keywords/", "name": "RSS 关键词", "requires_auth": True},
    {"url": "/policy/rss/logs/", "name": "RSS 抓取日志", "requires_auth": True},

    # Equity 模块
    {"url": "/equity/screen/", "name": "个股筛选", "requires_auth": True},

    # Fund 模块
    {"url": "/fund/dashboard/", "name": "基金分析仪表盘", "requires_auth": True},

    # Admin
    {"url": "/admin/", "name": "管理后台", "requires_auth": True},
]


class PageTester:
    """页面测试器"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.results: list[dict[str, Any]] = []
        self.console_errors: list[dict[str, Any]] = []
        self.failed_pages: list[dict[str, Any]] = []
        self.browser: Browser = None

    async def setup_browser(self):
        """设置浏览器"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        return playwright

    async def capture_console_messages(self, page: Page):
        """捕获控制台消息"""
        async def handle_console(msg):
            if msg.type in ['error', 'warning']:
                entry = {
                    'type': msg.type,
                    'text': msg.text,
                    'location': f"{msg.location.get('url', 'unknown')}:{msg.location.get('lineNumber', 0)}"
                }
                self.console_errors.append(entry)
                print(f"  [{msg.type.upper()}] {msg.text}")

        page.on('console', handle_console)

    async def test_page(self, page_info: dict[str, Any], credentials: dict[str, str] = None) -> dict[str, Any]:
        """测试单个页面"""
        url = page_info['url']
        name = page_info['name']
        requires_auth = page_info.get('requires_auth', False)
        full_url = f"{self.base_url}{url}"

        result = {
            'url': url,
            'name': name,
            'status': 'pending',
            'status_code': None,
            'title': None,
            'errors': [],
            'console_errors': [],
            'load_time': None,
            'screenshot': None,
            'redirected': False,
            'final_url': None,
        }

        print(f"\n{'='*60}")
        print(f"测试页面: {name} ({url})")
        print(f"{'='*60}")

        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            ignore_https_errors=True
        )

        # 如果需要认证，先登录
        if requires_auth and credentials:
            # 设置 cookies
            await context.add_cookies([{
                'name': 'sessionid',
                'value': credentials.get('sessionid', ''),
                'domain': 'localhost',
                'path': '/',
            }])

        page = await context.new_page()
        await self.capture_console_messages(page)

        try:
            # 记录开始时间
            start_time = datetime.now()

            # 导航到页面
            response = await page.goto(
                full_url,
                wait_until='networkidle',
                timeout=30000
            )

            # 计算加载时间
            load_time = (datetime.now() - start_time).total_seconds()
            result['load_time'] = load_time
            result['status_code'] = response.status if response else None
            result['final_url'] = page.url
            result['redirected'] = page.url != full_url

            # 获取页面标题
            title = await page.title()
            result['title'] = title

            print(f"  状态码: {result['status_code']}")
            print(f"  页面标题: {title}")
            print(f"  加载时间: {load_time:.2f}秒")

            if result['redirected']:
                print(f"  重定向到: {page.url}")

            # 检查是否有错误
            page_errors = []

            # 检查页面是否有明显的错误信息
            try:
                # 检查是否有 Django 错误页面
                error_present = await page.query_selector('h1:has-text("Page not found")')
                if error_present:
                    page_errors.append("页面未找到 (404)")

                error_present = await page.query_selector('h1:has-text("Server Error")')
                if error_present:
                    page_errors.append("服务器错误 (500)")

                error_present = await page.query_selector('h1:has-text("Forbidden")')
                if error_present:
                    page_errors.append("禁止访问 (403)")

                # 检查是否有异常堆栈
                exception_present = await page.query_selector('pre.exception_value')
                if exception_present:
                    exception_text = await exception_present.inner_text()
                    page_errors.append(f"异常: {exception_text[:100]}")

            except Exception as e:
                print(f"  警告: 无法检测页面错误: {e}")

            result['errors'] = page_errors

            # 检查 HTTP 状态码
            if response and response.status >= 400:
                result['status'] = 'failed'
                result['errors'].append(f"HTTP {response.status}")
                self.failed_pages.append(result)
            elif page_errors:
                result['status'] = 'error'
                self.failed_pages.append(result)
            else:
                result['status'] = 'passed'

            # 截图（仅在失败时）
            if result['status'] != 'passed':
                screenshot_dir = BASE_DIR / 'screenshots'
                screenshot_dir.mkdir(exist_ok=True)
                screenshot_path = screenshot_dir / f"{name.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(screenshot_path))
                result['screenshot'] = str(screenshot_path)
                print(f"  截图保存: {screenshot_path}")

        except Exception as e:
            result['status'] = 'failed'
            result['errors'].append(f"异常: {str(e)}")
            self.failed_pages.append(result)
            print(f"  ❌ 测试失败: {e}")

        finally:
            await context.close()
            self.results.append(result)

        return result

    async def run_all_tests(self):
        """运行所有测试"""
        print(f"\n{'='*80}")
        print("开始测试 AgomTradePro 系统页面")
        print(f"基础 URL: {self.base_url}")
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")

        playwright = await self.setup_browser()

        try:
            # 首先测试不需要认证的页面
            print("\n### 测试公开页面 ###")
            for page_info in PAGE_ROUTES:
                if not page_info.get('requires_auth', False):
                    await self.test_page(page_info)

            # 测试需要认证的页面
            print("\n### 测试需要登录的页面 ###")
            print("注意: 需要认证的页面可能会失败，因为没有有效的 session")

            for page_info in PAGE_ROUTES:
                if page_info.get('requires_auth', False):
                    await self.test_page(page_info)

        finally:
            await self.browser.close()
            await playwright.stop()

        # 生成报告
        self.generate_report()

    def generate_report(self):
        """生成测试报告"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r['status'] == 'passed')
        failed = sum(1 for r in self.results if r['status'] == 'failed')
        errors = sum(1 for r in self.results if r['status'] == 'error')

        print(f"\n{'='*80}")
        print("测试报告摘要")
        print(f"{'='*80}")
        print(f"总页面数: {total}")
        print(f"通过: {passed} ({passed/total*100:.1f}%)")
        print(f"失败: {failed} ({failed/total*100:.1f}%)")
        print(f"错误: {errors} ({errors/total*100:.1f}%)")
        print(f"控制台错误/警告: {len(self.console_errors)}")

        # 失败的页面
        if self.failed_pages:
            print(f"\n{'='*80}")
            print("失败的页面:")
            print(f"{'='*80}")
            for page in self.failed_pages:
                print(f"\n  ❌ {page['name']} ({page['url']})")
                print(f"     状态: {page['status']}")
                print(f"     状态码: {page['status_code']}")
                if page['errors']:
                    for error in page['errors']:
                        print(f"     - {error}")
                if page.get('screenshot'):
                    print(f"     截图: {page['screenshot']}")

        # 控制台错误汇总
        if self.console_errors:
            print(f"\n{'='*80}")
            print("控制台错误/警告汇总:")
            print(f"{'='*80}")
            for error in self.console_errors[:20]:  # 只显示前20个
                print(f"  [{error['type'].upper()}] {error['text']}")
                print(f"     位置: {error['location']}")

        # 保存详细报告到 JSON
        report_path = BASE_DIR / 'test_results.json'
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': total,
                'passed': passed,
                'failed': failed,
                'errors': errors,
                'console_errors': len(self.console_errors),
            },
            'results': self.results,
            'console_errors': self.console_errors,
        }

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        print(f"\n详细报告已保存到: {report_path}")


def ensure_django_server():
    """确保 Django 服务器正在运行"""
    import psutil
    import requests

    # 检查服务器是否已经在运行
    try:
        response = requests.get('http://localhost:8000/api/health/', timeout=2)
        print("Django 开发服务器已在运行")
        return True
    except:
        pass

    print("启动 Django 开发服务器...")
    # 启动 Django 开发服务器
    env = os.environ.copy()
    env['PYTHONPATH'] = str(BASE_DIR)

    server_process = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', '--noreload'],
        cwd=str(BASE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 等待服务器启动
    import time
    for i in range(30):
        try:
            response = requests.get('http://localhost:8000/api/health/', timeout=1)
            print("Django 开发服务器启动成功")
            return True
        except:
            time.sleep(1)
            if i % 5 == 0:
                print(f"等待服务器启动... ({i}/30秒)")

    print("警告: Django 服务器可能未正确启动")
    return False


async def main():
    """主函数"""
    # 确保 Django 服务器正在运行
    ensure_django_server()

    # 运行测试
    tester = PageTester(base_url="http://localhost:8000")
    await tester.run_all_tests()


if __name__ == '__main__':
    asyncio.run(main())

