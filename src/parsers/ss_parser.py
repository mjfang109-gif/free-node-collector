import base64
import logging
import re
from urllib.parse import unquote, quote

logger = logging.getLogger(__name__)

def _decode_base64(data: str) -> str:
    """安全地解码 Base64 字符串，自动处理 padding 和非 ASCII 字符。"""
    # 修正：移除所有非 Base64 字符
    data = re.sub(r'[^A-Za-z0-9+/=]', '', data)
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode('utf-8', errors='ignore')

def parse_ss_link(ss_link: str):
    """
    健壮地解析 SS (Shadowsocks) 链接。
    """
    try:
        # 修正：确保只处理 ss:// 协议
        if not ss_link.startswith('ss://'):
            return None

        link_part = ss_link[5:].split('#', 1)[0]
        name_part = unquote(ss_link.split('#', 1)[1]) if '#' in ss_link else ''

        # 尝试格式 1: <base64>@<server>:<port>
        if '@' in link_part:
            try:
                encoded_part, server_info = link_part.split('@', 1)
                decoded_user_info = _decode_base64(encoded_part)
                
                # 修正：严格检查格式
                if ':' not in decoded_user_info or decoded_user_info.count(':') != 1:
                    raise ValueError("格式不符合 cipher:password")

                cipher, password = decoded_user_info.split(':', 1)
                server, port_str = server_info.split(':', 1)
                port = int(port_str.strip())

                name = name_part or f"SS-{server}:{port}"
                return {
                    "name": name, "type": "ss", "server": server,
                    "port": port, "cipher": cipher, "password": password,
                }
            except Exception:
                pass # 失败则继续

        # 尝试格式 2: <base64>
        try:
            decoded_full = _decode_base64(link_part)
            
            # 修正：严格检查格式
            if '@' not in decoded_full or decoded_full.count('@') != 1 or decoded_full.count(':') != 2:
                 raise ValueError("格式不符合 cipher:password@server:port")

            user_info, server_info = decoded_full.split('@', 1)
            cipher, password = user_info.split(':', 1)
            server, port_str = server_info.split(':', 1)
            port = int(port_str.strip())

            name = name_part or f"SS-{server}:{port}"
            return {
                "name": name, "type": "ss", "server": server,
                "port": port, "cipher": cipher, "password": password,
            }
        except Exception as e:
            logger.debug(f"解析 SS 链接失败 (两种格式均尝试失败): {ss_link[:40]}...", exc_info=True)
            return None

    except Exception as e:
        logger.debug(f"解析 SS 链接时发生意外错误: {ss_link[:40]}...", exc_info=True)
        return None

def proxy_to_ss_link(proxy: dict):
    """
    将标准代理字典转换回 ss:// 链接 (使用最常见的格式 1)。
    """
    try:
        if proxy.get("type") != "ss":
            return None
        
        user_info = f'{proxy["cipher"]}:{proxy["password"]}'
        encoded_user_info = base64.urlsafe_b64encode(user_info.encode('utf-8')).decode('utf-8').rstrip('=')
        
        server_part = f'{proxy["server"]}:{proxy["port"]}'
        tag = quote(proxy.get("name", ""))
        
        return f'ss://{encoded_user_info}@{server_part}#{tag}'
    except Exception as e:
        logger.error(f"转换 SS 链接失败: {proxy.get('name', 'Unknown')}", exc_info=True)
        return None
