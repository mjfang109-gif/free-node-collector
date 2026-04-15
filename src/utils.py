import re
import ipaddress

COUNTRY_INFO = {
    'US': {'flag': '🇺🇸', 'keywords': ['美国', 'US', 'United States', 'USA']},
    'HK': {'flag': '🇭🇰', 'keywords': ['香港', 'HK', 'Hong Kong']},
    'JP': {'flag': '🇯🇵', 'keywords': ['日本', 'JP', 'Japan']},
    'SG': {'flag': '🇸🇬', 'keywords': ['新加坡', 'SG', 'Singapore']},
    'TW': {'flag': '🇹🇼', 'keywords': ['台湾', 'TW', 'Taiwan', 'ROC']},
    'GB': {'flag': '🇬🇧', 'keywords': ['英国', 'GB', 'United Kingdom', 'UK']},
    'CA': {'flag': '🇨🇦', 'keywords': ['加拿大', 'CA', 'Canada']},
    'DE': {'flag': '🇩🇪', 'keywords': ['德国', 'DE', 'Germany']},
    'FR': {'flag': '🇫🇷', 'keywords': ['法国', 'FR', 'France']},
    'AU': {'flag': '🇦🇺', 'keywords': ['澳大利亚', 'AU', 'Australia']},
    'KR': {'flag': '🇰🇷', 'keywords': ['韩国', 'KR', 'Korea']},
    'RU': {'flag': '🇷🇺', 'keywords': ['俄罗斯', 'RU', 'Russia']},
    'NL': {'flag': '🇳🇱', 'keywords': ['荷兰', 'NL', 'Netherlands']},
    'IE': {'flag': '🇮🇪', 'keywords': ['爱尔兰', 'IE', 'Ireland']},
}

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def _is_garbage_name(name: str) -> bool:
    """判断名称是否是无意义的垃圾值（纯数字、IP地址、过短）。"""
    if not name or len(name.strip()) < 2:
        return True
    stripped = name.strip()
    # 纯数字（序号）
    if stripped.isdigit():
        return True
    # IP 地址
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass
    return False


def clean_node_name(proxy: dict) -> str:
    """
    智能净化节点名称。
    修复：当名称是纯数字/IP/垃圾时，生成可读的 [旗帜][协议]-[地区] 格式。
    """
    original_name = proxy.get("name", "")
    country_code, country_flag = get_country_info_from_name(original_name)

    # 1. 移除所有 Emoji
    cleaned_name = EMOJI_PATTERN.sub('', original_name)

    # 2. 移除广告标签（注意：不要删括号内有意义的地区信息！）
    patterns_to_remove = [
        r'@[a-zA-Z0-9_]+',
        r'(?i)telegram',
        r'(?i)youtube',
        r'(?i)www\.[a-zA-Z0-9-]+\.[a-z]+',
        r'[a-zA-Z0-9-]+\.(tech|xyz|top|shop)',
        r'(?i)powered by\s.*',
        r'#\S+',
    ]
    for pattern in patterns_to_remove:
        cleaned_name = re.sub(pattern, '', cleaned_name)

    # 3. 清理多余空格和边界符号
    cleaned_name = ' '.join(cleaned_name.split()).strip(' -_|=')

    # 4. 如果是垃圾名称，尝试从 server 域名推断地区，生成可读名称
    if _is_garbage_name(cleaned_name):
        proxy_type = proxy.get("type", "proxy").upper()
        server = proxy.get("server", "")

        # 尝试从 server 域名再提取一次国家信息
        if not country_flag:
            country_code, country_flag = get_country_info_from_name(server)

        # 生成可读名称：[协议]-[国家代码 或 服务器前缀]
        if country_code and country_code != "未知":
            cleaned_name = f"{proxy_type}-{country_code}"
        else:
            # 取域名的第一段作为标识，比纯数字好看得多
            server_label = server.split('.')[0][:12] if server else "unknown"
            cleaned_name = f"{proxy_type}-{server_label}"

    # 5. 组合旗帜
    if country_flag:
        return f"{country_flag} {cleaned_name}"
    return cleaned_name

def get_country_info_from_name(name: str):
    """从节点名称中提取国家信息（代码和旗帜）。"""
    if not name:
        return "未知", ""
    for code, info in COUNTRY_INFO.items():
        for keyword in info['keywords']:
            if re.search(r'\b' + re.escape(keyword) + r'\b', name, re.IGNORECASE) or keyword in name:
                return code, info['flag']
    return "未知", ""
