"""Optional owned BPE vocabulary. Loading model assets belongs to host assembly."""

import copy
import hashlib
from importlib.metadata import version

from .errors import DefinitionMismatch, ValidationError
from .task_controls import _binding
from .tokenization import _text_bytes, _units


def _native(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except BaseException as exc:
        # PyO3 exposes Rust panics outside Exception. Normalize only this native
        # failure and ordinary exceptions; preserve cancellation/process exit.
        if isinstance(exc, Exception) or (
            type(exc).__name__ == "PanicException" and type(exc).__module__ == "pyo3_runtime"
        ):
            raise ValidationError("Native tokenizer failed") from None
        raise


class TiktokenTokenizer:
    unit = "tiktoken-tokens"

    def __init__(self, *, name, pat_str, mergeable_ranks, special_tokens=None):
        try:
            import tiktoken
        except ImportError:
            raise ValidationError("Install relf-agent[tokenizer] for TiktokenTokenizer") from None
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValidationError("Tokenizer requires a bounded encoding name")
        if not isinstance(pat_str, str) or not pat_str or len(pat_str) > 16384:
            raise ValidationError("Tokenizer requires a bounded splitting expression")
        ranks = copy.deepcopy(mergeable_ranks)
        special = {} if special_tokens is None else copy.deepcopy(special_tokens)
        if (
            not isinstance(ranks, dict)
            or not 256 <= len(ranks) <= 1000000
            or any(
                not isinstance(k, bytes)
                or not 1 <= len(k) <= 1024
                or type(v) is not int
                or not 0 <= v < 2**32
                for k, v in ranks.items()
            )
            or any(bytes([i]) not in ranks for i in range(256))
            or len(set(ranks.values())) != len(ranks)
            or not isinstance(special, dict)
            or len(special) > 1024
            or any(
                not isinstance(k, str)
                or not k
                or len(k) > 1024
                or type(v) is not int
                or not 0 <= v < 2**32
                for k, v in special.items()
            )
            or len(set(special.values())) != len(special)
            or set(special.values()) & set(ranks.values())
            or sum(len(k) for k in ranks) > 32 * 1024 * 1024
        ):
            raise ValidationError("Tokenizer requires a complete bounded byte vocabulary")
        hasher = hashlib.sha256()
        for key, rank in sorted(ranks.items()):
            hasher.update(len(key).to_bytes(4, "big") + key + rank.to_bytes(4, "big"))
        self._encoding = _native(
            tiktoken.Encoding, name, pat_str=pat_str, mergeable_ranks=ranks, special_tokens=special
        )
        self._identity = {
            "kind": "tiktoken-tokenizer",
            "version": "1",
            "library_version": version("tiktoken"),
            "name": name,
            "pattern": pat_str,
            "vocabulary_sha256": hasher.hexdigest(),
            "special_tokens": special,
            "special_handling": "ordinary-text",
        }
        self._core = self._encoding._core_bpe
        self._bindings = {
            n: _binding(getattr(self._encoding, n)) for n in ("encode_ordinary", "decode_bytes")
        }

    def _check(self):
        if self._encoding._core_bpe is not self._core or any(
            _binding(getattr(self._encoding, n)) != b for n, b in self._bindings.items()
        ):
            raise DefinitionMismatch("Native tokenizer implementation changed")

    @property
    def identity(self):
        self._check()
        return copy.deepcopy(self._identity)

    def _tokens(self, text):
        data = _text_bytes(text)
        self._check()
        tokens = _native(self._encoding.encode_ordinary, text)
        self._check()
        complete = _native(self._encoding.decode_bytes, tokens) == data
        self._check()
        if not complete:
            raise ValidationError("Tokenizer pattern omitted source text")
        return tokens

    def count(self, text):
        return len(self._tokens(text))

    def _slice(self, text, limit, suffix):
        limit = _units(limit)
        tokens = self._tokens(text)
        if len(tokens) <= limit:
            return text
        # Token boundaries can split UTF-8. Do not decode with replacement, and
        # do not assume BPE counts are monotonic for truncated text.
        for size in range(limit, max(-1, limit - 64), -1):
            selected = tokens[-size:] if suffix and size else tokens[:size]
            data = _native(self._encoding.decode_bytes, selected)
            self._check()
            try:
                candidate = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if (text.endswith(candidate) if suffix else text.startswith(candidate)) and self.count(
                candidate
            ) <= limit:
                self._check()
                return candidate
        self._check()
        return ""

    def prefix(self, text, limit):
        return self._slice(text, limit, False)

    def suffix(self, text, limit):
        return self._slice(text, limit, True)
