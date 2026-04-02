#!/usr/bin/env python3
"""Full integration test for Log Hunter - with real LLM"""

import os
import sys
import time

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
sys.path.insert(0, os.path.join(script_dir, "sandbox"))
sys.path.insert(0, os.path.join(script_dir, "..", "..", "answer", "log_hunter_answer"))

from sandbox.environment import LogHunterEnvironment
from sandbox.generator import generate_case


def simple_solve(env):
    """Simple solution that finds IPs with suspicious keywords (for testing only)"""
    import re

    log_content = env.get_problem()
    print(f"[Solve] Got log content: {len(log_content)} chars")

    # Simple regex-based detection (not the real solution, just for testing)
    # In real solution, this would use LLM semantic analysis
    lines = log_content.split('\n')

    # Find lines with suspicious keywords
    suspicious_ips = []
    suspicious_keywords = [
        'ghost', 'shaman', 'temporal', 'compliance', 'gallery mode',
        'security protocols', 'root access', 'admin', 'emergency'
    ]

    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in suspicious_keywords):
            # Extract IP
            match = re.search(r'IP[:\s]+(\d+\.\d+\.\d+\.\d+)', line)
            if match:
                ip = match.group(1)
                suspicious_ips.append(ip)

    # Count frequency and get unique IPs
    from collections import Counter
    counter = Counter(suspicious_ips)

    # Get most common suspicious IPs
    most_common = counter.most_common(3)
    answers = [ip for ip, _ in most_common]

    # Fill with placeholders if needed
    while len(answers) < 3:
        answers.append("0.0.0.0")

    print(f"[Solve] Submitting answers: {answers[:3]}")
    result = env.submit_answer(answers[:3])
    print(f"[Solve] Result: {result}")
    return result


def test_full_flow():
    """Test full flow: generate -> solve -> score"""
    print("=" * 70)
    print("Log Hunter Full Integration Test")
    print("=" * 70)

    # Set up environment
    os.environ['LLM_API_KEY'] = 'sk-cp-rqsiHmkcOlKpES7LYmYiCXDcKrsgcJTU0r5LpCR3jsxgArI3HMz8Y70BTrtcC_dGF0C7jFOe7fvg_87HWT6f1Wl2c6LSFZ0bveTUNI5TjnovCbjBIwf1FWk'
    os.environ['LLM_BASE_URL'] = 'https://api.minimaxi.com/v1'
    os.environ['LLM_MODEL'] = 'MiniMax-M2.5-highspeed'

    # Generate case (smaller size for testing)
    print("\n[1] Generating test case...")
    start = time.time()
    case = generate_case(target_chars=160000, seed=42)  # 40K tokens
    gen_time = time.time() - start
    print(f"    Generated in {gen_time:.1f}s")
    print(f"    Log size: {len(case['log_content'])/1024:.1f} KB")
    print(f"    Target IPs: {case['target_ips']}")

    # Create environment
    env = LogHunterEnvironment(case)

    # Run solution
    print("\n[2] Running solution...")
    result = simple_solve(env)

    # Print results
    print("\n[3] Results:")
    print(f"    Correct: {result['correct']}/{result['total']}")
    print(f"    Score: {result['score']}")
    print(f"    Passed: {result['passed']}")
    print(f"    Time: {result['elapsed_seconds']:.1f}s")
    print(f"    Target IPs: {result['target_ips']}")
    print(f"    User Answers: {result['user_answers']}")

    print("\n" + "=" * 70)
    if result['passed']:
        print("PASS - Test completed successfully")
    else:
        print("FAIL - Test did not pass (expected with simple regex solution)")
    print("=" * 70)

    return result['passed']


if __name__ == "__main__":
    success = test_full_flow()
    sys.exit(0 if success else 1)
