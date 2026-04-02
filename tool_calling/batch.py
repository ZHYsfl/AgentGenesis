try:
    # Package import path (agent_genesis.tool_calling.batch)
    from .async_tool_calling import Agent
except Exception:  # pragma: no cover - script mode fallback
    # Script-mode fallback (python tool_calling/batch.py)
    from async_tool_calling import Agent

import asyncio

async def batch(agent: Agent, observations: list[list[dict]], max_concurrent: int = 20) -> list[list[dict]]:
    '''
    Batch concurrent LLM calls with a maximum concurrency limit.

    Uses a semaphore (Semaphore) to control concurrency: when a slot is free,
    a new task is started immediately, keeping max_concurrent tasks running
    until all tasks are completed.

    Args:
        agent: Agent instance
        observations: Initial context list for LLM, each context is list[dict]
        max_concurrent: Maximum concurrent tasks, default 20

    Returns:
        list[list[dict]]: Results list, corresponding one-to-one with observations
    '''
    semaphore = asyncio.Semaphore(max_concurrent)
    num = len(observations)

    assert num > 0, "observations cannot be empty"
    assert max_concurrent > 0, "max_concurrent must be >= 1"

    async def _execute_with_index(idx: int) -> tuple[int, list[dict]]:
        '''Execute single task, returns (index, result)'''
        async with semaphore:  # Acquire slot, wait if no free slots
            result = await agent.chat(observations[idx])
            return idx, result

    # Create all tasks (but controlled by semaphore, won't start all at once)
    tasks = [_execute_with_index(i) for i in range(num)]

    # Collect all results (maintain order)
    results_with_index = await asyncio.gather(*tasks)

    # Sort by original index to ensure output order matches input
    results_with_index.sort(key=lambda x: x[0])

    # Extract results
    results = [r[1] for r in results_with_index]
    return results