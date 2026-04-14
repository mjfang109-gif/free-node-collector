import asyncio
import time
import logging

logger = logging.getLogger(__name__)

async def test_proxy_latency(proxy: dict, timeout: int = 10):
    """
    对所有类型的代理进行统一的 TCP 连接延迟测试。
    这测量的是到代理服务器的网络路径延迟，作为一个核心性能指标。
    """
    name = proxy.get('name', 'Unknown')
    server = proxy.get("server")
    port = proxy.get("port")
    
    if not server or not isinstance(port, int):
        return proxy, 9999, "Invalid server/port"

    start_time = time.time()
    try:
        # 对所有协议类型，我们都只测试到其 server:port 的 TCP 连接延迟
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=timeout
        )
        # 计算延迟
        latency = int((time.time() - start_time) * 1000)
        # 成功后立即关闭连接
        writer.close()
        await writer.wait_closed()
        
        logger.debug(f"✅ {name:<30} - 延迟: {latency}ms")
        return proxy, latency, None
        
    except Exception as e:
        error_type = type(e).__name__
        logger.debug(f"❌ {name:<30} - 测试失败. Reason: {error_type}")
        return proxy, 9999, error_type


async def speed_test_all(proxies: list, max_workers: int = 100, top_n: int = 150):
    """
    批量异步测试所有代理，并返回延迟最低的一批。
    """
    logger.info(f"🚀 开始对 {len(proxies)} 个节点进行统一 TCP 延迟测试（并发数: {max_workers}）...")
    
    sem = asyncio.Semaphore(max_workers)
    
    async def test_with_semaphore(p):
        async with sem:
            return await test_proxy_latency(p)

    tasks = [test_with_semaphore(proxy) for proxy in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_proxies = []
    for res in results:
        if isinstance(res, tuple):
            proxy, latency, error = res
            if error is None:
                proxy['latency'] = latency
                valid_proxies.append(proxy)
    
    # 按延迟从小到大排序
    sorted_proxies = sorted(valid_proxies, key=lambda p: p['latency'])
    
    logger.info(f"✅ 统一延迟测试完成！发现 {len(valid_proxies)} 个可用节点。")
    
    if not sorted_proxies:
        logger.warning("⚠️ 未发现任何可用节点，无法生成订阅文件。")
        return []

    if len(sorted_proxies) > top_n:
        logger.info(f"🔪 保留延迟最低的前 {top_n} 个节点。")
        return sorted_proxies[:top_n]
        
    return sorted_proxies
