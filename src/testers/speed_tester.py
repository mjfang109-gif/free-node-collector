"""
speed_tester.py - 基于 clash-speedtest 的节点测速模块

【测速策略】
1. 阶段一：TCP 快速存活探测（过滤不可达节点）
2. 阶段二：clash-speedtest 完整测速（最准确）
   - 使用 download 模式测试实际下载速度
   - 同时测量延迟、抖动、丢包率

【参数说明】
- max-latency: 最大可接受延迟 (ms)
- min-download-speed: 最小下载速度 (MB/s)
- speed-mode: fast/download/full
- timeout: 单节点超时时间
- concurrent: 并发测试数
"""

import asyncio
import logging
import re
import shutil
import ssl
import subprocess
import time
import yaml
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_clash_speedtest() -> Optional[str]:
    """查找 clash-speedtest 二进制文件。"""
    p = shutil.which("clash-speedtest")
    if p:
        return p
    # 常见安装路径
    for path in [
        Path.home() / "go" / "bin" / "clash-speedtest",
        Path("/root/go/bin/clash-speedtest"),
        Path("/usr/local/go/bin/clash-speedtest"),
        Path("/home/runner/go/bin/clash-speedtest"),
        Path("/usr/local/bin/clash-speedtest"),
    ]:
        if path.exists():
            return str(path)
    return None


CLASH_SPEEDTEST_BIN = _find_clash_speedtest()

if CLASH_SPEEDTEST_BIN:
    logger.info(f"✅ clash-speedtest 就绪：{CLASH_SPEEDTEST_BIN}")
else:
    logger.warning("⚠️ 未找到 clash-speedtest，将降级为 TCP/TLS 测试模式。")


# ─────────────────────────────────────────────────────────────
#  TCP/TLS 基础探测工具
# ─────────────────────────────────────────────────────────────

async def _tcp_connect(host: str, port: int, timeout: float) -> int:
    """TCP 连接测试，返回延迟 ms。失败返回 9999。"""
    start = time.time()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


async def _tls_connect(host: str, port: int, sni: str, timeout: float) -> int:
    """TLS 握手测试，返回延迟 ms。失败返回 9999。"""
    start = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return int((time.time() - start) * 1000)
    except Exception:
        return 9999


# ─────────────────────────────────────────────────────────────
#  代理字典清洗与验证
# ─────────────────────────────────────────────────────────────

_ALLOWED_FIELDS = {
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
            "fingerprint", "alpn", "ca", "ca-str", "cwnd", "udp"},
}

_VALID_SS_CIPHERS = {
    "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
    "aes-128-cfb", "aes-256-cfb", "chacha20-ietf",
    "xchacha20-ietf-poly1305", "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
}


def _sanitize_proxy(proxy: dict) -> Optional[dict]:
    """清洗代理字典，移除无效或多余字段。"""
    p = dict(proxy)
    ptype = str(p.get("type", "")).lower()

    if ptype == "hysteria2":
        p["type"] = "hy2"
        ptype = "hy2"

    # Shadowsocks  cipher 验证
    if ptype == "ss":
        cipher = str(p.get("cipher", "")).lower().strip()
        if cipher not in _VALID_SS_CIPHERS:
            return None
        if not p.get("password"):
            return None

    # Vmess alterId 转 int
    if ptype == "vmess":
        p["alterId"] = int(p.get("alterId") or 0)

    # 只保留允许的字段
    allowed = _ALLOWED_FIELDS.get(ptype)
    if allowed:
        p = {k: v for k, v in p.items() if k in allowed and v is not None}
    else:
        p = {k: v for k, v in p.items() if v is not None}

    # ws-opts 清洗
    if "ws-opts" in p and isinstance(p["ws-opts"], dict):
        p["ws-opts"] = {k: v for k, v in p["ws-opts"].items() if v and v != ""}
        if not p["ws-opts"]:
            del p["ws-opts"]

    # 基本验证
    if not p.get("server") or not isinstance(p.get("port"), int):
        return None
    if not (1 <= p["port"] <= 65535):
        return None

    return p


