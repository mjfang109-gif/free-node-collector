"""
parsers/__init__.py - 通用解析器

解析优先级：
1. Clash YAML (type=clash)
2. 纯文本节点链接列表（每行一个，最常见）
3. Base64 编码订阅
4. 混合内容兜底（含链接的 HTML 等）
"""

import logging
import base64
import re
from .clash_parser import parse_clash
from .v2ray_parser import parse_vless_link, parse_trojan_link, parse_vmess_link
from .ss_parser import parse_ss_link
from .hy2_parser import parse_hy2_link

logger = logging.getLogger(__name__)

KNOWN_PREFIXES = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hy2://", "hysteria2://")


def _parse_line(line: str):
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
    for line in text.splitlines()[:20]:
        line = line.strip()
        if any(line.startswith(prefix) for prefix in KNOWN_PREFIXES):
            return True
    return False


def _try_base64_decode(content: str):
    stripped = content.strip()
    if stripped.startswith(('<', '{', '[', 'proxies:', 'rules:')):
        return None
    try:
        cleaned = stripped.replace('\n', '').replace('\r', '').replace(' ', '')
        if not re.match(r'^[A-Za-z0-9+/=_-]+$', cleaned[:100]):
            return None
        decoded = base64.b64decode(cleaned + "==").decode("utf-8", errors="ignore")
        lines = decoded.splitlines()
        valid_lines = [l for l in lines if any(l.strip().startswith(p) for p in KNOWN_PREFIXES)]
        if valid_lines:
            logger.debug(f"Base64 解码成功，包含 {len(valid_lines)} 个节点链接")
            return lines
        return None
    except Exception:
        return None


def universal_parser(content: str, source_type: str = None) -> list:
    if not content:
        return []

    if source_type == 'clash':
        return parse_clash(content)

    proxies = []
    if _has_proxy_links(content):
        lines_to_parse = content.splitlines()
    else:
        decoded_lines = _try_base64_decode(content)
        lines_to_parse = decoded_lines if decoded_lines is not None else content.splitlines()

    for line in lines_to_parse:
        proxy = _parse_line(line)
        if proxy:
            proxies.append(proxy)

    return proxies
