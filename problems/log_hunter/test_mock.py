#!/usr/bin/env python3
"""Mock test for Log Hunter - 无需真实LLM调用"""

import json
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
sys.path.insert(0, os.path.join(script_dir, "sandbox"))
sys.path.insert(0, os.path.join(script_dir, "..", "..", "answer", "log_hunter_answer"))

from sandbox.environment import LogHunterEnvironment
from sandbox.generator import generate_case, generate_random_ip


def test_parse_action():
    """测试 parse_action 函数"""
    from sandbox.run import parse_action

    test_cases = [
        # Runtime sends actions wrapped in "data" field
        {
            "input": {"data": {"type": "submit_answer", "answers": ["1.2.3.4", "5.6.7.8", "9.10.11.12"]}},
            "expected_type": "submit_answer",
            "expected_payload": ["1.2.3.4", "5.6.7.8", "9.10.11.12"]
        },
        {
            "input": {"data": {"type": "get_problem"}},
            "expected_type": "get_problem",
            "expected_payload": None
        },
    ]

    print("=" * 60)
    print("测试 parse_action 函数")
    print("=" * 60)

    for i, test in enumerate(test_cases, 1):
        action_type, action_payload = parse_action(test["input"])

        type_ok = action_type == test["expected_type"]
        payload_ok = action_payload == test["expected_payload"]

        status = "PASS" if (type_ok and payload_ok) else "FAIL"
        print(f"\n测试 {i}: {status}")
        print(f"  输入: {json.dumps(test['input'], ensure_ascii=False)[:80]}...")
        print(f"  解析 type: {action_type} (期望: {test['expected_type']})")
        print(f"  解析 payload: {action_payload} (期望: {test['expected_payload']})")

        if not (type_ok and payload_ok):
            return False

    return True


def test_environment_scoring():
    """测试评分逻辑"""
    print("\n" + "=" * 60)
    print("测试评分逻辑")
    print("=" * 60)

    # 创建 mock case
    case_data = {
        "log_content": "mock log content",
        "target_ips": ["192.168.1.1", "10.0.0.1", "172.16.0.1"]
    }
    env = LogHunterEnvironment(case_data)

    # 模拟获取问题（启动计时）
    env.get_problem()

    # 测试1: 3个全对，快速完成
    import time
    env._start_time = time.time() - 5  # 模拟5秒前开始
    result = env.submit_answer(["192.168.1.1", "10.0.0.1", "172.16.0.1"])

    print(f"\n测试1: 3个全对，5秒完成")
    print(f"  correct: {result['correct']} (期望: 3)")
    print(f"  score: {result['score']} (期望: 100)")
    print(f"  passed: {result['passed']} (期望: True)")

    if result['correct'] != 3 or result['score'] != 100 or not result['passed']:
        print("  FAIL FAIL")
        return False
    print("  PASS PASS")

    # 重置
    env = LogHunterEnvironment(case_data)
    env.get_problem()

    # 测试2: 只有2个对
    env._start_time = time.time() - 5
    result = env.submit_answer(["192.168.1.1", "10.0.0.1", "0.0.0.0"])

    print(f"\n测试2: 只有2个对，5秒完成")
    print(f"  correct: {result['correct']} (期望: 2)")
    print(f"  score: {result['score']} (期望: 0，必须全对才给分)")
    print(f"  passed: {result['passed']} (期望: False)")

    if result['correct'] != 2 or result['score'] != 0 or result['passed']:
        print("  FAIL FAIL")
        return False
    print("  PASS PASS")

    return True


def test_generator():
    """测试日志生成器"""
    print("\n" + "=" * 60)
    print("测试日志生成器")
    print("=" * 60)

    # 使用 mock reasons（无需LLM）
    case = generate_case(target_chars=10000, seed=42)

    log_content = case["log_content"]
    target_ips = case["target_ips"]

    print(f"\n生成日志大小: {len(log_content)} 字符")
    print(f"目标IP: {target_ips}")

    # 检查目标IP是否在日志中
    found_ips = set()
    for ip in target_ips:
        if ip in log_content:
            found_ips.add(ip)

    print(f"在日志中找到的目标IP: {found_ips}")

    if len(found_ips) != 3:
        print("  FAIL FAIL: 不是所有目标IP都在日志中")
        return False

    # 检查日志行数
    lines = log_content.strip().split('\n')
    print(f"日志行数: {len(lines)}")

    if len(lines) < 10:
        print("  FAIL FAIL: 日志行数太少")
        return False

    print("  PASS PASS")
    return True


def main():
    print("\n" + "=" * 60)
    print("Log Hunter Mock Test Suite")
    print("=" * 60)

    all_passed = True

    all_passed &= test_parse_action()
    all_passed &= test_environment_scoring()
    all_passed &= test_generator()

    print("\n" + "=" * 60)
    if all_passed:
        print("PASS 所有测试通过！")
    else:
        print("FAIL 有测试失败")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