# ─────────────────────────────────────────────────────────────
#  阶段一：TCP 快速预过滤
# ─────────────────────────────────────────────────────────────

async def _tcp_prefilter(
    proxies: list,
    max_workers: int = 200,
    timeout: float = 2.5,
    keep_top_n: int = 600,
) -> list:
    """TCP 存活探测，过滤掉无法连接的节点。"""
    sem = asyncio.Semaphore(max_workers)

    async def _check(p: dict) -> tuple:
        async with sem:
            server = p.get("server", "")
            port = p.get("port")
            if not server or not isinstance(port, int):
                return p, 9999
            latency = await _tcp_connect(server, port, timeout)
            return p, latency

    tasks = [_check(p) for p in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤成功连接的节点
    valid = [(p, lat) for r in results if isinstance(r, tuple) for p, lat in [r] if lat < 9999]
    # 按延迟排序
    valid.sort(key=lambda x: x[1])
    # 保留前 N 个
    survivors = [p for p, _ in valid[:keep_top_n]]

    logger.info(
        f"[阶段一] TCP 可达：{len(valid)}/{len(proxies)} 个，"
        f"保留最优 {len(survivors)} 个"
    )
    return survivors


# ─────────────────────────────────────────────────────────────
#  阶段二：clash-speedtest 完整测速
# ─────────────────────────────────────────────────────────────

def _build_clash_config(proxies: list) -> tuple[str, dict]:
    """生成 Clash 配置文件及索引映射。"""
    clean_proxies = []
    index_map = {}

    for i, proxy in enumerate(proxies):
        cleaned = _sanitize_proxy(proxy)
        if cleaned is None:
            continue
        idx = f"node_{i:05d}"
        cleaned["name"] = idx
        index_map[idx] = proxy
        clean_proxies.append(cleaned)

    config = {
        "mixed-port": 17890,
        "allow-lan": False,
        "mode": "global",
        "log-level": "silent",
        "proxies": clean_proxies,
        "proxy-groups": [{
            "name": "PROXY",
            "type": "select",
            "proxies": [p["name"] for p in clean_proxies],
        }],
        "rules": ["MATCH,PROXY"],
    }

    return yaml.dump(config, allow_unicode=True, sort_keys=False), index_map


def _parse_speedtest_output(stdout: str, index_map: dict,
                            max_latency_ms: int, min_speed_mbps: float) -> list:
    """解析 clash-speedtest 标准输出。"""
    result = []
    skipped_no_latency = 0
    skipped_no_speed_data = 0
    skipped_low_speed = 0
    skip_header_count = 0
    short_line_count = 0
    no_node_prefix_count = 0

    logger.info(f"📊 开始解析测速输出，index_map 大小：{len(index_map)}")
    logger.info(f"📊 筛选条件：延迟≤{max_latency_ms}ms, 速度≥{min_speed_mbps}MB/s")
    logger.info(f"📊 stdout 原始内容长度：{len(stdout)} 字符")

    # 打印完整 stdout 用于调试（前 500 字符 + 后 500 字符）
    if len(stdout) <= 1000:
        logger.info(f"📄 完整 stdout:\n{stdout}")
    else:
        logger.info(f"📄 stdout 头部 (500 字符):\n{stdout[:500]}")
        logger.info(f"📄 stdout 尾部 (500 字符):\n{stdout[-500:]}")

    for line in stdout.splitlines():
        # 跳过表头
        if line.strip().startswith('序号') or not line.strip():
            skip_header_count += 1
            continue

        # 使用空白字符分割（空格和 tab 都支持）
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) < 6:
            short_line_count += 1
            if short_line_count <= 3:
                logger.warning(f"⚠️ parts 不足 ({len(parts)}): {line[:100]}")
            continue

        # 节点名格式：node_XXXXX
        idx_name = parts[1].strip() if len(parts) > 1 else ""
        if not idx_name.startswith("node_"):
            no_node_prefix_count += 1
            if no_node_prefix_count <= 3:
                logger.warning(f"⚠️ 非 node_前缀：idx_name={idx_name}, parts[0:3]={parts[0:3]}")
            continue

        # 解析丢包率 (第 6 列，索引 5)
        packet_loss = None
        if len(parts) >= 6:
            m = re.match(r'^([\d.]+)%$', parts[5].strip())
            if m:
                packet_loss = float(m.group(1))

        # 解析延迟 (第 4 列，索引 3)
        latency = None
        if len(parts) >= 4:
            val = parts[3].strip()
            if val != 'N/A':
                m = re.match(r'^(\d+)ms$', val)
                if m:
                    latency = int(m.group(1))

        # 解析速度 (第 7 列，索引 6)
        speed = 0.0
        has_speed_column = len(parts) >= 7
        if has_speed_column:
            s = parts[6].strip()
            if s != 'N/A':
                m = re.match(r'^([\d.]+)(MB/s|KB/s)$', s)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2)
                    speed = val if unit == "MB/s" else val / 1024

        # 调试：打印部分解析结果
        if len(result) < 5:
            logger.debug(f"🔍 {idx_name}: parts={len(parts)}, latency={latency}, speed={speed}, has_col7={has_speed_column}")

        # 筛选条件：延迟达标且速度达标（不强求丢包率为 0）
        if latency is None or latency > max_latency_ms:
            skipped_no_latency += 1
            continue
        # 速度筛选：有速度数据时才检查，无速度数据也通过（网络限制可能无法测速）
        if speed > 0 and speed < min_speed_mbps:
            skipped_low_speed += 1
            continue

        # 调试信息：记录被跳过的情况
        if speed == 0 and has_speed_column:
            skipped_no_speed_data += 1

        # 恢复原始代理信息
        original = index_map.get(idx_name)
        if original:
            node = dict(original)
            node["latency"] = latency
            if speed > 0:
                node["speed_mbps"] = speed
            result.append(node)

    logger.info(
        f"📈 解析统计：通过={len(result)}, 跳过头部/空行={skip_header_count}, "
        f"parts 不足={short_line_count}, 非 node_前缀={no_node_prefix_count}, "
        f"无延迟/超时={skipped_no_latency}, 低速={skipped_low_speed}, 无速度数据={skipped_no_speed_data}"
    )

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
    """运行 clash-speedtest 进行完整测速。"""
    bin_path = bin_path or CLASH_SPEEDTEST_BIN
    if not bin_path:
        raise RuntimeError("clash-speedtest 未找到")
    if not proxies:
        return []

    logger.info(
        f"🚀 [阶段二] clash-speedtest | {len(proxies)} 个节点 | "
        f"延迟≤{max_latency_ms}ms | 速度≥{min_speed_mbps}MB/s"
    )

    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config_file = tmp / "config.yaml"
        output_file = tmp / "result.yaml"

        yaml_content, index_map = _build_clash_config(proxies)
        if not index_map:
            logger.warning("⚠️ 无有效节点可供测速")
            return []

        config_file.write_text(yaml_content, encoding="utf-8")

        cmd = [
            bin_path,
            "-c", str(config_file),
            "-output", str(output_file),
            "-max-latency", f"{max_latency_ms}ms",
            "-min-download-speed", str(min_speed_mbps),
            "-speed-mode", "download",
            "-timeout", f"{timeout_s}s",
            "-concurrent", str(concurrent),
            "-rename=false",
        ]

        total_timeout = len(index_map) * timeout_s + 180
        try:
            proc = subprocess.run(
                cmd,
                timeout=total_timeout,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            logger.error("❌ clash-speedtest 超时")
            return []
        except Exception as e:
            logger.error(f"❌ clash-speedtest 异常：{e}")
            return []

        if proc.returncode != 0:
            logger.warning(f"⚠️ clash-speedtest 退出码：{proc.returncode}")
        if proc.stderr:
            logger.debug(f"stderr: {proc.stderr[:300]}")
        if not proc.stdout:
            logger.warning("⚠️ clash-speedtest 无输出")
            return []

        result = _parse_speedtest_output(proc.stdout, index_map, max_latency_ms, min_speed_mbps)

    if result:
        fastest = result[0]
        logger.info(
            f"✅ 通过：{len(result)}/{len(proxies)} 个 | "
            f"最快：{fastest.get('latency')}ms @ {fastest.get('speed_mbps', '?')}MB/s | "
            f"最慢：{result[-1].get('latency')}ms"
        )
    else:
        logger.warning("⚠️ 无节点通过测速筛选")

    return result


# ─────────────────────────────────────────────────────────────
#  降级方案：TLS/TLS 连通性测试
# ─────────────────────────────────────────────────────────────

async def _fallback_test(
    proxies: list,
    max_workers: int = 100,
    timeout: float = 5.0,
    latency_threshold: int = 3000,
) -> list:
    """降级测试：仅验证 TLS/TCP 连通性，不测速。"""
    sem = asyncio.Semaphore(max_workers)

    async def _check(p: dict) -> tuple:
        async with sem:
            server = p.get("server", "")
            port = p.get("port")
            ptype = str(p.get("type", "")).lower()

            if not server or not isinstance(port, int):
                return p, 9999

            # TLS 协议优先测试
            if ptype in ("vless", "trojan", "hy2", "hysteria2") or p.get("tls"):
                sni = p.get("sni") or p.get("servername") or server
                latency = await _tls_connect(server, port, sni, timeout)
            else:
                latency = await _tcp_connect(server, port, timeout)

            return p, latency

    tasks = [_check(p) for p in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for r in results:
        if isinstance(r, tuple):
            p, lat = r
            if 0 < lat <= latency_threshold:
                node = dict(p)
                node["latency"] = lat
                valid.append(node)

    valid.sort(key=lambda x: x.get("latency", 9999))
    logger.info(f"[降级] 可达：{len(valid)}/{len(proxies)} 个")
    return valid


# ─────────────────────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────────────────────

async def speed_test_all(
    proxies: list,
    top_n: int = 50,
    phase1_workers: int = 200,
    phase1_timeout: float = 2.5,
    phase1_keep: int = 600,
    max_latency_ms: int = 3000,
    min_speed_mbps: float = 0.3,
    test_timeout_s: int = 10,
    concurrent: int = 4,
    fallback_workers: int = 100,
    fallback_latency_threshold: int = 3000,
) -> list:
    """
    完整测速流程：
    1. TCP 快速预过滤
    2. clash-speedtest 完整测速（或降级为 TLS 测试）
    3. 返回速度最快的前 N 个节点
    """
    if not proxies:
        return []

    mode = "clash-speedtest ✅" if CLASH_SPEEDTEST_BIN else "TCP/TLS 降级 ⚠️"
    logger.info(f"🔬 测速模式：{mode} | 总节点：{len(proxies)}")

    # 阶段一：TCP 预过滤
    survivors = await _tcp_prefilter(
        proxies,
        max_workers=phase1_workers,
        timeout=phase1_timeout,
        keep_top_n=phase1_keep,
    )
    if not survivors:
        logger.warning("❌ 阶段一后无存活节点")
        return []

    # 阶段二：完整测速
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
        valid = await _fallback_test(
            survivors,
            max_workers=fallback_workers,
            timeout=float(test_timeout_s),
            latency_threshold=fallback_latency_threshold,
        )

    result = valid[:top_n]
    if result:
        logger.info(
            f"🎉 最终保留 {len(result)} 个节点 | "
            f"最快 {result[0].get('latency')}ms | "
            f"最慢 {result[-1].get('latency')}ms"
        )
    else:
        logger.warning("⚠️ 无节点通过筛选")

    return result
