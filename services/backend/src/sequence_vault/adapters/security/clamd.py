"""ClamAV clamd client using the INSTREAM command. Any failure fails closed."""

import socket
import struct

from sequence_vault.application.ports import ScannerUnavailable, ScanVerdict

CHUNK = 64 * 1024


class ClamdScanner:
    def __init__(self, address: str, *, timeout: float = 30.0) -> None:
        """``address`` is ``host:port`` or a Unix socket path."""
        self.address = address
        self.timeout = timeout

    def _connect(self) -> socket.socket:
        if self.address.startswith("/"):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            target: str | tuple[str, int] = self.address
        else:
            host, _, port = self.address.rpartition(":")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target = (host, int(port))
        sock.settimeout(self.timeout)
        sock.connect(target)
        return sock

    def scan(self, data: bytes) -> ScanVerdict:
        try:
            with self._connect() as sock:
                sock.sendall(b"zINSTREAM\0")
                for start in range(0, len(data), CHUNK):
                    chunk = data[start : start + CHUNK]
                    sock.sendall(struct.pack("!L", len(chunk)) + chunk)
                sock.sendall(struct.pack("!L", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = sock.recv(4096)
                    if not part:
                        break
                    reply += part
        except OSError as error:
            raise ScannerUnavailable(f"clamd unreachable: {error}") from error
        text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
        if text.endswith("OK"):
            return ScanVerdict(clean=True)
        if text.endswith("FOUND"):
            signature = text.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanVerdict(clean=False, signature=signature)
        raise ScannerUnavailable(f"clamd error: {text or 'empty reply'}")


EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class DevelopmentScanner:
    """Development only: treats the EICAR test string as infected, everything else as clean."""

    def scan(self, data: bytes) -> ScanVerdict:
        if EICAR in data:
            return ScanVerdict(clean=False, signature="Eicar-Test-Signature")
        return ScanVerdict(clean=True)
