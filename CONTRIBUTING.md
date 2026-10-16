# Contributing

This repository is an early Python preview. Read [architecture/design.md](architecture/design.md), the three runtime specifications, and [implementation status](docs/implementation-status.md) before changing execution guarantees.

For application development, start with [getting started](docs/getting-started.md) and the generated standalone Agent. The [M1 acceptance protocol](docs/m1-acceptance.md) lists the remaining experiments; an offline regression is not a live model quality result. File an issue in the repository with the version, a minimal reproduction, expected/actual behavior and redacted events. See [SECURITY.md](SECURITY.md) for security reports and [the release guide](docs/releasing.md) for preview packaging.

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

## License

Ralf-Agent is licensed under the [Apache License 2.0](LICENSE). Unless explicitly
stated otherwise, contributions intentionally submitted for inclusion in this
project are provided under the same license, as described in Section 5. Preserve
applicable copyright and attribution notices, including [NOTICE](NOTICE), when
incorporating third-party material.
