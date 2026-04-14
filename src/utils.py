import re

# 增强版国家/地区代码和名称的映射，增加了 Emoji 旗帜
COUNTRY_MAP = {
    'US': ['美国', 'US', 'United States', 'USA', '🇺🇸'],
    'HK': ['香港', 'HK', 'Hong Kong', '🇭🇰'],
    'JP': ['日本', 'JP', 'Japan', '🇯🇵'],
    'SG': ['新加坡', 'SG', 'Singapore', '🇸🇬'],
    'TW': ['台湾', 'TW', 'Taiwan', 'ROC', '🇹🇼'],
    'GB': ['英国', 'GB', 'United Kingdom', 'UK', '🇬🇧'],
    'CA': ['加拿大', 'CA', 'Canada', '🇨🇦'],
    'DE': ['德国', 'DE', 'Germany', '🇩🇪'],
    'FR': ['法国', 'FR', 'France', '🇫🇷'],
    'AU': ['澳大利亚', 'AU', 'Australia', '🇦🇺'],
    'KR': ['韩国', 'KR', 'Korea', '🇰🇷'],
    'RU': ['俄罗斯', 'RU', 'Russia', '🇷🇺'],
    'NL': ['荷兰', 'NL', 'Netherlands', '🇳🇱'],
    'IE': ['爱尔兰', 'IE', 'Ireland', '🇮🇪'],
    # ...可以继续添加更多...
}

def get_country_code_from_name(name: str):
    """
    从节点名称中提取国家/地区代码。
    通过关键字和 Emoji 旗帜进行匹配。

    :param name: 节点名称字符串。
    :return: 国家/地区代码字符串 (如 "US", "HK") 或 "未知"。
    """
    if not name:
        return "未知"
        
    for code, keywords in COUNTRY_MAP.items():
        for keyword in keywords:
            # 使用正则表达式确保匹配的是完整的单词或标志
            if re.search(r'\b' + re.escape(keyword) + r'\b', name, re.IGNORECASE) or keyword in name:
                return code
    return "未知"
