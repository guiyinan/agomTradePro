"""
使用 Playwright 抓取国家统计局 PMI 分项数据
"""
import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

# NBS PMI data page URL
NBS_PMI_URL = "http://www.stats.gov.cn/sj/zxfb/202502/t20250207_1954758.html"

async def fetch_pmi_subitems():
    """
    使用 Playwright 抓取国家统计局 PMI 分项数据
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 访问 NBS PMI 页面
            await page.goto(NBS_PMI_URL, wait_until="networkidle", timeout=30000)

            # 等待页面加载
            await page.wait_for_selector("table", timeout=10000)

            # 提取表格数据
            tables = await page.query_selector_all("table")

            pmi_data = []

            for table in tables:
                rows = await table.query_selector_all("tr")
                for row in rows:
                    cells = await row.query_selector_all("td, th")
                    if cells:
                        row_data = []
                        for cell in cells:
                            text = await cell.inner_text()
                            row_data.append(text.strip())
                        if row_data:
                            pmi_data.append(row_data)

            print("PMI Data found:")
            print(json.dumps(pmi_data, ensure_ascii=False, indent=2))

            # 保存到文件
            with open("pmi_data.json", "w", encoding="utf-8") as f:
                json.dump(pmi_data, f, ensure_ascii=False, indent=2)

            print(f"\nData saved to pmi_data.json")
            return pmi_data

        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(fetch_pmi_subitems())
