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


def generate_per_type_subscriptions(proxies: list, dist_dir: Path):
    """
    按节点类型将节点分类，并为每种类型生成独立的 Base64 编码订阅文件。
    """
    logger.info("📦 正在按类型生成独立的订阅文件...")

    grouped_proxies: dict[str, list] = {}
    for proxy in proxies:
        proxy_type = proxy.get("type")
        if proxy_type in PROXY_CONVERTERS:
            grouped_proxies.setdefault(proxy_type, []).append(proxy)

    if not grouped_proxies:
        logger.info("ℹ️ 未发现可按类型分类的节点。")
        return

    for proxy_type, proxy_list in grouped_proxies.items():
        converter = PROXY_CONVERTERS[proxy_type]

        # 修复：每个节点只调用一次 converter，避免重复执行
        links = []
        for p in proxy_list:
            link = converter(p)
            if link is not None:
                links.append(link)

        if not links:
            continue

        encoded_content = base64.b64encode(
            "\n".join(links).encode("utf-8")
        ).decode("utf-8")

        file_path = dist_dir / f"{proxy_type.lower()}_sub.txt"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(encoded_content)
            logger.info(f"  - ✅ 成功生成 {proxy_type.upper()} 订阅: {file_path.name} ({len(links)} 个节点)")
        except Exception as e:
            logger.error(f"  - ❌ 生成 {proxy_type.upper()} 订阅失败: {e}", exc_info=True)
