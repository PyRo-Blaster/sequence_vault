"""Sandboxed parser process: untrusted bytes on stdin, DocumentIR JSON on stdout.

Limits are applied before any untrusted byte is read. The process receives no credentials:
the launcher starts it with an empty environment.
"""

import json
import resource
import sys

from sequence_vault.adapters.parsers.registry import parse
from sequence_vault.application.ports import ParseFailed


def _limit(kind: int, value: int) -> None:
    resource.setrlimit(kind, (value, value))


def main() -> int:
    memory_mb, cpu_seconds = int(sys.argv[5]), int(sys.argv[6])
    _limit(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
    _limit(resource.RLIMIT_CPU, cpu_seconds)
    _limit(resource.RLIMIT_FSIZE, 0)
    _limit(resource.RLIMIT_NOFILE, 32)
    format, file_id, run_id, options = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    data = sys.stdin.buffer.read()
    try:
        document = parse(
            format, data, file_id=file_id, run_id=run_id, parse_options=json.loads(options)
        )
    except ParseFailed as error:
        json.dump({"error": error.code, "message": str(error)}, sys.stdout)
        return 2
    except MemoryError:
        json.dump({"error": "parser_memory_limit", "message": "Memory limit exceeded."}, sys.stdout)
        return 2
    json.dump(document, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
