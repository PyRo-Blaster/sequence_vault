"""Content-based file type detection. Extensions are only a hint and never trusted alone."""

import io
import zipfile
from pathlib import PurePath

from sequence_vault.application.ports import Detection

MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_RATIO = 100
MAX_ENTRIES = 5000

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_REJECTED_MAGIC = {
    b"\x1f\x8b": "gzip archive",
    b"7z\xbc\xaf\x27\x1c": "7z archive",
    b"Rar!": "RAR archive",
    b"MZ": "executable",
    b"\x7fELF": "executable",
}
_TEXT_EXTENSIONS = {".fasta", ".fa", ".faa", ".fas", ".txt", ".csv", ".tsv", ".seq"}


def _ooxml(data: bytes) -> Detection:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except zipfile.BadZipFile:
        return Detection(None, "corrupt_archive")
    if len(infos) > MAX_ENTRIES:
        return Detection(None, "archive_too_many_entries")
    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED or total > MAX_RATIO * max(len(data), 1):
        return Detection(None, "decompression_limit")
    names = {info.filename for info in infos}
    if "[Content_Types].xml" not in names:
        return Detection(None, "archive")
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        return Detection(None, "macro_enabled_office")
    content_types = archive.read("[Content_Types].xml").decode("utf-8", "replace")
    if "macroEnabled" in content_types:
        return Detection(None, "macro_enabled_office")
    if "word/document.xml" in names:
        return Detection("docx", "ooxml_word")
    if "xl/workbook.xml" in names:
        return Detection("xlsx", "ooxml_spreadsheet")
    return Detection(None, "unsupported_office_format")


def _looks_like_text(data: bytes) -> bool:
    sample = data[:65536]
    if b"\0" in sample:
        return False
    controls = sum(1 for byte in sample if byte < 32 and byte not in (9, 10, 12, 13))
    return controls <= len(sample) // 100


class ContentTypeDetector:
    def detect(self, data: bytes, file_name: str) -> Detection:
        if not data:
            return Detection(None, "empty_file")
        if data.startswith(_OLE):
            return Detection(None, "legacy_office_format")
        for magic, reason in _REJECTED_MAGIC.items():
            if data.startswith(magic):
                return Detection(None, reason.replace(" ", "_"))
        if data.startswith(b"%PDF-"):
            return Detection("text_pdf", "pdf")
        if data.startswith(b"PK\x03\x04"):
            return _ooxml(data)
        if not _looks_like_text(data):
            return Detection(None, "binary_content")
        stripped = data.lstrip(b"\xef\xbb\xbf \t\r\n")
        if stripped.startswith(b">"):
            return Detection("fasta", "fasta_header")
        suffix = PurePath(file_name).suffix.lower()
        if suffix in {".csv", ".tsv"}:
            return Detection("csv", "delimited_text")
        if suffix and suffix not in _TEXT_EXTENSIONS:
            return Detection("txt", f"text_with_{suffix[1:]}_extension")
        return Detection("txt", "text")
