import socket
import struct
import threading
from collections.abc import Iterator

import pytest

from sequence_vault.adapters.security.clamd import EICAR, ClamdScanner, DevelopmentScanner
from sequence_vault.application.ports import ScannerUnavailable


def fake_clamd(reply: bytes) -> tuple[str, list[bytes], threading.Thread]:
    """A one-connection clamd that records the streamed bytes and sends ``reply``."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received: list[bytes] = []

    def serve() -> None:
        connection, _ = server.accept()
        with connection, server:
            command = b""
            while not command.endswith(b"\0"):
                command += connection.recv(1)
            assert command == b"zINSTREAM\0"
            data = b""
            while True:
                (size,) = struct.unpack("!L", connection.recv(4, socket.MSG_WAITALL))
                if size == 0:
                    break
                data += connection.recv(size, socket.MSG_WAITALL)
            received.append(data)
            connection.sendall(reply)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return f"127.0.0.1:{server.getsockname()[1]}", received, thread


@pytest.fixture
def payload() -> Iterator[bytes]:
    yield b">A\nMKT\n" * 30_000  # several INSTREAM chunks


def test_clean_file_streams_every_byte(payload: bytes) -> None:
    address, received, thread = fake_clamd(b"stream: OK\0")
    assert ClamdScanner(address).scan(payload).clean
    thread.join(5)
    assert received == [payload]


def test_infected_file_reports_the_signature() -> None:
    address, _, thread = fake_clamd(b"stream: Eicar-Signature FOUND\0")
    verdict = ClamdScanner(address).scan(EICAR)
    thread.join(5)
    assert (verdict.clean, verdict.signature) == (False, "Eicar-Signature")


def test_scanner_errors_and_outages_fail_closed() -> None:
    address, _, thread = fake_clamd(b"INSTREAM size limit exceeded. ERROR\0")
    with pytest.raises(ScannerUnavailable):
        ClamdScanner(address).scan(b"data")
    thread.join(5)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused = probe.getsockname()[1]
    with pytest.raises(ScannerUnavailable):
        ClamdScanner(f"127.0.0.1:{unused}", timeout=2).scan(b"data")


def test_development_scanner_detects_eicar_only() -> None:
    assert DevelopmentScanner().scan(b">A\nMKT").clean
    assert not DevelopmentScanner().scan(b"x" + EICAR).clean
