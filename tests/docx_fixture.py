"""Hand-authored OOXML package; no production parser creates expectations."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"
CONTENT_TYPES = b"""<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
RELS = b"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
BODY = """<w:p><w:r><w:t>Pool timeout</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">  Inspect connections.</w:t><w:tab/><w:t>Retry</w:t><w:br/><w:t>Then stop.</w:t></w:r></w:p>"""


def xml(body=BODY, namespace=WORD):
    return f'<w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'.encode()


def docx(document=None, *, content_types=CONTENT_TYPES, relationships=RELS, extras=()):
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:

        def part(name, data):
            info = ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)

        if content_types is not None:
            part("[Content_Types].xml", content_types)
        if relationships is not None:
            part("_rels/.rels", relationships)
        if document is not None:
            part("word/document.xml", document)
        for name, data in extras:
            part(name, data)
    return buffer.getvalue()
