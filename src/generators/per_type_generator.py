import base64
import logging
from pathlib import Path
# 修正：导入所有需要的、具体的转换器函数
from parsers.v2ray_parser import proxy_to_vmess_link, proxy_to_vless_link, proxy_to_trojan_link
from parsers.ss_parser import proxy_to_ss_link
from parsers.hy2_parser import proxy_to_hy2_link

logger = logging.getLogger(__name__)

# 定义一个包含所有转换器的映射
PROXY_CONVERTERS = {
    "vmess": proxy_to_vmess_link,
    "vless": proxy_to_vless_link,
    "trojan": proxy_to_trojan_link,
    "ss": proxy_to_ss_link,
    "hy2": proxy_to_hy2_link,
}

def generate_per_type_subscriptions(proxies: list, dist_dir: Path):
    """
    按节点类型将节点分类，并为每种类型生成独立的 Base64 编码的订阅文件。
    """
    logger.info("📦 正在按类型生成独立的订阅文件...")

    grouped_proxies = {}
    for proxy in proxies:
        proxy_type = proxy.get("type")
        if proxy_type in PROXY_CONVERTERS:
            if proxy_type not in grouped_proxies:
                grouped_proxies[proxy_type] = []
            grouped_proxies[proxy_type].append(proxy)

    if not grouped_proxies:
        logger.info("ℹ️ 未发现可按类型分类的节点。")
        return

    for proxy_type, proxy_list in grouped_proxies.items():
        # 根据节点类型查找对应的转换器
        converter = PROXY_CONVERTERS[proxy_type]
        links = [converter(p) for p in proxy_list if converter(p) is not None]
        
        if not links:
            continue

        content = "\n".join(links)
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        
        file_path = dist_dir / f"{proxy_type.lower()}_sub.txt"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(encoded_content)
            logger.info(f"  - ✅ 成功生成 {proxy_type.upper()} 订阅: {file_path.name}")
        except Exception as e:
            logger.error(f"  - ❌ 生成 {proxy_type.upper()} 订阅失败: {e}", exc_info=True)
