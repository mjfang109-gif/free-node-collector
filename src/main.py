"""
main.py - Free-Node-Collector 主入口
"""

import asyncio
import base64
import json
import sys
import re
from pathlib import Path

_src_dir = Path(__file__).parent.resolve()
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from logger import setup_logger
from config import load_all_sources, get_dist_dir
from collectors import TelegramWebCollector
from parsers.v2ray_parser import parse_vless_link, parse_trojan_link, parse_vmess_link
from parsers.ss_parser import parse_ss_link
from parsers.hy2_parser import parse_hy2_link
from parsers.clash_parser import parse_clash
from testers.speed_tester import speed_test_all, CLASH_SPEEDTEST_BIN
from generators import generate_all_subscriptions
from utils import get_country_info_from_name, clean_node_name

logger = setup_logger()

_SS_VALID_CIPHERS = {
    "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
    "aes-128-cfb", "aes-256-cfb", "chacha20-ietf",
    "xchacha20-ietf-poly1305", "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
}

# 已知的协议前缀
_PROTOCOL_PREFIXES = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hy2://")


def _parse_proxy_line(line: str):
    """单行解析代理链接。"""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if line.startswith('vless://'):
        return parse_vless_link(line)
    if line.startswith('trojan://'):
        return parse_trojan_link(line)
    if line.startswith('ss://'):
        return parse_ss_link(line)
    if line.startswith('hy2://') or line.startswith('hysteria2://'):
        return parse_hy2_link(line)
    if line.startswith('vmess://'):
        return parse_vmess_link(line)
    return None


def _try_base64_decode(content: str):
    """尝试 Base64 解码。"""
    stripped = content.strip()
    # 排除已经结构化的格式
    if stripped.startswith(('<', '{', '[', 'proxies:', 'rules:')):
        return None
    try:
        cleaned = stripped.replace('\n', '').replace('\r', '').replace(' ', '')
        if not re.match(r'^[A-Za-z0-9+/=_-]+$', cleaned[:100]):
            return None
        decoded = base64.b64decode(cleaned + "==").decode("utf-8", errors="ignore")
        lines = decoded.splitlines()
        valid_lines = [l for l in lines if any(l.strip().startswith(p) for p in _PROTOCOL_PREFIXES)]
        if valid_lines:
            return lines
        return None
    except Exception:
        return None


def universal_parser(content: str, source_type: str = None) -> list:
    """通用解析器：根据内容类型自动选择解析方式。"""
    if not content:
        return []

    # Clash YAML 格式
    if source_type == 'clash':
        return parse_clash(content)

    proxies = []

    # 检查是否是链接列表格式
    if any(line.strip().startswith(_PROTOCOL_PREFIXES) for line in content.splitlines()[:20]):
        lines_to_parse = content.splitlines()
    else:
        # 尝试 Base64 解码
        decoded_lines = _try_base64_decode(content)
        lines_to_parse = decoded_lines if decoded_lines is not None else content.splitlines()

    for line in lines_to_parse:
        proxy = _parse_proxy_line(line)
        if proxy:
            proxies.append(proxy)

    return proxies


def _proxy_fingerprint(p: dict) -> str:
    """节点唯一指纹：type + server + port + 凭证前 16 字符。"""
    ptype = str(p.get("type", "")).lower()
    server = str(p.get("server", "")).lower()
    port = str(p.get("port", ""))
    cred = str(p.get("uuid") or p.get("password") or "")[:16]
    return f"{ptype}:{server}:{port}:{cred}"


def _is_valid_for_testing(p: dict) -> bool:
    """静态预过滤：丢弃 100% 无效的节点。"""
    server = p.get("server", "")
    port = p.get("port")
    ptype = str(p.get("type", "")).lower()

    if not server or not isinstance(port, int) or not (1 <= port <= 65535):
        return False
    # 过滤内网/保留地址
    if any(server.startswith(pfx) for pfx in (
            "127.", "0.0.0.0", "localhost", "::1",
            "10.", "192.168.",
            *(f"172.{i}." for i in range(16, 32)),
    )):
        return False
    if ptype in ("vmess", "vless") and not p.get("uuid"):
        return False
    if ptype in ("trojan", "hy2", "hysteria2") and not p.get("password"):
        return False
    if ptype == "ss":
        if not p.get("password"):
            return False
        if str(p.get("cipher", "")).lower() not in _SS_VALID_CIPHERS:
            return False
    return True


