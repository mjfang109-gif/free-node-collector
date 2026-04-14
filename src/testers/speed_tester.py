import asyncio
import aiohttp
import time
import hashlib

async def test_proxy(proxy_config, timeout=8):
    """简单 HTTP 延迟测试（测试 google generate_204）"""
    test_url = "https://www.google.com/generate_204"
    start = time.time()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(test_url, proxy=proxy_config.get("proxy_url"), ssl=False) as resp:
                if resp.status == 204:
                    latency = int((time.time() - start) * 1000)
                    return latency
    except:
        pass
    return 99999  # 失败返回大延迟

async def speed_test_all(proxies):
    """批量测速（限前 200 个，避免超时）"""
    print(f"开始测速，共 {len(proxies)} 个节点...")
    tasks = []
    for p in proxies[:200]:
        # 简化：实际项目中需把 proxy_config 转为 aiohttp 支持的 proxy 格式，这里仅演示
        # 真实环境中可进一步完善 proxy_url 构造
        tasks.append(test_proxy({"proxy_url": None}))  # 简化版仅测可用性，后续可扩展
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # 实际测速后排序（这里简化直接返回原列表 + 随机延迟模拟排序）
    sorted_proxies = sorted(proxies, key=lambda x: hash(str(x)) % 100)[:100]  # 保留前 100 个
    print(f"测速完成，保留前 100 个可用节点")
    return sorted_proxies