# problems/__init__.py
"""
Problem plugin directory.

Each subdirectory is an independent problem:
- maze/      Maze exploration
- werewolf/  Isolated multi-agent werewolf game

Steps to add a new problem:
1. Create subdirectory problems/your_problem/
2. Create config.py - inherit PhaseConfig, define problem params, description, starter code, deps
3. Create sandbox/generator.py - case generation logic (pure function module)
4. Create sandbox/environment.py - environment state and interaction logic (optional, per problem type)
5. Create sandbox/run.py - Judge entry script (uses agent_genesis.runtime judge scaffold, runs inside sandbox)
6. Create sandbox/user_adapter.py - problem-side user adapter defining the user API shape
   (e.g. maze provides solve(move))
7. Create register.py - package artifact and register/sync problem to backend
   - build_artifact_from_dir() returns base64-encoded artifact zip
   - private_files in PhaseConfig lists protected file paths: ["sandbox/run.py", ...]
   - Files not in the list default to public; contributors can freely add/modify them
   - SDK automatically writes visibility_manifest.json into the artifact zip

Notes:
- Problems can use different evaluators via evaluator_module/evaluator_class
- Evaluation deps are installed at runtime via phase_config.pip_dependencies into the template image
- Per-case isolation: each test case runs in a fresh judge + user container pair
- Template images are cached per unique pip_dependencies set (LRU with GC)

Run registration:
    cd problems/your_problem
    python register.py

Environment variables:
    BACKEND_URL: Go backend address (default http://localhost:8080)
    INTERNAL_API_KEY: internal API key
"""
