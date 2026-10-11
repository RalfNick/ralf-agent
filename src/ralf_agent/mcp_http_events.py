"""Bounded SSE framing for POST responses, independent of RPC/execution state."""

from .tool_sources import ToolSourceError


def iter_sse_messages(chunks, *, limit):
    line, data = bytearray(), []
    kind, size, after_cr, first_line = "", 0, False, True
    pending, payload = False, None

    def decoded(value):
        try:
            return value.decode("utf-8")
        except UnicodeError:
            raise ToolSourceError("MCP SSE requires valid UTF-8") from None

    for chunk in chunks:
        for byte in chunk:
            if after_cr:
                after_cr = False
                if byte == 10:
                    size += 1
                    if size > limit:
                        raise ToolSourceError("MCP SSE event exceeds its byte limit")
                    if pending:
                        if payload is not None:
                            yield payload
                        data, kind, size, pending = [], "", 0, False
                    continue
                if pending:
                    if payload is not None:
                        yield payload
                    data, kind, size, pending = [], "", 0, False
            size += 1
            if size > limit:
                raise ToolSourceError("MCP SSE event exceeds its byte limit")
            if byte not in (10, 13):
                line.append(byte)
                continue
            after_cr = byte == 13
            text = decoded(bytes(line))
            line.clear()
            if first_line:
                text = text.removeprefix("\ufeff")
                first_line = False
            if not text:
                message = "\n".join(data) if kind in {"", "message"} else ""
                payload = message.encode("utf-8") if message else None
                if after_cr:
                    # A following LF still belongs to this event. Do not adopt
                    # until that byte (or EOF/a new non-LF byte) is accounted.
                    pending = True
                else:
                    if payload is not None:
                        yield payload
                    data, kind, size = [], "", 0
            elif not text.startswith(":"):
                field, _, value = text.partition(":")
                value = value.removeprefix(" ")
                if field == "data":
                    data.append(value)
                elif field == "event":
                    kind = value
    decoded(bytes(line))
    if pending and payload is not None:
        yield payload
