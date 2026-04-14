"""
main.py - Free-Node-Collector 主入口

【优化说明】
1. 移除"丢弃未知地区节点"的过滤逻辑（原来会把大量可用节点丢掉）
2. 测速前只做基础合法性过滤（有 server+port 即可参与测速）
3. 地区识别失败不影响节点进入测速，只影响地区分组显示
4. 在生成 Clash 订阅时由 clash_generator 的 _sanitize_proxy 做精确清洗
"""

import asyncio
import json
from logger import setup_logger
from config import load_all_sources, get_dist_dir
from collectors import UnifiedCollector, TelegramWebCollector
from parsers import universal_parser
from testers.speed_tester import speed_test_all
from generators import generate_all_subscriptions
from utils import get_country_info_from_name, clean_node_name

logger = setup_logger()


def generate_top_nodes_json(proxies: list, top_n: int = 20):
    """将 top N 节点信息写入 JSON 文件，供 ffmg/render.py 使用。"""
    if not proxies:
        logger.info("JSON 生成器：没有可用的节点。")
        return

    top_proxies = proxies[:top_n]
    nodes_info = [
        {
            "protocol": p.get("type", "N/A"),
            "location": get_country_info_from_name(p.get("name", ""))[0],
            "ip": p.get("server", "N/A"),
            "port": p.get("port", 0),
            "latency_ms": p.get("latency", 9999),
            "name": p.get("name", "N/A"),
        }
        for p in top_proxies
    ]

    dist_dir = get_dist_dir()
    dist_dir.mkdir(exist_ok=True)
    file_path = dist_dir / "top_nodes.json"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(nodes_info, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Top {top_n} 节点 JSON 生成完成 → {file_path}")
    except Exception as e:
        logger.error(f"❌ 生成 JSON 文件失败: {e}", exc_info=True)


async def main():
    """主入口函数。"""
    logger.info("🚀 Free-Node-Collector 开始运行...")

    # ── 1. 加载信源 ───────────────────────────────────────────────
    sources = load_all_sources()
    if not sources:
        logger.critical("❌ 未加载到任何信源，程序退出。")
        return

    collector = UnifiedCollector()
    tg_web_collector = TelegramWebCollector()

    # ── 2. 抓取并解析节点 ─────────────────────────────────────────
    all_proxies: list[dict] = []
    seen_proxies: set[str] = set()

    for source in sources:
        source_name = source.get("name", "未知信源")
        logger.info(f"🔍 正在抓取: {source_name}")

        if source.get("type") == "telegram_web":
            content_data = tg_web_collector.fetch(source)
        else:
            content_data = collector.fetch(source)

        if not content_data or not content_data.get("content"):
            continue

        proxies = universal_parser(content_data["content"], source_type=source.get("type"))
        if not proxies:
            logger.info(f"ℹ️ [{source_name}] 未解析到任何有效节点。")
            continue

        logger.info(f"💡 [{source_name}] 解析到 {len(proxies)} 个节点。")

        # 去重（以 server:port 为 key）
        for p in proxies:
            identifier = f'{p.get("server")}:{p.get("port")}'
            if identifier not in seen_proxies:
                seen_proxies.add(identifier)
                all_proxies.append(p)

    logger.info(f"✅ 全部信源处理完毕，共获得 {len(all_proxies)} 个不重复节点。")

    # ── 3. 测速前基础过滤 ─────────────────────────────────────────
    logger.info("🧹 开始测速前基础过滤（仅校验 server/port 必填字段）...")
    filtered_proxies = [
        p for p in all_proxies
        if p.get("server") and isinstance(p.get("port"), int)
    ]
    removed = len(all_proxies) - len(filtered_proxies)
    logger.info(f"过滤结果：保留 {len(filtered_proxies)} 个节点（丢弃 {removed} 个无效节点）。")

    # ── 4. 净化节点名称 ───────────────────────────────────────────
    logger.info("🧼 开始净化节点名称...")
    for proxy in filtered_proxies:
        proxy["name"] = clean_node_name(proxy)

    # ── 5. 测速 ───────────────────────────────────────────────────
    TOTAL_NODES_TO_KEEP = 200
    TOP_N_NODES = 20

    logger.info(f"⚡ 开始测速（目标：保留最优 {TOTAL_NODES_TO_KEEP} 个节点）...")
    sorted_proxies = await speed_test_all(
        filtered_proxies,
        max_workers=30,  # 修正：为内核模式设置一个更保守的并发数
        top_n=TOTAL_NODES_TO_KEEP,
        batch_size=200,
        total_timeout=900,
        latency_threshold=3000,
    )

    # ── 6. 生成订阅文件 ───────────────────────────────────────────
    if sorted_proxies:
        logger.info(f"🎉 测速完成，{len(sorted_proxies)} 个节点通过验证，开始生成订阅...")
        generate_top_nodes_json(sorted_proxies, top_n=TOP_N_NODES)
        generate_all_subscriptions(sorted_proxies, top_n=TOP_N_NODES)
    else:
        logger.warning("🤷‍ 没有任何节点通过测速，无法生成任何文件。")
        logger.warning("   请检查：1) 网络连通性  2) 信源节点质量  3) 测速超时设置")

    logger.info("🎊 全部任务完成！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 程序被用户手动中断。")
    except Exception as e:
        logger.critical(f"💥 程序因意外错误而终止: {e}", exc_info=True)
