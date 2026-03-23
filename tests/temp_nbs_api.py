"""
使用 NBS API 获取 PMI 分项数据
"""
import json
from datetime import datetime

import requests

# NBS API endpoint
NBS_API_URL = "http://data.stats.gov.cn/easyquery.htm"

def fetch_pmi_subitems():
    """
    使用 NBS API 获取 PMI 分项数据
    """
    # NBS PMI 指标参数
    # 根据国家统计局数据分类，PMI 相关的指标代码
    params = {
        "cn": "E0103",  # 国民经济核算 -> 物价 -> 价格指数
        "zb": "A0304",  # 具体指标分类
        "sj": "202401"   # 时间段
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        r = requests.get(NBS_API_URL, params=params, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('Content-Type')}")
        print(f"Content length: {len(r.text)}")

        # 保存原始响应用于调试
        with open("nbs_response.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("Response saved to nbs_response.html")

        # 尝试解析为 JSON
        try:
            data = r.json()
            print("\nJSON Data:")
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except:
            print("\nNot a JSON response, checking for data patterns...")
            # 查找数据模式
            if "data" in r.text:
                print("Found 'data' in response")
            if "PMI" in r.text or "pmi" in r.text:
                print("Found 'PMI' in response")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fetch_pmi_subitems()
