"""
speed_tester.py - 基于 clash-speedtest 的节点测速模块

【架构】
  阶段一  高并发 TCP 存活探测 → 剔除完全不通的死节点
  阶段二  clash-speedtest 真实下载测速 → 验证代理功能 + 过滤延迟/速度
          （无 clash-speedtest 时降级为 TLS/TCP 连通性检测）

【已修复问题】
  - 移除了不存在的 -speed-mode 参数（会导致 clash-speedtest 报错退出）
  - subprocess.run 增加 capture_output，错误日志可见
  - 喂给 clash-speedtest 的 proxy dict 预先清洗，移除 mihomo 无法识别的字段
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
    """按优先级查找 clash-speedtest 二进制。"""
    p = shutil.which("clash-speedtest")
    if p:
        return p
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
        "   安装: go install github.com/faceair/clash-speedtest@latest"
    )


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

async def _tcp_connect(host: str, port: int, timeout: float) -> int:
    """TCP 连通性探测，返回延迟 ms，失败返回 9999。"""
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
    """TLS 握手探测，返回延迟 ms，失败返回 9999。"""
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
#  代理字段清洗（喂给 clash-speedtest 前调用）
# ══════════════════════════════════════════════════════════════

# 各协议 mihomo 认识的字段白名单
_ALLOWED_FOR_TEST = {
    "ss":       {"name", "type", "server", "port", "cipher", "password", "udp", "plugin", "plugin-opts"},
    "vmess":    {"name", "type", "server", "port", "uuid", "alterId", "cipher",
                 "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
                 "http-opts", "grpc-opts", "servername", "udp"},
    "vless":    {"name", "type", "server", "port", "uuid", "flow",
                 "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
                 "reality-opts", "servername", "sni", "udp"},
    "trojan":   {"name", "type", "server", "port", "password",
                 "tls", "skip-cert-verify", "sni", "network", "ws-opts", "grpc-opts", "udp"},
    "hy2":      {"name", "type", "server", "port", "password",
                 "sni", "skip-cert-verify", "obfs", "obfs-password",
                 "fingerprint", "alpn", "cwnd", "udp"},
    "hysteria2": {"name", "type", "server", "port", "password",
                  "sni", "skip-cert-verify", "obfs", "obfs-password",
                  "fingerprint", "alpn", "cwnd", "udp"},
}

_SS_VALID_CIPHERS = {
    "aes-128-gcm", "aes-256-gcm", "aes-128-cfb", "aes-256-cfb",
    "aes-128-ctr", "aes-192-ctr", "aes-256-ctr",
    "rc4-md5", "chacha20", "chacha20-ietf",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
}


def _sanitize_for_speedtest(proxy: dict) -> Optional[dict]:
    """
    清洗 proxy dict，确保能被 mihomo/clash-speedtest 正确解析。
    返回 None 表示该节点应被跳过。
    """
    p = dict(proxy)
    ptype = str(p.get("type", "")).lower()

    # 统一 hysteria2 → hy2
    if ptype == "hysteria2":
        p["type"] = "hy2"
        ptype = "hy2"

    # SS：非法 cipher 直接跳过
    if ptype == "ss":
        cipher = str(p.get("cipher", "")).lower().strip()
        if cipher not in _SS_VALID_CIPHERS:
            return None

    # VMess：修正 alterId 类型
    if ptype == "vmess":
        p["alterId"] = int(p.get("alterId") or 0)

    # 字段白名单过滤
    allowed = _ALLOWED_FOR_TEST.get(ptype)
    if allowed:
        p = {k: v for k, v in p.items() if k in allowed and v is not None}
    else:
        p = {k: v for k, v in p.items() if v is not None}

    # 清理 ws-opts 中的空字段
    if "ws-opts" in p and isinstance(p["ws-opts"], dict):
        p["ws-opts"] = {k: v for k, v in p["ws-opts"].items() if v}
        if not p["ws-opts"]:
            del p["ws-opts"]

    return p if p.get("server") and isinstance(p.get("port"), int) else None


# ══════════════════════════════════════════════════════════════
#  阶段一：TCP 快速预过滤
# ══════════════════════════════════════════════════════════════

async def phase1_tcp_prefilter(
        proxies: list,
        max_workers: int = 200,
        timeout: float = 2.5,
        keep_top_n: int = 600,
) -> list:
    """高并发 TCP 存活探测，剔除完全不通的死节点。"""
    logger.info(
        f"⚡ [阶段一] TCP 存活探测 {len(proxies)} 个节点"
        f"（并发: {max_workers}，超时: {timeout}s）"
    )
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            server = p.get("server", "")
            port   = p.get("port")
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
#  阶段二A：clash-speedtest 真实下载测速
# ══════════════════════════════════════════════════════════════

def _build_clash_yaml_for_speedtest(proxies: list) -> tuple[str, dict]:
    """
    生成供 clash-speedtest 读取的最小化 Clash YAML。
    节点名用索引编码，彻底避免 emoji / 特殊字符 / 重名问题。
    返回 (yaml_string, {index_name: original_proxy})
    """
    clean_proxies = []
    index_map: dict[str, dict] = {}

    for i, proxy in enumerate(proxies):
        sanitized = _sanitize_for_speedtest(proxy)
        if sanitized is None:
            continue
        idx_name = f"node_{i:05d}"
        sanitized["name"] = idx_name
        index_map[idx_name] = proxy   # 保留原始 proxy，含 name 等信息
        clean_proxies.append(sanitized)

    config = {
        "mixed-port": 7890,
        "allow-lan":  False,
        "mode":       "global",
        "log-level":  "silent",
        "proxies":    clean_proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select",
             "proxies": [p["name"] for p in clean_proxies]}
        ],
        "rules": ["MATCH,PROXY"],
    }
    return yaml.dump(config, allow_unicode=True, sort_keys=False), index_map


def _parse_speedtest_output(output_yaml_path: Path, index_map: dict) -> list:
    """
    解析 clash-speedtest 输出的 YAML，映射回原始节点并附加延迟/速度字段。
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

        latency = _try_extract_int(fp, ["latency", "delay", "rtt"])
        speed   = _try_extract_speed(fp, idx_name)

        # 部分版本把结果写进名字字符串，例如 "node_00001 ↑ 2.50MB/s 123ms"
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
            return round(v / 1_048_576 if v > 10_000 else v, 2)
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
        bin_path: Optional[str] = None,
) -> list:
    """
    调用 clash-speedtest 对节点列表做真实下载测速。

    参数：
        max_latency_ms  延迟上限（ms），超过则丢弃
        min_speed_mbps  速度下限（MB/s），低于则丢弃
        timeout_s       单节点测速超时秒数
        concurrent      并发连接数
    """
    bin_path = bin_path or CLASH_SPEEDTEST_BIN
    if not bin_path:
        raise RuntimeError("clash-speedtest 未找到，请先安装。")
    if not proxies:
        return []

    logger.info(
        f"🚀 [clash-speedtest] 测速 {len(proxies)} 个节点 | "
        f"延迟≤{max_latency_ms}ms  速度≥{min_speed_mbps}MB/s  超时:{timeout_s}s"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp         = Path(tmpdir)
        input_yaml  = tmp / "input.yaml"
        output_yaml = tmp / "filtered.yaml"

        yaml_content, index_map = _build_clash_yaml_for_speedtest(proxies)
        if not index_map:
            logger.warning("⚠️ 清洗后无合法节点，跳过 clash-speedtest。")
            return []

        input_yaml.write_text(yaml_content, encoding="utf-8")

        # 注意：clash-speedtest 没有 -speed-mode 参数，已移除
        cmd = [
            bin_path,
            "-c",            str(input_yaml),
            "-output",       str(output_yaml),
            "-max-latency",  f"{max_latency_ms}ms",
            "-min-speed",    str(min_speed_mbps),
            "-timeout",      f"{timeout_s}s",
            "-concurrent",   str(concurrent),
        ]

        logger.info(f"   CMD: {' '.join(cmd)}")

        # 动态超时：每节点最多 timeout_s 秒 × 数量 + 2 分钟缓冲
        total_timeout = len(index_map) * timeout_s + 120

        try:
            proc = subprocess.run(
                cmd,
                timeout=total_timeout,
                capture_output=True,   # 捕获 stdout/stderr 供日志使用
                text=True,
            )
            if proc.returncode != 0:
                logger.warning(f"⚠️ clash-speedtest 退出码 {proc.returncode}")
            if proc.stderr:
                logger.debug(f"clash-speedtest stderr: {proc.stderr[:500]}")
        except subprocess.TimeoutExpired:
            logger.error("❌ clash-speedtest 超时，尝试使用已完成的部分结果")
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

    if result:
        logger.info(
            f"✅ [clash-speedtest] 通过: {len(result)}/{len(proxies)} 个 | "
            f"最快: {result[0].get('latency', '?')}ms"
            + (f" @ {result[0].get('speed_mbps', '?')}MB/s" if result[0].get("speed_mbps") else "")
            + f"  最慢: {result[-1].get('latency', '?')}ms"
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
        "   此模式只验证连通性，无法保证代理真实可用！"
    )
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            server = p.get("server", "")
            port   = p.get("port")
            ptype  = str(p.get("type", "")).lower()
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
        concurrent: int = 4,
        # 降级参数
        fallback_workers: int = 100,
        fallback_latency_threshold: int = 3000,
        # 兼容旧参数（忽略）
        **kwargs,
) -> list:
    """完整两阶段测速流程。"""
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
        loop  = asyncio.get_event_loop()
        valid = await loop.run_in_executor(
            None,
            lambda: run_clash_speedtest(
                survivors,
                max_latency_ms=max_latency_ms,
                min_speed_mbps=min_speed_mbps,
                timeout_s=test_timeout_s,
                concurrent=concurrent,
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
