import base64
import logging
import re
from urllib.parse import unquote, quote

logger = logging.getLogger(__name__)

def _decode_base64(data: str) -> str:
    data = re.sub(r'[^A-Za-z0-9+/=]', '', data)
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode('utf-8', errors='ignore')

def parse_ss_link(ss_link: str):
    try:
        if not ss_link.startswith('ss://'):
            return None
        link_part = ss_link[5:].split('#', 1)[0]
        name_part = unquote(ss_link.split('#', 1)[1]) if '#' in ss_link else ''

        # 格式1: ss://<base64(cipher:pass)>@server:port
        if '@' in link_part:
            try:
                encoded_part, server_info = link_part.split('@', 1)
                decoded_user_info = _decode_base64(encoded_part)
                if ':' in decoded_user_info:
                    cipher, password = decoded_user_info.split(':', 1)
                    server, port_str = server_info.rsplit(':', 1)
                    return {
                        "name": name_part or f"SS-{server}:{port_str.strip()}",
                        "type": "ss", "server": server,
                        "port": int(port_str.strip()),
                        "cipher": cipher, "password": password,
                    }
            except Exception:
                pass

        # 格式2: ss://<base64(cipher:pass@server:port)>
        try:
            decoded_full = _decode_base64(link_part)
            if '@' in decoded_full:
                user_info, server_info = decoded_full.rsplit('@', 1)
                cipher, password = user_info.split(':', 1)
                server, port_str  = server_info.rsplit(':', 1)
                return {
                    "name": name_part or f"SS-{server}:{port_str.strip()}",
                    "type": "ss", "server": server,
                    "port": int(port_str.strip()),
                    "cipher": cipher, "password": password,
                }
        except Exception:
            pass

        logger.debug(f"解析 SS 链接失败: {ss_link[:40]}...")
        return None
    except Exception as e:
        logger.debug(f"解析 SS 链接意外错误: {ss_link[:40]}...", exc_info=True)
        return None

def proxy_to_ss_link(proxy: dict):
    try:
        if proxy.get("type") != "ss":
            return None
        user_info = f'{proxy["cipher"]}:{proxy["password"]}'
        encoded   = base64.urlsafe_b64encode(user_info.encode('utf-8')).decode('utf-8').rstrip('=')
        tag = quote(proxy.get("name", ""))
        return f'ss://{encoded}@{proxy["server"]}:{proxy["port"]}#{tag}'
    except Exception as e:
        logger.error(f"转换 SS 链接失败: {proxy.get('name', 'Unknown')}", exc_info=True)
        return None
