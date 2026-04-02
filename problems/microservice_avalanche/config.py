"""Microservice Avalanche - Distributed Transaction Challenge Configuration"""

from typing import Optional

from agent_genesis import PhaseConfig


class MicroserviceAvalancheConfig(PhaseConfig):
    """Configuration for Microservice Avalanche V3 challenge."""

    # Phase metadata
    phase_name: str = "microservice_avalanche"
    phase_type: str = "agent"
    phase_order: int = 1
    phase_level: str = "Hard"

    # Evaluation parameters
    num_cases: int = 3
    min_passed_cases: Optional[int] = None
    parallel_cases: int = 1
    time_limit: float = 60.0  # 60 seconds per case
    sandbox_timeout: int = 90
    case_idle_timeout: int = 30

    # Dependencies
    pip_dependencies: list[str] = ["openai", "pydantic"]

    # User bridge
    solve_attr_name: str = "solve"
    adapter_preset: str = "microservice_avalanche"

    # Multi-agent configuration
    agent_ids: list[str] = ["order", "inventory", "payment"]
    solve_entry_map: dict[str, str] = {
        "order": "solve_order",
        "inventory": "solve_inventory",
        "payment": "solve_payment",
    }

    # Evaluator
    evaluator_module: str = "agent_genesis.isolated_evaluator"
    evaluator_class: str = "IsolatedMultiAgentEvaluator"


# Localized content
MICROSERVICE_AVALANCHE_OVERVIEW_EN = (
    "Distributed Transaction Challenge: Implement 2PC protocol across 3 microservices "
    "(Order, Inventory, Payment) with chaos engineering (random failures, network delays). "
    "Guarantee ACID consistency or face the avalanche."
)

MICROSERVICE_AVALANCHE_OVERVIEW_ZH = (
    "分布式事务挑战：在 3 个微服务（订单、库存、支付）上实现 2PC 协议，"
    "面对混沌工程（随机故障、网络延迟）。保证 ACID 一致性，否则雪崩。"
)

MICROSERVICE_AVALANCHE_BACKGROUND = """
# Microservice Avalanche: Distributed Transaction Challenge

## Background

In microservice architectures, maintaining data consistency across services is one of the hardest problems. This challenge simulates a real-world scenario where three services must coordinate to process transactions using the **Two-Phase Commit (2PC)** protocol.

## The Setup

**Three Services:**
- **Order Service (Coordinator)**: Orchestrates the transaction
- **Inventory Service (RM)**: Manages stock/reservations
- **Payment Service (RM)**: Manages payment processing

**The Task:**
Process 10 transactions. Each transaction must either:
- **Commit**: All three services commit (all-or-nothing)
- **Rollback**: All three services rollback (if any failure)

## The Challenge: Chaos Engineering

The Judge environment is hostile:

1. **Resource Failures (20%)**: When calling `prepare_tx()`, you may receive:
   - `"out_of_stock"`: Inventory cannot reserve
   - `"insufficient_balance"`: Payment cannot process

2. **Network Issues (10%)**: When sending RPC messages:
   - **Delay**: Message arrives 1-3 rounds late
   - **Packet Loss**: Message never arrives (timeout)

## The Rules

### State Machine (Strict!)
```
INIT -> PREPARED -> COMMITTED
  |        |
  +-> ROLLED_BACK <-+
```

- **Must PREPARE before COMMIT**: Calling commit without prepare = Illegal
- **Partial Commit = Death**: If Inventory commits but Payment rolls back, you fail
- **Timeout = Rollback**: If you don't hear back in time, you MUST rollback

### Scoring
- **100 points**: All 10 transactions consistent (all committed or all rolled back per transaction)
- **0 points**: Any inconsistency detected (partial commit)
- **Timeout**: If you exceed 60 seconds, score based on correctly processed transactions

## Key Concepts

### Two-Phase Commit (2PC)

**Phase 1 - Prepare:**
1. Order asks Inventory: "Can you prepare?"
2. Order asks Payment: "Can you prepare?"
3. If both say YES → proceed to commit
4. If any says NO or TIMEOUT → rollback

**Phase 2 - Commit/Rollback:**
- Order sends COMMIT to both
- Or Order sends ROLLBACK to both

### Handling Network Issues

Since messages can be delayed or lost:
- Implement **timeout detection** (3 rounds without response)
- Be prepared to **compensate** (send rollback if you already told someone to prepare)
- **Idempotency**: Same message twice shouldn't break things

## Victory Conditions

Your agents must:
1. Implement proper 2PC state machines
2. Handle resource failures gracefully
3. Detect network timeouts and compensate
4. NEVER allow partial commits (the ultimate sin)
""".strip()

