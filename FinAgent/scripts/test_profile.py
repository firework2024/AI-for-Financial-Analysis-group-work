import json
import sys

sys.path.insert(0, "FinAgent")
from finagent.chat.eastmoney_profile import fetch_eastmoney_profile

p = fetch_eastmoney_profile("300274")
print(json.dumps({k: p[k] for k in p if k != "company"}, ensure_ascii=False, indent=2, default=str)[:6000])
print("\n--- summary ---\n", p.get("summary_text", "")[:1500])
