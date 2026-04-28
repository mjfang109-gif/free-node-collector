import requests
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class BaseCollector(ABC):
    @abstractmethod
    def fetch(self, source: dict):
        pass

class WebCollector(BaseCollector):
    def fetch(self, source: dict):
        source_name = source.get("name", "未知网页信源")
        url = source.get("url")
        if not url:
            logger.warning(f"[{source_name}] 缺少 'url' 字段，无法抓取。")
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, timeout=30, headers=headers)
            r.raise_for_status()
            return {"name": source_name, "type": source.get("type"), "content": r.text.strip()}
        except requests.exceptions.RequestException as e:
            logger.error(f"[{source_name}] 抓取失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[{source_name}] 未知错误: {e}", exc_info=True)
            return None
