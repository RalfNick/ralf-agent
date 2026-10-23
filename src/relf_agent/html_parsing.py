"""Bounded HTML text extraction; no browser, file I/O or URL fetching."""

import re
from html.parser import HTMLParser

from .errors import ValidationError
from .ingestion_types import MAX_PARSED_CHARS, ParsedDocument, SourceDocument
from .retrieval import Document
from .tools import _callable_identity
from .types import digest

_SKIP = frozenset({"head", "script", "style", "template", "iframe", "object", "noscript"})
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.events = self.chars = 0

    def _event(self):
        self.events += 1
        if self.events > 65536:
            raise ValidationError("HTML exceeds the 65536 parser event limit")

    def _append(self, text, preformatted=False):
        self.chars += len(text)
        if self.chars > MAX_PARSED_CHARS:
            raise ValidationError("HTML parsed text exceeds the 1MiB character limit")
        self.parts.append((text, preformatted))

    def _break(self):
        if not self.parts or not self.parts[-1][0].endswith("\n"):
            self._append("\n")

    def _suppressed(self):
        return bool(self.stack and self.stack[-1][1])

    def _start(self, tag, attrs):
        suppressed = (
            self._suppressed()
            or tag in _SKIP
            or any(
                key == "hidden" or key == "aria-hidden" and (value or "").strip().lower() == "true"
                for key, value in attrs
            )
        )
        if not suppressed and tag in _BLOCK:
            self._break()
        if tag not in _VOID:
            if len(self.stack) >= 256:
                raise ValidationError("HTML exceeds the 256 element nesting limit")
            preformatted = tag == "pre" or bool(self.stack and self.stack[-1][2])
            self.stack.append((tag, suppressed, preformatted))

    def _end(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                suppressed = self.stack[index][1]
                del self.stack[index:]
                if not suppressed and tag in _BLOCK:
                    self._break()
                break

    def handle_starttag(self, tag, attrs):
        self._event()
        self._start(tag, attrs)

    def handle_endtag(self, tag):
        self._event()
        self._end(tag)

    def handle_startendtag(self, tag, attrs):
        self._event()
        self._start(tag, attrs)
        self._end(tag)

    def handle_data(self, data):
        self._event()
        if not self._suppressed():
            preformatted = bool(self.stack and self.stack[-1][2])
            self._append(data if preformatted else re.sub(r"\s+", " ", data), preformatted)

    def handle_comment(self, data):
        self._event()

    def handle_decl(self, decl):
        self._event()

    def handle_pi(self, data):
        self._event()

    def unknown_decl(self, data):
        self._event()

    def text(self):
        lines, current, protected = [], "", False
        for text, preformatted in self.parts:
            for index, part in enumerate(text.split("\n")):
                if index:
                    if protected or current.strip():
                        lines.append(current if protected else current.strip())
                    current, protected = "", False
                current += part
                protected = protected or preformatted
        if protected or current.strip():
            lines.append(current if protected else current.strip())
        return "\n".join(lines)


class HtmlDocumentParser:
    @property
    def identity(self):
        return {
            "kind": "utf8-html-document-parser",
            "version": "1",
            "media_types": ["text/html"],
            "policy": "normalized-text-preserve-pre-no-fetch-v1",
            "max_depth": 256,
            "max_events": 65536,
            "max_parsed_chars": MAX_PARSED_CHARS,
            "suppressed_elements": sorted(_SKIP),
            "void_elements": sorted(_VOID),
            "block_elements": sorted(_BLOCK),
            "implementation": {
                name: digest(_callable_identity(method))
                for name, method in sorted(vars(_TextExtractor).items())
                if callable(method)
            },
        }

    def parse(self, source):
        if not isinstance(source, SourceDocument) or source.media_type != "text/html":
            raise ValidationError("HTML parser requires text/html SourceDocument")
        try:
            text = source.data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("HTML source is not valid UTF-8") from None
        extractor = _TextExtractor()
        try:
            extractor.feed(text)
            extractor.close()
        except ValidationError:
            raise
        except (AssertionError, ValueError) as exc:
            raise ValidationError("Malformed or unsupported HTML declaration") from exc
        return ParsedDocument(
            Document(source.document_id, extractor.text(), source.source_uri, source.metadata),
            source.sha256,
        )
