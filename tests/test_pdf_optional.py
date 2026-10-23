import pytest

from relf_agent import SourceDocument
from relf_agent.errors import ValidationError


def parser():
    import relf_agent

    assert hasattr(relf_agent, "PdfDocumentParser"), "Missing optional PDF parser"
    return relf_agent.PdfDocumentParser()


def test_pdf_missing_optional_dependency_is_typed_and_sdk_stays_usable(monkeypatch):
    import sys

    import relf_agent

    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert (
        relf_agent.TextDocumentParser().parse(SourceDocument("a", b"text")).document.text == "text"
    )
    with pytest.raises(ValidationError, match=r"relf-agent\[pdf\]"):
        parser()
