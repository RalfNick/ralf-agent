import pytest

from ralf_agent import SourceDocument
from ralf_agent.errors import ValidationError


def parser():
    import ralf_agent

    assert hasattr(ralf_agent, "PdfDocumentParser"), "Missing optional PDF parser"
    return ralf_agent.PdfDocumentParser()


def test_pdf_missing_optional_dependency_is_typed_and_sdk_stays_usable(monkeypatch):
    import sys

    import ralf_agent

    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert (
        ralf_agent.TextDocumentParser().parse(SourceDocument("a", b"text")).document.text == "text"
    )
    with pytest.raises(ValidationError, match=r"ralf-agent\[pdf\]"):
        parser()
