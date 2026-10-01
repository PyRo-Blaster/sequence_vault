import io
import zipfile

import pytest

from sequence_vault.adapters.security.filetype import ContentTypeDetector

detect = ContentTypeDetector().detect


def ooxml(parts: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


DOCX = ooxml({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"})


@pytest.mark.parametrize(
    ("data", "name", "expected"),
    [
        (b">A1\nMKT\n", "a.fasta", "fasta"),
        (b"\xef\xbb\xbf>A1\nMKT\n", "a.txt", "fasta"),
        (b"RSPO3\nMKTAYIAKQR\n", "a.txt", "txt"),
        (b"name,sequence\nA,MKT\n", "a.csv", "csv"),
        (b"%PDF-1.7\n...", "a.pdf", "text_pdf"),
        (DOCX, "a.docx", "docx"),
        (ooxml({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<w/>"}), "a.xlsx", "xlsx"),
    ],
)
def test_detects_supported_content(data: bytes, name: str, expected: str) -> None:
    assert detect(data, name).format == expected


@pytest.mark.parametrize(
    ("data", "name", "reason"),
    [
        (b"%PDF-1.4 disguised", "sequences.fasta", None),  # misleading extension: still a PDF
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 50, "a.doc", "legacy_office_format"),
        (
            ooxml({"[Content_Types].xml": b"macroEnabled", "word/document.xml": b"x"}),
            "a.docx",
            "macro_enabled_office",
        ),
        (
            ooxml({"[Content_Types].xml": b"<T/>", "word/vbaProject.bin": b"x"}),
            "a.docx",
            "macro_enabled_office",
        ),
        (ooxml({"readme.txt": b"hello"}), "a.docx", "archive"),
        (b"PK\x03\x04broken", "a.docx", "corrupt_archive"),
        (b"\x1f\x8b\x08\x00", "a.fasta", "gzip_archive"),
        (b"MZ\x90\x00", "a.txt", "executable"),
        (b"\x00\x01\x02\x03" * 100, "a.fasta", "binary_content"),
        (b"", "a.fasta", "empty_file"),
    ],
)
def test_rejects_by_content_not_extension(data: bytes, name: str, reason: str | None) -> None:
    detection = detect(data, name)
    if reason is None:
        assert detection.format == "text_pdf"
    else:
        assert (detection.format, detection.reason) == (None, reason)


def test_rejects_zip_bombs() -> None:
    bomb = ooxml({"[Content_Types].xml": b"<T/>", "word/document.xml": b"A" * 50_000_000})
    assert detect(bomb, "a.docx").reason == "decompression_limit"
