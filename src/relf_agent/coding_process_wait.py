"""Nonreaping observation of an original direct child, never cold PID control.

The caller owns Popen and must keep SIGCHLD at its default disposition, with
no external waiter/reaper for this child. Observe exit, signal its original
unreaped session group, and only then wait. Neither this monitor nor its close
method reaps. A PID remains reserved by our unreaped child throughout signalling.
"""

import ctypes
import errno
import math
import os
import select
import signal
import sys
import time
from subprocess import Popen

_GROUP_LIMIT = 4096
_PGRP_ONLY = 2


def _default_child_policy():
    if os.name != "posix" or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise RuntimeError("Direct child supervision requires default SIGCHLD")


def _darwin_group_members(pgid):
    """Bounded kernel inventory while our unreaped leader still reserves PGID."""
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    function = library.proc_listpids
    function.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    members = (ctypes.c_int * _GROUP_LIMIT)()
    size = ctypes.sizeof(members)
    ctypes.set_errno(0)
    result = function(_PGRP_ONLY, pgid, members, size)
    if (
        result < 0
        or (result == 0 and ctypes.get_errno() != 0)
        or result >= size
        or result % ctypes.sizeof(ctypes.c_int)
    ):
        raise RuntimeError("Original child group inventory is unavailable")
    return set(members[: result // ctypes.sizeof(ctypes.c_int)])


class ChildExitMonitor:
    """Preflight before spawn; register one direct Popen; observe without wait."""

    def __init__(self):
        _default_child_policy()
        self._process = None
        self._queue = None
        self._pidfd = None
        self._ended = False
        self._closed = False
        self._backend = None
        if sys.platform == "darwin" and all(
            hasattr(select, name) for name in ("kqueue", "kevent", "KQ_FILTER_PROC", "KQ_NOTE_EXIT")
        ):
            self._queue = select.kqueue()
            self._backend = "kqueue"
        elif sys.platform == "linux":
            if hasattr(os, "pidfd_open"):
                try:
                    descriptor = os.pidfd_open(os.getpid())
                except OSError:
                    pass
                else:
                    os.close(descriptor)
                    self._backend = "pidfd"
            if self._backend is None and all(
                hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOWAIT", "WNOHANG")
            ):
                try:
                    os.waitid(os.P_PID, os.getpid(), os.WEXITED | os.WNOWAIT | os.WNOHANG)
                except ChildProcessError:
                    self._backend = "waitid"
        if self._backend is None:
            raise RuntimeError("Nonreaping direct child exit observation is unavailable")

    def register(self, process):
        _default_child_policy()
        if (
            self._closed
            or self._process is not None
            or not isinstance(process, Popen)
            or type(process.pid) is not int
            or process.pid <= 0
            or process.returncode is not None
        ):
            raise RuntimeError("Exit observation requires one unreaped original Popen child")
        self._process = process
        if self._backend == "pidfd":
            self._pidfd = os.pidfd_open(process.pid)
        elif self._backend == "kqueue":
            change = select.kevent(
                process.pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                fflags=select.KQ_NOTE_EXIT,
            )
            try:
                events = self._queue.control([change], 1, 0)
            except ProcessLookupError:
                # Darwin cannot attach to an already exited zombie. The
                # original direct child has not been reaped and reserves PID.
                self._ended = True
            else:
                self._events(events, registering=True)

    def _events(self, events, *, registering=False):
        for event in events:
            if event.ident != self._process.pid or event.filter != select.KQ_FILTER_PROC:
                raise RuntimeError("Original child exit event changed")
            if event.flags & select.KQ_EV_ERROR:
                if registering and event.data == errno.ESRCH:
                    self._ended = True
                else:
                    raise RuntimeError("Original child exit observation failed")
            elif event.fflags & select.KQ_NOTE_EXIT:
                self._ended = True

    def exited(self, timeout=0):
        _default_child_policy()
        if (
            self._closed
            or self._process is None
            or self._process.returncode is not None
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 60
        ):
            raise RuntimeError("Exit observation requires its unreaped child and bounded timeout")
        if self._ended:
            return True
        if self._backend == "kqueue":
            self._events(self._queue.control([], 1, timeout))
        elif self._backend == "pidfd":
            self._ended = bool(select.select([self._pidfd], [], [], timeout)[0])
        else:
            deadline = time.monotonic() + timeout
            while True:
                result = os.waitid(
                    os.P_PID, self._process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG
                )
                if result is not None and result.si_pid == self._process.pid:
                    self._ended = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.01, remaining))
        return self._ended

    def close(self):
        if self._queue is not None:
            self._queue.close()
            self._queue = None
        if self._pidfd is not None:
            os.close(self._pidfd)
            self._pidfd = None
        self._closed = True


def signal_unreaped_group(process, monitor):
    """Signal only the live Popen ownership; never retry a numeric PGID after reap."""
    _default_child_policy()
    if monitor._process is not process or process.returncode is not None or monitor._closed:
        raise RuntimeError("Original child has already been reaped or changed")
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        # Darwin's all-zombie group returns EPERM. Do not reap then retry the
        # old integer. Check bounded kernel group membership while our child
        # still reserves its number; only its exited leader (or no member) is
        # safe. Every other denial remains unconfirmed cleanup.
        if not (
            sys.platform == "darwin"
            and error.errno == errno.EPERM
            and monitor.exited()
            and _darwin_group_members(process.pid) <= {process.pid}
        ):
            raise
