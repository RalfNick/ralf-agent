# Contributing

This repository is an early Python preview. Read [architecture/design.md](architecture/design.md), the three runtime specifications, and [implementation status](docs/implementation-status.md) before changing execution guarantees.

Use Python 3.11+ on Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
```

New runtime behavior should have a failing regression test before implementation. Recovery tests must inspect actual external write counts and persisted identities, not only final answers. Use temporary SQLite databases; never call production business tools or inherit credential environment into fixture subprocesses.

Keep one authoritative scheduler, stable Action identities and explicit outcome_unknown handling. Do not silently add SDK/business retries or approve a changed operation. A new backend/Runner needs a capability report and applicable contract tests before it is described as supported.

Use focused branches and pull requests describing the concrete behavior, validation and remaining capability limits. Never commit `.env`, credentials, runtime databases or generated package artifacts.
