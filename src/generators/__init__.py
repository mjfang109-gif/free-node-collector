import logging
from pathlib import Path
from .clash_generator import generate_clash_subscription
from .v2ray_generator import generate_v2ray_subscription
from .per_type_generator import generate_per_type_subscriptions
from .top_nodes_generator import generate_top_nodes_subscription

logger = logging.getLogger(__name__)

def generate_all_subscriptions(proxies: list, top_n: int = 20):
    if not proxies:
        logger.warning("🤷 没有可用节点来生成任何订阅文件。")
        return

    logger.info("🚀 开始生成订阅文件...")
    dist_dir = Path(__file__).parent.parent.parent / "dist"
    dist_dir.mkdir(exist_ok=True)

    top_proxies = proxies[:top_n]

    # Top 20 订阅（Clash + V2Ray）
    generate_clash_subscription(top_proxies, dist_dir, filename="top20_clash.yaml", max_proxies=top_n)
    generate_top_nodes_subscription(top_proxies, dist_dir, filename="top20_v2ray.txt")

    # 完整订阅（Clash + V2Ray）
    generate_clash_subscription(proxies, dist_dir, filename="clash.yaml")
    generate_v2ray_subscription(proxies, dist_dir)

    # 按协议类型的独立订阅
    generate_per_type_subscriptions(proxies, dist_dir)

    logger.info("✅ 所有订阅文件均已生成完毕！")