MICROSERVICE_AVALANCHE_BACKGROUND_ZH = """
# 微服务雪崩：分布式事务挑战

## 背景

在微服务架构中，跨服务维护数据一致性是最难的问题之一。本题模拟真实场景，三个服务必须使用**两阶段提交（2PC）**协议协调处理事务。

## 设定

**三个服务：**
- **订单服务（协调者）**：编排事务
- **库存服务（资源管理器）**：管理库存/预留
- **支付服务（资源管理器）**：管理支付处理

**任务：**
处理 10 笔交易。每笔交易必须：
- **提交**：三个服务都提交（全或无）
- **回滚**：三个服务都回滚（如果有任何失败）

## 挑战：混沌工程

Judge 环境是敌对的：

1. **资源故障（20%）**：调用 `prepare_tx()` 时可能收到：
   - `"out_of_stock"`：库存无法预留
   - `"insufficient_balance"`：支付无法处理

2. **网络问题（10%）**：发送 RPC 消息时：
   - **延迟**：消息 1-3 轮后才到达
   - **丢包**：消息永远不到达（超时）

## 规则

### 状态机（严格！）
```
INIT -> PREPARED -> COMMITTED
  |        |
  +-> ROLLED_BACK <-+
```

- **必须先 PREPARE 再 COMMIT**：未 prepare 就 commit = 非法
- **部分提交 = 死亡**：如果库存提交了但支付回滚了，你失败
- **超时 = 回滚**：如果超时没收到响应，你必须回滚

### 评分
- **100 分**：10 笔交易全部一致（每笔要么全提交要么全回滚）
- **0 分**：检测到任何不一致（部分提交）
- **超时**：如果超过 60 秒，按正确处理的交易数给分

## 核心概念

### 两阶段提交（2PC）

**第一阶段 - 准备：**
1. 订单问库存："你能准备吗？"
2. 订单问支付："你能准备吗？"
3. 如果都说 YES → 继续提交
4. 如果有任何 NO 或超时 → 回滚

**第二阶段 - 提交/回滚：**
- 订单向双方发送 COMMIT
- 或订单向双方发送 ROLLBACK

### 处理网络问题

由于消息可能延迟或丢失：
- 实现**超时检测**（3 轮无响应）
- 准备**补偿**（如果已经告诉某人准备，要回滚）
- **幂等性**：同一条消息两次不应破坏状态

## 胜利条件

你的 Agent 必须：
1. 实现正确的 2PC 状态机
2. 优雅处理资源故障
3. 检测网络超时并补偿
4. **绝对不允许部分提交**（终极罪恶）
""".strip()

