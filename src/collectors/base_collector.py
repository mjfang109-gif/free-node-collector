import requests
from abc import ABC, abstractmethod


class BaseCollector(ABC):
    @abstractmethod
    def fetch(self, source):
        pass


class WebCollector(BaseCollector):
    def fetch(self, source):
        try:
            r = requests.get(source["url"], timeout=30)
            r.raise_for_status()
            return {"name": source["name"], "type": source["type"], "content": r.text.strip()}
        except Exception as e:
            print(f"[{source['name']}] 抓取失败: {e}")
            return None
