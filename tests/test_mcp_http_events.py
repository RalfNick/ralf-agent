"""SSE wire framing independent from execution authority."""

import pytest

from ralf_agent import ToolSourceError


def messages(chunks, limit=1024):
    from ralf_agent.mcp_http_events import iter_sse_messages

    return list(iter_sse_messages(chunks, limit=limit))


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_chunked_unicode_multiline_comment_bom_and_empty_priming(newline):
    wire = b"\xef\xbb\xbf: keepalive" + newline + newline + b"data:" + newline + newline
    wire += b"event: message" + newline + b'data: {"text":' + newline
    wire += 'data: "中文🙂"}'.encode() + newline + newline
    chunks = [wire[index : index + 1] for index in range(len(wire))]
    assert messages(chunks) == ['{"text":\n"中文🙂"}'.encode()]


@pytest.mark.parametrize(
    "wire", [b"data: " + b"x" * 30 + b"\n\n", b":" + b"x" * 30, b"data: \xff\n\n"]
)
def test_invalid_encoding_and_unbounded_events_refuse(wire):
    with pytest.raises(ToolSourceError):
        messages([wire], limit=16)


def test_nonmessage_events_are_ignored_but_not_exempt_from_limit():
    assert messages([b"event: ignored\ndata: secret\n\ndata: {}\n\n"]) == [b"{}"]
    with pytest.raises(ToolSourceError):
        messages([b"event: ignored\ndata: " + b"x" * 50 + b"\n\n"], limit=20)


def test_eof_does_not_adopt_an_unterminated_event():
    assert messages([b"data: {}\n"]) == []


@pytest.mark.parametrize("newline", [b"\n", b"\r", b"\r\n"])
@pytest.mark.parametrize("split", [False, True])
def test_exact_wire_limit_includes_the_complete_event_delimiter(newline, split):
    wire = b"data: {}" + newline + newline
    chunks = [bytes([byte]) for byte in wire] if split else [wire]
    assert messages(chunks, limit=len(wire)) == [b"{}"]
    with pytest.raises(ToolSourceError, match="byte limit"):
        messages(chunks, limit=len(wire) - 1)
