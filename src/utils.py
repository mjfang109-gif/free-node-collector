import re

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

def get_country_info_from_name(name: str):
    """从节点名称中提取国家信息（代码和旗帜）。"""
    if not name:
        return "未知", ""
    for code, info in COUNTRY_INFO.items():
        for keyword in info['keywords']:
            if re.search(r'\b' + re.escape(keyword) + r'\b', name, re.IGNORECASE) or keyword in name:
                return code, info['flag']
    return "未知", ""

def clean_node_name(proxy: dict):
    """
    智能净化节点名称，并确保名称的唯一性。
    """
    original_name = proxy.get("name", "")
    
    country_code, country_flag = get_country_info_from_name(original_name)
    
    # 1. 移除所有 Emoji
    cleaned_name = EMOJI_PATTERN.sub('', original_name)
    
    # 2. 移除常见的广告标签和多余字符
    patterns_to_remove = [
        r'\[.*?\]', r'\{.*?\}', r'\(.*?\)',
        r'@[a-zA-Z0-9_]+',
        r'(?i)telegram', r'(?i)youtube',
        r'(?i)www\.[a-zA-Z0-9-]+\.[a-z]+',
        r'[a-zA-Z0-9-]+\.(tech|xyz|top|shop)',
        r'by\s.*', r'Powered by',
        r'#\S+', # 移除 # 开头的话题标签
    ]
    for pattern in patterns_to_remove:
        cleaned_name = re.sub(pattern, '', cleaned_name)
        
    # 3. 清理多余的空格和特殊字符
    cleaned_name = ' '.join(cleaned_name.split()).strip(' -_|=')
    
    # 4. 修正：如果净化后名字为空，则生成一个唯一的备用名
    if not cleaned_name:
        proxy_type = proxy.get("type", "Proxy")
        server = proxy.get("server", "unknown.server")
        port = proxy.get("port", "0")
        # 使用 hash 值确保在 server:port 相同但其他信息不同时也能有区分
        unique_suffix = hash(f"{proxy_type}-{server}-{port}") % 10000 # 取模确保后缀短
        cleaned_name = f"{proxy_type.upper()}-{server}:{port}-{unique_suffix}"
        
    # 5. 最终组合: [旗帜] [净化后的名称]
    if country_flag:
        return f"{country_flag} {cleaned_name}"
    
    return cleaned_name
