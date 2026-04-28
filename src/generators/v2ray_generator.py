import base64
import logging
from pathlib import Path
from parsers.v2ray_parser import proxy_to_vmess_link, proxy_to_vless_link, proxy_to_trojan_link
from parsers.ss_parser import proxy_to_ss_link
from parsers.hy2_parser import proxy_to_hy2_link

logger = logging.getLogger(__name__)

PROXY_CONVERTERS = {
    "vmess":  proxy_to_vmess_link,
    "vless":  proxy_to_vless_link,
    "trojan": proxy_to_trojan_link,
    "ss":     proxy_to_ss_link,
    "hy2":    proxy_to_hy2_link,
}

def generate_v2ray_subscription(proxies: list, dist_dir: Path, filename: str = "v2ray.txt"):
    if not proxies:
        logger.warning(f"V2Ray 生成器：没有可用节点来生成 {filename}。")
        return
    links = []
    for proxy in proxies:
        converter = PROXY_CONVERTERS.get(proxy.get("type"))
        if converter:
            link = converter(proxy)
            if link:
                links.append(link)
    if not links:
        logger.warning(f"V2Ray 生成器：没有可转换的节点。")
        return
    encoded = base64.b64encode("\n".join(links).encode("utf-8")).decode("utf-8")
    file_path = dist_dir / filename
    try:
        file_path.write_text(encoded, encoding="utf-8")
        logger.info(f"✅ V2Ray 订阅生成完成（{len(links)} 个节点）→ {file_path.name}")
    except Exception as e:
        logger.error(f"❌ 生成 {filename} 失败: {e}", exc_info=True)
