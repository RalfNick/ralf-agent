"""Pure replaceable character/paragraph spans over parsed text."""

import re
from bisect import bisect_right
from typing import Protocol

from .errors import ValidationError
from .ingestion_types import MAX_CHUNKS, ChunkSpan, ParsedDocument
from .retrieval import _chunk_config


class Chunker(Protocol):
    identity: dict

    def split(self, parsed: ParsedDocument) -> tuple[ChunkSpan, ...]: ...


class CharacterChunker:
    def __init__(self, *, size=1000, overlap=100):
        _chunk_config(size, overlap)
        self.size, self.overlap = size, overlap

    @property
    def identity(self):
        return {
            "kind": "character-chunker",
            "version": "1",
            "size": self.size,
            "overlap": self.overlap,
        }

    def split(self, parsed):
        if not isinstance(parsed, ParsedDocument):
            raise ValidationError("Chunker requires ParsedDocument")
        _chunk_config(self.size, self.overlap)
        result = []
        start = 0
        text = parsed.document.text
        while start < len(text):
            if len(result) >= MAX_CHUNKS:
                raise ValidationError("Chunk count exceeds the limit")
            end = min(start + self.size, len(text))
            result.append(ChunkSpan(start, end))
            if end == len(text):
                break
            start += self.size - self.overlap
        return tuple(result)


class ParagraphChunker:
    def __init__(self, *, size=1000):
        _chunk_config(size, 0)
        self.size = size

    @property
    def identity(self):
        return {"kind": "paragraph-chunker", "version": "1", "size": self.size}

    def split(self, parsed):
        if not isinstance(parsed, ParsedDocument):
            raise ValidationError("Chunker requires ParsedDocument")
        _chunk_config(self.size, 0)
        text = parsed.document.text
        breaks = [match.end() for match in re.finditer(r"\n[ \t]*\r?\n", text)] + [len(text)]
        result = []
        start = 0
        while start < len(text):
            if len(result) >= MAX_CHUNKS:
                raise ValidationError("Chunk count exceeds the limit")
            hard = min(start + self.size, len(text))
            index = bisect_right(breaks, hard) - 1
            end = breaks[index] if index >= 0 and breaks[index] > start else hard
            result.append(ChunkSpan(start, end))
            start = end
        return tuple(result)
