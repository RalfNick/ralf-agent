# Implementation progress — 2026-10-05 M1 local runtime

Plan: docs/superpowers/plans/2026-10-05-m1-local-runtime.md.

- Baseline: remote repository has no refs; local architecture committed as aa074d9.
- Ruling: develop in the newly initialized feature branch in the user workspace; there is no pre-existing code branch to protect. Preserve the architecture files and avoid moving the user's project.
- Ruling: this deliverable is v0.1.0.dev1, the first M1 increment. Temporal probe and full enterprise integrations remain tracked; local software must run without those dependencies.
- Ruling: execution credits are an enforceable attempt budget, not a currency guarantee. Unknown provider billing remains explicit.
- Pre-flight: Engine consumes the same Scope/CommandReceipt, ToolRegistry and SQLite transaction contract exercised by storage tests; CLI consumes RunHandle and the same persisted snapshots. No competing scheduler.
- Tasks 1–4: core SDK/CLI implemented. RED: missing modules and CLI, followed by behavioral failures for unresolved-write resubmission and cancellation releasing the coordinator. GREEN: `python3 -m pytest -q` → 35 passed, including real os._exit(77) after downstream commit.
- Ruling: memory/provider modules were built before the native loop because the loop consumes them. All public runtime exports were verified together in one initial implementation commit.
- Ruling: file-backed preview runs on POSIX (Linux/macOS), enforced by OS file locking. Windows coordinator support is not declared.
- Security correction: subprocess tests now receive PATH/PYTHONPATH only; host credential environment is not inherited or expanded in failure diagnostics.
