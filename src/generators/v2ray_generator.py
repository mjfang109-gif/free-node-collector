import base64
import json
import logging
from pathlib import Path
from parsers.v2ray_parser import proxy_to_v2ray_link

logger = logging.getLogger(__name__)

def generate_v2ray_subscription(proxies: list, dist_dir: Path):
    """
    生成统一的 V2Ray 订阅文件 (Base64 编码)。
    包含所有可以通过 v2ray_parser 转换的节点类型。

    :param proxies: 代理字典列表。
    :param dist_dir: 输出目录的 Path 对象。
    """
    if not proxies:
        logger.warning("V2Ray 生成器：没有可用的节点。")
        return

    links = [proxy_to_v2ray_link(p) for p in proxies if proxy_to_v2ray_link(p) is not None]
    
    if not links:
        logger.warning("V2Ray 生成器：没有可转换的节点来生成订阅。")
        return

    content = "\n".join(links)
    encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    
    file_path = dist_dir / "v2ray_sub.txt"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(encoded_content)
        logger.info(f"✅ V2Ray 订阅生成完成 → {file_path}")
    except Exception as e:
        logger.error(f"❌ 生成 V2Ray 订阅文件失败: {e}", exc_info=True)
