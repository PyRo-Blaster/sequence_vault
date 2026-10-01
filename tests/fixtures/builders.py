"""Build small synthetic DOCX, XLSX and PDF files for tests. Nothing here is research data."""

import io
import zipfile
from collections.abc import Sequence
from xml.sax.saxutils import escape

from openpyxl import Workbook

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)

Run = tuple[str, str]  # (kind, text): t, ins, del, hidden, br, textbox


def _run(kind: str, text: str) -> str:
    t = escape(text)
    if kind == "t":
        return f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'
    if kind == "hidden":
        return f'<w:r><w:rPr><w:vanish/></w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>'
    if kind == "ins":
        return (
            f'<w:ins w:id="1" w:author="r"><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:ins>'
        )
    if kind == "del":
        return (
            f'<w:del w:id="2" w:author="r"><w:r><w:delText xml:space="preserve">{t}</w:delText>'
            "</w:r></w:del>"
        )
    if kind == "br":
        return "<w:r><w:br/></w:r>"
    if kind == "textbox":
        return (
            '<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>'
            f"<w:txbxContent><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:txbxContent>"
            "</v:textbox></v:shape></w:pict></w:r>"
        )
    raise ValueError(kind)


def docx(
    items: list[str | list[Run] | list[list[str]]],
    *,
    extra_parts: dict[str, bytes] | None = None,
) -> bytes:
    """Items: a string paragraph, a list of runs, or a table as a list of rows."""
    body = []
    for item in items:
        if isinstance(item, str):
            body.append(f"<w:p>{_run('t', item) if item else ''}</w:p>")
        elif item and isinstance(item[0], tuple):
            body.append("<w:p>" + "".join(_run(k, t) for k, t in item) + "</w:p>")
        else:
            rows = "".join(
                "<w:tr>"
                + "".join(f"<w:tc><w:p>{_run('t', c) if c else ''}</w:p></w:tc>" for c in row)
                + "</w:tr>"
                for row in item
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        for name, data in (extra_parts or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def xlsx(sheets: dict[str, list[list[object]]], *, hidden: tuple[str, ...] = ()) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
        if title in hidden:
            sheet.sheet_state = "hidden"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def pdf(pages: Sequence[Sequence[tuple[float, float, str]]]) -> bytes:
    """Text-only PDF with Helvetica. Each page is a list of (x, y, text), y from the bottom."""
    objects: list[bytes] = []
    page_ids = [3 + 2 * i for i in range(len(pages))]
    font_id = 3 + 2 * len(pages)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for page_id, lines in zip(page_ids, pages, strict=True):
        content = "".join(
            f"BT /F1 11 Tf {x} {y} Td ("
            + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            + ") Tj ET\n"
            for x, y, text in lines
        ).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {page_id + 1} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()
