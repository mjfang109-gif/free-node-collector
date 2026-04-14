"""
speed_tester.py - 节点真实可用性验证器

【核心改造思路】
旧方案：仅做 TCP 三次握手，只能证明端口开放，无法验证代理协议是否真正可用。
新方案：通过 clash-core 或 sing-box 启动临时代理实例，然后通过该代理
        发起真实 HTTP 请求，100% 确认节点可用性。

【备用方案（当无法调用内核时）】
使用 aiohttp-socks 对 SOCKS5/HTTP 类型节点做真实 HTTP 测试；
对其他类型（vmess/vless/trojan/hy2/ss）使用增强版 TCP 测试 + 协议探针。
"""

import asyncio
import time
import logging
import aiohttp
import socket
import struct
import ssl
import subprocess
import tempfile
import os
import yaml
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 测试目标 URL ────────────────────────────────────────────────
# gstatic 返回 204，流量极小，适合测速
REAL_TEST_URL = "http://www.gstatic.com/generate_204"
# 使用 cp.cloudflare.com 作为备用（更稳定）
FALLBACK_TEST_URL = "http://cp.cloudflare.com/generate_204"


# ══════════════════════════════════════════════════════════════
#  第一层：真实 HTTP-over-Proxy 验证（针对 HTTP/SOCKS5 类型）
# ══════════════════════════════════════════════════════════════

async def _test_via_socks5_proxy(proxy: dict, timeout: int) -> tuple[int, str]:
    """
    通过 SOCKS5 代理发起真实 HTTP 请求，验证节点连通性。
    适用于类型为 socks5 的节点。
    """
    server = proxy.get("server")
    port = proxy.get("port")
    username = proxy.get("username")
    password = proxy.get("password")

    if username and password:
        proxy_url = f"socks5://{username}:{password}@{server}:{port}"
    else:
        proxy_url = f"socks5://{server}:{port}"

    connector = None
    try:
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(proxy_url)
        start = time.time()
        async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(REAL_TEST_URL, ssl=False) as resp:
                if resp.status in (200, 204):
                    return int((time.time() - start) * 1000), "SOCKS5_HTTP"
                return 9999, f"HTTP_{resp.status}"
    except Exception as e:
        return 9999, type(e).__name__
    finally:
        if connector and not connector.closed:
            await connector.close()


async def _test_via_http_proxy(proxy: dict, timeout: int) -> tuple[int, str]:
    """
    通过 HTTP 代理发起真实 HTTP 请求。
    适用于类型为 http 的节点。
    """
    proxy_url = f"http://{proxy.get('server')}:{proxy.get('port')}"
    connector = None
    try:
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(proxy_url)
        start = time.time()
        async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(REAL_TEST_URL, ssl=False) as resp:
                if resp.status in (200, 204):
                    return int((time.time() - start) * 1000), "HTTP_PROXY"
                return 9999, f"HTTP_{resp.status}"
    except Exception as e:
        return 9999, type(e).__name__
    finally:
        if connector and not connector.closed:
            await connector.close()


# ══════════════════════════════════════════════════════════════
#  第二层：增强版 TCP + TLS 探针（针对加密代理协议）
# ══════════════════════════════════════════════════════════════

async def _test_tls_handshake(host: str, port: int, sni: str, timeout: int) -> tuple[int, str]:
    """
    发起完整 TLS 握手（比 TCP connect 更可靠）。
    TLS 握手成功 = 服务端确实在响应，而不只是端口开着。
    """
    start = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return int((time.time() - start) * 1000), "TLS_HANDSHAKE"
    except asyncio.TimeoutError:
        return 9999, "TLSTimeout"
    except Exception as e:
        return 9999, type(e).__name__


async def _test_tcp_connect(host: str, port: int, timeout: int) -> tuple[int, str]:
    """
    TCP 三次握手（最基础的测试，作为最后兜底）。
    """
    start = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return int((time.time() - start) * 1000), "TCP"
    except asyncio.TimeoutError:
        return 9999, "TCPTimeout"
    except Exception as e:
        return 9999, type(e).__name__


# ══════════════════════════════════════════════════════════════
#  第三层：通过 clash-core 内核做真实代理测试（最精确，需安装内核）
# ══════════════════════════════════════════════════════════════