def generate_top_nodes_json(proxies: list, top_n: int = 20):
    """写入 top_nodes.json 供外部工具消费。"""
    if not proxies:
        return
    nodes = [
        {
            "protocol": p.get("type", "N/A"),
            "location": get_country_info_from_name(p.get("name", ""))[0],
            "ip": p.get("server", "N/A"),
            "port": p.get("port", 0),
            "latency_ms": p.get("latency", 9999),
            "speed_mbps": p.get("speed_mbps", 0),
            "name": p.get("name", "N/A"),
        }
        for p in proxies[:top_n]
    ]
    out = get_dist_dir() / "top_nodes.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ top_nodes.json → {out}")


async def main():
    logger.info("🚀 Free-Node-Collector 启动")

    if CLASH_SPEEDTEST_BIN:
        logger.info(f"✅ clash-speedtest: {CLASH_SPEEDTEST_BIN}")
    else:
        logger.warning("⚠️ clash-speedtest 未就绪，将使用 TCP/TLS 降级模式。")

    # ── 1. 加载信源 ───────────────────────────────────────────
    sources = load_all_sources()
    if not sources:
        logger.critical("❌ 未加载任何信源，退出。")
        return
    logger.info(f"📋 已加载 {len(sources)} 个信源")

    # ── 2. 采集 + 解析 + 去重 ─────────────────────────────────
    tg_collector = TelegramWebCollector()
    all_proxies: list[dict] = []
    seen: set[str] = set()

    for i, source in enumerate(sources, 1):
        name = source.get("name", "未知")
        logger.info(f"🔍 [{i}/{len(sources)}] {name}")

        data = tg_collector.fetch(source)
        if not data or not data.get("content"):
            logger.info("  ↳ 内容为空，跳过")
            continue

        proxies = universal_parser(data["content"], source_type=source.get("type"))
        if not proxies:
            logger.info("  ↳ 未解析到节点")
            continue

        added = 0
        for p in proxies:
            fp = _proxy_fingerprint(p)
            if fp not in seen:
                seen.add(fp)
                all_proxies.append(p)
                added += 1

        logger.info(f"  ↳ 解析 {len(proxies)} 个，新增 {added} 个（共 {len(all_proxies)} 个）")

    logger.info(f"✅ 采集完毕，共 {len(all_proxies)} 个不重复节点")

    # ── 3. 静态预过滤 ─────────────────────────────────────────
    filtered = [p for p in all_proxies if _is_valid_for_testing(p)]
    logger.info(
        f"🧹 预过滤：保留 {len(filtered)} 个"
        f"（丢弃 {len(all_proxies) - len(filtered)} 个无效节点）"
    )
    if not filtered:
        logger.critical("❌ 预过滤后无节点，退出。")
        return

    # ── 4. 净化节点名称 ───────────────────────────────────────
    for p in filtered:
        p["name"] = clean_node_name(p)

    # ── 5. 两阶段测速 ─────────────────────────────────────────
    sorted_proxies = await speed_test_all(
        filtered,
        top_n=50,
        phase1_workers=200,
        phase1_timeout=2.5,
        phase1_keep=600,
        max_latency_ms=3000,
        min_speed_mbps=0.3,
        test_timeout_s=10,
        concurrent=4,
        fallback_workers=100,
        fallback_latency_threshold=3000,
    )

    # ── 6. 生成订阅文件 ───────────────────────────────────────
    if sorted_proxies:
        logger.info(
            f"🎉 {len(sorted_proxies)} 个节点通过验证 | "
            f"最快：{sorted_proxies[0].get('latency')}ms  "
            f"最慢：{sorted_proxies[-1].get('latency')}ms"
        )
        generate_top_nodes_json(sorted_proxies, top_n=50)
        generate_all_subscriptions(sorted_proxies, top_n=50)
    else:
        logger.warning(
            "🤷 无节点通过测速。排查方向：\n"
            "   1. 检查 clash-speedtest 是否正确安装\n"
            "   2. 检查 Actions 网络能否访问外网\n"
            "   3. 适当调高 max_latency_ms 或调低 min_speed_mbps"
        )

    logger.info("🎊 完成！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 用户中断。")
    except Exception as e:
        logger.critical(f"💥 异常退出：{e}", exc_info=True)
