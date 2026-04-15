"""
parsers/__init__.py - 通用解析器

【本次修复】
1. 优化 Base64 解码逻辑：大多数信源是「每行一个节点链接」的纯文本，不是整体 Base64
   旧逻辑：先尝试整体 Base64 解码 → 解码成功但内容乱码 → 解析出 0 个节点
   新逻辑：先逐行扫描是否有明确的协议前缀 → 有则直接按行解析 → 否则才尝试 Base64
2. 解决部分 Base64 内容「解码成功但内容是乱码节点」的问题
"""

import logging
import base64
from .clash_parser import parse_clash
from .v2ray_parser import parse_vless_link, parse_trojan_link, parse_vmess_link
from .ss_parser import parse_ss_link
from .hy2_parser import parse_hy2_link

logger = logging.getLogger(__name__)

# 已知协议前缀
KNOWN_PREFIXES = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hy2://", "hysteria2://")


def _parse_line(line: str):
    """解析单行文本，自动识别协议并返回代理字典。"""
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


def _has_proxy_links(text: str) -> bool:
    """快速判断文本中是否包含代理链接（用于决定是否跳过 Base64 解码）。"""
    for line in text.splitlines()[:20]:  # 只检查前20行，够快
        line = line.strip()
        if any(line.startswith(prefix) for prefix in KNOWN_PREFIXES):
            return True
    return False


def _try_base64_decode(content: str) -> list[str] | None:
    """
    安全地尝试 Base64 解码。
    返回解码后的行列表，如果解码失败或结果不像节点内容则返回 None。
    """
    # 过滤掉明显不是 Base64 的内容
    stripped = content.strip()
    if stripped.startswith('<'):  # HTML
        return None
    if stripped.startswith('{') or stripped.startswith('['):  # JSON
        return None
    if stripped.startswith('proxies:') or stripped.startswith('rules:'):  # Clash YAML
        return None

    try:
        # 移除空白字符后尝试解码
        cleaned = stripped.replace('\n', '').replace('\r', '').replace(' ', '')
        # Base64 字符串只包含这些字符
        import re
        if not re.match(r'^[A-Za-z0-9+/=_-]+$', cleaned[:100]):
            return None

        decoded = base64.b64decode(cleaned + "==").decode("utf-8", errors="ignore")
        lines = decoded.splitlines()

        # 验证解码结果是否真的包含节点链接
        valid_lines = [l for l in lines if any(l.strip().startswith(p) for p in KNOWN_PREFIXES)]
        if valid_lines:
            logger.debug(f"Base64 解码成功，包含 {len(valid_lines)} 个节点链接")
            return lines
        return None

    except Exception:
        return None


def universal_parser(content: str, source_type: str = None) -> list:
    """
    通用解析器，健壮地处理各种格式的信源内容。

    支持的格式：
    1. Clash YAML (type=clash)
    2. 每行一个代理链接的纯文本（最常见）
    3. Base64 编码的订阅内容
    4. 混合内容（含链接的 HTML 等）
    """
    if not content:
        return []

    # ── 格式1：Clash YAML ─────────────────────────────────────────
    if source_type == 'clash':
        return parse_clash(content)

    proxies = []
    lines_to_parse = []

    # ── 格式2：优先检测是否是纯文本链接列表 ──────────────────────
    # 大多数信源（matinghanbari、ebrasha 等）都是每行一个纯文本链接，
    # 不需要也不应该尝试 Base64 解码
    if _has_proxy_links(content):
        logger.debug("检测到纯文本节点链接格式，直接逐行解析。")
        lines_to_parse = content.splitlines()

    # ── 格式3：尝试 Base64 解码 ───────────────────────────────────
    else:
        decoded_lines = _try_base64_decode(content)
        if decoded_lines is not None:
            logger.debug(f"内容为 Base64 编码订阅，解码后共 {len(decoded_lines)} 行。")
            lines_to_parse = decoded_lines
        else:
            # 兜底：直接按行处理（处理含节点链接的 HTML 等混合内容）
            logger.debug("内容非 Base64，按纯文本逐行处理。")
            lines_to_parse = content.splitlines()

    # ── 逐行解析 ──────────────────────────────────────────────────
    for line in lines_to_parse:
        proxy = _parse_line(line)
        if proxy:
            proxies.append(proxy)

    return proxies