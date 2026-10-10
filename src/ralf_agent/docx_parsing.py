"""Bounded canonical DOCX body extraction from caller bytes, without file or URL I/O."""

import re
import stat
import zlib
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from .errors import ValidationError
from .ingestion_types import MAX_PARSED_CHARS, ParsedDocument, SourceDocument
from .retrieval import Document
from .tools import _callable_identity
from .types import digest

_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAIN_TYPE = _MIME + ".main+xml"
_WORD = frozenset(
    {
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main",
    }
)
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
    }
)
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SKIP = frozenset(
    {
        "del",
        "moveFrom",
        "delText",
        "instrText",
        "drawing",
        "pict",
        "object",
        "txbxContent",
        "rPr",
        "pPr",
        "sdtPr",
    }
)
_WRAPPERS = frozenset({"body", "sdt", "sdtContent", "customXml", "ins", "tc"})


def _parts(archive):
    values = archive.infolist()
    if len(values) > 256 or sum(v.file_size for v in values) > 8 * 1024 * 1024:
        raise ValidationError("DOCX archive exceeds member or declared expanded-size limits")
    names = set()
    for item in values:
        name = item.filename
        if (
            name in names
            or item.orig_filename != name
            or "\x00" in name
            or not name
            or len(name) > 256
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
            or item.flag_bits & 1
            or item.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise ValidationError("Unsupported or ambiguous DOCX archive member")
        names.add(name)
    if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
        raise ValidationError(
            "DOCX requires canonical content types, root relationships and main part"
        )


def _read(archive, name, limit):
    if archive.getinfo(name).file_size > limit:
        raise ValidationError("DOCX XML part exceeds its byte limit")
    with archive.open(name) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValidationError("DOCX XML part exceeds its byte limit")
    return data


def _xml(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("DOCX XML requires UTF-8") from None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValidationError("DOCX DTD/entity declarations are unsupported")
    if text.startswith("<?xml"):
        encoding = re.search(r"encoding\s*=\s*['\"]([^'\"]+)['\"]", text[: text.find("?>")])
        if encoding and encoding[1].replace("-", "").lower() != "utf8":
            raise ValidationError("DOCX XML requires a UTF-8 declaration")
    count, depth = 0, 0
    with BytesIO(text.encode("utf-8")) as stream:
        iterator = ET.iterparse(stream, events=("start", "end"))
        for event, _node in iterator:
            if event == "start":
                count, depth = count + 1, depth + 1
                if count > 65536 or depth > 256:
                    raise ValidationError("DOCX XML exceeds element or nesting limits")
            else:
                depth -= 1
        return iterator.root


def _package(archive):
    _parts(archive)
    types = _xml(_read(archive, "[Content_Types].xml", 65536))
    main_types = [
        n.get("ContentType")
        for n in types
        if n.tag == f"{{{_CT}}}Override" and n.get("PartName") == "/word/document.xml"
    ]
    if types.tag != f"{{{_CT}}}Types" or main_types != [_MAIN_TYPE]:
        raise ValidationError("DOCX requires one macro-free Word main content type")
    relationships = _xml(_read(archive, "_rels/.rels", 65536))
    main = [
        n
        for n in relationships
        if n.tag == f"{{{_REL}}}Relationship" and n.get("Type") in _OFFICE_REL
    ]
    if (
        relationships.tag != f"{{{_REL}}}Relationships"
        or len(main) != 1
        or main[0].get("Target") not in {"word/document.xml", "/word/document.xml"}
        or main[0].get("TargetMode", "Internal") != "Internal"
    ):
        raise ValidationError("DOCX requires one internal canonical main relationship")
    document = _xml(_read(archive, "word/document.xml", 4 * 1024 * 1024))
    namespace = next((ns for ns in _WORD if document.tag == f"{{{ns}}}document"), None)
    body = [] if namespace is None else document.findall(f"{{{namespace}}}body")
    if len(body) != 1:
        raise ValidationError("DOCX requires one WordprocessingML body")
    return body[0], namespace


def _name(node, namespace):
    prefix = "{" + namespace + "}"
    return node.tag[len(prefix) :] if node.tag.startswith(prefix) else None


def _hidden(node, namespace):
    for item in node.findall(f"{{{namespace}}}rPr/{{{namespace}}}vanish"):
        if item.get(f"{{{namespace}}}val", "true").lower() not in {"false", "0", "off"}:
            return True
    return False


def _inline(node, namespace):
    name = _name(node, namespace)
    if name is None or name in _SKIP or name == "r" and _hidden(node, namespace):
        return ""
    if name == "t":
        return node.text or ""
    if name == "tab":
        return "\t"
    if name == "noBreakHyphen":
        return "\u2011"
    if name == "softHyphen":
        return "\u00ad"
    if name in {"br", "cr"}:
        return "\n"
    return "".join(_inline(child, namespace) for child in node)


def _table_items(node, target, namespace):
    result = []
    for child in node:
        name = _name(child, namespace)
        if name == target:
            result.append(child)
        elif name in _WRAPPERS:
            result.extend(_table_items(child, target, namespace))
    return result


def _blocks(node, namespace):
    name = _name(node, namespace)
    if name == "p":
        return [_inline(node, namespace)]
    if name == "tbl":
        return [
            "\t".join(
                "\n".join(_blocks(cell, namespace)) for cell in _table_items(row, "tc", namespace)
            )
            for row in _table_items(node, "tr", namespace)
        ]
    if name not in _WRAPPERS:
        return []
    return [line for child in node for line in _blocks(child, namespace)]


class DocxDocumentParser:
    @property
    def identity(self):
        return {
            "kind": "canonical-docx-body-parser",
            "version": "1",
            "media_types": [_MIME],
            "max_members": 256,
            "max_declared_expanded_bytes": 8 * 1024 * 1024,
            "max_main_xml_bytes": 4 * 1024 * 1024,
            "max_metadata_xml_bytes": 65536,
            "max_xml_elements": 65536,
            "max_xml_depth": 256,
            "max_parsed_chars": MAX_PARSED_CHARS,
            "policy": "body-paragraph-table-preserve-whitespace-no-fetch-v1",
            "word_namespaces": sorted(_WORD),
            "relationship_namespace": _REL,
            "office_relationships": sorted(_OFFICE_REL),
            "content_types_namespace": _CT,
            "main_content_type": _MAIN_TYPE,
            "suppressed_elements": sorted(_SKIP),
            "block_wrappers": sorted(_WRAPPERS),
            "implementation": {
                f.__name__: digest(_callable_identity(f))
                for f in (
                    _parts,
                    _read,
                    _xml,
                    _package,
                    _name,
                    _hidden,
                    _inline,
                    _table_items,
                    _blocks,
                )
            },
        }

    def parse(self, source):
        if not isinstance(source, SourceDocument) or source.media_type != _MIME:
            raise ValidationError("DOCX parser requires a DOCX SourceDocument")
        try:
            with ZipFile(BytesIO(source.data)) as archive:
                body, namespace = _package(archive)
                text = "\n".join(_blocks(body, namespace))
        except ValidationError:
            raise
        except (
            BadZipFile,
            ET.ParseError,
            ValueError,
            RuntimeError,
            OSError,
            EOFError,
            zlib.error,
        ) as exc:
            raise ValidationError("Invalid or unsupported DOCX package") from exc
        if len(text) > MAX_PARSED_CHARS:
            raise ValidationError("DOCX parsed text exceeds the 1MiB character limit")
        return ParsedDocument(
            Document(source.document_id, text, source.source_uri, source.metadata), source.sha256
        )
