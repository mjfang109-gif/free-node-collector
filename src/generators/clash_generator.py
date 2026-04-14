"""
clash_generator.py - 生成合法的 Clash/Mihomo 配置文件

【本次主要修复】
1. SS 节点 cipher 字段不能为 "auto"，需过滤/替换为合法值
2. 清洗所有代理字段，移除 None 值和 Clash 不认识的自定义字段
3. 修复 VMess cipher 字段默认值问题
4. 为 hy2/hysteria2 节点生成正确的 Clash Meta 格式
5. 增加严格的字段校验，保证生成的 YAML 导入不报错
"""

import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── SS 合法加密方式白名单 ──────────────────────────────────────────
# "auto" 不在此列，来源节点中的 "auto" 必须被丢弃
SS_VALID_CIPHERS = {
    "aes-128-gcm", "aes-256-gcm", "aes-128-cfb", "aes-256-cfb",
    "aes-128-ctr", "aes-192-ctr", "aes-256-ctr",
    "rc4-md5", "chacha20", "chacha20-ietf",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
}

# ── VMess 合法加密方式 ────────────────────────────────────────────
VMESS_VALID_CIPHERS = {"auto", "aes-128-gcm", "chacha20-poly1305", "none"}

# ── 各协议在 Clash YAML 中允许出现的字段 ─────────────────────────
# 只保留合法字段，其余全部剔除，防止 Clash 解析报错
ALLOWED_FIELDS = {
    "ss": {
        "name", "type", "server", "port", "cipher", "password",
        "udp", "plugin", "plugin-opts",
    },
    "vmess": {
        "name", "type", "server", "port", "uuid", "alterId", "cipher",
        "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
        "http-opts", "grpc-opts", "servername", "udp",
    },
    "vless": {
        "name", "type", "server", "port", "uuid", "flow",
        "tls", "skip-cert-verify", "network", "ws-opts", "h2-opts",
        "reality-opts", "servername", "sni", "udp",
    },
    "trojan": {
        "name", "type", "server", "port", "password",
        "tls", "skip-cert-verify", "sni", "network",
        "ws-opts", "grpc-opts", "udp",
    },
    "hy2": {
        "name", "type", "server", "port", "password",
        "sni", "skip-cert-verify", "obfs", "obfs-password",
        "fingerprint", "alpn", "ca", "ca-str", "cwnd", "udp",
    },
    "hysteria2": {
        "name", "type", "server", "port", "password",
        "sni", "skip-cert-verify", "obfs", "obfs-password",
        "fingerprint", "alpn", "ca", "ca-str", "cwnd", "udp",
    },
    "http": {
        "name", "type", "server", "port", "username", "password",
        "tls", "skip-cert-verify", "sni", "headers", "udp",
    },
    "socks5": {
        "name", "type", "server", "port", "username", "password",
        "tls", "skip-cert-verify", "udp",
    },
}


def _sanitize_proxy(proxy: dict) -> dict | None:
    """
    清洗单个代理节点，确保其字段完全符合 Clash 规范。

    返回 None 表示该节点不合法，应被丢弃。
    """
    proxy_type = str(proxy.get("type", "")).lower()

    # ── 必填字段校验 ──────────────────────────────────────────────
    if not proxy.get("server") or not isinstance(proxy.get("port"), int):
        logger.debug(f"丢弃：缺少 server/port → {proxy.get('name')}")
        return None

    # ── 协议特定校验 ──────────────────────────────────────────────

    if proxy_type == "ss":
        cipher = str(proxy.get("cipher", "")).lower().strip()
        if cipher not in SS_VALID_CIPHERS:
            # "auto" 是最常见的非法值，直接丢弃整个节点
            logger.debug(f"丢弃 SS 节点（非法 cipher='{cipher}'）：{proxy.get('name')}")
            return None
        if not proxy.get("password"):
            logger.debug(f"丢弃 SS 节点（缺少 password）：{proxy.get('name')}")
            return None

    elif proxy_type == "vmess":
        if not proxy.get("uuid"):
            logger.debug(f"丢弃 VMess 节点（缺少 uuid）：{proxy.get('name')}")
            return None
        # VMess cipher 不合法时重置为 "auto"（auto 对 vmess 是合法的）
        cipher = str(proxy.get("cipher", "auto")).lower()
        if cipher not in VMESS_VALID_CIPHERS:
            proxy["cipher"] = "auto"
        # alterId 必须是整数
        proxy["alterId"] = int(proxy.get("alterId") or 0)

    elif proxy_type == "vless":
        if not proxy.get("uuid"):
            logger.debug(f"丢弃 VLess 节点（缺少 uuid）：{proxy.get('name')}")
            return None

    elif proxy_type in ("trojan",):
        if not proxy.get("password"):
            logger.debug(f"丢弃 Trojan 节点（缺少 password）：{proxy.get('name')}")
            return None

    elif proxy_type in ("hy2", "hysteria2"):
        if not proxy.get("password"):
            logger.debug(f"丢弃 Hy2 节点（缺少 password）：{proxy.get('name')}")
            return None
        # 统一使用 "hy2" 类型（Clash Meta 支持）
        proxy["type"] = "hy2"
        proxy_type = "hy2"

    # ── 字段白名单过滤 ────────────────────────────────────────────
    allowed = ALLOWED_FIELDS.get(proxy_type)
    if allowed:
        clean = {k: v for k, v in proxy.items() if k in allowed and v is not None}
    else:
        # 未知协议：只保留基本字段
        clean = {k: v for k, v in proxy.items() if v is not None}

    # ── 清理 ws-opts 中的空字段 ───────────────────────────────────
    if "ws-opts" in clean and isinstance(clean["ws-opts"], dict):
        clean["ws-opts"] = {k: v for k, v in clean["ws-opts"].items() if v is not None and v != ""}
        if not clean["ws-opts"]:
            del clean["ws-opts"]

    # ── 确保 name 字段存在 ────────────────────────────────────────
    if not clean.get("name"):
        clean["name"] = f"{proxy_type.upper()}-{clean['server']}:{clean['port']}"

    return clean


