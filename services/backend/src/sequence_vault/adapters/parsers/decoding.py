"""Decode text sources and report the encoding used."""

from charset_normalizer import from_bytes

from sequence_vault.application.ports import ParseFailed


def decode(data: bytes) -> tuple[str, str]:
    """UTF-8 (with or without BOM) first, then the best guess including GB18030."""
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    guess = from_bytes(data, cp_isolation=["gb18030", "big5", "utf_16", "cp1252", "latin_1"]).best()
    if guess is None:
        raise ParseFailed("The text encoding could not be determined.", code="undecodable_text")
    return str(guess), guess.encoding
