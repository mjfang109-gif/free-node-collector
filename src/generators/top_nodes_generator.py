import base64
import logging
from pathlib import Path
# 修正：使用从 src 目录开始的绝对导入
from parsers.v2ray_parser import proxy_to_vmess_link, proxy_to_vless_link, proxy_to_trojan_link
from parsers.ss_parser import proxy_to_ss_link
from parsers.hy2_parser import proxy_to_hy2_link

logger = logging.getLogger(__name__)

PROXY_CONVERTERS = {
    "vmess": proxy_to_vmess_link,
    "vless": proxy_to_vless_link,
    "trojan": proxy_to_trojan_link,
    "ss": proxy_to_ss_link,
    "hy2": proxy_to_hy2_link,
}

def generate_top_nodes_subscription(proxies: list, dist_dir: Path, filename: str = "top20_v2ray.txt"):
    """
    为给定的节点列表生成一个统一的 Base64 编码的 V2Ray 格式订阅链接。
    """
    if not proxies:
        logger.warning(f"Top V2Ray 生成器：没有可用的节点来生成 {filename}。")
        return

    links = []
    for proxy in proxies:
        proxy_type = proxy.get("type")
        if proxy_type in PROXY_CONVERTERS:
            converter = PROXY_CONVERTERS[proxy_type]
            link = converter(proxy)
            if link:
                links.append(link)
    
    if not links:
        logger.warning(f"Top V2Ray 生成器：没有可转换的节点来生成 {filename}。")
        return

    content = "\n".join(links)
    encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    
    file_path = dist_dir / filename
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(encoded_content)
        logger.info(f"✅ Top V2Ray 订阅生成完成 → {file_path.name}")
    except Exception as e:
        logger.error(f"❌ 生成 Top V2Ray 订阅文件 {filename} 失败: {e}", exc_info=True)
