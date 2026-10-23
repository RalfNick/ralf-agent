"""Pure parsing of caller-provided bytes; never reads files or follows URLs."""

from typing import Protocol

from .errors import ValidationError
from .ingestion_types import ParsedDocument, SourceDocument
from .retrieval import Document


class DocumentParser(Protocol):
    identity: dict

    def parse(self, source: SourceDocument) -> ParsedDocument: ...


class TextDocumentParser:
    identity = {
        "kind": "utf8-document-parser",
        "version": "1",
        "media_types": ["text/plain", "text/markdown"],
    }

    def parse(self, source):
        if (
            not isinstance(source, SourceDocument)
            or source.media_type not in self.identity["media_types"]
        ):
            raise ValidationError("Default parser supports text/plain and text/markdown")
        try:
            text = source.data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError("Source is not valid UTF-8") from None
        return ParsedDocument(
            Document(source.document_id, text, source.source_uri, source.metadata), source.sha256
        )
