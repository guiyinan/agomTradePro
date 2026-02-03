"""
使用正确的 NBS JSON API 获取 PMI 分项数据
"""
import requests
import json

# NBS JSON API endpoint
NBS_API_URL = "http://data.stats.gov.cn/easyquery.htm"

def test_nbs_api():
    """
    测试不同的 NBS API 参数
    """
    # 根据AKShare源码，NBS使用的数据库名称
    # dbcode 应该是 'hgnd' (宏观数据) 或类似
    params_list = [
        # 尝试1: 查询所有PMI相关指标
        {
            "m": "QueryData",
            "dbcode": "hgnd",  # 宏观数据
            "rowcode": "zb",
            "colcode": "sj",
            "wds": '[]',
            "sort": 1
        },
        # 尝试2: 使用月份代码查询
        {
            "m": "QueryData",
            "dbcode": "hgnd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": '[{"wdcode":"sj","valuecode":"202411"}]',
            "sort": 1
        },
        # 尝试3: GetTreeData - 获取指标树
        {
            "m": "GetTreeData",
            "dbcode": "hgnd",
            "treeid": "A0304",
            "selfid": ""
        }
    ]

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.stats.gov.cn/"
    }

    for i, params in enumerate(params_list):
        print(f"\n=== 尝试 {i+1}: {params.get('m')} ===")

        try:
            r = requests.get(NBS_API_URL, params=params, headers=headers, timeout=30)
            print(f"Status: {r.status_code}")

            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"JSON 响应成功!")

                    # 检查返回的数据结构
                    if isinstance(data, dict):
                        if data.get("returndata"):
                            print(f"找到 returndata，包含 {len(data['returndata'])} 条记录")
                            # 显示前几条
                            for item in data['returndata'][:3]:
                                print(f"  - {item}")

                        if data.get("nodes"):
                            print(f"找到 nodes，包含 {len(data['nodes'])} 个节点")
                            for node in data['nodes'][:5]:
                                print(f"  - {node}")

                        # 保存完整响应
                        with open(f"nbs_result_{i+1}.json", "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        print(f"已保存到 nbs_result_{i+1}.json")

                except Exception as e:
                    print(f"JSON解析失败: {e}")
                    print(f"响应前500字符: {r.text[:500]}")
        except Exception as e:
            print(f"请求失败: {e}")

if __name__ == "__main__":
    test_nbs_api()
