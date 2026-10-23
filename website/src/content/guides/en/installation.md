---
title: Installation
description: Prepare a small Python environment and run Relf-Agent locally from source.
locale: en
slug: installation
sources: [docs/installation.md, docs/getting-started.md, docs/alpha6-validation-status.md, docs/releases/0.1.0a6.md]
---

## Requirements

Use **Python 3.11 or newer** in a virtual environment. The local introduction uses SQLite and an offline provider. It needs no model key, Redis, Temporal or Docker. Linux and macOS are the local development environments described by the project.

Relf-Agent is in Alpha. APIs and deployment combinations continue to evolve. See the repository's [implementation status (Chinese)](repo:docs/implementation-status.md) for the actual verification scope of each combination.

This guide pins the **0.1.0a6** source of Relf-Agent at `RalfNick/relf-agent`. Its distribution, Python import and CLI names are `relf-agent`, `relf_agent`, and `relf` / `relf-*`.

## Install from source

```bash
git clone https://github.com/RalfNick/relf-agent.git
cd relf-agent
git checkout ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
relf --version
```

This documentation baseline is SDK **0.1.0a6**, commit `ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239`, verified on 2026-10-23. The checkout command pins it; `relf --version` should show `0.1.0a6`. The base dependencies include `httpx` and `jsonschema`. Newer source may differ; keep the original SDK and configuration for old runs.

> This guide verifies a fixed **a6 source candidate**; it does not claim a public a6 package on PyPI or GitHub Release. See the [a6 validation status (Chinese)](repo:docs/alpha6-validation-status.md) and [a6 notes (Chinese)](repo:docs/releases/0.1.0a6.md) for artifact, platform and release qualifications. The [historical a2 archive](https://github.com/RalfNick/relf-agent/releases/tag/v0.1.0a2) retains its own entrypoints and evidence. Use separate environments; old Runs, History and function identities are not automatically migrated.

If you have a local wheel, install it in a virtual environment with `python -m pip install /actual/path/package.whl`. Verify its source and version.

## Complete a local task first

Continue to the [complete offline quickstart](/en/docs/quickstart/). Create a project, approve, resume and inspect the result on one page. This flow needs no optional dependencies or model credentials.

## Add optional dependencies

Run these commands from the source checkout with the virtual environment active. Installing clients does not provision external services.

| Purpose | Command |
| --- | --- |
| Development and tests | `python -m pip install -e '.[dev]'` |
| Skill document parsing | `python -m pip install -e '.[skills]'` |
| Text PDF ingestion | `python -m pip install -e '.[pdf]'` |
| Redis client | `python -m pip install -e '.[redis]'` |
| PostgreSQL client | `python -m pip install -e '.[postgres]'` |
| Temporal client and related dependencies | `python -m pip install -e '.[temporal]'` |

The complete extras are declared in [pyproject.toml](repo:pyproject.toml). Supply model credentials through the process environment, outside source control.

## Verify the installation

```bash
relf --help
relf --version
```

If `relf` cannot be found, activate the virtual environment and inspect `python -m pip show relf-agent`. Continue to the [quickstart](/en/docs/quickstart/) for local approval and cross-process recovery.
