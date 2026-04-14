import requests
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class BaseCollector(ABC):
    """采集器的抽象基类，定义了所有采集器都必须实现的接口。"""
    @abstractmethod
    def fetch(self, source: dict):
        """
        根据给定的信源信息抓取内容。

        :param source: 包含信源信息的字典，至少应有 'name' 和 'url'。
        :return: 一个包含 'name', 'type', 'content' 的字典，或在失败时返回 None。
        """
        pass


class WebCollector(BaseCollector):
    """通用的网页内容采集器，通过 HTTP GET 请求获取内容。"""
    def fetch(self, source: dict):
        source_name = source.get("name", "未知网页信源")
        url = source.get("url")
        if not url:
            logger.warning(f"[{source_name}] 缺少 'url' 字段，无法抓取。")
            return None
            
        try:
            # 设置合理的超时和 User-Agent
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"}
            r = requests.get(url, timeout=30, headers=headers)
            r.raise_for_status()  # 如果状态码不是 2xx，则抛出异常
            
            # 返回包含信源名称、类型和内容的标准字典
            return {
                "name": source_name,
                "type": source.get("type"),
                "content": r.text.strip()
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"[{source_name}] 抓取失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[{source_name}] 处理时发生未知错误: {e}", exc_info=True)
            return None
