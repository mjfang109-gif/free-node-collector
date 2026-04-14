import asyncio
import json
from logger import setup_logger
from config import load_all_sources, get_dist_dir
from collectors import UnifiedCollector, TelegramWebCollector
from parsers import universal_parser
from testers.speed_tester import speed_test_all
from generators import generate_all_subscriptions
from utils import get_country_info_from_name, clean_node_name # 导入新函数

logger = setup_logger()

def generate_top_nodes_json(proxies: list, top_n: int = 20):
    """生成包含速度最快的前 N 个节点信息的 JSON 文件。"""
    if not proxies:
        logger.info("JSON 生成器：没有可用的节点。")
        return

    top_proxies = proxies[:top_n]
    nodes_info = [{
        "protocol": p.get("type", "N/A"),
        # 修正：如果 location 未知，则使用国家代码
        "location": get_country_info_from_name(p.get("name"))[0],
        "ip": p.get("server", "N/A"),
        "port": p.get("port", 0),
        "latency_ms": p.get("latency", 9999),
        "name": p.get("name", "N/A"), # name 字段现在是净化后的
    } for p in top_proxies]
    
    dist_dir = get_dist_dir()
    dist_dir.mkdir(exist_ok=True)
    file_path = dist_dir / "top_nodes.json"

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(nodes_info, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Top {top_n} 节点信息 JSON 生成完成 → {file_path}")
    except Exception as e:
        logger.error(f"❌ 生成 Top {top_n} JSON 文件失败: {e}", exc_info=True)


async def main():
    """主入口函数。"""
    logger.info("🚀 Free-Node-Collector 开始运行...")

    sources = load_all_sources()
    if not sources: return

    collector = UnifiedCollector()
    tg_web_collector = TelegramWebCollector()

    all_proxies = []
    seen_proxies = set()

    for source in sources:
        logger.info(f"🔍 正在抓取: {source.get('name', '未知信源')}")
        
        content_data = None
        source_type = source.get("type")

        if source_type == "telegram_web":
            content_data = tg_web_collector.fetch(source)
        else:
            content_data = collector.fetch(source)

        if not content_data or not content_data.get("content"): continue

        proxies = universal_parser(content_data["content"], source_type)
        if not proxies:
            logger.info(f"ℹ️ 在 {source.get('name')} 中未解析到任何有效节点。")
            continue
            
        logger.info(f"💡 从 {source.get('name')} 解析到 {len(proxies)} 个节点。")

        for p in proxies:
            identifier = f'{p.get("server")}:{p.get("port")}'
            if identifier not in seen_proxies:
                seen_proxies.add(identifier)
                all_proxies.append(p)

    logger.info(f"\n✅ 所有信源抓取和解析完成，共获得 {len(all_proxies)} 个不重复的节点。")

    # 净化所有节点的名称
    logger.info("🧼 开始净化所有节点名称...")
    for proxy in all_proxies:
        proxy["name"] = clean_node_name(proxy.get("name", ""))

    TOTAL_NODES_TO_KEEP = 200
    TOP_N_NODES = 20

    sorted_proxies = await speed_test_all(all_proxies, max_workers=100, top_n=TOTAL_NODES_TO_KEEP)

    if sorted_proxies:
        generate_top_nodes_json(sorted_proxies, top_n=TOP_N_NODES)
        generate_all_subscriptions(sorted_proxies, top_n=TOP_N_NODES)
    else:
        logger.warning("🤷‍♂️ 没有任何节点通过测速，无法生成任何文件。")

    logger.info("\n🎉 全部任务完成！祝您上网愉快！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 程序被用户手动中断。")
    except Exception as e:
        logger.critical(f"💥 程序因意外错误而终止: {e}", exc_info=True)
