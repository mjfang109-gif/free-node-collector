import yaml
import logging
from pathlib import Path
from utils import get_country_code_from_name # 导入新的工具函数

logger = logging.getLogger(__name__)

def generate_clash_subscription(proxies: list, dist_dir: Path, max_proxies: int = 300):
    """生成 Clash 配置文件 (YAML 格式)。"""
    if not proxies:
        logger.warning("Clash 生成器：没有可用的节点。")
        return

    proxies_to_use = proxies[:max_proxies]
    proxy_names = [p["name"] for p in proxies_to_use]

    proxy_groups = [
        {"name": "🚀 节点选择", "type": "select", "proxies": ["♻️ 自动选择", "🔮 故障转移"] + proxy_names},
        {"name": "♻️ 自动选择", "type": "url-test", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": proxy_names},
        {"name": "🔮 故障转移", "type": "fallback", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": proxy_names}
    ]
    
    country_groups = {}
    for proxy in proxies_to_use:
        # 修正：使用新的工具函数
        code = get_country_code_from_name(proxy['name'])
        if code != "未知":
            if code not in country_groups: country_groups[code] = []
            country_groups[code].append(proxy['name'])
            
    for code, names in country_groups.items():
        proxy_groups.append({"name": f"🌍 {code}", "type": "select", "proxies": ["🚀 节点选择"] + names})

    template = {
        "port": 7890, "socks-port": 7891, "allow-lan": True, "mode": "rule",
        "log-level": "info", "external-controller": '127.0.0.1:9090',
        "proxies": proxies_to_use, "proxy-groups": proxy_groups,
        "rules": [
            "DOMAIN-SUFFIX,google.com,🚀 节点选择", "DOMAIN-SUFFIX,github.com,🚀 节点选择",
            "DOMAIN-SUFFIX,youtube.com,🚀 节点选择", "DOMAIN-KEYWORD,telegram,🚀 节点选择",
            "GEOIP,CN,DIRECT", "MATCH,🚀 节点选择"
        ]
    }

    file_path = dist_dir / "clash.yaml"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(template, f, allow_unicode=True, sort_keys=False, default_flow_style=False, indent=2)
        logger.info(f"✅ Clash 订阅生成完成 → {file_path}")
    except Exception as e:
        logger.error(f"❌ 生成 Clash 配置文件失败: {e}", exc_info=True)
