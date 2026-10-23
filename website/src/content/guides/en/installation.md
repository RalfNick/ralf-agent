---
title: Installation
description: Prepare a small Python environment and run Relf-Agent locally from source.
locale: en
slug: installation
sources: [docs/installation.md, docs/getting-started.md]
---

## Requirements

Use **Python 3.11 or newer** in a virtual environment. The local introduction uses SQLite and an offline provider. It needs no model key, Redis, Temporal or Docker. Linux and macOS are the local development environments described by the project.

Relf-Agent is in Alpha. APIs and deployment combinations continue to evolve. See the repository's [implementation status (Chinese)](repo:docs/implementation-status.md) for the actual verification scope of each combination.

The project is Relf-Agent at `RalfNick/relf-agent`. Starting with a6, the distribution, import and commands are `relf-agent`, `relf_agent`, and `relf` / `relf-*`. a5 changed only the distribution name. This guide deliberately retains the actual `ralf_agent` imports and `ralf` commands for its pinned a1 source and public a2 archive; new commands do not run against those old packages.

## Install from source

```bash
git clone https://github.com/RalfNick/relf-agent.git
cd relf-agent
git checkout 0b9b6c9682c40285d91994cd831aa93d7e814bf1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

This documentation baseline is SDK **0.1.0a1**, commit `0b9b6c9682c40285d91994cd831aa93d7e814bf1`, verified on 2026-10-21. The checkout command pins it; `ralf --version` should show `0.1.0a1`. The base dependencies include `httpx` and `jsonschema`. Newer source may differ; keep the original SDK and configuration for old runs.

> This guide pins the original a1 source, not a public a1 package. The latest [0.1.0a2 Alpha](https://github.com/RalfNick/relf-agent/releases/tag/v0.1.0a2) is publicly available through GitHub Release; its release notes provide the verified installation command. PyPI remains unpublished, so `pip install ralf-agent` is not this guide's verified entry point.

> The current candidate is `relf-agent==0.1.0a6`; actual evidence is in `docs/alpha6-validation-status.md` in the maintenance checkout. a5 archives and records remain intact and do not qualify a6. Use separate versioned environments; old Runs, History and fingerprints are not automatically migrated.

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
ralf --help
ralf --version
```

If `ralf` cannot be found, activate the virtual environment and inspect `python -m pip show ralf-agent`. Continue to the [quickstart](/en/docs/quickstart/) for local approval and cross-process recovery.
