import asyncio
import time
import logging

logger = logging.getLogger(__name__)

async def test_proxy_latency(proxy: dict, timeout: int = 10):
    """
    对所有类型的代理进行统一的 TCP 连接延迟测试。
    """
    name = proxy.get('name', 'Unknown')
    server = proxy.get("server")
    port = proxy.get("port")
    
    if not server or not isinstance(port, int):
        return proxy, 9999, "Invalid server/port"

    start_time = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=timeout
        )
        latency = int((time.time() - start_time) * 1000)
        writer.close()
        await writer.wait_closed()
        
        logger.debug(f"✅ {name:<30} - 延迟: {latency}ms")
        return proxy, latency, None
        
    except Exception as e:
        error_type = type(e).__name__
        logger.debug(f"❌ {name:<30} - 测试失败. Reason: {error_type}")
        return proxy, 9999, error_type


async def speed_test_all(
    proxies: list, 
    max_workers: int = 100, 
    top_n: int = 150,
    batch_size: int = 500, # 新增：定义每批处理的节点数量
    total_timeout: int = 900 # 新增：总超时时间为 15 分钟
):
    """
    批量异步测试所有代理，并返回延迟最低的一批。
    采用分批处理和总超时机制，以适应资源受限的环境。
    """
    logger.info(f"🚀 开始对 {len(proxies)} 个节点进行统一 TCP 延迟测试（并发数: {max_workers}, 批大小: {batch_size}）...")
    
    valid_proxies = []
    sem = asyncio.Semaphore(max_workers)
    
    async def test_batch():
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i+batch_size]
            logger.info(f"开始处理批次 {i//batch_size + 1}，节点范围: {i+1}-{i+len(batch)}...")
            
            async def test_with_semaphore(p):
                async with sem:
                    return await test_proxy_latency(p)

            tasks = [test_with_semaphore(proxy) for proxy in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, tuple):
                    proxy, latency, error = res
                    if error is None:
                        proxy['latency'] = latency
                        valid_proxies.append(proxy)
        
    try:
        # 为整个测速过程设置一个总的超时时间
        await asyncio.wait_for(test_batch(), timeout=total_timeout)
    except asyncio.TimeoutError:
        logger.error(f"❌ 整个测速过程超过了设定的总超时时间 {total_timeout} 秒，已中断。")

    logger.info(f"✅ 统一延迟测试完成！在所有批次中，共发现 {len(valid_proxies)} 个可用节点。")
    
    if not valid_proxies:
        logger.warning("⚠️ 未发现任何可用节点，无法生成订阅文件。")
        return []

    # 对所有找到的可用节点进行最终排序
    sorted_proxies = sorted(valid_proxies, key=lambda p: p['latency'])

    if len(sorted_proxies) > top_n:
        logger.info(f"🔪 保留延迟最低的前 {top_n} 个节点。")
        return sorted_proxies[:top_n]
        
    return sorted_proxies
