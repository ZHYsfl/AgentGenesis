# Contributing to AgentGenesis

First off, thank you for considering contributing to AgentGenesis! 🎉

This document provides guidelines and workflows to help you get started. Whether you're reporting a bug, suggesting a feature, writing code, or authoring new problems — your contributions are welcome.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Pull Requests](#pull-requests)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Authoring New Problems](#authoring-new-problems)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Release Process](#release-process)

---

## Code of Conduct

This project adheres to a standard of respectful, constructive collaboration. By participating, you are expected to:

- Be respectful and inclusive in all interactions.
- Accept constructive criticism gracefully.
- Focus on what is best for the community and the project.

Harassment, trolling, or abusive behavior will not be tolerated.

---

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please:

1. **Search existing issues** to avoid duplicates.
2. **Update to the latest version** — your issue may already be fixed.

If the bug persists, open a new issue with the following template:

```markdown
**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

**Expected behavior**
A clear and concise description of what you expected to happen.

**Environment (please complete the following information):**
- OS: [e.g. Ubuntu 22.04, macOS 14, Windows 11]
- Python version: [e.g. 3.11.4]
- AgentGenesis version: [e.g. 0.0.57]
- Docker version (if applicable): [e.g. 24.0.7]

**Additional context**
Add any other context about the problem here, such as stack traces or screenshots.
```

> 💡 **Security issues**: If you discover a security vulnerability, **DO NOT** open a public issue. Please email the maintainers directly or use the security advisory feature on GitHub.

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub Discussions or Issues. When proposing an enhancement:

1. **Use a clear, descriptive title**.
2. **Explain the use case** — who benefits and why?
3. **Provide a concrete example** if applicable.
4. **Indicate willingness to implement** — this helps with prioritization.

### Pull Requests

1. **Fork the repository** and create your branch from `main`.
2. **Install development dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```
3. **Make your changes**, following our [coding standards](#coding-standards).
4. **Add or update tests** as necessary.
5. **Ensure all tests pass**:
   ```bash
   python -m pytest -q
   ```
6. **Update documentation** if your change affects public APIs or behavior.
7. **Submit the PR** with a clear description referencing any related issues.

#### PR Review Process

- All PRs require at least one review from a maintainer.
- CI checks (tests, coverage) must pass before merging.
- Squash merging is preferred for clean history.

---

## Development Setup

### Prerequisites

- Python ≥3.10
- Docker (for server/worker mode testing)
- Git

### Local Installation

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/agent-genesis.git
cd agent-genesis

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with all extras
pip install -e ".[server,dev]"
```

### Running Tests

```bash
# Quick unit + integration tests (no backend required)
python -m pytest -q

# With coverage report
python -m pytest agent_genesis/tests -q \
  --cov=agent_genesis \
  --cov-config=.coveragerc \
  --cov-report=term-missing:skip-covered

# Cross-module backend tests (requires live backend)
export BACKEND_URL="..."
export INTERNAL_API_KEY="..."
python -m pytest -m cross_module -q
```

### Code Quality Tools

We use the following tools (configured in `pyproject.toml` where applicable):

- **Ruff** for linting and import sorting.
- **MyPy** for static type checking.
- **pytest** with `pytest-cov` for testing and coverage.

Install and run:
```bash
pip install ruff mypy
ruff check .
mypy agent_genesis
```

---

## Coding Standards

### Python Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) with a line length of **100 characters**.
- Use **type hints** for all public functions and classes.
- Use **Google-style docstrings**.

```python
def evaluate_case(case_id: str, config: PhaseConfig) -> CaseResult:
    """Evaluate a single test case.

    Args:
        case_id: Unique identifier for the test case.
        config: Phase configuration containing evaluator and resource settings.

    Returns:
        CaseResult with score, status, and metadata.

    Raises:
        SandboxTimeoutError: If the case exceeds the configured timeout.
    """
    ...
```

### Naming Conventions

- `snake_case` for functions, variables, and modules.
- `PascalCase` for classes.
- `UPPER_CASE` for constants.
- Private methods prefixed with `_`.

### Testing Standards

- All new features must include unit tests.
- Integration tests should mock external services (backends, Docker) where possible.
- Cross-module tests are optional but encouraged for backend-dependent features.

---

## Authoring New Problems

AgentGenesis thrives on diverse, high-quality problems. If you'd like to contribute a new challenge:

### Problem Structure

```
problems/<problem_name>/
├── config.py              # PhaseConfig subclass
├── register.py            # Publish / sync script
├── register_zh.py         # (Optional) Chinese localization
└── sandbox/
    ├── run.py             # Judge entry point
    ├── user_adapter.py    # User-side API adapter
    ├── environment.py     # State machine & scoring
    ├── generator.py       # Test case generator
    ├── data/              # Static data (optional)
    └── visibility_manifest.json  # Auto-generated
```

### Key Requirements

1. **Clear Objective**: The problem should test a specific agent capability (tool use, planning, resilience, etc.).
2. **Scoring Granularity**: Scores should range from 0-100 with meaningful intermediate values.
3. **Anti-Cheat**: Use `private_files`, random seeds, and hybrid adapters to prevent trivial solutions.
4. **Local Evaluable**: Every problem must work with `LocalEvaluator` before cloud registration.

### Documentation

- Write problem descriptions in both English and Chinese when possible.
- Include `starter_code` that demonstrates the expected API.
- Document any special environment variables or dependencies.

For a detailed authoring guide, see:
- 🇨🇳 [出题指南.md](docs/出题指南.md) — Comprehensive Chinese guide
- 🇨🇳 [快速熟悉项目.md](docs/快速熟悉项目.md) — Quick start for problem authors

### Registration Checklist

Before submitting a new problem:

- [ ] `config.py` defines a valid `PhaseConfig` subclass.
- [ ] `sandbox/run.py` implements the judge logic correctly.
- [ ] `sandbox/user_adapter.py` exposes the expected API.
- [ ] `sandbox/environment.py` handles scoring and state transitions.
- [ ] Local evaluation passes: `LocalEvaluator(problem_path="...").evaluate()`.
- [ ] Artifact builds without errors: `build_artifact_from_dir(...)`.
- [ ] No secrets or API keys are hard-coded in registration scripts.

---

## Commit Message Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/) to maintain a clean changelog.

```
<type>(<scope>): <short summary>

<body: explain the motivation and contrast with previous behavior>

<footer: reference issues, breaking changes, etc.>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, semicolons, etc.)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding or correcting tests
- `chore`: Build process or auxiliary tool changes

**Examples**:
```
feat(problems): add new resilient_scraper challenge

fix(sandbox): resolve race condition in template image pooling

docs(readme): update installation instructions for Windows
test(local): add coverage for LocalEvaluator streaming events
```

---

## Release Process

Releases are managed by maintainers. The workflow is:

1. Update version in `pyproject.toml`.
2. Update `CHANGELOG.md` (if maintained).
3. Create a GitHub Release with release notes.
4. CI automatically publishes to PyPI.

---

## Questions?

If you have questions not covered by this guide:

- 📧 Open a [GitHub Discussion](https://github.com/YHYsfl/agent-genesis/discussions) for general questions.
- 🐛 Open a [GitHub Issue](https://github.com/ZHYsfl/agent-genesis/issues) for bugs or feature requests.
- 💬 Join our community (if applicable) ...

Thank you for making AgentGenesis better! 🚀
