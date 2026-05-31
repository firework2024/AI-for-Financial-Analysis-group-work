import json
import time
import requests

H = {"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
code = "SZ300274"
secid = "0.300274"

def get(name, url, params):
    time.sleep(1)
    r = requests.get(url, params=params, headers=H, timeout=15)
    data = r.json()
    with open(f"FinAgent/scripts/em_{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(name, r.status_code, list(data.keys()) if isinstance(data, dict) else type(data))

get(
    "finance",
    "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/MainTargetAjax",
    {"code": code},
)
get(
    "survey",
    "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
    {"code": code},
)
get(
    "spot_all",
    "https://push2.eastmoney.com/api/qt/stock/get",
    {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f84,f85,f116,f117,f152,f153,f161,f162,f167,f168,f169,f170,f171,f177,f178,f260,f261,f19,f20,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40",
        "ut": "fa5fd1943c7b386f172d7ef921b690b2",
        "invt": 2,
        "fltt": 2,
    },
)
