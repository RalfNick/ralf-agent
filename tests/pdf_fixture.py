"""Hand-authored minimal PDF objects/xref; no production extractor builds expectations."""

import zlib


def pdf(
    pages=(b"BT /F1 12 Tf 72 720 Td (Pool timeout) Tj 0 -20 Td (Inspect connections.) Tj ET",),
    *,
    compressed=False,
):
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for content in pages:
        page_id = len(objects) + 1
        stream_id = page_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode()
        )
        data = zlib.compress(content) if compressed else content
        filter_ = b" /Filter /FlateDecode" if compressed else b""
        objects.append(
            b"<< /Length "
            + str(len(data)).encode()
            + filter_
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kids)}] >>".encode()
    return package(objects)


def package(objects):
    result = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return (
        result
        + f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )


def form_pdf(
    *,
    invocations=1,
    form_content=b"BT /F1 12 Tf 72 700 Td (Inspect connections.) Tj ET",
    compressed=False,
    cyclic=False,
    missing=False,
):
    content = (
        b"BT /F1 12 Tf 72 720 Td (Pool timeout) Tj ET\n"
        + (b"/Absent Do\n" if missing else b"/Fm Do\n") * invocations
    )
    form_content += b"\n/Fm Do" if cyclic else b""
    data = zlib.compress(form_content) if compressed else form_content
    return package(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> /XObject << /Fm 6 0 R >> >> /Contents 5 0 R >>",
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
            b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> /XObject << /Fm 6 0 R >> >> /Length "
            + str(len(data)).encode()
            + (b" /Filter /FlateDecode" if compressed else b"")
            + b" >>\nstream\n"
            + data
            + b"\nendstream",
        ]
    )
