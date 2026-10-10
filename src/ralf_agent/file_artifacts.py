"""Durable JSON payload files with a bounded SQLite receipt index (POSIX)."""

import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from .artifacts import SQLiteArtifactStore, _Artifacts
from .errors import BudgetExceeded, DefinitionMismatch, NotFound, ValidationError
from .task_controls import _binding
from .types import canonical, digest


class FileArtifactStore(_Artifacts):
    def __init__(self, path, *, backend_id=None, max_bytes=1024 * 1024, capacity=1024):
        try:
            import fcntl
        except ImportError:
            raise ValidationError("FileArtifactStore requires POSIX file locks") from None
        self.path = str(Path(path).expanduser().resolve())
        self._configure(
            "file-artifacts:" + digest(self.path) if backend_id is None else backend_id,
            max_bytes,
            capacity,
        )
        self._fcntl = fcntl
        self._root_fd = self._lock_fd = self._index = None
        self._owned_root_fd = self._owned_lock_fd = None
        self._owned_index = None
        self._mkdir()
        try:
            self._root_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._owned_root_fd = self._root_fd
            info = os.fstat(self._root_fd)
            self._root = (info.st_dev, info.st_ino)
            self._lock_fd = os.open(
                ".artifact.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=self._root_fd,
            )
            self._owned_lock_fd = self._lock_fd
            self._lock_file = self._regular(self._lock_fd)
            try:
                index_fd = os.open(
                    ".index.sqlite",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                    0o600,
                    dir_fd=self._root_fd,
                )
            except OSError:
                raise ValidationError("Artifact index file is unsafe") from None
            try:
                self._index_file = self._regular(index_fd)
            finally:
                os.close(index_fd)
            self._index = SQLiteArtifactStore(
                Path(self.path) / ".index.sqlite",
                backend_id="file-artifact-index:" + digest(self.backend_id),
                max_bytes=16384,
                capacity=capacity,
            )
            self._owned_index = self._index
            if self._index.path != str(Path(self.path) / ".index.sqlite"):
                raise DefinitionMismatch("Artifact receipt index path changed")
            self._index_identity = self._index.identity
            self._index_path, self._index_connection = self._index.path, self._index.conn
            self._index_bindings = {
                n: _binding(getattr(self._index, n)) for n in ("put", "get", "delete")
            }
            self._open()
        except BaseException:
            self.close()
            raise

    def _mkdir(self):
        directory, missing = Path(self.path), []
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for target in reversed(missing):
            try:
                target.mkdir(mode=0o700)
            except FileExistsError:
                if not target.is_dir():
                    raise ValidationError("Artifact root requires directories") from None
            parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)

    @staticmethod
    def _regular(fd):
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValidationError("Artifact files must be regular files without hard links")
        return info.st_dev, info.st_ino

    def _open(self):
        super()._open()
        for name, identity in (("root", self._root), ("lock", self._lock_file)):
            fd = getattr(self, "_" + name + "_fd")
            if fd != getattr(self, "_owned_" + name + "_fd"):
                raise DefinitionMismatch("Artifact held descriptor changed")
            try:
                info = os.fstat(fd)
            except OSError:
                raise DefinitionMismatch("Artifact held descriptor changed") from None
            if (info.st_dev, info.st_ino) != identity:
                raise DefinitionMismatch("Artifact held descriptor changed")
        if (
            self._index is not self._owned_index
            or self._index.identity != self._index_identity
            or self._index.path != self._index_path
            or self._index.conn is not self._index_connection
            or any(
                not callable(getattr(self._index, n, None))
                or _binding(getattr(self._index, n)) != b
                for n, b in self._index_bindings.items()
            )
        ):
            raise DefinitionMismatch("Artifact receipt index changed")
        try:
            info = os.stat(self.path, follow_symlinks=False)
        except FileNotFoundError:
            raise DefinitionMismatch("Artifact root changed") from None
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._root:
            raise DefinitionMismatch("Artifact root changed")
        try:
            info = os.stat(".index.sqlite", dir_fd=self._root_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise ValidationError("Artifact receipt index file changed") from None
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != self._index_file
        ):
            raise ValidationError("Artifact receipt index file changed")

    def _check_lock(self):
        try:
            info = os.stat(".artifact.lock", dir_fd=self._root_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise DefinitionMismatch("Artifact lock file changed") from None
        if (info.st_dev, info.st_ino) != self._lock_file or info.st_nlink != 1:
            raise DefinitionMismatch("Artifact lock file changed")

    @contextmanager
    def _guard(self):
        with self._lock:
            self._open()
            self._check_lock()
            self._fcntl.flock(self._lock_fd, self._fcntl.LOCK_EX)
            try:
                self._open()
                self._check_lock()
                self._index._open()
                yield
                self._open()
                self._check_lock()
                self._index._open()
            finally:
                self._fcntl.flock(self._lock_fd, self._fcntl.LOCK_UN)

    def _payload(self, name, length, *, sync=False):
        try:
            fd = os.open(
                name,
                (os.O_RDWR if sync else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self._root_fd,
            )
        except FileNotFoundError:
            raise NotFound("Artifact payload is unavailable") from None
        except OSError:
            raise ValidationError("Artifact payload file is unsafe") from None
        try:
            identity = self._regular(fd)
            if os.fstat(fd).st_size != length:
                raise ValidationError("Artifact payload size changed")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(length + 1)
            info = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != identity or info.st_nlink != 1:
                raise DefinitionMismatch("Artifact payload file changed")
            if sync:
                os.fsync(fd)
            return data
        finally:
            os.close(fd)

    def _publish(self, name, data):
        temporary = ".pending-" + uuid.uuid4().hex
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._root_fd,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=self._root_fd, dst_dir_fd=self._root_fd)
            os.fsync(self._root_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=self._root_fd)
            except FileNotFoundError:
                pass

    def put(self, scope, namespace, value, *, expires_at=None):
        with self._guard():
            ref, text = self._prepare(scope, namespace, value, expires_at)
            index_ref, _ = self._index._prepare(scope, namespace, ref.to_dict(), expires_at)
            present = self._index.conn.execute(
                "SELECT 1 FROM ralf_artifacts WHERE artifact_id=?", (index_ref.artifact_id,)
            ).fetchone()
            if not present:
                count = self._index.conn.execute(
                    "SELECT COUNT(*) FROM ralf_artifacts WHERE workspace=? AND principal=? AND namespace=?",
                    (scope.workspace, scope.principal, namespace),
                ).fetchone()[0]
                if count >= self._capacity:
                    raise BudgetExceeded("Artifact namespace capacity is full")
            name, data = ref.artifact_id + ".json", text.encode("utf-8")
            try:
                previous = self._payload(name, ref.byte_length)
            except NotFound:
                self._publish(name, data)
            else:
                if previous != data:
                    raise ValidationError("Stored artifact content changed")
                if self._payload(name, ref.byte_length, sync=True) != data:
                    raise ValidationError("Stored artifact content changed")
                os.fsync(self._root_fd)
            self._open()
            self._index.put(scope, namespace, ref.to_dict(), expires_at=expires_at)
            self._open()
            if self._payload(name, ref.byte_length) != data:
                raise ValidationError("Artifact payload changed before confirmation")
            return ref

    def get(self, scope, reference, *, max_bytes=None):
        with self._guard():
            ref = self._reference(scope, reference, read=True, max_bytes=max_bytes)
            index_ref, _ = self._index._prepare(scope, ref.namespace, ref.to_dict(), ref.expires_at)
            receipt = self._index.get(scope, index_ref)
            payload = self._payload(ref.artifact_id + ".json", ref.byte_length)
            return self._decode(scope, ref, payload, canonical(receipt), max_bytes)

    def delete(self, scope, reference):
        with self._guard():
            ref = self._reference(scope, reference)
            index_ref, _ = self._index._prepare(scope, ref.namespace, ref.to_dict(), ref.expires_at)
            removed = self._index.delete(scope, index_ref)
            try:
                os.unlink(ref.artifact_id + ".json", dir_fd=self._root_fd)
                os.fsync(self._root_fd)
            except FileNotFoundError:
                pass
            return removed

    def close(self):
        with self._lock:
            self._closed = True
            if self._owned_index is not None:
                self._owned_index.close()
            for name in ("lock", "root"):
                owned = "_owned_" + name + "_fd"
                fd = getattr(self, owned, None)
                if fd is not None:
                    identity = getattr(self, "_root" if name == "root" else "_lock_file", None)
                    try:
                        info = os.fstat(fd)
                    except OSError:
                        info = None
                    if info is not None and (
                        identity is None or (info.st_dev, info.st_ino) == identity
                    ):
                        os.close(fd)
                    setattr(self, owned, None)
                    setattr(self, "_" + name + "_fd", None)
