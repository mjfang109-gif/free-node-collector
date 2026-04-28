"""
speed_tester.py - 基于 clash-speedtest 的节点测速模块（重构版）

【架构】
  阶段一  高并发 TCP 存活探测 → 剔除完全不通的死节点
  阶段二  clash-speedtest 真实下载测速 → 验证代理功能 + 过滤延迟/速度
          （无 clash-speedtest 时降级为 TLS/TCP 连通性检测）

【clash-speedtest 核心优势】
  - 内置协议栈与 Mihomo 同源（Go 原生实现），无需额外子进程
  - 真实下载文件（默认 50MB），比 generate_204 更准确
  - 单二进制，零进程冲突、零 mmdb 锁竞争
  - 直接输出筛选后的 Clash YAML，无需二次处理
  - 安装：go install github.com/faceair/clash-speedtest@latest
"""

import asyncio
import logging
import re
import shutil
import ssl
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ══════════════════════════════════════════════════════════════
#  clash-speedtest 二进制查找
# ══════════════════════════════════════════════════════════════

def _find_clash_speedtest() -> Optional[str]:
    """按优先级查找 clash-speedtest 二进制"""
    # 1. 系统 PATH
    p = shutil.which("clash-speedtest")
    if p:
        return p
    # 2. Go 默认安装路径（GitHub Actions 中 go install 的目标）
    candidates = [
        Path.home() / "go" / "bin" / "clash-speedtest",
        Path("/root/go/bin/clash-speedtest"),
        Path("/usr/local/go/bin/clash-speedtest"),
        Path("/home/runner/go/bin/clash-speedtest"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


CLASH_SPEEDTEST_BIN = _find_clash_speedtest()

if CLASH_SPEEDTEST_BIN:
    logger.info(f"✅ clash-speedtest 就绪: {CLASH_SPEEDTEST_BIN}")
else:
    logger.warning(
        "⚠️ 未找到 clash-speedtest，将降级为 TCP/TLS 测试模式。\n"
        "   安装: go install github.com/faceair/clash-speedtest@latest\n"
        "   或在 collect-nodes.yml 中添加安装步骤（见配套文件）。"
    )


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

async def _tcp_connect(host: str, port: int, timeout: float) -> int:
    """TCP 连通性探测，返回延迟 ms，失败返回 9999"""
    start = time.time()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await asyncio.shield(writer.wait_closed())
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


async def _tls_connect(host: str, port: int, sni: str, timeout: float) -> int:
    """TLS 握手探测，返回延迟 ms，失败返回 9999"""
    start = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout,
        )
        writer.close()
        await asyncio.shield(writer.wait_closed())
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


# ══════════════════════════════════════════════════════════════
#  阶段一：TCP 快速预过滤
# ══════════════════════════════════════════════════════════════

async def phase1_tcp_prefilter(
        proxies: list,
        max_workers: int = 200,
        timeout: float = 2.5,
        keep_top_n: int = 600,
) -> list:
    """
    高并发 TCP 存活探测，剔除完全不通的死节点。
    目的是减少后续 clash-speedtest 的测速量，不是精确筛选。
    """
    logger.info(
        f"⚡ [阶段一] TCP 存活探测 {len(proxies)} 个节点"
        f"（并发: {max_workers}，超时: {timeout}s）"
    )
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            server = p.get("server", "")
            port = p.get("port")
            if not server or not isinstance(port, int) or not (1 <= port <= 65535):
                return p, 9999
            return p, await _tcp_connect(server, port, timeout)

    raw = await asyncio.gather(*[_check(p) for p in proxies], return_exceptions=True)

    results = [
        (p, lat) for res in raw
        if isinstance(res, tuple)
        for p, lat in [res]
        if lat != 9999
    ]
    results.sort(key=lambda x: x[1])
    survivors = [p for p, _ in results[:keep_top_n]]

    logger.info(
        f"[阶段一] TCP 可达 {len(results)}/{len(proxies)} 个，"
        f"保留最优 {len(survivors)} 个进入精确测速"
    )
    return survivors


# ══════════════════════════════════════════════════════════════
#  阶段二A：clash-speedtest 真实下载测速（主路径）
# ══════════════════════════════════════════════════════════════

def _build_clash_yaml_for_speedtest(proxies: list) -> tuple[str, dict]:
    """
    生成供 clash-speedtest 读取的最小化 Clash YAML。
    节点名用 node_XXXXX 索引编码，彻底避免 emoji / 特殊字符 / 重名问题。
    返回 (yaml_string, {index_name: original_proxy})
    """
    clean_proxies = []
    index_map: dict[str, dict] = {}

    for i, proxy in enumerate(proxies):
        p = dict(proxy)
        idx_name = f"node_{i:05d}"
        p["name"] = idx_name
        index_map[idx_name] = proxy
        clean_proxies.append(p)

    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "global",
        "log-level": "silent",
        "proxies": clean_proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select",
             "proxies": [p["name"] for p in clean_proxies]}
        ],
        "rules": ["MATCH,PROXY"],
    }
    return yaml.dump(config, allow_unicode=True, sort_keys=False), index_map


