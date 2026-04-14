from .base_collector import BaseCollector
import logging

logger = logging.getLogger(__name__)

class TelegramCollector(BaseCollector):
    """
    基于 Telegram API 的采集器（目前为占位符）。
    需要 Telegram API 密钥，在 GitHub Actions 环境中通常不适用。
    """
    def fetch(self, source: dict):
        source_name = source.get("name", "未知Telegram API信源")
        logger.info(f"[{source_name}] Telegram API 采集需要 API 密钥，目前暂跳过。")
        return None