def generate_clash_subscription(
        proxies: list,
        dist_dir: Path,
        filename: str = "clash.yaml",
        max_proxies: int = 300,
):
    """
    生成合法的 Clash/Mihomo 配置文件（YAML 格式）。

    主要改进：
    - 严格清洗每个节点字段，杜绝 "cipher: auto" 等非法值
    - 使用 allow_unicode=True 正确输出 emoji 国旗
    - 生成更完整的 proxy-groups 结构
    """
    if not proxies:
        logger.warning(f"Clash 生成器：没有可用节点来生成 {filename}。")
        return

    # ── 步骤1：清洗节点 ──────────────────────────────────────────
    clean_proxies = []
    skipped = 0
    for proxy in proxies[:max_proxies]:
        sanitized = _sanitize_proxy(dict(proxy))  # 深拷贝避免污染原数据
        if sanitized:
            clean_proxies.append(sanitized)
        else:
            skipped += 1

    logger.info(f"🧹 节点清洗完成：保留 {len(clean_proxies)} 个，丢弃 {skipped} 个非法节点。")

    if not clean_proxies:
        logger.warning(f"⚠️ 清洗后无可用节点，跳过生成 {filename}。")
        return

    # ── 步骤2：确保名称唯一 ───────────────────────────────────────
    seen_names: set[str] = set()
    for proxy in clean_proxies:
        original = proxy["name"]
        name = original
        counter = 1
        while name in seen_names:
            name = f"{original}_{counter}"
            counter += 1
        proxy["name"] = name
        seen_names.add(name)

    # ── 步骤3：构建 proxy-groups ──────────────────────────────────
    proxy_names = [p["name"] for p in clean_proxies]

    proxy_groups = [
        {
            "name": "🚀 节点选择",
            "type": "select",
            "proxies": ["♻️ 自动选择", "🔮 故障转移", "DIRECT"] + proxy_names,
        },
        {
            "name": "♻️ 自动选择",
            "type": "url-test",
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 50,
            "proxies": proxy_names,
        },
        {
            "name": "🔮 故障转移",
            "type": "fallback",
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
            "proxies": proxy_names,
        },
    ]

    # 按地区分组
    from utils import get_country_info_from_name
    country_groups: dict[str, list[str]] = {}
    for proxy in clean_proxies:
        code, _ = get_country_info_from_name(proxy["name"])
        if code != "未知":
            country_groups.setdefault(code, []).append(proxy["name"])

    for code, names in sorted(country_groups.items()):
        proxy_groups.append({
            "name": f"🌍 {code}",
            "type": "select",
            "proxies": ["🚀 节点选择"] + names,
        })

    # ── 步骤4：构建完整配置 ───────────────────────────────────────
    config = {
        "mixed-port": 7890,
        "allow-lan": True,
        "bind-address": "*",
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "ipv6": False,
            "default-nameserver": ["114.114.114.114", "8.8.8.8"],
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "nameserver": ["https://doh.pub/dns-query", "https://dns.alidns.com/dns-query"],
            "fallback": ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"],
        },
        "proxies": clean_proxies,
        "proxy-groups": proxy_groups,
        "rules": [
            "DOMAIN-SUFFIX,google.com,🚀 节点选择",
            "DOMAIN-SUFFIX,googleapis.com,🚀 节点选择",
            "DOMAIN-SUFFIX,github.com,🚀 节点选择",
            "DOMAIN-SUFFIX,youtube.com,🚀 节点选择",
            "DOMAIN-KEYWORD,telegram,🚀 节点选择",
            "DOMAIN-KEYWORD,openai,🚀 节点选择",
            "GEOIP,LAN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 节点选择",
        ],
    }

    # ── 步骤5：写入文件 ───────────────────────────────────────────
    file_path = dist_dir / filename
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(
                config, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                indent=2,
            )
        logger.info(f"✅ Clash 配置生成完成（{len(clean_proxies)} 个节点）→ {file_path.name}")
    except Exception as e:
        logger.error(f"❌ 生成 Clash 配置文件 {filename} 失败: {e}", exc_info=True)
