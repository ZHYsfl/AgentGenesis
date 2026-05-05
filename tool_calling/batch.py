try:
    # Package import path (agent_genesis.tool_calling.batch)
    from .async_tool_calling import Agent
except Exception:  # pragma: no cover - script mode fallback
    # Script-mode fallback (python tool_calling/batch.py)
    from async_tool_calling import Agent

import asyncio

async def batch(agent: Agent, observations: list[list[dict]], max_concurrent: int = 20) -> list[list[dict]]:
    '''
    批量并发调用LLM，支持限制最大并发数
    
    使用信号量(Semaphore)控制并发：当有空闲槽位时立即启动新任务，
    始终保持 max_concurrent 个任务在运行，直到所有任务完成。
    
    Args:
        agent: Agent实例
        observations: LLM的初始上下文列表，每个上下文是一个list[dict]
        max_concurrent: 最大并发数，默认20
    
    Returns:
        list[list[dict]]: 结果列表，顺序与 observations 一一对应
    '''
    semaphore = asyncio.Semaphore(max_concurrent)
    num = len(observations)

    assert num > 0, "observations 不能为空"
    assert max_concurrent > 0, "max_concurrent 不能小于1"

    async def _execute_with_index(idx: int) -> tuple[int, list[dict]]:
        '''执行单个任务，返回(索引, 结果)'''
        async with semaphore:  # 获取槽位，如果没有空闲槽位则等待
            result = await agent.chat(observations[idx])
            return idx, result
    
    # 创建所有任务（但受信号量控制，不会立即全部启动）
    tasks = [_execute_with_index(i) for i in range(num)]
    
    # 收集所有结果（保持顺序）
    results_with_index = await asyncio.gather(*tasks)
    
    # 按原始索引排序，确保返回顺序与输入一致
    results_with_index.sort(key=lambda x: x[0])
    
    # 提取结果
    results = [r[1] for r in results_with_index]
    return results