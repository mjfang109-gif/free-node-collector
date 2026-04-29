import re
import ipaddress

# 品牌名称配置 - 可修改，用于订阅标识和节点命名
BRAND_NAME = "NodeHub"

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
    'TR': {'flag': '🇹🇷', 'keywords': ['土耳其', 'TR', 'Turkey']},
    'IN': {'flag': '🇮🇳', 'keywords': ['印度', 'IN', 'India']},
    'BR': {'flag': '🇧🇷', 'keywords': ['巴西', 'BR', 'Brazil']},
    'FI': {'flag': '🇫🇮', 'keywords': ['芬兰', 'FI', 'Finland']},
    'SE': {'flag': '🇸🇪', 'keywords': ['瑞典', 'SE', 'Sweden']},
    'NO': {'flag': '🇳🇴', 'keywords': ['挪威', 'NO', 'Norway']},
}

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def _is_garbage_name(name: str) -> bool:
    if not name or len(name.strip()) < 2:
        return True
    stripped = name.strip()
    if stripped.isdigit():
        return True
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass
    return False


def clean_node_name(proxy: dict) -> str:
    original_name = proxy.get("name", "")
    country_code, country_flag = get_country_info_from_name(original_name)

    cleaned_name = EMOJI_PATTERN.sub('', original_name)

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

    cleaned_name = ' '.join(cleaned_name.split()).strip(' -_|=')

    if _is_garbage_name(cleaned_name):
        proxy_type = proxy.get("type", "proxy").upper()
        server = proxy.get("server", "")
        if not country_flag:
            country_code, country_flag = get_country_info_from_name(server)
        if country_code and country_code != "未知":
            cleaned_name = f"{proxy_type}-{country_code}"
        else:
            server_label = server.split('.')[0][:12] if server else "unknown"
            cleaned_name = f"{proxy_type}-{server_label}"

    if country_flag:
        cleaned_name = f"{country_flag} {cleaned_name}"

    # 添加品牌前缀
    if not cleaned_name.startswith(f"{BRAND_NAME} "):
        cleaned_name = f"{BRAND_NAME} {cleaned_name}"

    return cleaned_name


def get_country_info_from_name(name: str):
    if not name:
        return "未知", ""
    for code, info in COUNTRY_INFO.items():
        for keyword in info['keywords']:
            if re.search(r'\b' + re.escape(keyword) + r'\b', name, re.IGNORECASE) or keyword in name:
                return code, info['flag']
    return "未知", ""
