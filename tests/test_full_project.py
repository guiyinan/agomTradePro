"""
AgomTradePro 项目无头浏览器全面测试脚本
测试所有主要功能并生成改进建议文档
"""
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, async_playwright


@dataclass
class TestResult:
    """测试结果"""
    url: str
    name: str
    status: str  # success, error, warning
    response_time: float
    error_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    screenshot: str = ""


TestResult.__test__ = False


@dataclass
class Improvement:
    """改进建议"""
    category: str  # UI, UX, Performance, Security, Functionality
    priority: str  # High, Medium, Low
    title: str
    description: str
    location: str  # URL or component
    suggestion: str = ""


class AgomTradeProBrowserTest:
    """无头浏览器测试类"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: list[TestResult] = []
        self.improvements: list[Improvement] = []
        self.browser = None
        self.page = None

    async def setup(self):
        """初始化浏览器"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        self.page = await context.new_page()

    async def teardown(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()

    async def login(self, username: str = "admin", password: str = "Aa123456") -> bool:
        """登录系统"""
        try:
            await self.page.goto(f"{self.base_url}/admin/login/", wait_until="networkidle")
            await self.page.fill("input[name='username']", username)
            await self.page.fill("input[name='password']", password)
            await self.page.click("input[type='submit']")
            await self.page.wait_for_url("**/admin/**", timeout=5000)
            return True
        except Exception as e:
            print(f"登录失败: {e}")
            return False

    async def test_page(self, url: str, name: str, check_elements: list[str] = None,
                       need_login: bool = True) -> TestResult:
        """测试单个页面"""
        start_time = datetime.now()
        full_url = urljoin(self.base_url, url)

        try:
            print(f"测试: {name} - {full_url}")
            await self.page.goto(full_url, wait_until="networkidle", timeout=10000)

            response_time = (datetime.now() - start_time).total_seconds()

            # 检查页面标题
            title = await self.page.title()

            # 检查错误提示
            error_indicators = await self.page.query_selector_all(
                ".error, .exception, .traceback, h1:has-text('404'), h1:has-text('500')"
            )

            # 检查指定元素
            element_checks = {}
            if check_elements:
                for selector in check_elements:
                    element = await self.page.query_selector(selector)
                    element_checks[selector] = element is not None

            # 检查页面是否有内容
            body_text = await self.page.evaluate("() => document.body.innerText")
            has_content = len(body_text.strip()) > 0

            # 截图
            screenshot_path = f"screenshots/{name.replace('/', '_').replace(' ', '_')}.png"
            try:
                await self.page.screenshot(path=screenshot_path, full_page=True)
            except:
                screenshot_path = ""

            status = "success"
            error_msg = ""

            if error_indicators:
                status = "error"
                error_msg = "发现错误提示元素"
            elif not has_content and "404" not in full_url:
                status = "warning"
                error_msg = "页面内容为空"

            result = TestResult(
                url=full_url,
                name=name,
                status=status,
                response_time=response_time,
                error_message=error_msg,
                details={
                    "title": title,
                    "content_length": len(body_text),
                    "element_checks": element_checks,
                    "error_count": len(error_indicators)
                },
                screenshot=screenshot_path
            )

        except Exception as e:
            result = TestResult(
                url=full_url,
                name=name,
                status="error",
                response_time=(datetime.now() - start_time).total_seconds(),
                error_message=str(e)
            )

        self.results.append(result)
        print(f"  状态: {result.status}, 耗时: {result.response_time:.2f}s")
        return result

    async def test_admin_pages(self):
        """测试管理后台页面"""
        print("\n=== 测试管理后台 ===")

        admin_pages = [
            ("/admin/", "Admin首页"),
            ("/admin/account/", "Account模块"),
            ("/admin/account/userprofile/", "用户管理"),
            ("/admin/account/currencymodel/", "货币管理"),
            ("/admin/account/assetcategorymodel/", "资产类别"),
            ("/admin/account/portfoliomodel/", "投资组合"),
            ("/admin/account/positionmodel/", "持仓管理"),
            ("/admin/account/transactionmodel/", "交易记录"),
            ("/admin/policy/", "Policy模块"),
            ("/admin/policy/policylog/", "政策事件"),
            ("/admin/policy/rsssourceconfigmodel/", "RSS源配置"),
        ]

        for url, name in admin_pages:
            await self.test_page(url, name)

    async def test_dashboard_pages(self):
        """测试仪表板页面"""
        print("\n=== 测试仪表板 ===")

        dashboard_pages = [
            ("/dashboard/", "主仪表板"),
            ("/api/dashboard/positions/", "持仓列表API"),
        ]

        for url, name in dashboard_pages:
            await self.test_page(url, name)

    async def test_policy_pages(self):
        """测试政策管理页面"""
        print("\n=== 测试政策管理 ===")

        policy_pages = [
            ("/policy/workbench/", "政策仪表板"),
            ("/policy/events/", "政策事件列表"),
            ("/policy/status/", "政策状态"),
            ("/policy/audit/queue/", "审计队列"),
            ("/policy/rss/sources/", "RSS管理"),
            ("/policy/rss/reader/", "RSS阅读器"),
        ]

        for url, name in policy_pages:
            await self.test_page(url, name)

    async def test_api_endpoints(self):
        """测试 API 端点"""
        print("\n=== 测试 API 端点 ===")

        api_endpoints = [
            ("/api/schema/", "OpenAPI Schema"),
            ("/api/docs/", "Swagger UI"),
            ("/api/account/profile/", "账户Profile API"),
            ("/api/account/portfolios/", "投资组合API"),
            ("/policy/api/events/", "政策事件API"),
            ("/api/dashboard/allocation/", "配置图表API"),
        ]

        for url, name in api_endpoints:
            await self.test_page(url, name, need_login=False)

    async def test_business_modules(self):
        """测试业务模块页面"""
        print("\n=== 测试业务模块 ===")

        module_pages = [
            ("/backtest/", "回测模块"),
            ("/regime/", "Regime分析"),
            ("/macro/", "宏观数据"),
            ("/filter/", "过滤器"),
            ("/signal/", "投资信号"),
            ("/audit/", "审计模块"),
            ("/asset-analysis/screen/", "资产筛选"),
            ("/simulated-trading/dashboard/", "模拟交易"),
        ]

        for url, name in module_pages:
            await self.test_page(url, name)

    async def analyze_results(self):
        """分析测试结果并生成改进建议"""
        print("\n=== 分析测试结果 ===")

        # 按响应时间分析
        slow_pages = [r for r in self.results if r.response_time > 3]
        if slow_pages:
            self.improvements.append(Improvement(
                category="Performance",
                priority="High",
                title="部分页面响应时间过长",
                description=f"发现 {len(slow_pages)} 个页面响应时间超过3秒",
                location=", ".join([f"{r.name}({r.response_time:.1f}s)" for r in slow_pages[:5]]),
                suggestion="检查数据库查询、添加缓存、优化N+1查询"
            ))

        # 按错误分析
        error_pages = [r for r in self.results if r.status == "error"]
        if error_pages:
            for ep in error_pages:
                self.improvements.append(Improvement(
                    category="Functionality",
                    priority="High",
                    title=f"页面错误: {ep.name}",
                    description=ep.error_message,
                    location=ep.url,
                    suggestion=f"检查错误日志: {ep.error_message}"
                ))

        # 按空内容分析
        empty_pages = [r for r in self.results if r.status == "warning"]
        if empty_pages:
            for ep in empty_pages:
                self.improvements.append(Improvement(
                    category="Functionality",
                    priority="Medium",
                    title=f"页面内容为空: {ep.name}",
                    description=ep.error_message,
                    location=ep.url,
                    suggestion="添加空状态提示或初始化数据"
                ))

    async def generate_report(self):
        """生成测试报告"""
        print("\n=== 生成测试报告 ===")

        # 统计数据
        total = len(self.results)
        success = len([r for r in self.results if r.status == "success"])
        errors = len([r for r in self.results if r.status == "error"])
        warnings = len([r for r in self.results if r.status == "warning"])

        # 生成 Markdown 报告
        report = f"""# AgomTradePro 项目测试报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 测试统计

- 总测试数: {total}
- 成功: {success} ({success/total*100:.1f}%)
- 错误: {errors} ({errors/total*100:.1f}%)
- 警告: {warnings} ({warnings/total*100:.1f}%)

## 详细测试结果

### 管理后台测试

| 页面 | 状态 | 响应时间 | 说明 |
|------|------|----------|------|
"""

        # 按模块分组结果
        for result in self.results:
            status_emoji = {"success": "✅", "error": "❌", "warning": "⚠️"}.get(result.status, "❓")
            report += f"| {result.name} | {status_emoji} {result.status} | {result.response_time:.2f}s | {result.error_message or '正常'} |\n"

        # 改进建议
        report += """

## 改进建议

### 按优先级分组

#### 高优先级
"""

        high_priority = [i for i in self.improvements if i.priority == "High"]
        if high_priority:
            for imp in high_priority:
                report += f"""
- **{imp.title}**
  - 类别: {imp.category}
  - 位置: {imp.location}
  - 描述: {imp.description}
  - 建议: {imp.suggestion}
"""
        else:
            report += "\n无高优先级改进项\n"

        report += "\n#### 中优先级\n"
        medium_priority = [i for i in self.improvements if i.priority == "Medium"]
        if medium_priority:
            for imp in medium_priority:
                report += f"""
- **{imp.title}**
  - 类别: {imp.category}
  - 位置: {imp.location}
  - 描述: {imp.description}
  - 建议: {imp.suggestion}
"""
        else:
            report += "\n无中优先级改进项\n"

        report += "\n#### 低优先级\n"
        low_priority = [i for i in self.improvements if i.priority == "Low"]
        if low_priority:
            for imp in low_priority:
                report += f"""
- **{imp.title}**
  - 类别: {imp.category}
  - 位置: {imp.location}
  - 描述: {imp.description}
  - 建议: {imp.suggestion}
"""
        else:
            report += "\n无低优先级改进项\n"

        # 详细错误日志
        if errors > 0:
            report += "\n## 错误详情\n\n```\n"
            for r in self.results:
                if r.status == "error":
                    report += f"\n### {r.name}\n"
                    report += f"URL: {r.url}\n"
                    report += f"错误: {r.error_message}\n"
                    report += f"详情: {json.dumps(r.details, indent=2, ensure_ascii=False)}\n"
            report += "\n```\n"

        # 保存报告
        with open("docs/test_report.md", "w", encoding="utf-8") as f:
            f.write(report)

        # 保存 JSON 结果
        json_results = [{
            "url": r.url,
            "name": r.name,
            "status": r.status,
            "response_time": r.response_time,
            "error_message": r.error_message,
            "details": r.details
        } for r in self.results]

        with open("docs/test_results.json", "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "summary": {"total": total, "success": success, "errors": errors, "warnings": warnings},
                "results": json_results,
                "improvements": [{
                    "category": i.category,
                    "priority": i.priority,
                    "title": i.title,
                    "description": i.description,
                    "location": i.location,
                    "suggestion": i.suggestion
                } for i in self.improvements]
            }, f, indent=2, ensure_ascii=False)

        print("报告已保存到 docs/test_report.md")
        print("详细数据已保存到 docs/test_results.json")

        return report

    async def run_full_test(self):
        """运行完整测试"""
        print("开始 AgomTradePro 项目全面测试...")

        # 创建截图目录
        import os
        os.makedirs("screenshots", exist_ok=True)
        os.makedirs("docs", exist_ok=True)

        await self.setup()

        # 登录
        print("\n=== 登录系统 ===")
        if not await self.login():
            print("登录失败，部分需要登录的页面可能无法访问")
        else:
            print("登录成功")

        # 运行测试
        await self.test_admin_pages()
        await self.test_dashboard_pages()
        await self.test_policy_pages()
        await self.test_api_endpoints()
        await self.test_business_modules()

        # 分析结果
        await self.analyze_results()

        # 生成报告
        report = await self.generate_report()

        await self.teardown()

        # 打印摘要
        print("\n" + "="*50)
        print("测试完成！")
        print("="*50)
        print(report)

        return self.results, self.improvements


async def main():
    """主函数"""
    tester = AgomTradeProBrowserTest(base_url="http://localhost:8000")
    await tester.run_full_test()


if __name__ == "__main__":
    asyncio.run(main())


