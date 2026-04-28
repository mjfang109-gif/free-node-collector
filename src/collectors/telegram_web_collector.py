import re
import requests
from .base_collector import BaseCollector
import logging

logger = logging.getLogger(__name__)

class TelegramWebCollector(BaseCollector):
    def fetch(self, source: dict):
        source_name = source.get("name", "未知Telegram信源")
        url = source.get("url")
        if not url:
            logger.warning(f"[{source_name}] 缺少 'url' 字段，无法抓取。")
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            patterns = [
                r'(vmess://[^\s<"]+)', r'(vless://[^\s<"]+)',
                r'(trojan://[^\s<"]+)', r'(ss://[^\s<"]+)',
                r'(ssr://[^\s<"]+)',    r'(hy2://[^\s<"]+)',
            ]
            all_links = []
            for pattern in patterns:
                all_links.extend(re.findall(pattern, r.text, re.IGNORECASE))
            unique_links = list(dict.fromkeys(all_links))
            if unique_links:
                logger.info(f"[{source_name}] 抓取到 {len(unique_links)} 个节点链接。")
                return {"name": source_name, "type": "v2ray_base64", "content": "\n".join(unique_links)}
            else:
                logger.info(f"[{source_name}] 未发现节点链接。")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[{source_name}] 抓取失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[{source_name}] 未知错误: {e}", exc_info=True)
            return None
