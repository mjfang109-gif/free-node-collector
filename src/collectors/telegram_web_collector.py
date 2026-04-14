import re
import requests
from .base_collector import BaseCollector
import logging

logger = logging.getLogger(__name__)

class TelegramWebCollector(BaseCollector):
    """
    专门用于从 Telegram 公开频道的网页版 (t.me/s/...) 抓取节点链接的采集器。
    """
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
            html = r.text

            # 使用正则表达式一次性提取所有类型的节点链接
            # 增加了对 hy2 的支持
            patterns = [
                r'(vmess://[^\s<"]+)',
                r'(vless://[^\s<"]+)',
                r'(trojan://[^\s<"]+)',
                r'(ss://[^\s<"]+)',
                r'(ssr://[^\s<"]+)',
                r'(hy2://[^\s<"]+)'
            ]
            
            all_links = []
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                all_links.extend(matches)

            # 使用字典来去重，保持原始顺序
            unique_links = list(dict.fromkeys(all_links))
            
            if unique_links:
                logger.info(f"[{source_name}] 从 Telegram 网页抓取到 {len(unique_links)} 个节点链接。")
                # 将所有链接合并成一个字符串，交由通用解析器处理
                return {
                    "name": source_name,
                    "type": "v2ray_base64", # 实际上是链接列表，但可以复用 v2ray_base64 的解析逻辑
                    "content": "\n".join(unique_links)
                }
            else:
                logger.info(f"[{source_name}] 未在 Telegram 网页中发现任何节点链接。")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"[{source_name}] Telegram 网页抓取失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[{source_name}] 处理时发生未知错误: {e}", exc_info=True)
            return None
