import base64
import json
import logging
from urllib.parse import urlparse, unquote, parse_qs, quote, urlencode

logger = logging.getLogger(__name__)


def parse_vmess_link(vmess_link: str):
    """解析 vmess:// 链接。"""
    try:
        decoded_str = base64.b64decode(vmess_link[8:]).decode("utf-8", errors="ignore")
        config = json.loads(decoded_str)

        # ps 为纯数字或空时留空，由 clean_node_name 后续处理
        ps = config.get("ps", "")
        name = ps if ps and not str(ps).strip().isdigit() else ""

        ws_opts = None
        if config.get("net") == "ws":
            ws_opts = {"path": config.get("path", "") or "/"}
            if config.get("host"):
                ws_opts["headers"] = {"Host": config["host"]}

        return {
            "name":    name,
            "type":    "vmess",
            "server":  config.get("add"),
            "port":    int(config.get("port")),
            "uuid":    config.get("id"),
            "alterId": int(config.get("aid", 0)),
            "cipher":  "auto",
            "tls":     config.get("tls") == "tls",
            "network": config.get("net"),
            "ws-opts": ws_opts,
        }
    except Exception:
        return None


def parse_vless_link(vless_link: str):
    """解析 vless:// 链接。"""
    try:
        parsed = urlparse(vless_link)
        if not parsed.port:
            raise ValueError("Port is missing")
        port = int(str(parsed.port).strip())

        query_params = parse_qs(parsed.query)
        security = query_params.get("security", ["none"])[0]
        network  = query_params.get("type", ["tcp"])[0]
        name     = unquote(parsed.fragment) if parsed.fragment else parsed.hostname

        ws_opts = None
        if network == "ws":
            ws_opts = {"path": query_params.get("path", ["/"])[0]}
            host = query_params.get("host", [None])[0]
            if host:
                ws_opts["headers"] = {"Host": host}

        # reality-opts
        reality_opts = None
        if security == "reality":
            public_key  = query_params.get("pbk", [None])[0]
            short_id    = query_params.get("sid", [None])[0]
            reality_opts = {}
            if public_key:
                reality_opts["public-key"] = public_key
            if short_id:
                reality_opts["short-id"] = short_id

        return {
            "name":          name,
            "type":          "vless",
            "server":        parsed.hostname,
            "port":          port,
            "uuid":          parsed.username,
            "tls":           security in ("tls", "reality"),
            "network":       network,
            "sni":           query_params.get("sni", [None])[0],
            "servername":    query_params.get("sni", [None])[0],
            "flow":          query_params.get("flow", [None])[0],
            "ws-opts":       ws_opts,
            "reality-opts":  reality_opts,
        }
    except Exception:
        return None


def parse_trojan_link(trojan_link: str):
    """解析 trojan:// 链接。"""
    try:
        parsed = urlparse(trojan_link)
        if not parsed.port:
            raise ValueError("Port is missing")
        port = int(str(parsed.port).strip())

        query_params = parse_qs(parsed.query)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname

        return {
            "name":             name,
            "type":             "trojan",
            "server":           parsed.hostname,
            "port":             port,
            "password":         parsed.username,
            "sni":              query_params.get("sni", [None])[0],
            "skip-cert-verify": query_params.get("allowInsecure", ["0"])[0] == "1",
        }
    except Exception:
        return None


# ── 反向转换：proxy dict → 链接字符串 ──────────────────────────────

def proxy_to_vmess_link(proxy: dict):
    """将代理字典转换为 vmess:// 链接。"""
    try:
        config = {
            "v":    "2",
            "ps":   proxy["name"],
            "add":  proxy["server"],
            "port": str(proxy["port"]),
            "id":   proxy["uuid"],
            "aid":  str(proxy.get("alterId", 0)),
            "net":  proxy.get("network", "tcp"),
            "type": "none",
            "host": "",
            "path": (proxy.get("ws-opts") or {}).get("path", ""),
            "tls":  "tls" if proxy.get("tls") else "",
        }
        # 移除空值，减小体积
        config = {k: v for k, v in config.items() if v or v == 0}
        json_str = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return "vmess://" + base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def proxy_to_vless_link(proxy: dict):
    """将代理字典转换为 vless:// 链接。"""
    try:
        params = {
            "type":     proxy.get("network", "tcp"),
            "security": "tls" if proxy.get("tls") else "none",
            "sni":      proxy.get("sni"),
            "path":     (proxy.get("ws-opts") or {}).get("path"),
            "flow":     proxy.get("flow"),
        }
        params = {k: v for k, v in params.items() if v is not None}
        query = urlencode(params)

        link = f"vless://{proxy['uuid']}@{proxy['server']}:{proxy['port']}"
        if query:
            link += f"?{query}"
        link += f"#{quote(proxy['name'])}"
        return link
    except Exception:
        return None


def proxy_to_trojan_link(proxy: dict):
    """将代理字典转换为 trojan:// 链接。"""
    try:
        params = {}
        if proxy.get("sni"):
            params["sni"] = proxy["sni"]
        query = f"?{urlencode(params)}" if params else ""
        return (
            f"trojan://{proxy['password']}@{proxy['server']}:{proxy['port']}"
            f"{query}#{quote(proxy['name'])}"
        )
    except Exception:
        return None
