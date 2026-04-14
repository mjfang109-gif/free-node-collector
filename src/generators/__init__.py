import logging
from pathlib import Path
from .clash_generator import generate_clash_subscription
from .v2ray_generator import generate_v2ray_subscription
from .per_type_generator import generate_per_type_subscriptions

logger = logging.getLogger(__name__)

def generate_all_subscriptions(proxies: list):
    """
    生成所有类型的订阅文件。
    这是总入口，会调用其他具体的生成器模块。

    :param proxies: 经过测速和排序的代理字典列表。
    """
    if not proxies:
        logger.warning("🤷‍♂️ 没有可用的节点来生成任何订阅文件。")
        return

    logger.info("🚀 开始生成订阅文件...")

    # 确保 dist 目录存在
    dist_dir = Path(__file__).parent.parent.parent / "dist" # 确保路径正确
    dist_dir.mkdir(exist_ok=True)

    # 1. 生成统一的 Clash 订阅
    generate_clash_subscription(proxies, dist_dir)

    # 2. 生成统一的 V2Ray (Base64) 订阅
    generate_v2ray_subscription(proxies, dist_dir)

    # 3. 按节点类型生成独立的订阅文件
    generate_per_type_subscriptions(proxies, dist_dir)

    logger.info("✅ 所有订阅文件均已生成完毕！")
