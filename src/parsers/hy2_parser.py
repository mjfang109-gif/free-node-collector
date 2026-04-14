import logging
import re
from urllib.parse import urlparse, unquote, quote, urlencode, parse_qs

logger = logging.getLogger(__name__)

def _preprocess_ipv6_link(link: str) -> str:
    """预处理链接，为其中的 IPv6 地址加上方括号，以兼容 urllib.parse。"""
    # 正则表达式匹配 "protocol://userinfo@ipv6_address:port..."
    # 它会捕获协议、用户信息、IPv6地址和端口及之后的部分
    match = re.match(r'^(hy2://[^@]+@)([0-9a-fA-F:]{10,})(:.+)$', link)
    if match:
        protocol_user, ipv6_addr, port_and_rest = match.groups()
        # 重组成带方括号的标准格式
        return f"{protocol_user}[{ipv6_addr}]{port_and_rest}"
    return link

def parse_hy2_link(hy2_link: str):
    """
    健壮地解析 Hy2 (Hysteria2) 链接，兼容 IPv6 地址。
    """
    try:
        # 修正：预处理链接以支持无方括号的 IPv6 地址
        processed_link = _preprocess_ipv6_link(hy2_link)
        parsed = urlparse(processed_link)
        
        # 修正：检查解析结果是否有效
        if not parsed.hostname or not parsed.port:
            raise ValueError("链接缺少主机名或端口")

        server = parsed.hostname
        port = int(parsed.port) # 在这里转换，如果失败会直接进入 except
        password = parsed.username
        name = unquote(parsed.fragment) if parsed.fragment else f"Hy2-{server}:{port}"
        
        query_params = parse_qs(parsed.query)
        sni = query_params.get('sni', [None])[0]
        insecure = query_params.get('insecure', ['0'])[0] == '1'
        
        return {
            "name": name, "type": "hy2", "server": server,
            "port": port, "password": password,
            "sni": sni, "skip-cert-verify": insecure,
        }
    except Exception as e:
        logger.debug(f"解析 Hy2 链接失败: {hy2_link[:40]}...", exc_info=True)
        return None

def proxy_to_hy2_link(proxy: dict):
    """
    将标准代理字典转换回 hy2:// 链接。
    """
    try:
        if proxy.get("type") != "hy2":
            return None
        
        server = proxy["server"]
        # 如果是 IPv6 地址，在生成链接时加上方括号
        if ':' in server:
            server = f"[{server}]"
            
        port = proxy["port"]
        password = proxy.get("password", "")
        name = proxy.get("name", f"Hy2-{server}:{port}")

        query_params = {}
        if proxy.get("sni"):
            query_params["sni"] = proxy["sni"]
        if proxy.get("skip-cert-verify"):
            query_params["insecure"] = "1"
        
        query_string = urlencode(query_params) if query_params else ""

        link = f"hy2://{password}@{server}:{port}"
        if query_string:
            link += f"?{query_string}"
        if name:
            link += f"#{quote(name)}"
            
        return link
    except Exception as e:
        logger.error(f"转换 Hy2 链接失败: {proxy.get('name', 'Unknown')}", exc_info=True)
        return None
