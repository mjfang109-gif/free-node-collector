import re
import requests
from .base_collector import BaseCollector


class TelegramWebCollector(BaseCollector):
    def fetch(self, source):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(source["url"], headers=headers, timeout=30)
            r.raise_for_status()
            html = r.text

            # 正则提取所有节点配置链接（vmess:// vless:// trojan:// ss:// 等）
            patterns = [
                r'(vmess://[^\s<"]+)',
                r'(vless://[^\s<"]+)',
                r'(trojan://[^\s<"]+)',
                r'(ss://[^\s<"]+)',
                r'(ssr://[^\s<"]+)'
            ]
            configs = []
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                configs.extend(matches)

            configs = list(dict.fromkeys(configs))  # 去重
            print(f"[{source['name']}] 从 Telegram 网页抓取到 {len(configs)} 个节点")
            return {"name": source["name"], "type": "v2ray_base64", "content": "\n".join(configs)}
        except Exception as e:
            print(f"[{source['name']}] Telegram 网页抓取失败: {e}")
            return None
