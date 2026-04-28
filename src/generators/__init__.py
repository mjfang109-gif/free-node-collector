"""订阅生成器模块。"""

import base64
import logging
from pathlib import Path
from .clash_generator import generate_clash_subscription
from .v2ray_generator import generate_v2ray_subscription
from parsers.v2ray_parser import (
    proxy_to_vmess_link, proxy_to_vless_link, proxy_to_trojan_link
)
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


def generate_top50_v2ray(proxies: list, dist_dir: Path):
    """生成前 50 个节点的 V2Ray Base64 订阅。"""
    links = []
    for p in proxies[:50]:
        converter = PROXY_CONVERTERS.get(p.get("type"))
        if converter:
            link = converter(p)
            if link:
                links.append(link)
    if not links:
        logger.warning("⚠️ V2Ray 生成器：无可转换节点。")
        return
    encoded = base64.b64encode("\n".join(links).encode()).decode()
    file_path = dist_dir / "top50_v2ray.txt"
    file_path.write_text(encoded, encoding="utf-8")
    logger.info(f"✅ top50_v2ray.txt → {len(links)} 个节点")


def generate_all_subscriptions(proxies: list, top_n: int = 50):
    """生成所有订阅文件。"""
    if not proxies:
        logger.warning("⚠️ 没有可用节点来生成任何订阅文件。")
        return

    dist_dir = Path(__file__).parent.parent.parent / "dist"
    dist_dir.mkdir(exist_ok=True)

    logger.info("🚀 开始生成订阅文件...")

    # Top 50 Clash
    generate_clash_subscription(proxies[:top_n], dist_dir, filename="top50_clash.yaml", max_proxies=top_n)
    # Top 50 V2Ray
    generate_top50_v2ray(proxies, dist_dir)

    # 完整订阅
    generate_clash_subscription(proxies, dist_dir, filename="clash.yaml")
    generate_v2ray_subscription(proxies, dist_dir)

    logger.info("✅ 所有订阅文件生成完毕！")