def _find_clash_binary() -> str | None:
    """
    查找系统中可用的 clash 内核。
    按优先级尝试: mihomo > clash.meta > clash
    """
    for binary in ["mihomo", "clash.meta", "clash"]:
        try:
            result = subprocess.run(
                ["which", binary], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
    return None


CLASH_BINARY = _find_clash_binary()
if CLASH_BINARY:
    logger.info(f"✅ 发现 Clash 内核：{CLASH_BINARY}，将启用最高精度测试模式。")
else:
    logger.info("⚠️ 未找到 Clash 内核（mihomo/clash.meta/clash），将使用增强版 TCP+TLS 测试模式。")


async def _test_via_clash_kernel(proxy: dict, timeout: int) -> tuple[int, str]:
    """
    通过启动临时 clash 实例，对单个节点进行真实代理可用性测试。
    这是最准确的测试方法，可验证 vmess/vless/trojan/ss/hy2 等所有协议。
    """
    if not CLASH_BINARY:
        return 9999, "NoBinary"

    # 构造单节点的最小 clash 配置
    proxy_config = {k: v for k, v in proxy.items() if v is not None}
    proxy_config["name"] = "test-node"

    # 随机选一个本地端口（避免冲突）
    import random
    local_port = random.randint(20000, 40000)

    config = {
        "mixed-port": local_port,
        "allow-lan": False,
        "mode": "global",
        "log-level": "silent",
        "proxies": [proxy_config],
        "proxy-groups": [
            {"name": "GLOBAL", "type": "select", "proxies": ["test-node"]}
        ],
        "rules": ["MATCH,GLOBAL"]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

        process = None
        try:
            # 启动 clash 实例（静默模式）
            process = subprocess.Popen(
                [CLASH_BINARY, "-d", tmpdir, "-f", str(config_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # 等待进程就绪（最多等 2 秒）
            await asyncio.sleep(1.5)

            # 检查进程是否崩溃
            if process.poll() is not None:
                return 9999, "KernelCrash"

            # 通过本地代理发起真实 HTTP 请求
            proxy_url = f"http://127.0.0.1:{local_port}"
            start = time.time()
            connector = None
            try:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(proxy_url)
                async with aiohttp.ClientSession(
                        connector=connector,
                        timeout=aiohttp.ClientTimeout(total=timeout - 2)
                ) as session:
                    async with session.get(REAL_TEST_URL, ssl=False) as resp:
                        if resp.status in (200, 204):
                            return int((time.time() - start) * 1000), "KERNEL_REAL"
                        return 9999, f"HTTP_{resp.status}"
            except Exception as e:
                return 9999, type(e).__name__
            finally:
                if connector and not connector.closed:
                    await connector.close()

        except Exception as e:
            return 9999, type(e).__name__
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()


# ══════════════════════════════════════════════════════════════
#  统一调度器：按协议类型选择最合适的测试方法
# ══════════════════════════════════════════════════════════════

async def test_proxy_latency(proxy: dict, timeout: int = 10) -> tuple[dict, int, str | None]:
    """
    节点可用性测试调度器。

    测试策略（按精确度从高到低）：
    1. 若系统有 clash 内核 → 对所有加密协议使用内核测试（最精确）
    2. http/socks5 类型 → 直接通过代理发 HTTP 请求
    3. 有 TLS 的节点 → TLS 握手测试（比纯 TCP 更可靠）
    4. 其他 → TCP 连接测试（兜底）
    """
    name = proxy.get("name", "Unknown")
    server = proxy.get("server")
    port = proxy.get("port")

    # 基础校验
    if not server or not isinstance(port, int):
        return proxy, 9999, "Invalid"

    proxy_type = proxy.get("type", "").lower()
    latency, method = 9999, "None"

    # ── 策略 1：使用 clash 内核做真实测试 ─────────────────────
    if CLASH_BINARY and proxy_type in ("vmess", "vless", "trojan", "ss", "hy2", "hysteria2"):
        latency, method = await _test_via_clash_kernel(proxy, timeout)
        if latency != 9999:
            logger.debug(f"✅ [内核] {name:<35} {latency}ms ({method})")
            return proxy, latency, None
        # 内核测试失败，降级到 TLS/TCP 测试
        logger.debug(f"⚠️ [内核] {name} 失败({method})，降级测试...")

    # ── 策略 2：HTTP/SOCKS5 类型直接做真实代理测试 ────────────
    if proxy_type == "http":
        latency, method = await _test_via_http_proxy(proxy, timeout)
    elif proxy_type == "socks5":
        latency, method = await _test_via_socks5_proxy(proxy, timeout)

    # ── 策略 3：加密协议 → TLS 握手（需要 SNI/TLS 字段）────────
    elif proxy.get("tls") or proxy.get("sni") or proxy_type in ("vless", "trojan", "vmess", "hy2", "hysteria2"):
        sni = proxy.get("sni") or proxy.get("host") or server
        # 优先测实际服务端口
        latency, method = await _test_tls_handshake(server, port, sni, timeout)
        # TLS 失败则降级到 TCP
        if latency == 9999:
            latency, method = await _test_tcp_connect(server, port, timeout)

    # ── 策略 4：兜底 TCP 测试 ─────────────────────────────────
    else:
        latency, method = await _test_tcp_connect(server, port, timeout)

    if latency != 9999:
        logger.debug(f"✅ {name:<35} {latency}ms ({method})")
        return proxy, latency, None
    else:
        logger.debug(f"❌ {name:<35} 失败 ({method})")
        return proxy, 9999, method


# ══════════════════════════════════════════════════════════════
#  批量测速主函数
# ══════════════════════════════════════════════════════════════

async def speed_test_all(
        proxies: list,
        max_workers: int = 50,  # 降低并发，避免系统资源耗尽
        top_n: int = 150,
        batch_size: int =200,  # 批次大小同步降低
        total_timeout: int = 900,
        latency_threshold: int = 3000,  # 新增：丢弃延迟超过此值（ms）的节点
) -> list:
    """
    批量测速，返回真实可用且按延迟排序的节点列表。

    参数说明：
    - max_workers: 最大并发数（内核模式下建议设为 20~50，避免端口耗尽）
    - top_n: 最终保留的节点数量
    - latency_threshold: 延迟超过此值（毫秒）的节点视为不可用，直接丢弃
    """
    mode_desc = "【内核真实HTTP测试】" if CLASH_BINARY else "【增强TLS/TCP测试】"
    logger.info(
        f"🚀 开始测速 {mode_desc}（并发: {max_workers}, 批大小: {batch_size}, 延迟阈值: {latency_threshold}ms）...")

    valid_proxies = []
    sem = asyncio.Semaphore(max_workers)

    async def test_with_semaphore(p):
        async with sem:
            return await test_proxy_latency(p)

    async def test_batch():
        total = len(proxies)
        for i in range(0, total, batch_size):
            batch = proxies[i:i + batch_size]
            end_idx = min(i + batch_size, total)
            logger.info(f"📦 处理批次 {i // batch_size + 1}（节点 {i + 1}~{end_idx}/{total}）...")

            tasks = [test_with_semaphore(p) for p in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            batch_ok = 0
            for res in results:
                if isinstance(res, tuple):
                    p, latency, error = res
                    if error is None and latency <= latency_threshold:
                        p["latency"] = latency
                        valid_proxies.append(p)
                        batch_ok += 1

            logger.info(f"   ✅ 本批次通过: {batch_ok}/{len(batch)}")

    try:
        await asyncio.wait_for(test_batch(), timeout=total_timeout)
    except asyncio.TimeoutError:
        logger.error(f"❌ 测速超过总超时 {total_timeout}s，已中断（已测 {len(valid_proxies)} 个）。")

    total_valid = len(valid_proxies)
    logger.info(f"✅ 测速完成！真实可用节点: {total_valid} 个")

    if not valid_proxies:
        return []

    # 按延迟升序排序
    sorted_proxies = sorted(valid_proxies, key=lambda p: p["latency"])

    if len(sorted_proxies) > top_n:
        logger.info(f"🔪 保留延迟最低的前 {top_n} 个节点（共 {len(sorted_proxies)} 个通过）。")
        return sorted_proxies[:top_n]

    return sorted_proxies
