"""
speed_tester.py - 节点真实可用性验证器（重构修复版 + SSL 兼容修复）

【修复说明】
1. 引入了严格的节点清洗逻辑，防止非法配置（如 cipher: auto）导致内核闪崩。
2. 引入共享的内核工作目录，彻底解决了并发测速时的 MMDB 数据库重复下载风暴。
3. 禁用了多进程缓存持久化，避免锁死。
4. 使用智能端口探测替代硬编码的 sleep 盲等，大幅提升测速的稳定性。
5. 【新增】忽略 urllib 的 SSL 证书验证，解决特定系统下下载内核报 CERTIFICATE_VERIFY_FAILED 的问题。
"""

import asyncio
import time
import logging
import aiohttp
import subprocess
import tempfile
import stat
import platform
import urllib.request
import zipfile
import gzip
import shutil
import ssl
import random
from pathlib import Path
import yaml

# 引入清洗函数，确保交给内核的配置绝对安全合法
from generators.clash_generator import _sanitize_proxy

logger = logging.getLogger(__name__)

# ── 测试目标 URL（返回 204，流量极小）──────────────────────────
REAL_TEST_URL = "http://www.gstatic.com/generate_204"
FALLBACK_TEST_URL = "http://cp.cloudflare.com/generate_204"

# ── mihomo 自动下载与全局路径配置 ─────────────────────────────────────────
MIHOMO_VERSION = "v1.19.10"
MIHOMO_BASE_URL = f"https://github.com/MetaCubeX/mihomo/releases/download/{MIHOMO_VERSION}"

# 获取 src 目录
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MIHOMO_CACHE_PATH = _PROJECT_ROOT / "mihomo-bin"

# 全局共享的内核数据目录，避免并发测速时每个子进程重复下载 mmdb
MIHOMO_HOME_DIR = _PROJECT_ROOT / "mihomo-home"
MIHOMO_HOME_DIR.mkdir(exist_ok=True)


