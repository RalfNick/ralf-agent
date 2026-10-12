"""Fixed local Unix Docker control I/O, called only by owned native threads."""

import json
import os
import stat
from pathlib import Path

import httpx

from .errors import ValidationError
from .sandbox import MAX_OUTPUT, SandboxError, SandboxUnavailable


def socket_identity(path):
    try:
        root = Path(path).resolve(strict=True)
        metadata = root.stat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise SandboxUnavailable("Docker endpoint must be an existing local Unix socket")
        return {"path": str(root), "device": metadata.st_dev, "inode": metadata.st_ino}
    except OSError:
        raise SandboxUnavailable("Configured local Docker socket is unavailable") from None


def lease_root(path):
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve(strict=True)
    value = root.stat()
    if value.st_uid != os.getuid() or not stat.S_ISDIR(value.st_mode) or value.st_mode & 0o077:
        raise SandboxUnavailable("Native Sandbox leases require a private owned directory")
    return {"path": str(root), "device": value.st_dev, "inode": value.st_ino}


class NativeSandboxLease:
    """Native dispatch FD ownership, never a Run authority or persisted task state."""

    def __init__(self, root, name):
        self.fd = None
        path = Path(root["path"]) / (name + ".lock")
        directory = Path(root["path"]).stat()
        if (directory.st_dev, directory.st_ino) != (root["device"], root["inode"]):
            raise SandboxUnavailable("Original native Sandbox lease directory changed")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            import fcntl

            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o077
            ):
                raise SandboxUnavailable("Native Sandbox invocation lease is unsafe")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (path.stat().st_dev, path.stat().st_ino) != (metadata.st_dev, metadata.st_ino):
                raise SandboxUnavailable("Native Sandbox invocation lease path changed")
            self.fd = fd
        except BlockingIOError:
            os.close(fd)
            raise SandboxUnavailable("Another native Sandbox owner holds this invocation") from None
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def decode_logs(data, *, max_bytes):
    if type(data) is not bytes or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_OUTPUT:
        raise ValidationError("Docker log decoding requires bounded ordinary bytes")
    if len(data) > MAX_OUTPUT + 65536:
        raise SandboxError("Docker log framing exceeds its byte allowance")
    streams, offset, size, truncated = {1: bytearray(), 2: bytearray()}, 0, 0, False
    while offset < len(data):
        if len(data) - offset < 8:
            raise SandboxError("Incomplete Docker log frame")
        kind, reserved = data[offset], data[offset + 1 : offset + 4]
        count = int.from_bytes(data[offset + 4 : offset + 8], "big")
        if kind not in streams or reserved != b"\x00\x00\x00" or count > len(data) - offset - 8:
            raise SandboxError("Malformed Docker log frame")
        available = max(0, max_bytes - size)
        streams[kind].extend(data[offset + 8 : offset + 8 + min(count, available)])
        truncated |= count > available
        size += min(count, available)
        offset += 8 + count
    try:
        return (
            bytes(streams[1]).decode("utf-8", errors="ignore" if truncated else "strict"),
            bytes(streams[2]).decode("utf-8", errors="ignore" if truncated else "strict"),
            truncated,
        )
    except UnicodeError:
        raise SandboxError("Docker tool output requires UTF-8 text") from None


class DockerControl:
    def __init__(self, path, api, timeout):
        self.client = httpx.Client(
            transport=httpx.HTTPTransport(uds=path),
            base_url="http://localhost/v" + api + "/",
            timeout=timeout,
            trust_env=False,
        )

    def request(self, method, path, *, body=None, accepted=(200,), max_bytes=1048576):
        try:
            with self.client.stream(method, path, json=body) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise SandboxError("Docker control response exceeds its byte allowance")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if response.status_code not in accepted:
                    raise SandboxUnavailable("Docker native control request was not acknowledged")
                return response.status_code, data
        except httpx.HTTPError:
            raise SandboxUnavailable("Local Docker native control is unavailable") from None

    def json(self, method, path, *, body=None, accepted=(200,)):
        status, data = self.request(method, path, body=body, accepted=accepted)
        if status == 404:
            return None
        try:
            value = json.loads(data)
            if type(value) is not dict:
                raise ValueError()
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise SandboxError("Docker native control returned malformed bounded JSON") from None

    def close(self):
        self.client.close()