def _parse_speedtest_output(output_yaml_path: Path, index_map: dict) -> list:
    """
    解析 clash-speedtest 输出的 YAML，将索引名映射回原始节点，
    并附加 latency / speed_mbps 字段。
    """
    try:
        with open(output_yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"读取 clash-speedtest 输出失败: {e}")
        return []

    raw_proxies = data.get("proxies", []) if isinstance(data, dict) else []
    if not raw_proxies:
        return []

    result = []
    for fp in raw_proxies:
        idx_name = fp.get("name", "")
        original = index_map.get(idx_name)

        # 从节点名或字段中提取延迟和速度
        # clash-speedtest 不同版本输出字段名略有不同，全部尝试
        latency = _try_extract_int(fp, ["latency", "delay", "rtt"])
        speed = _try_extract_speed(fp, idx_name)

        # 节点名格式：有些版本会改写为 "node_00001 ↑ 2.50MB/s"
        if latency == 9999:
            m = re.search(r'(\d+)\s*ms', idx_name)
            if m:
                latency = int(m.group(1))

        node = dict(original) if original else dict(fp)
        node["latency"] = latency
        if speed > 0:
            node["speed_mbps"] = speed
        result.append(node)

    result.sort(key=lambda p: p.get("latency", 9999))
    return result


def _try_extract_int(d: dict, keys: list, default: int = 9999) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return default


def _try_extract_speed(d: dict, name: str = "") -> float:
    for k in ("speed", "download_speed", "bandwidth"):
        v = d.get(k)
        if isinstance(v, (int, float)) and v > 0:
            # 如果单位是字节，转换为 MB/s
            return round(v / 1_048_576 if v > 10_000 else v, 2)
    # 从名称字符串解析
    m = re.search(r'([\d.]+)\s*MB/s', name, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)\s*KB/s', name, re.I)
    if m:
        return round(float(m.group(1)) / 1024, 2)
    return 0.0


