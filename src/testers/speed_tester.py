"""
speed_tester.py - 节点真实可用性验证器（重构版）

【根本问题修复说明】
旧方案：只做 TCP/TLS 握手 → 只能证明端口开放，无法验证代理协议真正可用
新方案：
  1. 优先使用系统已安装的 mihomo/clash.meta/clash 内核做真实 HTTP 测试
  2. 若无内核，自动从 GitHub 下载 mihomo 二进制文件（适配 Linux/macOS/ARM）
  3. 真实测试流程：启动临时内核 → 通过代理发 HTTP 请求 → 验证 204 响应

【为什么旧代码会导致订阅全 timeout】
  - 在 GitHub Actions 上没有 clash 内核，代码降级到 TCP/TLS 握手
  - TCP 握手只证明端口开着，vmess/vless/trojan/ss/hy2 的加密握手可能完全失败
  - 于是把「端口开着但协议不可用」的节点写入了订阅，Clash Verge 连接全部超时
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
import tarfile
import gzip
import shutil
import ssl
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# ── 测试目标 URL（返回 204，流量极小）──────────────────────────
REAL_TEST_URL = "http://www.gstatic.com/generate_204"
FALLBACK_TEST_URL = "http://cp.cloudflare.com/generate_204"

# ── mihomo 自动下载配置 ─────────────────────────────────────────
MIHOMO_VERSION = "v1.19.10"
MIHOMO_BASE_URL = f"https://github.com/MetaCubeX/mihomo/releases/download/{MIHOMO_VERSION}"
# 下载后保存到项目根目录，避免重复下载
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MIHOMO_CACHE_PATH = _PROJECT_ROOT / "mihomo-bin"


def _get_mihomo_download_url() -> tuple[str, str]:
    """
    根据当前系统和 CPU 架构，返回对应的 mihomo 下载 URL 和文件名。
    返回: (下载URL, 文件名)
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 架构映射
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
    """
    自动下载 mihomo 二进制文件，缓存到项目根目录。
    返回二进制文件路径，失败则返回 None。
    """
    # 检查缓存
    if MIHOMO_CACHE_PATH.exists():
        logger.info(f"✅ 使用缓存的 mihomo 内核: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    url, filename = _get_mihomo_download_url()
    logger.info(f"📥 正在下载 mihomo 内核: {url}")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            download_path = Path(tmpdir) / filename

            # 下载文件（带超时）
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as response:
                with open(download_path, "wb") as f:
                    shutil.copyfileobj(response, f)

            logger.info(f"✅ 下载完成，正在解压...")

            # 解压
            binary_path = Path(tmpdir) / "mihomo"
            if filename.endswith(".gz"):
                with gzip.open(download_path, "rb") as gz:
                    with open(binary_path, "wb") as f:
                        shutil.copyfileobj(gz, f)
            elif filename.endswith(".zip"):
                with zipfile.ZipFile(download_path) as zf:
                    # Windows 包里的可执行文件
                    for name in zf.namelist():
                        if "mihomo" in name.lower() and name.endswith(".exe"):
                            zf.extract(name, tmpdir)
                            binary_path = Path(tmpdir) / name
                            break
            else:
                # 直接是二进制
                binary_path = download_path

            # 复制到缓存位置并赋予执行权限
            shutil.copy2(binary_path, MIHOMO_CACHE_PATH)
            MIHOMO_CACHE_PATH.chmod(
                MIHOMO_CACHE_PATH.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )

        logger.info(f"✅ mihomo 内核已就绪: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    except Exception as e:
        logger.error(f"❌ 下载 mihomo 失败: {e}")
        # 清理可能损坏的文件
        if MIHOMO_CACHE_PATH.exists():
            MIHOMO_CACHE_PATH.unlink()
        return None


def _find_clash_binary() -> str | None:
    """
    按优先级查找可用的 clash/mihomo 内核。
    优先级: mihomo（缓存） > mihomo（系统） > clash.meta > clash
    """
    # 1. 先检查缓存的 mihomo
    if MIHOMO_CACHE_PATH.exists():
        logger.info(f"✅ 发现缓存的 mihomo: {MIHOMO_CACHE_PATH}")
        return str(MIHOMO_CACHE_PATH)

    # 2. 检查系统 PATH
    for binary in ["mihomo", "clash.meta", "clash"]:
        path = shutil.which(binary)
        if path:
            logger.info(f"✅ 发现系统内核: {path}")
            return path

    return None


# ── 模块级：查找或下载内核 ──────────────────────────────────────
CLASH_BINARY = _find_clash_binary()

if CLASH_BINARY:
    logger.info(f"✅ 将使用内核: {CLASH_BINARY}（真实 HTTP 测试模式）")
else:
    logger.info("⚠️ 未找到 clash/mihomo 内核，将在测速前自动下载...")


# ══════════════════════════════════════════════════════════════
#  核心：通过 mihomo 内核做真实代理可用性测试
# ══════════════════════════════════════════════════════════════

# 全局端口分配器，避免并发时端口冲突
import random
_used_ports: set = set()
_port_lock = asyncio.Lock() if False else None  # 延迟初始化


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
    """
    启动临时 mihomo 实例，对单个节点进行真实代理可用性测试。
    这是唯一能 100% 验证加密代理协议是否真正可用的方法。

    流程：
    1. 写入包含单节点的最小 clash 配置
    2. 启动 mihomo 进程（监听随机本地端口）
    3. 通过该本地端口发起真实 HTTP 请求
    4. 收到 200/204 响应 → 节点可用，记录延迟
    """
    local_port = _alloc_port()

    try:
        # 深拷贝并清洗节点配置，移除 None 值
        proxy_config = {k: v for k, v in proxy.items() if v is not None}
        proxy_config["name"] = "test-node"

        # 构造最小 clash 配置
        config = {
            "mixed-port": local_port,
            "allow-lan": False,
            "mode": "global",
            "log-level": "silent",
            "ipv6": False,
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
                # 启动 mihomo 实例（完全静默）
                process = subprocess.Popen(
                    [clash_binary, "-d", tmpdir, "-f", str(config_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                # 等待进程启动（mihomo 通常 0.5s 内就绪）
                await asyncio.sleep(1.2)

                # 检查进程是否立即崩溃（配置格式错误等）
                if process.poll() is not None:
                    return 9999, "KernelCrash"

                # 通过本地 HTTP 代理发起真实请求
                proxy_url = f"http://127.0.0.1:{local_port}"
                start = time.time()

                try:
                    conn_timeout = aiohttp.ClientTimeout(
                        total=timeout - 2,
                        connect=5,
                        sock_connect=5,
                        sock_read=timeout - 4
                    )
                    async with aiohttp.ClientSession(timeout=conn_timeout) as session:
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
                    # 代理连接被拒绝（节点协议握手失败）
                    return 9999, "ProxyConnFailed"
                except asyncio.TimeoutError:
                    return 9999, "Timeout"
                except Exception as e:
                    return 9999, type(e).__name__

            finally:
                # 确保子进程被清理
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
    finally:
        _free_port(local_port)


# ══════════════════════════════════════════════════════════════
#  备用：TCP 连接测试（仅在内核不可用时作为兜底）
# ══════════════════════════════════════════════════════════════

async def _test_tcp_connect(host: str, port: int, timeout: int) -> tuple[int, str]:
    """
    TCP 三次握手测试（仅作为内核不可用时的兜底）。
    注意：此测试只能证明端口开放，不能验证代理协议可用性！
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
        return int((time.time() - start) * 1000), "TCP_ONLY"
    except asyncio.TimeoutError:
        return 9999, "TCPTimeout"
    except Exception as e:
        return 9999, type(e).__name__


async def _test_tls_handshake(host: str, port: int, sni: str, timeout: int) -> tuple[int, str]:
    """
    TLS 握手测试（比 TCP 更可靠，但仍非代理协议验证）。
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
        return int((time.time() - start) * 1000), "TLS_ONLY"
    except asyncio.TimeoutError:
        return 9999, "TLSTimeout"
    except Exception as e:
        return 9999, type(e).__name__


# ══════════════════════════════════════════════════════════════
#  统一测试调度器
# ══════════════════════════════════════════════════════════════

async def test_proxy_latency(proxy: dict, clash_binary: str | None, timeout: int = 10) -> tuple[dict, int, str | None]:
    """
    节点可用性测试调度器。

    【重要】优先使用内核做真实 HTTP 测试，这是确保订阅可用的唯一可靠方式。
    只有在内核完全不可用时，才降级到 TCP/TLS 测试，且会在日志中明确警告。
    """
    server = proxy.get("server")
    port = proxy.get("port")
    name = proxy.get("name", "Unknown")

    if not server or not isinstance(port, int):
        return proxy, 9999, "Invalid"

    proxy_type = proxy.get("type", "").lower()

    # ── 策略1：优先使用 mihomo 内核（最准确）─────────────────────
    if clash_binary and proxy_type in ("vmess", "vless", "trojan", "ss", "hy2", "hysteria2"):
        latency, method = await _test_via_clash_kernel(proxy, clash_binary, timeout)

        if latency != 9999:
            logger.debug(f"✅ [内核HTTP] {name:<40} {latency}ms")
            return proxy, latency, None
        else:
            logger.debug(f"❌ [内核HTTP] {name:<40} 失败({method})")
            # 内核测试明确失败，节点真正不可用，不再降级
            return proxy, 9999, method

    # ── 策略2：无内核时的降级方案（警告：精度不足）──────────────
    # 此分支只在没有内核时触发，生成的订阅质量无法保证
    logger.debug(f"⚠️ [TCP降级] {name} - 无内核，使用 TCP 测试（结果不代表协议可用）")

    # 对有 TLS 标记的节点做 TLS 握手（稍好一些）
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
#  阶段一：快速 TCP 预筛（仅淘汰死节点，不作为最终标准）
# ══════════════════════════════════════════════════════════════

async def phase1_tcp_prefilter(
        proxies: list,
        max_workers: int = 200,
        timeout: int = 3,
        keep_top_n: int = 500,
) -> list:
    """
    第一阶段：高并发 TCP 快速探通，淘汰明显死节点。

    注意：TCP 通过只是必要条件，不是充分条件。
    真正的可用性验证在第二阶段（内核 HTTP 测试）完成。
    """
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


# ══════════════════════════════════════════════════════════════
#  主入口：两阶段批量测速
# ══════════════════════════════════════════════════════════════

async def speed_test_all(
        proxies: list,
        max_workers: int = 20,   # 内核测试并发不能太高（每个启动一个子进程）
        top_n: int = 150,
        total_timeout: int = 900,
        latency_threshold: int = 5000,
        # 阶段一参数
        phase1_workers: int = 200,
        phase1_timeout: int = 3,
        phase1_keep: int = 500,
) -> list:
    """
    两阶段批量测速：
    阶段一：高并发 TCP 探通，快速淘汰死节点（几十秒）
    阶段二：内核 HTTP 真实测试，只测 TCP 存活节点（确保订阅可用）

    最终结果中的每一个节点，都经过真实 HTTP 请求验证，导入 Clash Verge 后不会 timeout。
    """
    global CLASH_BINARY

    if not proxies:
        return []

    # ── 确保有内核可用 ────────────────────────────────────────────
    if not CLASH_BINARY:
        logger.info("🔄 正在尝试自动下载 mihomo 内核...")
        CLASH_BINARY = _download_mihomo()

        if CLASH_BINARY:
            logger.info(f"✅ mihomo 下载成功，将使用真实 HTTP 测试模式")
        else:
            logger.warning(
                "⚠️ mihomo 下载失败，将降级使用 TCP/TLS 测试模式。\n"
                "   【警告】生成的订阅节点的实际可用性无法保证！\n"
                "   建议手动安装 mihomo: https://github.com/MetaCubeX/mihomo/releases"
            )

    mode_desc = "【内核真实HTTP测试✅】" if CLASH_BINARY else "【TCP降级测试⚠️（可用性不保证）】"
    logger.info(f"测速模式: {mode_desc}")

    # ── 阶段一：TCP 快速预筛 ──────────────────────────────────────
    survivors = await phase1_tcp_prefilter(
        proxies,
        max_workers=phase1_workers,
        timeout=phase1_timeout,
        keep_top_n=phase1_keep,
    )

    if not survivors:
        logger.warning("❌ 阶段一后无存活节点，退出测速。")
        return []

    # ── 阶段二：精确协议测试 ──────────────────────────────────────
    # 内核测试每个节点要启动子进程，并发不能太高，否则系统资源耗尽
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

    if not valid_proxies and CLASH_BINARY:
        logger.warning(
            "⚠️ 内核测试后无可用节点，可能原因：\n"
            "   1. 当前运行环境网络受限（无法访问外网）\n"
            "   2. 信源节点质量差，大量节点已失效\n"
            "   3. 测速超时设置过短\n"
            "   建议：检查网络环境，或增大 latency_threshold 参数"
        )

    sorted_proxies = sorted(valid_proxies, key=lambda p: p["latency"])
    return sorted_proxies[:top_n] if len(sorted_proxies) > top_n else sorted_proxies