PHASE1_DESCRIPTION = """
# Phase 1: Distributed 2PC Implementation

## Your Task

Implement three coordinated agents that process transactions using the Two-Phase Commit protocol.

## Agent Roles

### 1. Order Agent (Coordinator)
- Receives new transactions
- Orchestrates 2PC protocol
- Makes commit/rollback decisions
- Handles timeouts and compensation

### 2. Inventory Agent (Resource Manager)
- Manages stock reservations
- Responds to prepare requests
- Commits or rollbacks based on coordinator decision

### 3. Payment Agent (Resource Manager)
- Manages payment authorization
- Responds to prepare requests
- Commits or rollbacks based on coordinator decision

## Interface

You need to implement three functions in `solution.py`:

```python
def solve_order(env):
    \"\"\"
    Order Service - Transaction Coordinator
    env.send_rpc(target, payload)
    env.prepare_tx(tx_id)  # Not used directly by coordinator
    env.commit_tx(tx_id)   # Not used directly by coordinator
    env.rollback_tx(tx_id) # Not used directly by coordinator
    env.connection()
    \"\"\"
    pass

def solve_inventory(env):
    \"\"\"
    Inventory Service - Resource Manager
    Waits for prepare requests from Order
    \"\"\"
    pass

def solve_payment(env):
    \"\"\"
    Payment Service - Resource Manager
    Waits for prepare requests from Order
    \"\"\"
    pass
```

## RPC Protocol

Message format for `env.send_rpc(target, payload)`:

```python
# Order -> Inventory/Payment
{
    "action": "prepare",
    "tx_id": "tx_0"
}

# Inventory/Payment -> Order (response)
{
    "action": "prepared",
    "tx_id": "tx_0",
    "status": "ok"  # or "failed"
}

# Order -> Inventory/Payment (Phase 2)
{
    "action": "commit",
    "tx_id": "tx_0"
}

# Order -> Inventory/Payment (if failure)
{
    "action": "rollback",
    "tx_id": "tx_0"
}
```

## 2PC Algorithm (Pseudocode)

### Order (Coordinator)
```python
for tx in transactions:
    # Phase 1: Prepare
    send_rpc("inventory", {"action": "prepare", "tx_id": tx.id})
    send_rpc("payment", {"action": "prepare", "tx_id": tx.id})

    # Wait for responses (max 3 rounds)
    responses = wait_for_responses(timeout=3)

    # Phase 2: Decide
    if all(r.status == "ok" for r in responses):
        send_rpc("inventory", {"action": "commit", "tx_id": tx.id})
        send_rpc("payment", {"action": "commit", "tx_id": tx.id})
    else:
        # IMPORTANT: Must rollback even if one prepared
        send_rpc("inventory", {"action": "rollback", "tx_id": tx.id})
        send_rpc("payment", {"action": "rollback", "tx_id": tx.id})
```

### Inventory/Payment (RM)
```python
while True:
    msg = receive_rpc()

    if msg.action == "prepare":
        result = env.prepare_tx(msg.tx_id)
        send_rpc("order", {
            "action": "prepared",
            "tx_id": msg.tx_id,
            "status": result["status"]
        })

    elif msg.action == "commit":
        env.commit_tx(msg.tx_id)

    elif msg.action == "rollback":
        env.rollback_tx(msg.tx_id)
```

## Handling Network Chaos

Since messages can be delayed or lost:

1. **Track pending requests**: Know which transactions you're waiting for
2. **Implement timeouts**: If no response in 3 rounds, assume failure
3. **Compensation**: If you already told RM to prepare but need to abort, send rollback
4. **Duplicate detection**: Same message twice shouldn't break your state machine

## Common Pitfalls

1. **Not handling prepare failure**: If prepare fails, don't try to commit!
2. **Missing rollback on timeout**: If you timeout waiting for Payment, rollback Inventory!
3. **Partial commit**: The ultimate sin - never commit at one RM and rollback at another
4. **Not using connection()**: Must call connection() when waiting for messages

## Scoring

- **100 points**: All 10 transactions processed with consistency
- **0 points**: Any partial commit detected
- Partial credit for correctly processed transactions before timeout
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：分布式 2PC 实现

## 任务

实现三个协调 Agent，使用两阶段提交协议处理事务。

## Agent 角色

### 1. 订单 Agent（协调者）
- 接收新交易
- 编排 2PC 协议
- 做出提交/回滚决策
- 处理超时和补偿

### 2. 库存 Agent（资源管理器）
- 管理库存预留
- 响应准备请求
- 根据协调者决策提交或回滚

### 3. 支付 Agent（资源管理器）
- 管理支付授权
- 响应准备请求
- 根据协调者决策提交或回滚

## 接口

需要在 `solution.py` 中实现三个函数：

```python
def solve_order(env):
    \"\"\"
    订单服务 - 事务协调者
    env.send_rpc(target, payload)
    env.prepare_tx(tx_id)  # 协调者不直接使用
    env.commit_tx(tx_id)   # 协调者不直接使用
    env.rollback_tx(tx_id) # 协调者不直接使用
    env.connection()
    \"\"\"
    pass

def solve_inventory(env):
    \"\"\"
    库存服务 - 资源管理器
    等待订单的准备请求
    \"\"\"
    pass

def solve_payment(env):
    \"\"\"
    支付服务 - 资源管理器
    等待订单的准备请求
    \"\"\"
    pass
```

## RPC 协议

`env.send_rpc(target, payload)` 的消息格式：

```python
# 订单 -> 库存/支付
{
    "action": "prepare",
    "tx_id": "tx_0"
}

# 库存/支付 -> 订单（响应）
{
    "action": "prepared",
    "tx_id": "tx_0",
    "status": "ok"  # 或 "failed"
}

# 订单 -> 库存/支付（第二阶段）
{
    "action": "commit",
    "tx_id": "tx_0"
}

# 订单 -> 库存/支付（如果失败）
{
    "action": "rollback",
    "tx_id": "tx_0"
}
```

## 2PC 算法（伪代码）

### 订单（协调者）
```python
for tx in transactions:
    # 第一阶段：准备
    send_rpc("inventory", {"action": "prepare", "tx_id": tx.id})
    send_rpc("payment", {"action": "prepare", "tx_id": tx.id})

    # 等待响应（最多3轮）
    responses = wait_for_responses(timeout=3)

    # 第二阶段：决策
    if all(r.status == "ok" for r in responses):
        send_rpc("inventory", {"action": "commit", "tx_id": tx.id})
        send_rpc("payment", {"action": "commit", "tx_id": tx.id})
    else:
        # 重要：即使一个准备了也要回滚
        send_rpc("inventory", {"action": "rollback", "tx_id": tx.id})
        send_rpc("payment", {"action": "rollback", "tx_id": tx.id})
```

### 库存/支付（RM）
```python
while True:
    msg = receive_rpc()

    if msg.action == "prepare":
        result = env.prepare_tx(msg.tx_id)
        send_rpc("order", {
            "action": "prepared",
            "tx_id": msg.tx_id,
            "status": result["status"]
        })

    elif msg.action == "commit":
        env.commit_tx(msg.tx_id)

    elif msg.action == "rollback":
        env.rollback_tx(msg.tx_id)
```

## 处理网络混沌

由于消息可能延迟或丢失：

1. **跟踪待处理请求**：知道你在等待哪些交易
2. **实现超时**：如果3轮无响应，假设失败
3. **补偿**：如果已告诉 RM 准备但要中止，发送回滚
4. **重复检测**：同一条消息两次不应破坏状态机

## 常见陷阱

1. **不处理准备失败**：如果准备失败，不要尝试提交！
2. **超时未回滚**：如果等待支付超时，回滚库存！
3. **部分提交**：终极罪恶 - 绝不要在一个 RM 提交而在另一个回滚
4. **未使用 connection()**：等待消息时必须调用 connection()

## 评分

- **100 分**：10 笔交易全部一致处理
- **0 分**：检测到任何部分提交
- 超时前正确处理的交易给部分分
""".strip()

