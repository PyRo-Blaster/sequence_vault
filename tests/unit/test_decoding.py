import pytest

from sequence_vault.adapters.parsers.decoding import decode
from sequence_vault.application.ports import ParseFailed


def test_utf8_and_bom() -> None:
    assert decode("序列 MKT".encode()) == ("序列 MKT", "utf-8")
    assert decode(b"\xef\xbb\xbfMKT") == ("MKT", "utf-8-sig")


def test_gbk_text_from_chinese_windows_is_decoded() -> None:
    text = "抗体重链序列\n名称：RSPO3_C07\nMKTAYIAKQRQISFVKSHFSRQ\n" * 3
    decoded, encoding = decode(text.encode("gb18030"))
    assert decoded == text
    assert encoding.lower().replace("_", "") in {"gb18030", "gbk", "gb2312"}


def test_undecodable_bytes_fail_explicitly() -> None:
    with pytest.raises(ParseFailed):
        decode(bytes(range(128, 256)) * 4 + b"\x81\x30")
