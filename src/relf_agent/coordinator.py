"""Default POSIX ownership; engine state never depends on a file descriptor."""

from pathlib import Path

from .errors import CoordinatorBusy, ValidationError


class FileCoordinator:
    def __init__(self, path, *, resource_validator=None):
        self.path = Path(path).resolve()
        if resource_validator is not None and not callable(resource_validator):
            raise ValidationError("Coordinator resource validator must be callable")
        self._resource_validator = resource_validator
        self._file = None

    def acquire(self):
        if self._file is not None:
            raise CoordinatorBusy("Coordinator lease is already owned")
        if self._resource_validator is not None:
            self._resource_validator()
        try:
            import fcntl
        except ImportError as exc:
            raise ValidationError("File coordinator currently requires POSIX file locks") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a+b")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self._resource_validator is not None:
                self._resource_validator()
        except BlockingIOError as exc:
            lock_file.close()
            raise CoordinatorBusy("Another coordinator owns this execution database") from exc
        except BaseException:
            lock_file.close()
            raise
        self._file = lock_file

    def release(self):
        if self._file is not None:
            self._file.close()
            self._file = None


class InProcessCoordinator:
    """Ownership for one in-memory execution store, never a shared file/DB."""

    def __init__(self):
        self._owned = False

    def acquire(self):
        if self._owned:
            raise CoordinatorBusy("Another coordinator owns this in-memory store")
        self._owned = True

    def release(self):
        self._owned = False
