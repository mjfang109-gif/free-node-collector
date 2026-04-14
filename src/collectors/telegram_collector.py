from .base_collector import BaseCollector

class TelegramCollector(BaseCollector):
    def fetch(self, source):
        print(f"[{source['name']}] Telegram 采集需要 API 密钥，暂跳过（Actions 环境不支持）")
        return None