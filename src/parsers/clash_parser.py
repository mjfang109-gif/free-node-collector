import yaml
import logging

logger = logging.getLogger(__name__)

def parse_clash(content: str):
    """
    解析 Clash 配置文件内容，提取其中的代理节点。

    :param content: Clash 配置文件的文本内容。
    :return: 一个包含代理字典的列表。
    """
    try:
        data = yaml.safe_load(content)
        
        if not isinstance(data, dict) or "proxies" not in data:
            logger.debug("Clash 内容解析：未找到 'proxies' 字段或内容非字典格式。")
            return []
            
        proxies = data.get("proxies", [])
        
        if not isinstance(proxies, list):
            logger.warning("Clash 内容解析：'proxies' 字段不是一个列表。")
            return []

        return proxies
        
    except (yaml.YAMLError, AttributeError) as e:
        logger.error(f"Clash 内容解析失败: {e}", exc_info=True)
        return []
