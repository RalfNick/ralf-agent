"""Pure text units, Unicode-safe slicing, and fixed replaceable tokenizers."""

import copy
import inspect
from typing import Protocol

from .context_budget import ContextMeasure, _positive
from .errors import DefinitionMismatch, RalfError, ValidationError
from .ports import is_sync_callable
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest


def _text_bytes(text):
    if not isinstance(text, str) or len(text) > 8 * 1024 * 1024:
        raise ValidationError("Tokenizer requires bounded text")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError("Tokenizer requires valid UTF-8") from None
    if len(data) > 8 * 1024 * 1024:
        raise ValidationError("Tokenizer text exceeds the byte limit")
    return data


def _units(value):
    if type(value) is not int or not 0 <= value <= 100000000:
        raise ValidationError("Tokenizer units must be a bounded non-negative integer")
    return value


class TextTokenizer(Protocol):
    identity: dict
    unit: str

    def count(self, text: str) -> int: ...

    def prefix(self, text: str, limit: int) -> str: ...

    def suffix(self, text: str, limit: int) -> str: ...


class UTF8ByteTokenizer:
    """Dependency-free byte units; deliberately not advertised as model tokens."""

    identity = {"kind": "utf8-byte-tokenizer", "version": "1"}
    unit = "utf8-bytes"

    def count(self, text):
        return len(_text_bytes(text))

    def prefix(self, text, limit):
        data = _text_bytes(text)[: _units(limit)]
        return data.decode("utf-8", errors="ignore")

    def suffix(self, text, limit):
        data = _text_bytes(text)
        limit = _units(limit)
        return data[-limit:].decode("utf-8", errors="ignore") if limit else ""


class _Tokenizer:
    def __init__(self, tokenizer):
        self.component = UTF8ByteTokenizer() if tokenizer is None else tokenizer
        identity = getattr(self.component, "identity", None)
        unit = getattr(self.component, "unit", None)
        if not isinstance(identity, dict) or not identity:
            raise ValidationError("Tokenizer requires a JSON identity")
        if not isinstance(unit, str) or not unit.strip() or len(unit) > 100:
            raise ValidationError("Tokenizer requires a bounded unit name")
        self._identity, self.unit = copy.deepcopy(identity), unit
        canonical(self._identity)
        self._bindings = {}
        implementations = {}
        for name in ("count", "prefix", "suffix"):
            method = getattr(self.component, name, None)
            if not is_sync_callable(method):
                raise ValidationError("Tokenizer methods must be pure synchronous callables")
            self._bindings[name] = _binding(method)
            implementations[name] = digest(_callable_identity(method))
        self.release = {"identity": self._identity, "unit": unit, "methods": implementations}

    def check(self):
        if (
            digest(getattr(self.component, "identity", None)) != digest(self._identity)
            or getattr(self.component, "unit", None) != self.unit
            or any(
                _binding(getattr(self.component, n, None)) != b for n, b in self._bindings.items()
            )
        ):
            raise DefinitionMismatch("Tokenizer configuration or implementation changed")

    def call(self, name, *args):
        self.check()
        try:
            value = getattr(self.component, name)(*args)
        except RalfError:
            raise
        except Exception:
            raise ValidationError("Tokenizer failed") from None
        self.check()
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        if name == "count":
            return _units(value)
        text, limit = args
        if not isinstance(value, str) or (
            name == "prefix"
            and not text.startswith(value)
            or name == "suffix"
            and not text.endswith(value)
        ):
            raise ValidationError("Tokenizer slice must preserve the original Unicode text")
        if self.call("count", value) > limit:
            raise ValidationError("Tokenizer slice exceeds its unit limit")
        return value


class TokenizerMessageCounter:
    """Canonical message text plus output reserve; not vendor framing or billing."""

    def __init__(self, tokenizer=None, *, output_reserve=0):
        self._tokenizer = _Tokenizer(tokenizer)
        self._reserve = _units(output_reserve)

    @property
    def identity(self):
        self._tokenizer.check()
        return copy.deepcopy(
            {
                "kind": "tokenizer-message-counter",
                "version": "1",
                "tokenizer": self._tokenizer.release,
                "output_reserve": self._reserve,
            }
        )

    def count(self, messages):
        text = canonical(messages)
        _text_bytes(text)
        return ContextMeasure(
            self._tokenizer.call("count", text) + self._reserve,
            f"canonical/{self._tokenizer.unit}",
            True,
        )


class TokenChunker:
    """Bounded token windows with exact parsed-character source locations."""

    def __init__(self, tokenizer=None, *, size=1000, overlap=100, window_chars=8192):
        self._size = _positive(size, "Token chunk size", 100000000)
        self._overlap = _units(overlap)
        if self._overlap >= self._size:
            raise ValidationError("Token overlap must be smaller than chunk size")
        self._window = _positive(window_chars, "Token window", 32768)
        self._tokenizer = _Tokenizer(tokenizer)

    @property
    def identity(self):
        self._tokenizer.check()
        return copy.deepcopy(
            {
                "kind": "token-chunker",
                "version": "1",
                "tokenizer": self._tokenizer.release,
                "size": self._size,
                "overlap": self._overlap,
                "window_chars": self._window,
            }
        )

    def split(self, parsed):
        from .ingestion_types import MAX_CHUNKS, MAX_PARSED_CHARS, ChunkSpan, ParsedDocument

        if not isinstance(parsed, ParsedDocument):
            raise ValidationError("Token chunker requires ParsedDocument")
        text = parsed.document.text
        _text_bytes(text)
        self._tokenizer.check()
        result, start, volume = [], 0, 0
        while start < len(text):
            if len(result) >= MAX_CHUNKS:
                raise ValidationError("Chunk count exceeds the limit")
            window = text[start : start + self._window]
            chunk = self._tokenizer.call("prefix", window, self._size)
            end = start + len(chunk)
            if result and end <= result[-1].end:
                # Wide characters or BPE boundary changes can consume the whole
                # budget in overlap. Retry new content without overlap; all
                # preceding text is already covered by the previous span.
                start = result[-1].end
                window = text[start : start + self._window]
                chunk = self._tokenizer.call("prefix", window, self._size)
                end = start + len(chunk)
            if not chunk or result and end <= result[-1].end:
                raise ValidationError("Tokenizer cannot make Unicode-safe forward progress")
            volume += len(chunk)
            if volume > 4 * MAX_PARSED_CHARS:
                raise ValidationError("Expanded token chunks exceed the limit")
            result.append(ChunkSpan(start, end))
            if end == len(text):
                break
            suffix = self._tokenizer.call("suffix", chunk[1:], self._overlap)
            start = end - len(suffix)
        self._tokenizer.check()
        return tuple(result)
