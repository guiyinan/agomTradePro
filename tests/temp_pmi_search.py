"""
使用 Playwright 搜索并抓取 PMI 分项数据
"""
import asyncio
import json
import re

from playwright.async_api import async_playwright


async def search_and_scrape_pmi():
    """
    搜索并抓取 PMI 数据
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # 使用非无头模式以便调试
        page = await browser.new_page()

        try:
            # 先访问国家统计局首页
            print("访问国家统计局首页...")
            await page.goto("http://www.stats.gov.cn/", wait_until="networkidle", timeout=30000)

            # 使用搜索功能
            search_box = await page.query_selector("input[name='keywords'], input[type='search'], #keyword")
            if search_box:
                await search_box.fill("PMI 采购经理指数")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)

                # 获取搜索结果
                current_url = page.url
                print(f"搜索页面URL: {current_url}")

                # 获取搜索结果
                results = await page.query_selector_all("a")
                print(f"找到 {len(results)} 个链接")

                pmi_links = []
                for result in results:
                    text = await result.inner_text()
                    href = await result.get_attribute("href")
                    if "PMI" in text or "采购经理" in text:
                        if href:
                            if href.startswith("/"):
                                href = "http://www.stats.gov.cn" + href
                            pmi_links.append({"title": text, "url": href})
                            print(f"找到: {text} -> {href}")

                # 保存结果
                with open("pmi_search_results.json", "w", encoding="utf-8") as f:
                    json.dump(pmi_links, f, ensure_ascii=False, indent=2)

                print(f"\n共找到 {len(pmi_links)} 个PMI相关链接")

                # 尝试访问第一个链接
                if pmi_links:
                    print(f"\n访问第一个链接: {pmi_links[0]['url']}")
                    await page.goto(pmi_links[0]['url'], wait_until="networkidle", timeout=30000)

                    # 获取页面内容
                    content = await page.inner_text("body")

                    # 保存内容
                    with open("pmi_first_page.txt", "w", encoding="utf-8") as f:
                        f.write(content)

                    print(f"页面内容已保存，长度: {len(content)}")

                    # 查找PMI分项数据
                    patterns = {
                        "新订单指数": r"新订单指数[^。\d]*(\d+\.?\d*)",
                        "生产指数": r"生产指数[^。\d]*(\d+\.?\d*)",
                        "产成品库存": r"产成品库存[^。\d]*(\d+\.?\d*)",
                        "原材料库存": r"原材料库存[^。\d]*(\d+\.?\d*)",
                        "采购量": r"采购量[^。\d]*(\d+\.?\d*)",
                    }

                    found_data = {}
                    for name, pattern in patterns.items():
                        match = re.search(pattern, content)
                        if match:
                            found_data[name] = match.group(1)
                            print(f"找到 {name}: {match.group(1)}")

                    print(f"\n解析到的数据: {json.dumps(found_data, ensure_ascii=False)}")

        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(search_and_scrape_pmi())
