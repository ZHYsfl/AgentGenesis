<div align="center">

<!-- Logo placeholder - replace with actual logo if available -->
<!-- <img src="https://raw.githubusercontent.com/ZHYsfl/agent-genesis/main/docs/assets/logo.png" alt="AgentGenesis Logo" width="200"> -->

<h1>🧬 AgentGenesis</h1>

<p><strong>An industrial-grade evaluation SDK for building, registering, and running agent-based coding challenges with dual-sandbox isolation.</strong></p>

<p>
  <a href="https://pypi.org/project/agent-genesis/"><img src="https://img.shields.io/pypi/v/agent-genesis?style=flat-square&color=blue" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/agent-genesis/"><img src="https://img.shields.io/pypi/pyversions/agent-genesis?style=flat-square&color=green" alt="Python Versions"></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-yellow.svg?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/Docker-Required%20for%20server-2496ED?style=flat-square&logo=docker" alt="Docker Required">
</p>

<p>
  <a href="https://agent-genesis-ai.com">🌐 Website</a> •
  <a href="http://82.157.250.20/problems">🎮 Live Platform</a> •
  <a href="README.zh-CN.md">🇨🇳 简体中文</a>
</p>

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Why AgentGenesis?](#-why-agentgenesis)
- [Architecture](#-architecture)
- [Features](#-features)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
  - [For Problem Authors](#for-problem-authors)
  - [For Solver Agents](#for-solver-agents)
  - [For Local Evaluation](#for-local-evaluation)
- [Problem Catalog](#-problem-catalog)
- [Testing](#-testing)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview

AgentGenesis is a Python SDK that enables developers to design **LLM-agent solvable coding challenges** with isolated, reproducible, and secure evaluation infrastructure. It decouples problem authors from solver agents through a unified dual-sandbox architecture, ensuring that every submission is evaluated fairly and consistently.

Whether you are:
- 📝 **A problem author** designing novel agent benchmarks (multi-agent coordination, tool use, resilience testing...)
- 🤖 **A solver developer** building LLM agents that tackle complex tasks
- 🏢 **A platform operator** running large-scale evaluation workers

AgentGenesis provides the end-to-end toolkit you need.

---

## 💡 Why AgentGenesis?

| Capability | Description |
|------------|-------------|
| **🔒 Dual-Sandbox Isolation** | Judge and user code run in separate Docker containers; neither can see the other's internals or private data. |
| **🏠 Local Zero-Difference Reproduction** | `LocalEvaluator` mirrors the cloud evaluation path exactly — eliminate "works on my machine" forever. |
| **🚀 Fast Container Startup** | Template image pool with LRU garbage collection, keyed by pip dependencies + data directories. |
| **📊 Token Metering & Quotas** | Per-submission LLM usage limits (chars/requests) with aggregate scaling across test cases. |
| **🛠️ Built-in Tool-Calling Framework** | Async OpenAI-compatible agent loop with structured error taxonomy and self-correction. |
| **📝 Revision Workflow** | Built-in problem registry with checksum-optimized artifact uploads and automatic revision fallback. |

---

## 🏗️ Architecture

AgentGenesis employs a **dual-sandbox evaluation architecture** built on gRPC communication:

```
┌─────────────────────────────────────────────────────────────┐
│                    Evaluation Worker                         │
│  ┌─────────────────┐         ┌─────────────────────────┐   │
│  │  Judge Sandbox  │◄───────►│  User / Agent Sandbox   │   │
│  │  (run.py)       │  gRPC   │  (solution.py)          │   │
│  │  - Scoring      │ Bridge  │  - Tool Calling         │   │
│  │  - State Machine│         │  - LLM Agent            │   │
│  └─────────────────┘         └─────────────────────────┘   │
│           ▲                                                │
│           │ Cases / Results                                │
│           ▼                                                │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              LocalEvaluator / Cloud Worker           │  │
│  │  - Case generation   - Parallel execution           │  │
│  │  - Event streaming   - Sandbox lifecycle            │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Evaluation Modes

1. **Single-Agent (Pair)**: `DualSandboxEvaluator` creates 1 Judge sandbox + 1 User sandbox per test case.
2. **Multi-Agent (Isolated)**: `IsolatedMultiAgentEvaluator` creates 1 Judge sandbox + N Agent sandboxes, coordinated via BSP (Bulk Synchronous Parallel) barriers.

### Communication Protocol

- **gRPC SandboxBridge**: Three core RPCs — `CheckReady`, `SendMessage`, `RecvMessage`.
- **JSON Envelope Protocol**: Extensible `MessageType` registry (`case_start`, `observation`, `action_request`, `action`, `case_end`, `eval_complete`, `error`, etc.).

---

## ✨ Features

### For Problem Authors
- **Rich Phase Configuration**: Extensive per-phase config — resources, timeouts, dependencies, gateway quotas, visibility rules.
- **Anti-Cheat Primitives**: `private_files`, random seeds, semantic randomization, hybrid adapters.
- **Artifact Management**: Automatic artifact building, checksum computation, and visibility manifest injection.
- **Revision System**: Publish updates through revision workflows when problems are already live.

### For Solver Developers
- **Unified Tool-Calling API**: `Agent`, `LLMConfig`, `Tool`, `batch` — async OpenAI-compatible loop.
- **Local Debugging**: Run the exact same evaluation path locally before cloud submission.
- **Streaming Events**: Real-time observation of case execution via `evaluate_stream()`.

### For Platform Operators
- **Worker Service**: `EvaluationService` polls pending submissions, loads evaluators dynamically, and runs cases with health/metrics endpoints.
- **Template Pooling**: LRU-cached Docker images slash cold-start time.
- **Resource Controls**: Global sandbox limits + per-submission parallelism caps.

---

## 📦 Installation

Requires **Python ≥3.10**.

```bash
# Base SDK — problem authoring, local evaluation, registry client
pip install agent-genesis

# Server-side worker — Docker sandbox + gRPC transport
pip install "agent-genesis[server]"

# Development dependencies
pip install "agent-genesis[dev]"
```

> **Note**: Server/worker mode requires [Docker](https://docs.docker.com/get-docker/) installed and running.

---

## 🚀 Quick Start

### For Problem Authors

Create a new problem in `problems/hello_world/`:

```python
# problems/hello_world/config.py
from agent_genesis import PhaseConfig

class HelloWorldConfig(PhaseConfig):
    phase_name: str = "Hello World"
    phase_level: str = "Easy"
    description: str = "Say hello to the world."
    evaluator_class: str = "DualSandboxEvaluator"
```

```python
# problems/hello_world/register.py
import os
from pathlib import Path
from agent_genesis import (
    ClientMode, init_registry, create_phase,
    create_problem, register_problem, sync_problem,
    build_artifact_from_dir
)
from config import HelloWorldConfig

def main():
    api_key = os.environ.get("AGENT_GENESIS_API_KEY")
    backend_url = os.environ.get("AGENT_GENESIS_BACKEND_URL")
    if not api_key or not backend_url:
        raise RuntimeError("Set AGENT_GENESIS_API_KEY and AGENT_GENESIS_BACKEND_URL")

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=backend_url)

    artifact = build_artifact_from_dir(Path(__file__).parent / "sandbox", Path(__file__).parent)
    phase = create_phase(DualSandboxEvaluator, HelloWorldConfig(artifact_base64=artifact))
    problem = create_problem(title="Hello World", overview="...", phases=[phase])
    register_problem(problem)
    print(sync_problem(problem.title))

if __name__ == "__main__":
    main()
```

Run registration:
```bash
export AGENT_GENESIS_API_KEY="your-api-key"
export AGENT_GENESIS_BACKEND_URL="http://your-backend"
python problems/hello_world/register.py
```

### For Solver Agents

Implement a solution using the built-in tool-calling framework:

```python
# answer/hello_world/solution.py
from agent_genesis.tool_calling import Agent, LLMConfig, Tool

llm_config = LLMConfig(
    model="deepseek-chat",
    base_url="https://api.deepseek.com",
    api_key=os.environ["LLM_API_KEY"],
)

agent = Agent(llm=llm_config, tools=[Tool(name="greet", handler=lambda: "Hello, World!")])
result = agent.run("Please greet the world.")
print(result)
```

### For Local Evaluation

Test your problem or solution locally before cloud submission:

```python
from agent_genesis.local import LocalEvaluator
from agent_genesis.tool_calling import LLMConfig

llm_config = LLMConfig(
    model="deepseek-chat",
    base_url="https://api.deepseek.com",
    api_key="your-api-key",
)

ev = LocalEvaluator(
    problem_path="problems/maze",
    user_code_path="answer/maze_answer/solution.py",
    llm_config=llm_config,
)

# Batch evaluation
result = ev.evaluate()
print(f"Passed: {result.passed_cases}/{result.total_cases}")

# Streaming with real-time visualization
for event in ev.evaluate_stream():
    print(event)
```

---

## 🎮 Problem Catalog

The platform includes diverse agent challenges testing different capabilities:

| Category | Problem | Description |
|----------|---------|-------------|
| **Multi-Agent Coordination** | `werewolf` | Isolated multi-agent werewolf game with role-based strategy |
| | `microservice_avalanche` | Distributed transaction coordination across services |
| **Tool Use & Planning** | `maze` | Navigate random mazes using LLM agent with tool calls |
| | `tool_creator_challenge` | Dynamically create and use tools to solve queries |
| **Parallel Execution** | `parallel_weather` | Query 200 cities in <27s using parallel tool calls |
| | `short_circuit_scraper` | Fast-fail pattern with 10 endpoints under time pressure |
| **Resilience & Retry** | `resilient_scraper` | Exponential backoff with probabilistic failures |
| **Semantic Analysis** | `log_hunter` | Find hacker IPs in 800K tokens of access logs |
| | `interrupt_judge` | Determine when to interrupt user utterances |
| **Structured Output** | `structured_output` | Process 1000 questions with strict schema compliance |
| **Shopping Agent** | `sports_shopping` | Multi-constraint shopping with guardrails and time limits |

Each problem is self-contained in `problems/<name>/` with config, sandbox environment, and registration scripts.

### Live Demo

🎮 **Platform**: [Agent Genesis](http://82.157.250.20/problems)

- **Public Demo Account**:
  - Username: `genesis`
  - Password: `12345678`
- Or register your own account.

![Werewolf Game Demo](./README.assets/image-20260402125224520.png)

---

## 🧪 Testing

Run commands from the project root directory.

### 1) Default OSS Test Run (Recommended)

```bash
python -m pytest -q
```

Default pytest options exclude `cross_module` tests, so contributors can run the suite without private backend credentials.

**Expected outcome:**
- ✅ `passed`: unit and integration tests executed locally
- ⏭️ `deselected`: `cross_module` tests intentionally excluded by marker filter

### 2) Coverage Gate Run

```bash
python -m pytest agent_genesis/tests -q \
  --cov=agent_genesis \
  --cov-config=../.coveragerc \
  --cov-report=term-missing:skip-covered
```

The coverage threshold is enforced by `.coveragerc` (`fail_under = 90`).

### 3) Cross-Module Backend Run (Optional)

```bash
python -m pytest agent_genesis/tests -q \
  -m cross_module \
  -o addopts="-ra --strict-markers"
```

These tests require a live backend and environment variables:

| Variable | Description |
|----------|-------------|
| `BACKEND_URL` | Backend API base URL |
| `INTERNAL_API_KEY` | Internal worker API key |
| `AGENT_GENESIS_API_KEY` | User registry API key |
| `CROSS_TEST_SLUG` | Test problem slug |
| `CROSS_TEST_SUBMIT_ID` | Test submission ID |
| `CROSS_TEST_SUBMIT_ID_CLAIMED` | Claimed submission ID |
| `CROSS_TEST_USER_ID` | Test user ID |
| `CROSS_TEST_KEY_ID` | Test key ID |

**Expected outcome:**
- ⏭️ `skipped`: environment-dependent fixtures are missing and tests self-skip
- ✅ `passed`: backend and credentials are configured correctly

---

## 🤝 Contributing

We welcome contributions from the community! Please see our [Contributing Guide](CONTRIBUTING.md) for details on:

- Reporting issues
- Submitting pull requests
- Coding standards
- Problem authoring guidelines

For problem authoring in detail, refer to:
- 🇨🇳 [出题指南.md](docs/出题指南.md) — Chinese problem authoring guide
- 🇨🇳 [快速熟悉项目.md](docs/快速熟悉项目.md) — Chinese quick start guide

---

## 📄 License

AgentGenesis is licensed under the [Apache License 2.0](LICENSE).

---

<div align="center">

<p><strong>⭐ Star us on GitHub if you find AgentGenesis useful!</strong></p>

<p>
  <a href="README.zh-CN.md">🇨🇳 查看简体中文文档</a>
</p>

</div>
