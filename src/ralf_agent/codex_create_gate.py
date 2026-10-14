"""Installed fixed CLI gate: self-register durably, then exec in the same PID."""

import os
import select
import sys
import time

from .codex_create_journal import (
    OperationJournal,
    accepted_frame,
    check_fd,
    gate_message,
    load_declaration,
    registration,
    require,
)


def run_gate(root, namespace_fd, operation_fd, grant_fd, ready_fd):
    declaration = load_declaration(root)
    journal = OperationJournal(root, declaration, actor="gate")
    check_fd(namespace_fd, declaration["namespace_lease"])
    check_fd(operation_fd, declaration["operation_lock"])
    journal.write("gate-register.json", registration(declaration))
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    raw = bytearray()
    deadline = time.monotonic() + declaration["timeout"]
    eof = False
    while time.monotonic() < deadline:
        if not select.select([grant_fd], [], [], min(0.05, deadline - time.monotonic()))[0]:
            continue
        part = os.read(grant_fd, 513)
        if not part:
            eof = True
            break
        raw.extend(part)
        if len(raw) > 512:
            break
    os.close(grant_fd)
    accepted = eof and accepted_frame(bytes(raw), declaration)
    if accepted:
        require(journal.read("inner-go.json") == gate_message(declaration))
    journal.write("inner-decision.json", {**registration(declaration), "accepted": accepted})
    if not accepted:
        return 0
    journal.write("gate-exec.json", registration(declaration))
    journal.check()
    for fd in (namespace_fd, operation_fd):
        os.set_inheritable(fd, True)
    os.execve(declaration["argv"][0], declaration["argv"], declaration["cli_env"])
    return 2  # execve does not return on success.


def main():
    try:
        require(len(sys.argv) == 6)
        return run_gate(sys.argv[1], *(int(value) for value in sys.argv[2:]))
    except BaseException:
        return 2


if __name__ == "__main__":
    sys.exit(main())
