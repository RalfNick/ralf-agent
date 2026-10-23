"""Standalone offline managed model/tool contract example."""

MODEL_CHECK_FILES = {
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\nraise SystemExit(main())\n",
    "agent_app/runtime.py": '''"""Run deterministic checks, then select a real model explicitly."""
import sys
from relf_agent.model_check_cli import main as check


def main():
    return check(["--offline", "--evidence-dir", ".ralf/model-check", *sys.argv[1:]])
''',
    "README.md": """# Model and typed-tool compatibility

Run `python -m agent_app`. This uses an explicitly offline Provider, a typed
read-only echo tool and managed LocalEngine Runs. The five checks cover text,
JSON Schema, tool roundtrip, complete streams and early consumer close. No paid
calls occur and model_quality is null. Raw evidence is private in
`.ralf/model-check`; repeat checks require a fresh evidence directory.

Edit runtime.py to select a real Provider through the SDK or use
`relf-check-model --adapter openai-responses --model YOUR_ACTUAL_MODEL
--api-key-env YOUR_KEY_ENV --evidence-dir PRIVATE_FRESH_DIRECTORY`.
The real command may incur fees. API keys belong in the application's credential
environment and never in source, config, messages or published reports.
This example is a compatibility evaluator and has no business Engine factory.

ToolRegistry.tool(effect="read_only") and register_function infer JSON Schema
from bounded annotations and adapt keyword functions to the existing executor.
Explicit effect classification is required; write tools retain approval/recovery
contracts. Default values are captured privately and only their digest enters the
release identity. Context injection is host-owned. Unsupported annotations require
an explicit Schema; inference never executes postponed annotation expressions.

A passed early-close check proves consumer cleanup, not supplier cancellation.
The original Run retains unknown model usage as waiting_reconciliation.
Protocol checks do not establish general task quality or enterprise readiness.
""",
}
