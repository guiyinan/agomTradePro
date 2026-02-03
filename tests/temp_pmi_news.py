"""
使用 Playwright 抓取国家统计局 PMI 新闻发布页面
国家统计局每月发布的 PMI 新闻稿通常包含分项数据
"""
import asyncio
import json
import re
from playwright.async_api import async_playwright
from datetime import datetime

# NBS PMI 新闻页面URL（最新的PMI发布页面）
NBS_PMI_NEWS_URL = "http://www.stats.gov.cn/sj/zxfb/202502/t20250207_1954758.html"

async def fetch_pmi_from_news_page():
    """
    使用 Playwright 抓取 PMI 新闻发布页面
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            print(f"访问页面: {NBS_PMI_NEWS_URL}")
            await page.goto(NBS_PMI_NEWS_URL, wait_until="networkidle", timeout=30000)

            # 获取页面文本内容
            content = await page.inner_text("body")

            # 查找PMI分项数据的模式
            patterns = {
                "新订单指数": r"新订单指数[为：]*\s*(\d+\.?\d*)%",
                "产成品库存指数": r"产成品库存指数[为：]*\s*(\d+\.?\d*)%",
                "原材料库存指数": r"原材料库存指数[为：]*\s*(\d+\.?\d*)%",
                "采购量指数": r"采购量指数[为：]*\s*(\d+\.?\d*)%",
                "生产指数": r"生产指数[为：]*\s*(\d+\.?\d*)%",
            }

            pmi_data = {}
            for name, pattern in patterns.items():
                match = re.search(pattern, content)
                if match:
                    value = float(match.group(1))
                    pmi_data[name] = value
                    print(f"找到 {name}: {value}")

            # 保存原始内容
            with open("pmi_news_content.txt", "w", encoding="utf-8") as f:
                f.write(content)

            print(f"\n解析到的 PMI 数据:")
            print(json.dumps(pmi_data, ensure_ascii=False, indent=2))

            # 也尝试提取发布日期
            date_match = re.search(r"(\d{4})年(\d{1,2})月", content)
            if date_match:
                year = date_match.group(1)
                month = date_match.group(2).zfill(2)
                pmi_data["发布日期"] = f"{year}-{month}"
                print(f"发布日期: {pmi_data['发布日期']}")

            return pmi_data

        finally:
            await browser.close()

async def fetch_pmi_list_pages():
    """
    获取PMI新闻列表页面，找到历史数据
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 访问国家统计局搜索页面
            search_url = "http://www.stats.gov.cn/search/index?keywords=%E9%87%87%E4%B8%9A%E7%BB%8F%E7%90%86%E6%8C%87%E6%95%B0"
            print(f"搜索PMI相关页面: {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            # 等待搜索结果
            await page.wait_for_timeout(3000)

            # 获取搜索结果链接
            links = await page.query_selector_all("a[href*='t2']")
            print(f"找到 {len(links)} 个PMI相关链接")

            pmi_urls = []
            for link in links[:10]:  # 只取前10个
                href = await link.get_attribute("href")
                text = await link.inner_text()
                if href and ("PMI" in text or "采购经理" in text):
                    if href.startswith("/"):
                        href = "http://www.stats.gov.cn" + href
                    pmi_urls.append({"url": href, "title": text})
                    print(f"  - {text}: {href}")

            # 保存URL列表
            with open("pmi_urls.json", "w", encoding="utf-8") as f:
                json.dump(pmi_urls, f, ensure_ascii=False, indent=2)

            return pmi_urls

        finally:
            await browser.close()

if __name__ == "__main__":
    print("=== 抓取最新PMI新闻页面 ===")
    data = asyncio.run(fetch_pmi_from_news_page())

    print("\n=== 获取PMI历史页面列表 ===")
    urls = asyncio.run(fetch_pmi_list_pages())
