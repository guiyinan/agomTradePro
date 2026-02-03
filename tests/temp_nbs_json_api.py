"""
使用 NBS JSON API 获取 PMI 分项数据
"""
import requests
import json
from datetime import datetime

# NBS JSON API endpoint
NBS_API_URL = "http://data.stats.gov.cn/easyquery.htm"

def fetch_pmi_subitems():
    """
    使用 NBS JSON API 获取 PMI 分项数据
    """
    # 尝试不同的参数组合
    params_list = [
        # 尝试1: 月度数据查询
        {
            "m": "QueryData",
            "dbcode": "hgyd",  # 宏观月度
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",  # 筛选条件
            "sort": 1
        },
        # 尝试2: 制造业PMI
        {
            "m": "QueryData",
            "dbcode": "hgyd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": '[{"wdcode":"zb","valuecode":"A0304"}]',  # PMI指标
            "sort": 1
        },
        # 尝试3: 获取PMI相关指标列表
        {
            "m": "GetNodeData",
            "dbcode": "hgyd",
            "parentcode": "A0303",  # 尝试获取PMI分类下的指标
        }
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://data.stats.gov.cn/easyquery.htm?cn=A01"
    }

    for i, params in enumerate(params_list):
        print(f"\n=== 尝试 {i+1} ===")
        print(f"参数: {json.dumps(params, ensure_ascii=False)}")

        try:
            r = requests.get(NBS_API_URL, params=params, headers=headers, timeout=30)
            print(f"Status: {r.status_code}")

            if r.status_code == 200:
                # 尝试解析为 JSON
                try:
                    data = r.json()
                    print(f"成功获取 JSON 数据!")
                    print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

                    # 保存完整数据
                    with open(f"nbs_api_result_{i+1}.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"数据已保存到 nbs_api_result_{i+1}.json")

                    if data.get("result") or data.get("returndata"):
                        print("\n找到有效数据！")
                        return data

                except Exception as e:
                    print(f"JSON解析失败: {e}")
                    print(f"响应内容: {r.text[:500]}")

        except Exception as e:
            print(f"请求失败: {e}")

if __name__ == "__main__":
    fetch_pmi_subitems()
