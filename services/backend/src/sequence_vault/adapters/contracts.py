"""Load the versioned JSON contracts, QC registry and processing policy."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from sequence_vault.domain.qc.registry import QcRegistry


@dataclass(frozen=True, slots=True)
class Limits:
    max_file_bytes: int
    max_files_per_batch: int
    max_pdf_pages: int
    max_candidates_per_file: int
    max_residues_per_sequence: int


@dataclass(frozen=True, slots=True)
class Policy:
    version: str
    limits: Limits
    supported_formats: frozenset[str]
    max_transient_retries: int
    ai_enabled_by_default: bool


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def validators(contracts_dir: Path) -> dict[str, Draft202012Validator]:
    folder = contracts_dir / "schemas/v1"
    schemas = {path.name: _read(path) for path in sorted(folder.glob("*.schema.json"))}
    registry: Registry[Any] = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return {
        name.removesuffix(".schema.json"): Draft202012Validator(schema, registry=registry)
        for name, schema in schemas.items()
    }


def schema_errors(contracts_dir: Path, name: str, document: Any) -> list[str]:
    """Readable validation errors; empty when the document conforms."""
    validator = validators(contracts_dir)[name]
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]


def load_registry(config_dir: Path) -> QcRegistry:
    return QcRegistry.from_dict(_read(config_dir / "qc-rules.v1.json"))


def load_policy(config_dir: Path) -> Policy:
    data = _read(config_dir / "processing-policy.v1.json")
    limits = data["limits"]
    return Policy(
        version=data["policy_version"],
        limits=Limits(
            max_file_bytes=limits["max_file_bytes"],
            max_files_per_batch=limits["max_files_per_batch"],
            max_pdf_pages=limits["max_pdf_pages"],
            max_candidates_per_file=limits["max_candidates_per_file"],
            max_residues_per_sequence=limits["max_residues_per_sequence"],
        ),
        supported_formats=frozenset(data["supported_release_one_formats"]),
        max_transient_retries=data["retry"]["max_transient_retries"],
        ai_enabled_by_default=data["ai_enabled_by_default"],
    )
