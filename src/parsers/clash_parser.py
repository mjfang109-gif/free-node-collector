import yaml
import logging

logger = logging.getLogger(__name__)

def parse_clash(content: str):
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict) or "proxies" not in data:
            return []
        proxies = data.get("proxies", [])
        if not isinstance(proxies, list):
            return []
        return proxies
    except (yaml.YAMLError, AttributeError) as e:
        logger.error(f"Clash 内容解析失败: {e}", exc_info=True)
        return []
