import base64
import json
import logging
from urllib.parse import urlparse, unquote, parse_qs, quote, urlencode

logger = logging.getLogger(__name__)

# --- 解析器部分: 链接 -> 字典 ---
# (parse_vmess_link, parse_vless_link, parse_trojan_link, parse_v2ray_base64 functions remain the same)
def parse_vmess_link(vmess_link: str):
    """解析 vmess:// 链接。"""
    try:
        decoded_str = base64.b64decode(vmess_link[8:]).decode("utf-8", errors='ignore')
        config = json.loads(decoded_str)
        name = config.get("ps", config.get("add"))
        return {
            "name": name, "type": "vmess", "server": config.get("add"),
            "port": int(config.get("port")), "uuid": config.get("id"),
            "alterId": int(config.get("aid")), "cipher": "auto",
            "tls": config.get("tls") == "tls", "network": config.get("net"),
            "ws-opts": {"path": config.get("path", "")} if config.get("net") == "ws" else None,
        }
    except Exception: return None
def parse_vless_link(vless_link: str):
    """解析 vless:// 链接。"""
    try:
        parsed = urlparse(vless_link)
        query_params = parse_qs(parsed.query)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname
        port = int(parsed.port.strip()) if parsed.port else 0
        return {
            "name": name, "type": "vless", "server": parsed.hostname,
            "port": port, "uuid": parsed.username,
            "tls": query_params.get('security', [None])[0] == 'tls',
            "network": query_params.get('type', ['tcp'])[0],
            "sni": query_params.get('sni', [None])[0],
            "ws-opts": {"path": query_params.get('path', ['/'])[0]} if query_params.get('type', ['tcp'])[0] == 'ws' else None,
        }
    except Exception: return None
def parse_trojan_link(trojan_link: str):
    """解析 trojan:// 链接。"""
    try:
        parsed = urlparse(trojan_link)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname
        port = int(parsed.port.strip()) if parsed.port else 0
        return {
            "name": name, "type": "trojan", "server": parsed.hostname,
            "port": port, "password": parsed.username,
        }
    except Exception: return None
def parse_v2ray_base64(content: str):
    """解析 Base64 编码的 V2Ray 订阅内容。"""
    try:
        decoded_content = base64.b64decode(content + "==").decode("utf-8", errors="ignore")
        return decoded_content.splitlines()
    except (ValueError, TypeError):
        return content.splitlines()

# --- 转换器部分: 字典 -> 链接 ---

def proxy_to_vmess_link(proxy: dict):
    """将代理字典转换为 vmess:// 链接。"""
    try:
        config = {
            "v": "2", "ps": proxy["name"], "add": proxy["server"],
            "port": str(proxy["port"]), "id": proxy["uuid"],
            "aid": str(proxy.get("alterId", 0)), "net": proxy.get("network", "tcp"),
            "type": "none", "host": "", "path": (proxy.get('ws-opts') or {}).get('path', ""),
            "tls": "tls" if proxy.get("tls") else ""
        }
        config = {k: v for k, v in config.items() if v}
        json_str = json.dumps(config, sort_keys=True)
        return "vmess://" + base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
    except Exception: return None

def proxy_to_vless_link(proxy: dict):
    """将代理字典转换为 vless:// 链接。"""
    try:
        params = {
            'type': proxy.get('network', 'tcp'),
            'security': 'tls' if proxy.get('tls') else 'none',
            'sni': proxy.get('sni'),
            'path': (proxy.get('ws-opts') or {}).get('path')
        }
        params = {k: v for k, v in params.items() if v is not None}
        query = urlencode(params)
        
        link = f"vless://{proxy['uuid']}@{proxy['server']}:{proxy['port']}"
        if query: link += f"?{query}"
        link += f"#{quote(proxy['name'])}"
        return link
    except Exception: return None

def proxy_to_trojan_link(proxy: dict):
    """将代理字典转换为 trojan:// 链接。"""
    try:
        return f"trojan://{proxy['password']}@{proxy['server']}:{proxy['port']}#{quote(proxy['name'])}"
    except Exception: return None
