import asyncio
from config import load_sources
from collectors import UnifiedCollector, TelegramCollector
from parsers import parse_clash, parse_v2ray_base64
from testers.speed_tester import speed_test_all
from generators import generate_clash, generate_v2ray
from collectors import TelegramWebCollector
import hashlib


async def main():
    sources = load_sources()
    all_proxies = []
    all_v2ray_configs = []

    collector = UnifiedCollector()
    tg_collector = TelegramCollector()
    tg_web_collector = TelegramWebCollector()
    for source in sources:
        print(f"正在抓取: {source['name']}")
        data = None
        if source.get("type") == "telegram_web":
            data = tg_web_collector.fetch(source)
        else:
            data = collector.fetch(source) or tg_collector.fetch(source)

        if not data:
            continue

        if data["type"] == "clash":
            proxies = parse_clash(data["content"])
            all_proxies.extend(proxies)
        elif data["type"] == "v2ray_base64":
            configs = parse_v2ray_base64(data["content"])
            all_v2ray_configs.extend(configs)

    # 去重（简单 hash）
    seen = set()
    unique_proxies = []
    for p in all_proxies:
        h = hashlib.md5(str(p).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_proxies.append(p)

    # 测速排序
    sorted_proxies = await speed_test_all(unique_proxies)

    # 生成订阅
    generate_clash(sorted_proxies)
    generate_v2ray(all_v2ray_configs + [str(p) for p in sorted_proxies])  # 合并

    print("🎉 全部完成！节点已更新到 dist/ 目录")


if __name__ == "__main__":
    asyncio.run(main())
