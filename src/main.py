"""
main.py - Free-Node-Collector 主入口

【本次优化说明】
1. 调整测速并发参数，适配 GitHub Actions 资源限制
2. 内核测试模式下，适当降低并发（每个节点启动子进程，并发过高会 OOM）
3. 增加更详细的进度日志，方便排查问题
4. 在本地开发环境自动尝试下载 mihomo，不依赖手动安装
"""

import asyncio
import json
import sys
from pathlib import Path

# 确保 src 目录在 sys.path 中（支持 python -m src.main 和直接运行两种方式）
_src_dir = Path(__file__).parent.resolve()
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from logger import setup_logger
from config import load_all_sources, get_dist_dir
from collectors import UnifiedCollector, TelegramWebCollector
from parsers import universal_parser
from testers.speed_tester import speed_test_all, CLASH_BINARY, _download_mihomo
from generators import generate_all_subscriptions
from utils import get_country_info_from_name, clean_node_name

logger = setup_logger()


def _is_valid_for_testing(p: dict) -> bool:
    """
    静态预过滤：淘汰明显不可用的节点，避免浪费测速资源。
    只过滤「100% 无效」的节点，不要过度过滤（内核测试会精确验证）。
    """
    server = p.get("server", "")
    port = p.get("port")
    ptype = str(p.get("type", "")).lower()

    # 基础：server/port 必须有效
    if not server or not isinstance(port, int) or not (1 <= port <= 65535):
        return False

    # 协议专项：缺少必要凭证直接丢弃
    if ptype in ("vmess", "vless") and not p.get("uuid"):
        return False
    if ptype in ("trojan", "hy2", "hysteria2") and not p.get("password"):
        return False
    if ptype == "ss":
        if not p.get("password"):
            return False
        # cipher 为 auto 会让 Clash 内核崩溃，提前拦截
        cipher = str(p.get("cipher", "")).lower()
        valid_ciphers = {
            "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
            "aes-128-cfb", "aes-256-cfb", "chacha20-ietf",
            "xchacha20-ietf-poly1305", "2022-blake3-aes-128-gcm",
            "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
        }
        if cipher not in valid_ciphers:
            return False

    return True


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

    # ── 1. 预检：确认内核状态 ─────────────────────────────────────
    if CLASH_BINARY:
        logger.info(f"✅ 内核就绪: {CLASH_BINARY}")
    else:
        logger.info("🔄 尝试下载 mihomo 内核...")
        binary = _download_mihomo()
        if binary:
            logger.info(f"✅ 内核下载成功: {binary}")
        else:
            logger.warning(
                "⚠️ 无法获取 mihomo 内核！\n"
                "   将降级使用 TCP 测试，生成的订阅可能包含不可用节点。\n"
                "   在 GitHub Actions 中请确认 collect-nodes.yml 已添加安装步骤。"
            )

    # ── 2. 加载信源 ───────────────────────────────────────────────
    sources = load_all_sources()
    if not sources:
        logger.critical("❌ 未加载到任何信源，程序退出。")
        return

    logger.info(f"📋 共加载 {len(sources)} 个信源")

    collector = UnifiedCollector()
    tg_web_collector = TelegramWebCollector()

    # ── 3. 抓取并解析节点 ─────────────────────────────────────────
    all_proxies: list[dict] = []
    seen_proxies: set[str] = set()

    for i, source in enumerate(sources, 1):
        source_name = source.get("name", "未知信源")
        logger.info(f"🔍 [{i}/{len(sources)}] 正在抓取: {source_name}")

        if source.get("type") == "telegram_web":
            content_data = tg_web_collector.fetch(source)
        else:
            content_data = collector.fetch(source)

        if not content_data or not content_data.get("content"):
            logger.info(f"  ↳ 抓取失败或内容为空，跳过")
            continue

        proxies = universal_parser(content_data["content"], source_type=source.get("type"))
        if not proxies:
            logger.info(f"  ↳ 未解析到任何节点")
            continue

        # 去重（以 server:port 为 key）
        new_count = 0
        for p in proxies:
            identifier = f'{p.get("server")}:{p.get("port")}'
            if identifier not in seen_proxies:
                seen_proxies.add(identifier)
                all_proxies.append(p)
                new_count += 1

        logger.info(f"  ↳ 解析到 {len(proxies)} 个节点，新增 {new_count} 个（去重后共 {len(all_proxies)} 个）")

    logger.info(f"✅ 全部信源处理完毕，共获得 {len(all_proxies)} 个不重复节点")

    # ── 4. 测速前基础过滤 ─────────────────────────────────────────
    logger.info("🧹 开始测速前预过滤...")
    filtered_proxies = [p for p in all_proxies if _is_valid_for_testing(p)]
    logger.info(
        f"预过滤结果：保留 {len(filtered_proxies)} 个"
        f"（丢弃 {len(all_proxies) - len(filtered_proxies)} 个明显无效节点）"
    )

    if not filtered_proxies:
        logger.critical("❌ 预过滤后无可用节点，程序退出。")
        return

    # ── 5. 净化节点名称 ───────────────────────────────────────────
    logger.info("🧼 开始净化节点名称...")
    for proxy in filtered_proxies:
        proxy["name"] = clean_node_name(proxy)

    # ── 6. 两阶段测速 ─────────────────────────────────────────────
    TOTAL_NODES_TO_KEEP = 200  # 最终保留的节点总数
    TOP_N_NODES = 20  # JSON 和 top 订阅的节点数

    # 内核测试并发数：每个节点启动一个 mihomo 子进程
    # GitHub Actions (2核4G) 建议 10-15，本地开发可调高
    KERNEL_WORKERS = 12
    TOTAL_TEST_TIMEOUT = 1200  # 20分钟总超时

    logger.info(
        f"⚡ 开始两阶段测速\n"
        f"   目标: 保留最优 {TOTAL_NODES_TO_KEEP} 个节点\n"
        f"   内核并发: {KERNEL_WORKERS}\n"
        f"   总超时: {TOTAL_TEST_TIMEOUT}s"
    )

    sorted_proxies = await speed_test_all(
        filtered_proxies,
        max_workers=KERNEL_WORKERS,
        top_n=TOTAL_NODES_TO_KEEP,
        total_timeout=TOTAL_TEST_TIMEOUT,
        latency_threshold=5000,  # 5秒内响应均视为可用
        phase1_workers=200,
        phase1_timeout=3,
        phase1_keep=500,  # 阶段一最多保留500个进入精确测试
    )

    # ── 7. 生成订阅文件 ───────────────────────────────────────────
    if sorted_proxies:
        logger.info(
            f"🎉 测速完成！{len(sorted_proxies)} 个节点通过验证\n"
            f"   最快: {sorted_proxies[0].get('latency')}ms ({sorted_proxies[0].get('name', '')})\n"
            f"   最慢: {sorted_proxies[-1].get('latency')}ms ({sorted_proxies[-1].get('name', '')})"
        )
        generate_top_nodes_json(sorted_proxies, top_n=TOP_N_NODES)
        generate_all_subscriptions(sorted_proxies, top_n=TOP_N_NODES)
    else:
        logger.warning(
            "🤷 没有任何节点通过测速，无法生成任何文件。\n"
            "   可能原因：\n"
            "   1. GitHub Actions 网络环境被限制（无法访问外网做 HTTP 测试）\n"
            "   2. 信源节点质量太差（大量节点失效）\n"
            "   3. mihomo 内核未正确安装\n"
            "   排查建议：检查 Actions 日志中的 [阶段二] 输出"
        )

    logger.info("🎊 全部任务完成！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 程序被用户手动中断。")
    except Exception as e:
        logger.critical(f"💥 程序因意外错误而终止: {e}", exc_info=True)
