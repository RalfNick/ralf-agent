"""Trusted, dependency-free CLI fixture; no shell or sandbox assumption."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

mode, directory = sys.argv[1:3]
root = Path(directory)
if mode == "child":
    (root / "child-pid").write_text(str(os.getpid()))
    while True:
        with (root / "child-audit").open("a") as audit:
            audit.write("tick\n")
        time.sleep(0.01)
(root / "pid").write_text(str(os.getpid()))
arguments = json.load(sys.stdin)
(root / "started").touch()
if mode == "descendant":
    subprocess.Popen(
        [sys.executable, __file__, "child", directory],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 3
    while not (root / "child-audit").exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
if mode == "hang":
    while True:
        time.sleep(0.01)
if mode == "nonzero":
    sys.stderr.write("private-diagnostic")
    sys.exit(9)
if mode == "oversized":
    sys.stdout.write("x" * 2097152)
elif mode == "invalid":
    sys.stdout.write("private-invalid-json")
elif mode == "nan":
    sys.stdout.write('{"value":NaN}')
elif mode == "duplicate":
    sys.stdout.write('{"value":1,"value":2}')
elif mode == "surrogate-value":
    sys.stdout.write('{"value":"\\ud800"}')
elif mode == "surrogate-key":
    sys.stdout.write('{"\\udfff":1}')
elif mode == "schema":
    sys.stdout.write("[1]")
elif mode == "environment":
    print(
        json.dumps(
            {
                "inherited": "RALF_TEST_CLI_PARENT" in os.environ,
                "explicit": os.getenv("CLI_EXPLICIT"),
                "cwd": os.getcwd(),
                "argv": sys.argv[3:],
            }
        )
    )
else:
    print(json.dumps({"value": arguments["value"]}))
