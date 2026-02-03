import requests
import json

url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
params = {
    "reportName": "RPT_ECONOMY_PMI",
    "columns": "ALL",
    "pageNumber": 1,
    "pageSize": 50,
    "sortColumns": "REPORT_DATE",
    "sortTypes": "-1"
}

headers = {
    "User-Agent": "Mozilla/5.0"
}

r = requests.get(url, params=params, headers=headers)
print("Status:", r.status_code)
data = r.json()
print("Success:", data.get("success"))

if data.get("result"):
    result = data["result"]
    if "data" in result:
        print("Data count:", len(result["data"]))
        if result["data"]:
            print("Sample data:", json.dumps(result["data"][0], ensure_ascii=False, indent=2))
