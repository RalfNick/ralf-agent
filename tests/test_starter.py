import json
import os
import sqlite3
import subprocess
import sys
import venv
from pathlib import Path

import httpx
import pytest

from relf_agent.errors import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def create_starter(directory):
    from relf_agent.starter import create_starter

    return create_starter(directory)


@pytest.mark.parametrize("existing", ["file", "directory", "hidden"])
def test_starter_refuses_existing_user_content_without_overwriting(tmp_path, existing):
    destination = tmp_path / "my-agent"
    if existing == "file":
        destination.write_text("my application", encoding="utf-8")
        protected = destination
    else:
        destination.mkdir()
        protected = destination / (".settings" if existing == "hidden" else "application.py")
        protected.write_text("my application", encoding="utf-8")
    with pytest.raises(ValidationError):
        create_starter(destination)
    assert protected.read_text(encoding="utf-8") == "my application"
    if existing != "file":
        assert list(destination.iterdir()) == [protected]


def test_starter_accepts_an_existing_empty_directory(tmp_path):
    destination = tmp_path / "my-agent"
    destination.mkdir()
    project = create_starter(destination)
    assert Path(project.directory) == destination
    assert (destination / "agent_app" / "runtime.py").is_file()
    with pytest.raises(ValidationError):
        create_starter(destination)


def subprocess_result(arguments, *, cwd, timeout=30, returncode=0):
    # The child receives neither credentials nor any repository PYTHONPATH.
    result = subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == returncode, result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory):
    work = tmp_path_factory.mktemp("starter-wheel")
    wheels = work / "wheels"
    subprocess_result(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels],
        cwd=ROOT,
        timeout=60,
    )
    environment = work / "environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    purelib = Path(
        subprocess_result(
            [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], cwd=work
        ).strip()
    )
    # Reuse already-installed third-party dependencies without fetching anything.
    # A path entry does not execute the parent environment's editable .pth files.
    (purelib / "dependencies.pth").write_text(
        str(Path(httpx.__file__).resolve().parent.parent) + "\n", encoding="utf-8"
    )
    subprocess_result(
        [
            python,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-index",
            "--no-deps",
            "--no-cache-dir",
            next(wheels.glob("relf_agent-*.whl")),
        ],
        cwd=work,
    )
    imported = Path(
        subprocess_result(
            [python, "-c", "import relf_agent; print(relf_agent.__file__)"], cwd=work
        ).strip()
    )
    assert imported.is_relative_to(purelib)
    return python, environment / "bin" / "relf"


@pytest.mark.parametrize("crash_after_write", [False, True])
def test_wheel_starter_approves_and_recovers_once_without_repository_imports(
    tmp_path, installed_wheel, crash_after_write
):
    python, ralf = installed_wheel
    destination = tmp_path / "standalone-agent"
    project = json.loads(
        subprocess_result(
            [
                python,
                "-c",
                "import json, sys; from dataclasses import asdict; "
                "from relf_agent.starter import create_starter; "
                "print(json.dumps(asdict(create_starter(sys.argv[1]))))",
                destination,
            ],
            cwd=tmp_path,
        )
    )
    db = ".ralf/starter.sqlite"
    start = [python, "-m", project["module"], "--db", db, "--ticket", "INC-START"]
    waiting = json.loads(subprocess_result(start, cwd=destination))
    assert waiting["state"] == "waiting_approval"
    assert len(waiting["pending"]) == 1
    pending = waiting["pending"][0]
    business = destination / (db + ".business.sqlite")
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 0
    factory = [ralf, "--db", db, "--factory", project["factory"]]
    approval = json.loads(
        subprocess_result(
            [
                *factory,
                "approve",
                waiting["run_id"],
                pending["action_id"],
                "--digest",
                pending["digest"],
                "--command-id",
                "approve-INC-START",
            ],
            cwd=destination,
        )
    )
    assert approval["apply_state"] == "applied"
    if crash_after_write:
        # Fault injection runs only in this subprocess. The real service commits
        # before the process dies; normal factory recovery must query its receipt.
        crash = """
import asyncio
import os
import sys
from agent_app.runtime import ChangeService, create_engine

apply_change = ChangeService.apply

def commit_then_exit(self, arguments, effect_key):
    apply_change(self, arguments, effect_key)
    os._exit(77)

ChangeService.apply = commit_then_exit
with create_engine(sys.argv[1]) as engine:
    asyncio.run(engine.drive(sys.argv[2]))
"""
        subprocess_result(
            [python, "-c", crash, db, waiting["run_id"]], cwd=destination, returncode=77
        )
        with sqlite3.connect(business) as connection:
            assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
    complete = json.loads(
        subprocess_result([*factory, "resume", waiting["run_id"]], cwd=destination)
    )
    assert complete["state"] == "succeeded"
    assert complete["result"]["verified"] is True
    assert complete["result"]["ticket"] == "INC-START"
    replay = json.loads(subprocess_result(start, cwd=destination))
    assert replay["run_id"] == waiting["run_id"]
    assert replay["state"] == "succeeded"
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
        effect = connection.execute("SELECT effect_key FROM effects").fetchone()[0]
    assert complete["result"]["change_id"] == effect
