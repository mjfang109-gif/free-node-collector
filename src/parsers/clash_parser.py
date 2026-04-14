import yaml


def parse_clash(content):
    try:
        data = yaml.safe_load(content)
        if not data or "proxies" not in data:
            return []
        proxies = data.get("proxies", [])
        print(f"从 Clash 解析到 {len(proxies)} 个节点")
        return proxies
    except Exception as e:
        print(f"Clash 解析失败: {e}")
        return []
