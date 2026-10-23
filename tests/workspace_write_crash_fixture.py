"""Owned real-process downstream file-effect windows; no host credentials."""

import os
import sys
import time
from pathlib import Path

from relf_agent import FileSystemWritableWorkspace, Scope

root, mode = Path(sys.argv[1]), sys.argv[2]
port = FileSystemWritableWorkspace(root, version="1")
try:
    if mode == "hold":
        (root.parent / "ready").touch()
        deadline = time.monotonic() + 20
        while not (root.parent / "release").exists():
            if time.monotonic() > deadline:
                raise AssertionError("owned writer release timeout")
            time.sleep(0.01)
    else:
        original_replace = os.replace
        original_confirm = port._journal.confirm

        def replace(*args, **kwargs):
            if mode == "before_rename":
                os._exit(77)
            original_replace(*args, **kwargs)
            if mode == "after_rename":
                os._exit(77)

        def confirm(*args, **kwargs):
            value = original_confirm(*args, **kwargs)
            if mode == "after_receipt":
                os._exit(77)
            return value

        os.replace = replace
        port._journal.confirm = confirm
        original = port.read_text(Scope(), "note")["version"]
        port.write_text(Scope(), "note", "A", expected_version=original, effect_key="original")
        raise AssertionError("owned crash window did not terminate")
finally:
    port.close()
