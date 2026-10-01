"""Run a parser in a separate, credential-free, resource-limited process (ADR 0003, level 1)."""

import json
import subprocess
import sys
from typing import Any

from sequence_vault.application.ports import ParseFailed

MAX_OUTPUT = 256 * 1024 * 1024


class SandboxedParser:
    def __init__(
        self, *, memory_mb: int = 1024, cpu_seconds: int = 60, timeout: float = 90
    ) -> None:
        self.memory_mb = memory_mb
        self.cpu_seconds = cpu_seconds
        self.timeout = timeout

    def parse(
        self, format: str, data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
    ) -> dict[str, Any]:
        command = [
            sys.executable,
            "-I",  # isolated mode: ignore PYTHON* variables and the user site directory
            "-m",
            "sequence_vault.entrypoints.parser_main",
            format,
            file_id,
            run_id,
            json.dumps(parse_options),
            str(self.memory_mb),
            str(self.cpu_seconds),
        ]
        try:
            completed = subprocess.run(
                command,
                input=data,
                capture_output=True,
                timeout=self.timeout,
                env={"PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"},
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ParseFailed(
                "The parser exceeded its time limit.", code="parser_timeout"
            ) from error
        if len(completed.stdout) > MAX_OUTPUT:
            raise ParseFailed(
                "The parser output exceeded its size limit.", code="parser_output_limit"
            )
        try:
            result: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ParseFailed(
                f"The parser stopped unexpectedly (exit {completed.returncode}).",
                code="parser_crash",
            ) from error
        if completed.returncode != 0 or "error" in result:
            raise ParseFailed(
                str(result.get("message", "Parse failed.")),
                code=str(result.get("error", "parse_failed")),
            )
        return result