def run_clash_speedtest(
        proxies: list,
        max_latency_ms: int = 3000,
        min_speed_mbps: float = 0.3,
        timeout_s: int = 10,
        concurrent: int = 4,
        speed_mode: str = "fast",
        bin_path: Optional[str] = None,
) -> list:
    """
    调用 clash-speedtest 对节点列表做真实下载测速。

    参数说明：
        max_latency_ms  延迟超过此值的节点被丢弃（建议免费节点用 3000）
        min_speed_mbps  下载速度低于此值的节点被丢弃（免费节点建议 0.3）
        timeout_s       单节点测速超时秒数
        concurrent      下载并发连接数（4 是准确性和速度的平衡点）
        speed_mode      fast=仅延迟, download=下载速度, full=上下行均测
    """
    bin_path = bin_path or CLASH_SPEEDTEST_BIN
    if not bin_path:
        raise RuntimeError("clash-speedtest 未找到，请先安装。")
    if not proxies:
        return []

    logger.info(
        f"🚀 [clash-speedtest] 测速 {len(proxies)} 个节点\n"
        f"   延迟 ≤ {max_latency_ms}ms  速度 ≥ {min_speed_mbps}MB/s  "
        f"模式: {speed_mode}  单节点超时: {timeout_s}s"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_yaml = tmp / "input.yaml"
        output_yaml = tmp / "filtered.yaml"

        yaml_content, index_map = _build_clash_yaml_for_speedtest(proxies)
        input_yaml.write_text(yaml_content, encoding="utf-8")

        cmd = [
            bin_path,
            "-c", str(input_yaml),
            "-output", str(output_yaml),
            "-max-latency", f"{max_latency_ms}ms",
            "-min-speed", str(min_speed_mbps),
            "-timeout", f"{timeout_s}s",
            "-concurrent", str(concurrent),
            "-speed-mode", speed_mode,
        ]

        logger.info(f"   CMD: {' '.join(cmd)}")

        # 动态超时：每节点最多 timeout_s 秒 × 数量，再加 2 分钟缓冲
        total_timeout = len(proxies) * timeout_s + 120

        try:
            subprocess.run(cmd, timeout=total_timeout)
        except subprocess.TimeoutExpired:
            logger.error("❌ clash-speedtest 超时，使用已完成部分结果")
        except FileNotFoundError:
            logger.error(f"❌ 找不到二进制: {bin_path}")
            return []
        except Exception as e:
            logger.error(f"❌ clash-speedtest 异常: {e}")
            return []

        if not output_yaml.exists():
            logger.warning("⚠️ clash-speedtest 未生成输出（可能节点全部不可用）")
            return []

        result = _parse_speedtest_output(output_yaml, index_map)

    logger.info(
        f"✅ [clash-speedtest] 通过: {len(result)}/{len(proxies)} 个"
        + (
            f"\n   最快: {result[0].get('latency', '?')}ms"
            + (f" @ {result[0].get('speed_mbps', '?')}MB/s" if result[0].get("speed_mbps") else "")
            + f"  |  最慢: {result[-1].get('latency', '?')}ms"
            if result else ""
        )
    )
    return result


# ══════════════════════════════════════════════════════════════
#  阶段二B：TCP/TLS 降级测速（无 clash-speedtest 时的兜底）
# ══════════════════════════════════════════════════════════════

async def phase2_fallback_test(
        proxies: list,
        max_workers: int = 100,
        timeout: float = 5.0,
        latency_threshold: int = 3000,
) -> list:
    """
    降级方案：TLS/TCP 连通性测试。
    只验证端口是否能连通，不能保证代理功能正常。
    仅在无法安装 clash-speedtest 的环境下使用。
    """
    logger.warning(
        f"⚠️ [降级] TLS/TCP 测试 {len(proxies)} 个节点\n"
        "   此模式只验证连通性，无法保证代理真实可用！\n"
        "   强烈建议安装 clash-speedtest 以获得准确结果。"
    )
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            server = p.get("server", "")
            port = p.get("port")
            ptype = str(p.get("type", "")).lower()
            if not server or not isinstance(port, int):
                return p, 9999
            if ptype in ("vless", "trojan", "hy2", "hysteria2") or p.get("tls"):
                sni = p.get("sni") or p.get("servername") or server
                lat = await _tls_connect(server, port, sni, timeout)
            else:
                lat = await _tcp_connect(server, port, timeout)
            return p, lat

    raw = await asyncio.gather(*[_check(p) for p in proxies], return_exceptions=True)

    valid = []
    for res in raw:
        if isinstance(res, tuple):
            p, lat = res
            if 0 < lat <= latency_threshold:
                node = dict(p)
                node["latency"] = lat
                valid.append(node)

    valid.sort(key=lambda x: x.get("latency", 9999))
    logger.info(f"[降级] 可达: {len(valid)}/{len(proxies)} 个")
    return valid


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════

async def speed_test_all(
        proxies: list,
        top_n: int = 200,
        # 阶段一
        phase1_workers: int = 200,
        phase1_timeout: float = 2.5,
        phase1_keep: int = 600,
        # 阶段二（clash-speedtest）
        max_latency_ms: int = 3000,
        min_speed_mbps: float = 0.3,
        test_timeout_s: int = 10,
        speed_mode: str = "fast",
        concurrent: int = 4,
        # 降级参数
        fallback_workers: int = 100,
        fallback_latency_threshold: int = 3000,
        # 兼容旧参数（忽略）
        **kwargs,
) -> list:
    """
    完整两阶段测速。

    speed_mode 选择建议：
      "fast"     只测延迟，速度最快，适合节点量 > 300 时
      "download" 测延迟 + 下载速度，筛选更准确（推荐日常使用）
      "full"     全测，最慢但最准确

    min_speed_mbps 建议值：
      免费节点质量参差不齐，0.3 MB/s 是合理下限
      如果想要高质量节点，可以调到 1.0 或更高
    """
    if not proxies:
        return []

    mode = "clash-speedtest ✅" if CLASH_SPEEDTEST_BIN else "TCP/TLS 降级 ⚠️"
    logger.info(f"🔬 测速模式: {mode}  总节点: {len(proxies)}")

    # ── 阶段一 ────────────────────────────────────────────────
    survivors = await phase1_tcp_prefilter(
        proxies,
        max_workers=phase1_workers,
        timeout=phase1_timeout,
        keep_top_n=phase1_keep,
    )
    if not survivors:
        logger.warning("❌ 阶段一后无存活节点。")
        return []

    # ── 阶段二 ────────────────────────────────────────────────
    if CLASH_SPEEDTEST_BIN:
        # clash-speedtest 是同步阻塞调用，放入线程池避免阻塞事件循环
        loop = asyncio.get_event_loop()
        valid = await loop.run_in_executor(
            None,
            lambda: run_clash_speedtest(
                survivors,
                max_latency_ms=max_latency_ms,
                min_speed_mbps=min_speed_mbps,
                timeout_s=test_timeout_s,
                concurrent=concurrent,
                speed_mode=speed_mode,
            ),
        )
    else:
        valid = await phase2_fallback_test(
            survivors,
            max_workers=fallback_workers,
            timeout=float(test_timeout_s),
            latency_threshold=fallback_latency_threshold,
        )

    result = valid[:top_n]
    if result:
        logger.info(
            f"🎉 最终保留 {len(result)} 个节点 | "
            f"最快 {result[0].get('latency', '?')}ms  最慢 {result[-1].get('latency', '?')}ms"
        )
    else:
        logger.warning("⚠️ 无节点通过筛选。")
    return result