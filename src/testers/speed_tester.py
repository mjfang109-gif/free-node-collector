"""
speed_tester.py - 基于 clash-speedtest 的节点测速模块

【clash-speedtest 实际 Flag（来自 -h 确认）】
  -max-latency duration     延迟过滤，如 "3000ms"
  -min-download-speed float 速度过滤 MB/s（不是 -min-speed！）
  -speed-mode string        fast / download / full
  -rename bool              默认 true，必须传 -rename=false！
                            否则节点名被改成 "🇺🇸 US | 44ms ↑ 129.88MB/s"，
                            index_map 用 node_XXXXX 查不到，全部结果丢失。

【解析策略】
  直接解析 stdout 的制表符表格，比 output YAML 更可靠：
    序号  节点名称    类型    延迟   抖动   丢包率   下载速度
    2.    node_00244  Vless   63ms   47ms   0.0%    85.93MB/s
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


def _find_clash_speedtest() -> Optional[str]:
    p = shutil.which("clash-speedtest")
    if p:
        return p
    for c in [
        Path.home() / "go" / "bin" / "clash-speedtest",
        Path("/root/go/bin/clash-speedtest"),
        Path("/usr/local/go/bin/clash-speedtest"),
        Path("/home/runner/go/bin/clash-speedtest"),
    ]:
        if c.exists():
            return str(c)
    return None


CLASH_SPEEDTEST_BIN = _find_clash_speedtest()

if CLASH_SPEEDTEST_BIN:
    logger.info(f"✅ clash-speedtest 就绪: {CLASH_SPEEDTEST_BIN}")
else:
    logger.warning("⚠️ 未找到 clash-speedtest，将降级为 TCP/TLS 测试模式。")


# ══════════════════════════════════════════════════════════════
#  TCP / TLS 探测工具
# ══════════════════════════════════════════════════════════════

async def _tcp_connect(host: str, port: int, timeout: float) -> int:
    start = time.time()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await asyncio.shield(writer.wait_closed())
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


async def _tls_connect(host: str, port: int, sni: str, timeout: float) -> int:
    start = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout)
        writer.close()
        await asyncio.shield(writer.wait_closed())
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


# ══════════════════════════════════════════════════════════════
#  代理字段清洗
# ══════════════════════════════════════════════════════════════

_ALLOWED_FOR_TEST = {
    "ss": {"name", "type", "server", "port", "cipher", "password", "udp", "plugin", "plugin-opts"},
    "vmess": {"name", "type", "server", "port", "uuid", "alterId", "cipher",
              "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
              "http-opts", "grpc-opts", "servername", "udp"},
    "vless": {"name", "type", "server", "port", "uuid", "flow",
              "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
              "reality-opts", "servername", "sni", "udp"},
    "trojan": {"name", "type", "server", "port", "password",
               "tls", "skip-cert-verify", "sni", "network", "ws-opts", "grpc-opts", "udp"},
    "hy2": {"name", "type", "server", "port", "password",
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
    p = dict(proxy)
    ptype = str(p.get("type", "")).lower()

    if ptype == "hysteria2":
        p["type"] = "hy2"
        ptype = "hy2"

    if ptype == "ss":
        if str(p.get("cipher", "")).lower().strip() not in _SS_VALID_CIPHERS:
            return None

    if ptype == "vmess":
        p["alterId"] = int(p.get("alterId") or 0)

    allowed = _ALLOWED_FOR_TEST.get(ptype)
    if allowed:
        p = {k: v for k, v in p.items() if k in allowed and v is not None}
    else:
        p = {k: v for k, v in p.items() if v is not None}

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
    logger.info(f"⚡ [阶段一] TCP 存活探测 {len(proxies)} 个节点（并发:{max_workers} 超时:{timeout}s）")
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            s, port = p.get("server", ""), p.get("port")
            if not s or not isinstance(port, int) or not (1 <= port <= 65535):
                return p, 9999
            return p, await _tcp_connect(s, port, timeout)

    raw = await asyncio.gather(*[_check(p) for p in proxies], return_exceptions=True)
    results = [(p, lat) for res in raw if isinstance(res, tuple) for p, lat in [res] if lat != 9999]
    results.sort(key=lambda x: x[1])
    survivors = [p for p, _ in results[:keep_top_n]]
    logger.info(f"[阶段一] TCP 可达 {len(results)}/{len(proxies)} 个，保留最优 {len(survivors)} 个")
    return survivors


# ══════════════════════════════════════════════════════════════
#  阶段二A：clash-speedtest
# ══════════════════════════════════════════════════════════════

def _build_clash_yaml_for_speedtest(proxies: list) -> tuple[str, dict]:
    """生成最小化 Clash YAML，节点名用 node_XXXXX 索引编码。"""
    clean_proxies, index_map = [], {}
    for i, proxy in enumerate(proxies):
        s = _sanitize_for_speedtest(proxy)
        if s is None:
            continue
        idx = f"node_{i:05d}"
        s["name"] = idx
        index_map[idx] = proxy
        clean_proxies.append(s)

    config = {
        "mixed-port": 17890,
        "allow-lan": False,
        "mode": "global",
        "log-level": "silent",
        "proxies": clean_proxies,
        "proxy-groups": [{"name": "PROXY", "type": "select",
                          "proxies": [p["name"] for p in clean_proxies]}],
        "rules": ["MATCH,PROXY"],
    }
    return yaml.dump(config, allow_unicode=True, sort_keys=False), index_map


def _parse_speedtest_stdout(stdout: str, index_map: dict,
                            max_latency_ms: int, min_speed_mbps: float) -> list:
    """
    解析 clash-speedtest stdout 制表符表格，返回通过筛选的原始节点列表。

    表格格式（制表符分隔）：
        序号\t节点名称\t类型\t延迟\t抖动\t丢包率\t下载速度
        2.\tnode_00244\tVless\t63ms\t47ms\t0.0%\t85.93MB/s

    筛选条件：
        丢包率 == 0%  AND  延迟 <= max_latency_ms  AND  速度 >= min_speed_mbps
    """
    result = []
    for line in stdout.splitlines():
        parts = line.strip().split('\t')
        if len(parts) < 6:
            continue

        idx_name = parts[1].strip()
        if not idx_name.startswith("node_"):
            continue  # 跳过表头

        # 丢包率
        m = re.match(r'^([\d.]+)%$', parts[5].strip())
        if not m or float(m.group(1)) > 0:
            continue  # N/A 或丢包 > 0，跳过

        # 延迟
        m = re.match(r'^(\d+)ms$', parts[3].strip())
        if not m:
            continue
        latency = int(m.group(1))
        if latency > max_latency_ms:
            continue

        # 下载速度
        speed = 0.0
        if len(parts) >= 7:
            s = parts[6].strip()
            mm = re.match(r'^([\d.]+)MB/s$', s) or re.match(r'^([\d.]+)KB/s$', s)
            if mm:
                speed = float(mm.group(1))
                if 'KB' in s:
                    speed = round(speed / 1024, 2)
        if speed > 0 and speed < min_speed_mbps:
            continue

        original = index_map.get(idx_name)
        if original is None:
            continue

        node = dict(original)
        node["latency"] = latency
        if speed > 0:
            node["speed_mbps"] = speed
        result.append(node)

    result.sort(key=lambda x: x.get("latency", 9999))
    return result


def run_clash_speedtest(
        proxies: list,
        max_latency_ms: int = 3000,
        min_speed_mbps: float = 0.3,
        timeout_s: int = 10,
        concurrent: int = 4,
        bin_path: Optional[str] = None,
) -> list:
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
        tmp = Path(tmpdir)
        input_yaml = tmp / "input.yaml"
        output_yaml = tmp / "result.yaml"

        yaml_content, index_map = _build_clash_yaml_for_speedtest(proxies)
        if not index_map:
            logger.warning("⚠️ 清洗后无合法节点，跳过 clash-speedtest。")
            return []

        input_yaml.write_text(yaml_content, encoding="utf-8")
        logger.info(f"📄 输入：{len(index_map)} 个节点，{input_yaml.stat().st_size // 1024} KB")

        cmd = [
            bin_path,
            "-c", str(input_yaml),
            "-output", str(output_yaml),
            "-max-latency", f"{max_latency_ms}ms",
            "-min-download-speed", str(min_speed_mbps),
            "-speed-mode", "download",
            "-timeout", f"{timeout_s}s",
            "-concurrent", str(concurrent),
            "-rename=false",  # 保留 node_XXXXX 名称，否则 index_map 查不到
        ]
        logger.info(f"   CMD: {' '.join(cmd)}")

        total_timeout = len(index_map) * timeout_s + 120
        try:
            proc = subprocess.run(cmd, timeout=total_timeout,
                                  capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            logger.error("❌ clash-speedtest 超时")
            return []
        except FileNotFoundError:
            logger.error(f"❌ 找不到二进制: {bin_path}")
            return []
        except Exception as e:
            logger.error(f"❌ clash-speedtest 异常: {e}")
            return []

        if proc.returncode != 0:
            logger.warning(f"⚠️ clash-speedtest 退出码 {proc.returncode}")
        if proc.stderr:
            logger.warning(f"stderr: {proc.stderr[:500]}")
        if not proc.stdout:
            logger.warning("⚠️ clash-speedtest 无任何输出")
            return []

        result = _parse_speedtest_stdout(
            proc.stdout, index_map, max_latency_ms, min_speed_mbps)

    if result:
        logger.info(
            f"✅ 通过: {len(result)}/{len(proxies)} 个 | "
            f"最快: {result[0].get('latency')}ms"
            + (f" @ {result[0].get('speed_mbps')}MB/s" if result[0].get("speed_mbps") else "")
            + f"  最慢: {result[-1].get('latency')}ms"
        )
    else:
        logger.warning("⚠️ 无节点通过筛选")
    return result


# ══════════════════════════════════════════════════════════════
#  阶段二B：TCP/TLS 降级
# ══════════════════════════════════════════════════════════════

async def phase2_fallback_test(
        proxies: list,
        max_workers: int = 100,
        timeout: float = 5.0,
        latency_threshold: int = 3000,
) -> list:
    logger.warning(f"⚠️ [降级] TLS/TCP 测试 {len(proxies)} 个节点（只验证连通性）")
    sem = asyncio.Semaphore(max_workers)

    async def _check(p):
        async with sem:
            s, port = p.get("server", ""), p.get("port")
            ptype = str(p.get("type", "")).lower()
            if not s or not isinstance(port, int):
                return p, 9999
            if ptype in ("vless", "trojan", "hy2", "hysteria2") or p.get("tls"):
                sni = p.get("sni") or p.get("servername") or s
                lat = await _tls_connect(s, port, sni, timeout)
            else:
                lat = await _tcp_connect(s, port, timeout)
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
        phase1_workers: int = 200,
        phase1_timeout: float = 2.5,
        phase1_keep: int = 600,
        max_latency_ms: int = 3000,
        min_speed_mbps: float = 0.3,
        test_timeout_s: int = 10,
        concurrent: int = 4,
        fallback_workers: int = 100,
        fallback_latency_threshold: int = 3000,
        **kwargs,
) -> list:
    if not proxies:
        return []

    mode = "clash-speedtest ✅" if CLASH_SPEEDTEST_BIN else "TCP/TLS 降级 ⚠️"
    logger.info(f"🔬 测速模式: {mode}  总节点: {len(proxies)}")

    survivors = await phase1_tcp_prefilter(
        proxies, max_workers=phase1_workers,
        timeout=phase1_timeout, keep_top_n=phase1_keep)
    if not survivors:
        logger.warning("❌ 阶段一后无存活节点。")
        return []

    if CLASH_SPEEDTEST_BIN:
        loop = asyncio.get_event_loop()
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
            survivors, max_workers=fallback_workers,
            timeout=float(test_timeout_s),
            latency_threshold=fallback_latency_threshold)

    result = valid[:top_n]
    if result:
        logger.info(
            f"🎉 最终保留 {len(result)} 个节点 | "
            f"最快 {result[0].get('latency', '?')}ms  最慢 {result[-1].get('latency', '?')}ms"
        )
    else:
        logger.warning("⚠️ 无节点通过筛选。")
    return result
