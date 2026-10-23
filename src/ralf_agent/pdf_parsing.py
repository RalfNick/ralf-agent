"""Optional text-PDF adapter over caller bytes; no file, URL or OCR I/O."""

import copy
import importlib
import re
from dataclasses import asdict
from io import BytesIO

from .errors import DefinitionMismatch, ValidationError
from .ingestion_types import MAX_PARSED_CHARS, ParsedDocument, SourceDocument
from .retrieval import Document
from .tools import _callable_identity
from .types import digest

_LIMITS = {
    "maximum_declared_stream_length": 8 * 1024 * 1024,
    "array_based_stream_maximum_output_length": 8 * 1024 * 1024,
    "jbig2_maximum_output_length": 8 * 1024 * 1024,
    "lzw_maximum_output_length": 8 * 1024 * 1024,
    "run_length_maximum_output_length": 8 * 1024 * 1024,
    "zlib_maximum_output_length": 8 * 1024 * 1024,
    "zlib_maximum_recovery_input_length": 1024 * 1024,
    "brotli_maximum_output_length": 8 * 1024 * 1024,
    "image_maximum_buffer_size": 8 * 1024 * 1024,
    "stream_filters_maximum_length": 8,
    "stream_decoding_work_maximum_length": 32 * 1024 * 1024,
    "page_tree_maximum_entries": 256,
    "page_tree_maximum_depth": 64,
    "xform_maximum_invocations_per_extraction": 128,
    "jbig2dec_binary": None,
    "disable_legacy_handling": True,
}


def _library():
    try:
        module = importlib.import_module("pypdf")
    except ImportError:
        raise ValidationError("PDF parsing requires optional relf-agent[pdf]") from None
    version = getattr(module, "__version__", "")
    match = re.fullmatch(r"6\.(\d+)\.(\d+)", version)
    if not match or int(match[1]) < 20:
        raise ValidationError("PDF parsing requires relf-agent[pdf] with pypdf>=6.20,<7")
    return module


_RTL_FIELDS = ("CUSTOM_RTL_MIN", "CUSTOM_RTL_MAX", "CUSTOM_RTL_SPECIAL_CHARS")


def _rtl(module):
    return tuple(getattr(module, field) for field in _RTL_FIELDS)


def _preflight(content, resources, reader, stream_type, extract_form, budget, path, depth=0):
    if content is None:
        return
    if depth > 32:
        raise ValidationError("PDF Form nesting exceeds the limit")
    budget["bytes"] += len(content.get_data())
    if budget["bytes"] > 8 * 1024 * 1024:
        raise ValidationError("PDF content including Form work exceeds the 8MiB limit")
    resources = {} if resources is None else resources.get_object()
    if not isinstance(resources, dict):
        raise ValidationError("Unsupported PDF resources")
    for operands, operator in content.operations:
        if operator != b"Do":
            continue
        if len(operands) != 1:
            raise ValidationError("Invalid PDF XObject invocation")
        obj = resources["/XObject"][operands[0]].get_object()
        subtype = obj.get("/Subtype")
        if subtype == "/Image":
            continue
        if subtype != "/Form":
            raise ValidationError("Unsupported PDF XObject")
        budget["forms"] += 1
        if budget["forms"] > 128 or id(obj) in path:
            raise ValidationError("PDF Form invocation limit or cycle")
        if "/Resources" not in obj:
            raise ValidationError("PDF Form requires explicit resources")
        path.add(id(obj))
        try:
            _preflight(
                stream_type(obj, reader),
                obj["/Resources"],
                reader,
                stream_type,
                extract_form,
                budget,
                path,
                depth + 1,
            )
            # Validate each Form outside the parent extractor's catch-and-skip boundary.
            if not isinstance(extract_form(obj), str):
                raise ValidationError("PDF Form extractor must return text")
        finally:
            path.remove(id(obj))


class PdfDocumentParser:
    def __init__(self):
        self._library = _library()
        self._version = self._library.__version__
        self._rtl_module = importlib.import_module("pypdf._text_extraction")
        self._rtl = _rtl(self._rtl_module)
        self._generic = importlib.import_module("pypdf.generic")
        self._stream_type = self._generic.ContentStream
        self._bindings = {
            name: getattr(self._library, name)
            for name in ("PdfReader", "Configuration", "apply_configuration")
        }
        self._configuration = self._bindings["Configuration"](**_LIMITS)

    @property
    def identity(self):
        self._check()
        return {
            "kind": "pypdf-text-document-parser",
            "version": "1",
            "media_types": ["application/pdf"],
            "dependency_version": self._library.__version__,
            "configuration": asdict(self._configuration),
            "rtl_settings": list(self._rtl),
            "rtl_fields": list(_RTL_FIELDS),
            "limits": copy.deepcopy(_LIMITS),
            "max_pages": 64,
            "max_content_work_bytes": 8 * 1024 * 1024,
            "max_form_depth": 32,
            "max_parsed_chars": MAX_PARSED_CHARS,
            "policy": "strict-unencrypted-plain-page-order-no-ocr-v1",
            "implementation": {
                "library_loader": digest(_callable_identity(_library)),
                "dependency_check": digest(_callable_identity(self._check)),
                "form_preflight": digest(_callable_identity(_preflight)),
                "rtl_reader": digest(_callable_identity(_rtl)),
            },
        }

    def _check(self):
        if (
            self._library.__version__ != self._version
            or _rtl(self._rtl_module) != self._rtl
            or self._generic.ContentStream is not self._stream_type
            or any(
                getattr(self._library, name) is not function
                for name, function in self._bindings.items()
            )
        ):
            raise DefinitionMismatch("PDF dependency registration changed")

    def parse(self, source):
        if not isinstance(source, SourceDocument) or source.media_type != "application/pdf":
            raise ValidationError("PDF parser requires an application/pdf SourceDocument")
        self._check()
        reader = None
        try:
            with (
                BytesIO(source.data) as stream,
                self._bindings["apply_configuration"](self._configuration),
            ):
                reader = self._bindings["PdfReader"](stream, strict=True)
                if reader.is_encrypted:
                    raise ValidationError(
                        "Encrypted PDF is unsupported; provide unencrypted text PDF"
                    )
                if len(reader.pages) > 64:
                    raise ValidationError("PDF exceeds the 64-page limit")
                pages, total_chars = [], 0
                budget = {"bytes": 0, "forms": 0}
                for page in reader.pages:
                    content = page.get_contents()
                    budget["forms"] = 0
                    _preflight(
                        content,
                        page.get("/Resources"),
                        reader,
                        self._stream_type,
                        page.extract_xform_text,
                        budget,
                        set(),
                    )
                    text = page.extract_text(extraction_mode="plain")
                    if not isinstance(text, str):
                        raise ValidationError("PDF extractor must return text")
                    total_chars += len(text) + bool(pages)
                    if total_chars > MAX_PARSED_CHARS:
                        raise ValidationError("PDF parsed text exceeds the 1MiB character limit")
                    pages.append(text)
                text = "\n".join(pages)
                if not text.strip():
                    raise ValidationError("PDF has no extractable text; OCR is not provided")
                self._check()
        except (ValidationError, DefinitionMismatch):
            raise
        except Exception as exc:
            raise ValidationError("Invalid or unsupported text PDF") from exc
        finally:
            if reader is not None:
                reader.close()
        return ParsedDocument(
            Document(source.document_id, text, source.source_uri, source.metadata), source.sha256
        )