PHASE1_STARTER_CODE = r'''
def solve_order(env):
    """
    Order Service - Transaction Coordinator (TC)

    Implements Two-Phase Commit protocol:
    1. Send prepare requests to Inventory and Payment
    2. Collect responses (handle failures/timeouts)
    3. Send commit or rollback to all

    Tools:
    - env.send_rpc(target, payload)
    - env.connection()
    """
    # Get list of transactions
    obs = env.connection()
    transactions = obs.get("transactions", [])

    for tx in transactions:
        tx_id = tx["tx_id"]

        # TODO: Phase 1 - Send prepare to both RMs
        # env.send_rpc("inventory", {"action": "prepare", "tx_id": tx_id})
        # env.send_rpc("payment", {"action": "prepare", "tx_id": tx_id})

        # TODO: Wait for responses (handle timeout!)

        # TODO: Phase 2 - Decide commit or rollback
        # If both prepared OK -> commit
        # If any failed or timeout -> rollback

        pass


def solve_inventory(env):
    """
    Inventory Service - Resource Manager (RM)

    Waits for prepare requests from Order.
    Responds with prepare result.
    Waits for commit or rollback decision.

    Tools:
    - env.prepare_tx(tx_id)
    - env.commit_tx(tx_id)
    - env.rollback_tx(tx_id)
    - env.send_rpc(target, payload)
    - env.connection()
    """
    while True:
        # Wait for messages
        obs = env.connection()

        # TODO: Check obs["rpc_messages"] for prepare requests
        # For each prepare request:
        #   result = env.prepare_tx(tx_id)
        #   env.send_rpc("order", {"action": "prepared", ...})

        # TODO: Check for commit/rollback messages
        # If commit: env.commit_tx(tx_id)
        # If rollback: env.rollback_tx(tx_id)

        pass


def solve_payment(env):
    """
    Payment Service - Resource Manager (RM)

    Same logic as Inventory - wait for Order's commands.
    """
    while True:
        obs = env.connection()
        # TODO: Same as solve_inventory
        pass
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve_order(env):
    """
    订单服务 - 事务协调者 (TC)

    实现两阶段提交协议：
    1. 向库存和支付发送准备请求
    2. 收集响应（处理失败/超时）
    3. 向所有节点发送提交或回滚

    工具：
    - env.send_rpc(target, payload)
    - env.connection()
    """
    # 获取交易列表
    obs = env.connection()
    transactions = obs.get("transactions", [])

    for tx in transactions:
        tx_id = tx["tx_id"]

        # TODO: 第一阶段 - 向两个 RM 发送准备
        # env.send_rpc("inventory", {"action": "prepare", "tx_id": tx_id})
        # env.send_rpc("payment", {"action": "prepare", "tx_id": tx_id})

        # TODO: 等待响应（处理超时！）

        # TODO: 第二阶段 - 决定提交或回滚
        # 如果都准备好了 -> 提交
        # 如果有失败或超时 -> 回滚

        pass


def solve_inventory(env):
    """
    库存服务 - 资源管理器 (RM)

    等待订单的准备请求。
    响应准备结果。
    等待提交或回滚决策。

    工具：
    - env.prepare_tx(tx_id)
    - env.commit_tx(tx_id)
    - env.rollback_tx(tx_id)
    - env.send_rpc(target, payload)
    - env.connection()
    """
    while True:
        # 等待消息
        obs = env.connection()

        # TODO: 检查 obs["rpc_messages"] 中的准备请求
        # 对每个准备请求：
        #   result = env.prepare_tx(tx_id)
        #   env.send_rpc("order", {"action": "prepared", ...})

        # TODO: 检查提交/回滚消息
        # 如果提交：env.commit_tx(tx_id)
        # 如果回滚：env.rollback_tx(tx_id)

        pass


def solve_payment(env):
    """
    支付服务 - 资源管理器 (RM)

    逻辑与库存相同 - 等待订单的命令。
    """
    while True:
        obs = env.connection()
        # TODO: 与 solve_inventory 相同
        pass
'''.strip()
