import asyncio
import time
import logging
import aiohttp
from aiohttp_socks import ProxyConnector

logger = logging.getLogger(__name__)

REAL_TEST_URL = "http://www.gstatic.com/generate_204"

async def _test_tcp_latency(proxy: dict, timeout: int):
    """
    对非 HTTP 代理进行 TCP 连接延迟测试。
    这测量的是到代理服务器的网络路径延迟。
    """
    server = proxy.get("server")
    port = proxy.get("port")
    start_time = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=timeout
        )
        latency = int((time.time() - start_time) * 1000)
        writer.close()
        await writer.wait_closed()
        return latency, None
    except Exception as e:
        return 9999, type(e).__name__

async def _test_http_rtt(proxy: dict, timeout: int):
    """
    对 HTTP 代理进行真实的 RTT (往返时间) 测试。
    """
    proxy_url = f"http://{proxy.get('server')}:{proxy.get('port')}"
    connector = ProxyConnector.from_url(proxy_url)
    start_time = time.time()
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.head(REAL_TEST_URL, ssl=False) as response:
                if response.status < 500:
                    latency = int((time.time() - start_time) * 1000)
                    return latency, None
                else:
                    return 9999, f"HTTP Status {response.status}"
    except Exception as e:
        return 9999, type(e).__name__
    finally:
        # 确保连接器被关闭
        if connector and not connector.closed:
            await connector.close()

async def test_proxy_latency(proxy: dict, timeout: int = 10):
    """
    混合测试调度器：根据代理类型选择最合适的测试方法。
    """
    name = proxy.get('name', 'Unknown')
    proxy_type = proxy.get("type")
    
    if not proxy.get("server") or not isinstance(proxy.get("port"), int):
        return proxy, 9999, "Invalid server/port"

    latency, error = 9999, "Unsupported protocol"

    if proxy_type == "http":
        # 对 HTTP 代理使用更准确的 RTT 测试
        latency, error = await _test_http_rtt(proxy, timeout)
    elif proxy_type in ["ss", "trojan", "vmess", "vless", "hy2"]:
        # 对其他协议使用 TCP 延迟测试
        latency, error = await _test_tcp_latency(proxy, timeout)

    if error is None:
        logger.debug(f"✅ {name:<30} - 延迟: {latency}ms (类型: {proxy_type})")
    else:
        logger.debug(f"❌ {name:<30} - 测试失败. Reason: {error} (类型: {proxy_type})")
        
    return proxy, latency, error


async def speed_test_all(proxies: list, max_workers: int = 100, top_n: int = 150):
    """
    批量异步测试所有代理，并返回延迟最低的一批。
    """
    logger.info(f"🚀 开始对 {len(proxies)} 个节点进行混合延迟测试（并发数: {max_workers}）...")
    
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
    
    sorted_proxies = sorted(valid_proxies, key=lambda p: p['latency'])
    
    logger.info(f"✅ 混合延迟测试完成！发现 {len(valid_proxies)} 个可用节点。")
    
    if not sorted_proxies:
        logger.warning("⚠️ 未发现任何可用节点，无法生成订阅文件。")
        return []

    if len(sorted_proxies) > top_n:
        logger.info(f"🔪 保留延迟最低的前 {top_n} 个节点。")
        return sorted_proxies[:top_n]
        
    return sorted_proxies
