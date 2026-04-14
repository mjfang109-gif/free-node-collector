import logging
import base64
from .clash_parser import parse_clash
from .v2ray_parser import parse_vless_link, parse_trojan_link, parse_vmess_link
from .ss_parser import parse_ss_link
from .hy2_parser import parse_hy2_link

logger = logging.getLogger(__name__)

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
    if line.startswith('hy2://'):
        return parse_hy2_link(line)
    if line.startswith('vmess://'):
        return parse_vmess_link(line)
        
    return None

def universal_parser(content: str, source_type: str):
    """
    通用解析器，能健壮地处理混合内容的信源。
    """
    if not content:
        return []

    if source_type == 'clash':
        return parse_clash(content)
        
    proxies = []
    lines_to_parse = []

    # 步骤 1: 尝试将整个内容作为 Base64 解码
    try:
        # 增加判断，避免对明显不是 Base64 的内容（如 HTML）进行解码
        if not content.strip().startswith('<'):
            decoded_content = base64.b64decode(content + "==").decode("utf-8", errors="ignore")
            lines_to_parse = decoded_content.splitlines()
            logger.debug(f"内容被成功识别为 Base64 订阅，共 {len(lines_to_parse)} 行。")
        else:
            raise ValueError("内容看起来像 HTML，跳过 Base64 解码。")
    except (ValueError, TypeError):
        # 步骤 2: 如果解码失败，则认为内容是纯文本链接列表
        logger.debug("内容不是有效的 Base64 编码，将按纯文本逐行处理。")
        lines_to_parse = content.splitlines()

    # 步骤 3: 逐行解析
    for line in lines_to_parse:
        proxy = _parse_line(line)
        if proxy:
            proxies.append(proxy)

    return proxies
