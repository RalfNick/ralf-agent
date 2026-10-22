"""Execute bilingual tutorial examples against the published SDK, offline only.

Requires the SDK's base dependencies in the current Python environment. All
databases and the extracted SDK live in a temporary directory. The paid model
example is checked with a substituted deterministic Provider, never an endpoint.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

WEBSITE = Path(__file__).resolve().parents[1]
ROOT = WEBSITE.parent
BASELINE = json.loads((WEBSITE / "repository.json").read_text())["ref"]

FIXTURE = """from ralf_agent import ModelResponse, ToolCall
class _OfflineFixture:
    identity = {"kind": "website-model-smoke", "version": "1"}
    async def complete(self, messages, tools):
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=(ToolCall("lookup", {"ticket": "INC-001"}, "one"),))
        return ModelResponse(output={"ticket": "INC-001", "status": "open"})
"""


def blocks(locale, slug, language="python"):
    source = (WEBSITE / f"src/content/guides/{locale}/{slug}.md").read_text()
    return re.findall(rf"```{language}\n(.*?)\n```", source, re.S)


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise AssertionError(f"{args}:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def execute(code, path, env):
    path.write_text(code)
    return run([sys.executable, str(path)], path.parent, env)


with TemporaryDirectory(prefix="ralf-website-examples-") as tmp:
    work = Path(tmp)
    sdk = work / "sdk"
    sdk.mkdir()
    archive = subprocess.check_output(
        ["git", "archive", BASELINE, "src", "examples", "pyproject.toml"], cwd=ROOT
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(sdk, filter="data")
    env = {
        **os.environ,
        "PYTHONPATH": str(sdk / "src"),
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    }

    for locale in ("zh", "en"):
        directory = work / locale
        directory.mkdir()
        models = blocks(locale, "models-tools")
        original = next(code for code in models if "engine.submit(spec," in code)
        hook = 'OpenAIChatProvider(model=os.environ["RALF_MODEL"])'
        assert hook in original, "Update the offline substitution when the tutorial changes"
        original = FIXTURE + original.replace(hook, "_OfflineFixture()")
        schema = next(code for code in models if "output_schema=" in code)
        tree = ast.parse(original)
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "spec" for t in node.targets)
        )
        lines = original.splitlines()
        structured = "\n".join(
            lines[: assignment.lineno - 1] + [schema] + lines[assignment.end_lineno :]
        )
        guide = (WEBSITE / f"src/content/guides/{locale}/models-tools.md").read_text()
        new_id = re.search(r'command_id="(request-structured-[^\"]+)"', guide)
        assert new_id, "Structured-output instructions need a new command identity"
        structured = structured.replace('command_id="request-001"', f'command_id="{new_id[1]}"')
        path = directory / "ticket_agent.py"
        first = execute(original, path, env)
        repeated = execute(original, path, env)
        updated = execute(structured, path, env)
        for output in (first, repeated, updated):
            assert "state='succeeded'" in output, output

        def identity(output):
            return re.search(r"run_id='([^']+)'", output)[1]

        assert identity(first) == identity(repeated) != identity(updated)

        session = next(
            code for code in blocks(locale, "sessions-memory") if "class OfflineSupport" in code
        )
        for _ in range(2):
            output = execute(session, directory / "session_agent.py", env)
            assert output.count("succeeded {'order': '123'}") == 2, output

        app_test = next(
            code for code in blocks(locale, "testing") if "class OfflineProvider" in code
        )
        assert "PASS:" in execute(app_test, directory / "test_app.py", env)
        input_test = next(
            code for code in blocks(locale, "user-input") if "asyncio.run(main())" in code
        )
        assert "succeeded" in execute(input_test, directory / "input_agent.py", env)

        hybrid = next(
            code
            for code in blocks(locale, "sessions-memory", "bash")
            if "--template hybrid" in code
        )
        output = run(["bash", "-eu", "-c", hybrid], directory, env)
        assert '"status": "index_call_completed"' in output and '"grounded": true' in output, output
        print(
            f"{locale}: model→schema identity/replay, Session continuation/replay, app test, input and hybrid recipes passed"
        )

print(
    f"Tutorial examples passed against published SDK {BASELINE[:12]}; online model/embedding probes excluded."
)
