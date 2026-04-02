"""
Interrupt Judge Solution

使用微调模型 interrupt_judge 判断用户话语是否需要打断。
异步并行调用以满足25秒时间限制。
"""

import os
import asyncio
from openai import AsyncOpenAI

# 配置 - 从环境变量获取
client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY") or os.getenv("API_KEY") or "EMPTY",
    base_url=os.getenv("LLM_BASE_URL"),
)

# 微调模型名称
MODEL_NAME = "interrupt_judge"

# System prompt
SYSTEM_PROMPT = """你是一个打断判断助手。判断用户话语是否需要打断。

规则：
- 需要打断（返回True）：完整句子/有明确意图/指令/请求/半句话有明确意图
- 不需要打断（返回False）：语气词（如啊啊、嗯嗯、哇哇、喟喟等）/无语义/不完整表达

直接返回 "True" 或 "False"，不要有其他内容。"""


async def predict(utterance: str) -> bool:
    """
    异步判断单个话语是否需要打断。
    """
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"判断这句话是否需要打断：{utterance}"}
        ],
        temperature=0,
    )
    result = response.choices[0].message.content.strip()
    return "True" in result or "true" in result


async def predict_batch(utterances: list[str]) -> list[bool]:
    """
    异步并行预测所有话语。
    """
    tasks = [predict(u) for u in utterances]
    return await asyncio.gather(*tasks)


async def solve_async(env):
    """
    异步主函数：通过 env 对象调用 API。
    """
    # 第一步：获取所有问题
    questions = env.get_problem()

    # 第二步：异步并行预测所有问题
    answers = await predict_batch(questions)

    # 第三步：提交所有答案
    result = env.submit_answer(answers)

    # 第四步：打印结果
    accuracy = result.get("accuracy", 0)
    passed = result.get("passed", False)
    print(f"Accuracy: {accuracy * 100:.1f}%, Passed: {passed}")


def solve(env):
    """
    主函数入口：接收 env 对象，调用异步版本。
    """
    asyncio.run(solve_async(env))
