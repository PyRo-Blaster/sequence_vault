"""Structured logs without research content (design section 9).

Ordinary telemetry carries IDs, counts, durations and error codes. Any residue-like run that
still reaches a log line (an exception message, a traceback) is masked before it is written.
"""

import json
import logging
import re
from datetime import UTC, datetime

# 20+ letters, possibly in blocks separated by single spaces or line breaks.
_RESIDUES = re.compile(r"(?:[A-Za-z]{10,}[ \t\n]?){2,}|[A-Za-z]{20,}")


def redact(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        run = match.group()
        letters = sum(1 for c in run if c.isalpha())
        # Residue runs are written in a single case; mixed-case runs are identifiers or prose.
        if run.isupper() or run.islower():
            return f"[{letters} residues redacted]"
        return run

    return _RESIDUES.sub(mask, text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