def _get_mihomo_download_url() -> tuple[str, str]:
    """根据当前系统和 CPU 架构，返回对应的 mihomo 下载 URL 和文件名。"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7",
    }
    arch = arch_map.get(machine, "amd64")

    if system == "linux":
        filename = f"mihomo-linux-{arch}-{MIHOMO_VERSION}.gz"
        url = f"{MIHOMO_BASE_URL}/{filename}"
    elif system == "darwin":
        filename = f"mihomo-darwin-{arch}-{MIHOMO_VERSION}.gz"
        url = f"{MIHOMO_BASE_URL}/{filename}"
    elif system == "windows":
        filename = f"mihomo-windows-{arch}-{MIHOMO_VERSION}.zip"
        url = f"{MIHOMO_BASE_URL}/{filename}"
    else:
        filename = f"mihomo-linux-amd64-{MIHOMO_VERSION}.gz"
        url = f"{MIHOMO_BASE_URL}/{filename}"

    return url, filename


def _download_mihomo() -> str | None:
    """自动下载 mihomo 二进制文件，缓存到项目目录。"""
    if MIHOMO_CACHE_PATH.exists():
        logger.info(f"✅ 使用缓存的 mihomo 内核: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    url, filename = _get_mihomo_download_url()
    logger.info(f"📥 正在下载 mihomo 内核: {url}")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            download_path = Path(tmpdir) / filename

            # 【修复 SSL 证书问题】创建一个忽略证书验证的 SSL 上下文
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            # 【修复 SSL 证书问题】将 context 传入 urlopen
            with urllib.request.urlopen(req, timeout=60, context=ctx) as response:
                with open(download_path, "wb") as f:
                    shutil.copyfileobj(response, f)

            logger.info(f"✅ 下载完成，正在解压...")

            binary_path = Path(tmpdir) / "mihomo"
            if filename.endswith(".gz"):
                logger.info("gz解压....")
                with gzip.open(download_path, "rb") as gz:
                    with open(binary_path, "wb") as f:
                        shutil.copyfileobj(gz, f)
            elif filename.endswith(".zip"):
                logger.info("zip解压....")
                with zipfile.ZipFile(download_path) as zf:
                    for name in zf.namelist():
                        if "mihomo" in name.lower() and name.endswith(".exe"):
                            zf.extract(name, tmpdir)
                            binary_path = Path(tmpdir) / name
                            break
            else:
                binary_path = download_path

            shutil.copy2(binary_path, MIHOMO_CACHE_PATH)
            MIHOMO_CACHE_PATH.chmod(
                MIHOMO_CACHE_PATH.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )

        logger.info(f"✅ mihomo 内核已就绪: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    except Exception as e:
        logger.error(f"❌ 下载 mihomo 失败: {e}")
        if MIHOMO_CACHE_PATH.exists():
            MIHOMO_CACHE_PATH.unlink()
        return None


def _find_clash_binary() -> str | None:
    """按优先级查找可用的 clash/mihomo 内核。"""
    if MIHOMO_CACHE_PATH.exists():
        logger.info(f"✅ 发现缓存的 mihomo: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    for binary in ["mihomo", "clash.meta", "clash"]:
        path = shutil.which(binary)
        if path:
            logger.info(f"✅ 发现系统内核: {path}")
            return path

    return None


CLASH_BINARY = _find_clash_binary()

if CLASH_BINARY:
    logger.info(f"✅ 将使用内核: {CLASH_BINARY}（真实 HTTP 测试模式）")
else:
    logger.info("⚠️ 未找到 clash/mihomo 内核，将在测速前自动下载...")


# ══════════════════════════════════════════════════════════════
#  核心：通过 mihomo 内核做真实代理可用性测试
# ══════════════════════════════════════════════════════════════

_used_ports: set = set()

def _alloc_port() -> int:
    """分配一个随机本地端口，避免冲突。"""
    for _ in range(100):
        port = random.randint(20000, 55000)
        if port not in _used_ports:
            _used_ports.add(port)
            return port
    return random.randint(20000, 55000)

def _free_port(port: int):
    """释放端口。"""
    _used_ports.discard(port)


async def _test_via_clash_kernel(proxy: dict, clash_binary: str, timeout: int) -> tuple[int, str]:
    local_port = _alloc_port()

    try:
        # 复用生成器的严格清洗逻辑，防止内核因无效字段闪崩
        sanitized_proxy = _sanitize_proxy(dict(proxy))
        if not sanitized_proxy:
            return 9999, "SanitizeFailed"

        sanitized_proxy["name"] = "test-node"

        # 构造最小化配置，明确禁用缓存和持久化以防止多进程冲突
        config = {
            "mixed-port": local_port,
            "allow-lan": False,
            "mode": "global",
            "log-level": "silent",
            "ipv6": False,
            "profile": {
                "store-selected": False,
                "store-fake-ip": False
            },
            "proxies": [sanitized_proxy],
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
                # 使用共享的 MIHOMO_HOME_DIR 而不是空目录 tmpdir
                process = subprocess.Popen(
                    [clash_binary, "-d", str(MIHOMO_HOME_DIR), "-f", str(config_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                # 智能探测端口，不使用盲目的 sleep
                port_ready = False
                for _ in range(15):  # 最多等待 3 秒 (15 * 0.2s)
                    if process.poll() is not None:
                        return 9999, "KernelCrash"
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection('127.0.0.1', local_port),
                            timeout=0.2
                        )
                        writer.close()
                        await writer.wait_closed()
                        port_ready = True
                        break
                    except Exception:
                        await asyncio.sleep(0.2)

                if not port_ready:
                    return 9999, "KernelInitTimeout"

                # 通过本地 HTTP 代理发起真实请求
                proxy_url = f"http://127.0.0.1:{local_port}"
                start = time.time()

                try:
                    conn_timeout = aiohttp.ClientTimeout(
                        total=timeout - 2,
                        connect=4,
                        sock_read=timeout - 4
                    )
                    # 增加 User-Agent 防止被 WAF 拦截
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    async with aiohttp.ClientSession(timeout=conn_timeout, headers=headers) as session:
                        async with session.get(
                            REAL_TEST_URL,
                            proxy=proxy_url,
                            ssl=False,
                            allow_redirects=True
                        ) as resp:
                            if resp.status in (200, 204):
                                latency = int((time.time() - start) * 1000)
                                return latency, "KERNEL_REAL"
                            return 9999, f"HTTP_{resp.status}"

                except aiohttp.ClientProxyConnectionError:
                    return 9999, "ProxyConnFailed"
                except asyncio.TimeoutError:
                    return 9999, "Timeout"
                except Exception as e:
                    return 9999, type(e).__name__

            finally:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
    finally:
        _free_port(local_port)


# ══════════════════════════════════════════════════════════════
#  备用：TCP / TLS 测试（仅在内核不可用时兜底）
# ══════════════════════════════════════════════════════════════

async def _test_tcp_connect(host: str, port: int, timeout: int) -> tuple[int, str]:
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
        return int((time.time() - start) * 1000), "TCP_ONLY"
    except asyncio.TimeoutError:
        return 9999, "TCPTimeout"
    except Exception as e:
        return 9999, type(e).__name__


async def _test_tls_handshake(host: str, port: int, sni: str, timeout: int) -> tuple[int, str]:
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
        return int((time.time() - start) * 1000), "TLS_ONLY"
    except asyncio.TimeoutError:
        return 9999, "TLSTimeout"
    except Exception as e:
        return 9999, type(e).__name__


# ══════════════════════════════════════════════════════════════
#  统一测试调度器
# ══════════════════════════════════════════════════════════════

async def test_proxy_latency(proxy: dict, clash_binary: str | None, timeout: int = 10) -> tuple[dict, int, str | None]:
    server = proxy.get("server")
    port = proxy.get("port")
    name = proxy.get("name", "Unknown")

    if not server or not isinstance(port, int):
        return proxy, 9999, "Invalid"

    proxy_type = proxy.get("type", "").lower()

    # 策略1：优先使用 mihomo 内核
    if clash_binary and proxy_type in ("vmess", "vless", "trojan", "ss", "hy2", "hysteria2"):
        latency, method = await _test_via_clash_kernel(proxy, clash_binary, timeout)

        if latency != 9999:
            logger.debug(f"✅ [内核HTTP] {name:<40} {latency}ms")
            return proxy, latency, None
        else:
            logger.debug(f"❌ [内核HTTP] {name:<40} 失败({method})")
            return proxy, 9999, method

    # 策略2：TCP / TLS 降级测试
    logger.debug(f"⚠️ [TCP降级] {name} - 无内核，使用 TCP 测试")
    if proxy.get("tls") or proxy_type in ("vless", "trojan", "vmess", "hy2", "hysteria2"):
        sni = proxy.get("sni") or proxy.get("servername") or server
        latency, method = await _test_tls_handshake(server, port, sni, timeout)
        if latency != 9999:
            return proxy, latency, None

    latency, method = await _test_tcp_connect(server, port, timeout)
    if latency != 9999:
        return proxy, latency, None

    return proxy, 9999, method


# ══════════════════════════════════════════════════════════════
#  阶段一与主调度器
# ══════════════════════════════════════════════════════════════

async def phase1_tcp_prefilter(
        proxies: list,
        max_workers: int = 200,
        timeout: int = 3,
        keep_top_n: int = 500,
) -> list:
    logger.info(f"⚡ [阶段一] TCP 快速探通 {len(proxies)} 个节点（并发: {max_workers}, 超时: {timeout}s）...")
    sem = asyncio.Semaphore(max_workers)
    results = []

    async def _check(p):
        async with sem:
            server = p.get("server")
            port = p.get("port")
            if not server or not isinstance(port, int):
                return p, 9999
            latency, _ = await _test_tcp_connect(server, port, timeout)
            return p, latency

    raw = await asyncio.gather(*[_check(p) for p in proxies], return_exceptions=True)

    for res in raw:
        if isinstance(res, tuple):
            p, lat = res
            if lat != 9999:
                results.append((p, lat))

    results.sort(key=lambda x: x[1])
    survivors = [p for p, _ in results[:keep_top_n]]

    logger.info(
        f"[阶段一] 完成：TCP 可达 {len(survivors)}/{len(proxies)} 个"
        f"（丢弃 {len(proxies) - len(survivors)} 个死节点）"
    )
    return survivors


async def speed_test_all(
        proxies: list,
        max_workers: int = 20,
        top_n: int = 150,
        total_timeout: int = 900,
        latency_threshold: int = 5000,
        phase1_workers: int = 200,
        phase1_timeout: int = 3,
        phase1_keep: int = 500,
) -> list:
    global CLASH_BINARY

    if not proxies:
        return []

    if not CLASH_BINARY:
        logger.info("🔄 正在尝试自动下载 mihomo 内核...")
        CLASH_BINARY = _download_mihomo()

        if CLASH_BINARY:
            logger.info(f"✅ mihomo 下载成功，将使用真实 HTTP 测试模式")
        else:
            logger.warning(
                "⚠️ mihomo 下载失败，将降级使用 TCP/TLS 测试模式。\n"
                "   【警告】生成的订阅节点的实际可用性无法保证！\n"
                "   建议手动安装 mihomo"
            )

    mode_desc = "【内核真实HTTP测试✅】" if CLASH_BINARY else "【TCP降级测试⚠️（可用性不保证）】"
    logger.info(f"测速模式: {mode_desc}")

    survivors = await phase1_tcp_prefilter(
        proxies,
        max_workers=phase1_workers,
        timeout=phase1_timeout,
        keep_top_n=phase1_keep,
    )

    if not survivors:
        logger.warning("❌ 阶段一后无存活节点，退出测速。")
        return []

    effective_workers = max_workers if CLASH_BINARY else min(max_workers * 3, 80)

    logger.info(
        f"🚀 [阶段二] {mode_desc} 对 {len(survivors)} 个节点进行精确测速"
        f"（并发: {effective_workers}）..."
    )

    valid_proxies = []
    sem = asyncio.Semaphore(effective_workers)

    async def test_with_semaphore(p):
        async with sem:
            return await test_proxy_latency(p, CLASH_BINARY)

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[test_with_semaphore(p) for p in survivors], return_exceptions=True),
            timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"❌ 阶段二超过总超时 {total_timeout}s，已使用当前结果。")
        results = []

    for res in results:
        if isinstance(res, Exception):
            continue
        if isinstance(res, tuple):
            p, latency, error = res
            if error is None and latency <= latency_threshold:
                p["latency"] = latency
                valid_proxies.append(p)

    logger.info(f"✅ [阶段二] 完成！{'真实可用' if CLASH_BINARY else 'TCP可达'}节点: {len(valid_proxies)} 个")

    sorted_proxies = sorted(valid_proxies, key=lambda p: p["latency"])
    return sorted_proxies[:top_n] if len(sorted_proxies) > top_n else sorted_proxies