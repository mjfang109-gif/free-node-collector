import yaml
from pathlib import Path

def generate_clash(proxies):
    template = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies[:300],  # 限制数量
        "proxy-groups": [
            {"name": "🚀 自动选择", "type": "select", "proxies": [p["name"] for p in proxies[:300]]},
            {"name": "🇺🇸 美国", "type": "select", "proxies": [p["name"] for p in proxies if "US" in str(p.get("name", ""))]},
        ],
        "rules": ["MATCH,🚀 自动选择"]
    }
    Path("dist").mkdir(exist_ok=True)
    with open("dist/clash.yaml", "w", encoding="utf-8") as f:
        yaml.dump(template, f, allow_unicode=True, sort_keys=False)
    print("✅ Clash 订阅生成完成 → dist/clash.yaml")