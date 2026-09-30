# Domain Core Implementation Plan (P1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use anthropic-skills:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the framework-free Python core that turns evidence spans into validated, reviewable protein candidates: span reconstruction, normalization, the QC rule engine, candidate and task lifecycles, publication decisions, and the mapping to the JSON contracts.

**Architecture:** Pure functions and frozen dataclasses in `sequence_vault.domain`, plus one mapping module in `sequence_vault.application`. No database, HTTP, queue or model SDK is involved; import-linter enforces that. Severities come only from `config/qc-rules.v1.json`. Every edit bumps the candidate revision and voids approval.

**Tech Stack:** Python 3.12, uv 0.8.17 workspace, pytest 9.1.1, Hypothesis 6.168.3, ruff 0.16.9, mypy 2.3.1 (strict), import-linter 2.15, jsonschema 4.26.0.

---

## Context for the engineer

Read these first (20 minutes):

- `docs/design/Protein_Sequence_App_Design_v1.0_EN.md` sections 3, 4, 6 and 7: task states, spans, QC rules, review and commit.
- `docs/decisions/0002-extraction-contract-boundaries.md`: the model returns spans and observations only; QC decides severities.
- `docs/workflow.md`: diagrams 3–7 show exactly what this plan builds.
- `packages/contracts/schemas/v1/*.json` and `packages/contracts/examples/*.json`: Task 12 must reproduce `candidate.json` exactly.

Domain terms:

- **Block**: an immutable piece of source text from DocumentIR, with an ID (`p1`, `h1`).
- **Span**: `[start, end)` inside one block, measured in Unicode code points. Python `str` indexing already uses code points, so `text[start:end]` is correct. Never encode to bytes to compute offsets.
- **Reconstruction**: copying span characters out of blocks in `order`. The model never supplies sequence text.
- **QC issue**: a rule result with severity `INFO`, `REVIEW` or `BLOCK`. `BLOCK` cannot be resolved by clicking; the candidate must change.
- **Revision**: an integer that increases on every edit. Approvals and resolutions are only valid for the revision they were made on.

Conventions: frozen dataclasses with `slots=True`; methods return new instances (use `dataclasses.replace`); errors are specific exception classes. Commit subjects follow Conventional Commits with a scope, imperative, under 50 characters (`CONTRIBUTING.md`).

## File structure

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `.python-version`, `uv.lock` | Workspace root: dev tools and their configuration |
| `services/backend/pyproject.toml` | The `sequence-vault` package (no runtime dependencies yet) |
| `Makefile`, `.github/workflows/check.yml` | `make setup` and `make check` locally and in CI |
| `domain/spans.py` | Spans, reconstruction, mapping text positions back to block evidence |
| `domain/normalization.py` | QC02 whitespace and case normalization with a transformation log |
| `domain/qc/registry.py` | Rule definitions, severities and allowed resolutions from the registry file |
| `domain/qc/characters.py` | Character classes for QC03–QC06 |
| `domain/qc/engine.py` | Runs every rule, adds context rules (QC05, QC07, QC08), classifies molecule type (QC11) |
| `domain/extraction.py` | Extracted records and the cross-field checks JSON Schema cannot express |
| `domain/naming.py` | `name_key` |
| `domain/candidate.py` | Candidate lifecycle: revisions, resolutions, approval, commit guard |
| `domain/task.py` | File task lifecycle and duplicate-delivery detection |
| `domain/publication.py` | Dedup and version decisions (QC09, QC10) |
| `application/contract_mapping.py` | JSON contracts to and from domain objects |
| `tests/unit/test_*.py` | One test module per source module; `conftest.py` loads the real registry |

All `domain/` and `application/` paths are under `services/backend/src/sequence_vault/`.

## Task 1: Workspace and checks

**Files:**
- Create: `pyproject.toml`, `.python-version`, `services/backend/pyproject.toml`, `tests/unit/test_package.py`
- Create (generated): `uv.lock`
- Modify: `Makefile`, `README.md`, `scripts/README.md`, `scripts/check_scaffold.py` (formatting only)
- Rename and modify: `.github/workflows/scaffold.yml` → `.github/workflows/check.yml`
- Delete: `scripts/requirements.txt` (its pins move into the `dev` group)

- [ ] **Step 1: Install uv 0.8.17 if needed**

Run: `uv --version`
Expected: `uv 0.8.17`. Otherwise: `python3 -m pip install uv==0.8.17`.

- [ ] **Step 2: Create the workspace root `pyproject.toml`**

```toml
# Workspace root: shared tooling only. Runtime packages live in their own folders.
[tool.uv.workspace]
members = ["services/backend"]

[dependency-groups]
dev = [
  "sequence-vault",
  "hypothesis==6.168.3",
  "import-linter==2.15",
  "jsonschema==4.26.0",
  "mypy==2.3.1",
  "pytest==9.1.1",
  "ruff==0.16.9",
  "types-jsonschema==4.26.0.20260518",
]

[tool.uv.sources]
sequence-vault = { workspace = true }

[tool.pytest.ini_options]
testpaths = ["tests/unit"]
addopts = ["--strict-markers", "--import-mode=importlib"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.ruff.lint.isort]
known-first-party = ["sequence_vault"]

[tool.ruff.lint.per-file-ignores]
# Tests feed look-alike characters (Cyrillic, full-width) to QC on purpose.
"tests/**" = ["RUF001", "RUF003"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["services/backend/src", "tests/unit"]

[tool.importlinter]
root_package = "sequence_vault"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Backend layers"
type = "layers"
layers = [
  "sequence_vault.api | sequence_vault.workers",
  "sequence_vault.adapters",
  "sequence_vault.application",
  "sequence_vault.domain",
]

[[tool.importlinter.contracts]]
name = "Domain stays free of frameworks and providers"
type = "forbidden"
source_modules = ["sequence_vault.domain"]
forbidden_modules = ["anthropic", "boto3", "fastapi", "httpx", "pydantic", "sqlalchemy"]
allow_indirect_imports = true
```

- [ ] **Step 3: Create `.python-version`**

```text
3.12
```

- [ ] **Step 4: Create `services/backend/pyproject.toml`**

```toml
[project]
name = "sequence-vault"
version = "0.1.0"
description = "Protein sequence import, evidence review and quality control backend."
requires-python = ">=3.12"
dependencies = []

[build-system]
requires = ["uv_build>=0.8.17,<0.9"]
build-backend = "uv_build"
```

- [ ] **Step 5: Write the smoke test `tests/unit/test_package.py`**

```python
import sequence_vault


def test_backend_package_is_installed() -> None:
    assert sequence_vault.__doc__
```

- [ ] **Step 6: Lock, install and run the smoke test**

Run: `uv lock && uv sync --locked && uv run pytest`
Expected: `Resolved 28 packages`, then `1 passed`.

- [ ] **Step 7: Check that the import contracts load**

Run: `uv run lint-imports`
Expected: `Backend layers KEPT`, `Domain stays free of frameworks and providers KEPT`, `Contracts: 2 kept, 0 broken.`

- [ ] **Step 8: Replace the `Makefile`**

```make
UV ?= uv

.PHONY: setup check scaffold lint typecheck test
setup:
	$(UV) sync --locked

check: scaffold lint typecheck test

scaffold:
	$(UV) run --locked python scripts/check_scaffold.py
	git diff --check

lint:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .
	$(UV) run --locked lint-imports

typecheck:
	$(UV) run --locked mypy

test:
	$(UV) run --locked pytest
```

- [ ] **Step 9: Move CI to uv**

Run: `git mv .github/workflows/scaffold.yml .github/workflows/check.yml && git rm scripts/requirements.txt`

Replace the contents of `.github/workflows/check.yml` with:

```yaml
name: Checks

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: '3.12'
      - run: python -m pip install uv==0.8.17
      - run: make setup
      - run: make check
```

- [ ] **Step 10: Format the existing scaffold checker once**

Run: `uv run ruff format scripts/check_scaffold.py`
Expected: `1 file reformatted`.

- [ ] **Step 11: Update the docs that mention the old command**

In `README.md`, replace the whole `## Check the scaffold` section (up to `## Design constraints`) with:

````markdown
## Check the repository

Requires [uv](https://docs.astral.sh/uv/) 0.8.17. uv installs the Python version in `.python-version` (3.12) when it is missing.

```sh
make setup   # create .venv from uv.lock
make check   # scaffold checks, lint, import contracts, types and unit tests
```

`make check` validates the synthetic examples against the draft JSON Schemas, checks that the schemas reject states the design forbids, runs ruff, mypy and the import-linter layer contracts, and runs the backend unit tests. CI runs the same commands. Backend unit tests live in `tests/unit`; no application server exists yet.
````

In `scripts/README.md`, replace the last paragraph with:

```markdown
Its dependencies come from the `dev` group in the root `pyproject.toml`. Run it with `make scaffold`.
```

- [ ] **Step 12: Run every check**

Run: `make check`
Expected: `Scaffold checks passed`, `All checks passed!`, both import contracts `KEPT`, mypy `Success: no issues found`, `1 passed`.

- [ ] **Step 13: Commit**

```bash
git add pyproject.toml .python-version uv.lock services/backend/pyproject.toml tests/unit/test_package.py Makefile .github/workflows README.md scripts
git commit -m "build(backend): add uv workspace and checks"
```

## Task 2: Spans and reconstruction

**Files:**
- Create: `services/backend/src/sequence_vault/domain/spans.py`
- Test: `tests/unit/test_spans.py`

Reconstruction is the core safety property: the sequence always comes from stored blocks. `evidence_for` lets every later QC issue point at exact source characters. The Hypothesis test checks the property for arbitrary text, including non-ASCII.

- [ ] **Step 1: Write the failing test `tests/unit/test_spans.py`**

```python
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sequence_vault.domain.spans import (
    BlockSpan,
    InvalidSpans,
    SequenceSpan,
    check_spans,
    reconstruct,
    typed_text,
)

BLOCKS = {"p1": "MKTAYIAK", "p2": "QRQISFVK", "cjk": "序列：ACDE"}


def test_reconstructs_spans_in_assembly_order_not_list_order() -> None:
    spans = [SequenceSpan("p2", 0, 3, order=2), SequenceSpan("p1", 0, 4, order=1)]
    assert reconstruct(BLOCKS, spans).text == "MKTAQRQ"


def test_offsets_are_code_points_not_bytes() -> None:
    # "序列：" is three code points but nine UTF-8 bytes.
    assert reconstruct(BLOCKS, [SequenceSpan("cjk", 3, 7, order=1)]).text == "ACDE"


@pytest.mark.parametrize(
    ("spans", "expected"),
    [
        ([], "no sequence spans"),
        ([SequenceSpan("zz", 0, 1, 1)], "unknown block 'zz'"),
        ([SequenceSpan("p1", 3, 3, 1)], "span [3, 3) is outside block 'p1'"),
        ([SequenceSpan("p1", 0, 9, 1)], "span [0, 9) is outside block 'p1'"),
        ([SequenceSpan("p1", 0, 2, 1), SequenceSpan("p2", 0, 2, 3)], "without gaps"),
        ([SequenceSpan("p1", 0, 4, 1), SequenceSpan("p1", 3, 6, 2)], "overlapping spans"),
    ],
)
def test_rejects_unusable_spans(spans: list[SequenceSpan], expected: str) -> None:
    assert any(expected in problem for problem in check_spans(BLOCKS, spans))
    with pytest.raises(InvalidSpans):
        reconstruct(BLOCKS, spans)


def test_maps_text_positions_back_to_merged_block_evidence() -> None:
    rebuilt = reconstruct(BLOCKS, [SequenceSpan("p1", 4, 8, 1), SequenceSpan("p2", 0, 2, 2)])
    assert rebuilt.text == "YIAKQR"
    assert rebuilt.evidence_for([2, 3, 4]) == (BlockSpan("p1", 6, 8), BlockSpan("p2", 0, 1))


def test_typed_text_has_no_evidence() -> None:
    assert typed_text("MKT").evidence_for([0, 1]) == ()


@given(st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=5), st.data())
def test_reconstruction_equals_slices_joined_by_order(
    texts: list[str], data: st.DataObject
) -> None:
    blocks = {f"b{index}": text for index, text in enumerate(texts)}
    spans = []
    for index, text in enumerate(texts):
        start = data.draw(st.integers(0, len(text) - 1))
        end = data.draw(st.integers(start + 1, len(text)))
        spans.append(SequenceSpan(f"b{index}", start, end, order=index + 1))
    rebuilt = reconstruct(blocks, list(reversed(spans)))
    assert rebuilt.text == "".join(blocks[s.block_id][s.start : s.end] for s in spans)
    for position, character in enumerate(rebuilt.text):
        located = rebuilt.locate(position)
        assert located is not None
        assert blocks[located[0]][located[1]] == character
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_spans.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.spans'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/spans.py`**

```python
"""Evidence spans and deterministic sequence reconstruction.

Offsets are Unicode code points in half-open ranges, which is exactly how Python
indexes ``str``. Sequence text always comes from stored blocks, never from model text.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True, slots=True)
class BlockSpan:
    block_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SequenceSpan:
    block_id: str
    start: int
    end: int
    order: int


@dataclass(frozen=True, slots=True)
class Segment:
    """Where one span's characters landed in the reconstructed text."""

    block_id: str
    block_start: int
    text_start: int
    length: int


@dataclass(frozen=True, slots=True)
class Reconstruction:
    text: str
    segments: tuple[Segment, ...]

    def locate(self, position: int) -> tuple[str, int] | None:
        """Map a text position to (block_id, block offset); None for manually typed text."""
        for segment in self.segments:
            if segment.text_start <= position < segment.text_start + segment.length:
                return segment.block_id, segment.block_start + position - segment.text_start
        return None

    def evidence_for(self, positions: Iterable[int]) -> tuple[BlockSpan, ...]:
        """Merge text positions into the fewest contiguous block spans."""
        spans: list[BlockSpan] = []
        for position in sorted(set(positions)):
            located = self.locate(position)
            if located is None:
                continue
            block_id, offset = located
            if spans and spans[-1].block_id == block_id and spans[-1].end == offset:
                spans[-1] = BlockSpan(block_id, spans[-1].start, offset + 1)
            else:
                spans.append(BlockSpan(block_id, offset, offset + 1))
        return tuple(spans)


class InvalidSpans(ValueError):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def check_spans(blocks: Mapping[str, str], spans: Sequence[SequenceSpan]) -> tuple[str, ...]:
    """Return every reason the spans cannot be reconstructed; empty when they can."""
    if not spans:
        return ("no sequence spans",)
    problems: list[str] = []
    orders = sorted(span.order for span in spans)
    if orders != list(range(1, len(spans) + 1)):
        problems.append(f"assembly orders must run 1..{len(spans)} without gaps, got {orders}")
    for span in spans:
        text = blocks.get(span.block_id)
        if text is None:
            problems.append(f"unknown block {span.block_id!r}")
        elif not 0 <= span.start < span.end <= len(text):
            problems.append(
                f"span [{span.start}, {span.end}) is outside block {span.block_id!r} "
                f"of length {len(text)}"
            )
    by_position = sorted(spans, key=lambda span: (span.block_id, span.start))
    for previous, current in pairwise(by_position):
        if previous.block_id == current.block_id and current.start < previous.end:
            problems.append(f"overlapping spans in block {current.block_id!r}")
    return tuple(problems)


def reconstruct(blocks: Mapping[str, str], spans: Sequence[SequenceSpan]) -> Reconstruction:
    """Copy span characters out of the blocks in assembly order."""
    problems = check_spans(blocks, spans)
    if problems:
        raise InvalidSpans(problems)
    pieces: list[str] = []
    segments: list[Segment] = []
    cursor = 0
    for span in sorted(spans, key=lambda item: item.order):
        piece = blocks[span.block_id][span.start : span.end]
        segments.append(Segment(span.block_id, span.start, cursor, len(piece)))
        pieces.append(piece)
        cursor += len(piece)
    return Reconstruction("".join(pieces), tuple(segments))


def typed_text(text: str) -> Reconstruction:
    """Wrap manually typed sequence text, which has no block evidence."""
    return Reconstruction(text, ())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_spans.py -v`
Expected: `11 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `12 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/spans.py tests/unit/test_spans.py
git commit -m "feat(domain): reconstruct sequences from spans"
```

## Task 3: QC02 normalization

**Files:**
- Create: `services/backend/src/sequence_vault/domain/normalization.py`
- Test: `tests/unit/test_normalization.py`

`raw_positions` keeps the link from each normalized residue back to the raw text, so issues found after normalization still locate their evidence. Only ASCII letters are upper-cased because `"ß".upper()` is `"SS"`.

- [ ] **Step 1: Write the failing test `tests/unit/test_normalization.py`**

```python
from hypothesis import given
from hypothesis import strategies as st

from sequence_vault.domain.normalization import normalize


def test_removes_whitespace_including_ideographic_space_and_logs_positions() -> None:
    result = normalize("MK T\n　AY")
    assert result.sequence == "MKTAY"
    assert [(t.operation, t.positions) for t in result.transformations] == [
        ("remove_whitespace", (2, 4, 5))
    ]


def test_uppercases_ascii_only() -> None:
    result = normalize("mkß")
    assert result.sequence == "MKß"
    assert result.transformations[0].operation == "uppercase"
    assert result.transformations[0].positions == (0, 1)


def test_clean_input_has_no_transformations() -> None:
    assert normalize("ACDEFGHIKLMNPQRSTVWY").transformations == ()


@given(st.text(max_size=60))
def test_every_normalized_character_maps_back_to_the_raw_text(raw: str) -> None:
    result = normalize(raw)
    assert len(result.raw_positions) == len(result.sequence)
    for character, position in zip(result.sequence, result.raw_positions, strict=True):
        assert raw[position].upper() == character or raw[position] == character
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_normalization.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.normalization'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/normalization.py`**

```python
"""QC02: deterministic whitespace and case normalization with a transformation log."""

from dataclasses import dataclass

_ASCII_LOWER = frozenset("abcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True, slots=True)
class Transformation:
    rule_id: str
    operation: str
    reason: str
    positions: tuple[int, ...]
    """Code-point positions in the raw text."""


@dataclass(frozen=True, slots=True)
class Normalized:
    sequence: str
    raw_positions: tuple[int, ...]
    """raw_positions[i] is the raw-text position that produced sequence[i]."""
    transformations: tuple[Transformation, ...]


def normalize(raw: str) -> Normalized:
    """Drop whitespace and upper-case ASCII letters; leave every other character alone.

    Only ASCII letters are upper-cased: ``str.upper`` can change length (``"ß"`` becomes
    ``"SS"``), which would break the position mapping and hide a look-alike character.
    """
    removed: list[int] = []
    uppercased: list[int] = []
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(raw):
        if character.isspace():
            removed.append(index)
            continue
        if character in _ASCII_LOWER:
            uppercased.append(index)
            character = character.upper()
        characters.append(character)
        positions.append(index)
    transformations: list[Transformation] = []
    if removed:
        transformations.append(
            Transformation(
                "QC02",
                "remove_whitespace",
                "Whitespace and line breaks are not residues.",
                tuple(removed),
            )
        )
    if uppercased:
        transformations.append(
            Transformation(
                "QC02",
                "uppercase",
                "Residue letters are stored in upper case.",
                tuple(uppercased),
            )
        )
    return Normalized("".join(characters), tuple(positions), tuple(transformations))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_normalization.py -v`
Expected: `4 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `16 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/normalization.py tests/unit/test_normalization.py
git commit -m "feat(domain): normalize whitespace and case"
```

## Task 4: QC rule registry

**Files:**
- Create: `services/backend/src/sequence_vault/domain/qc/__init__.py`
- Create: `services/backend/src/sequence_vault/domain/qc/registry.py`
- Test: `tests/unit/conftest.py`
- Test: `tests/unit/test_qc_registry.py`

Issues are created only through `QcRegistry.issue`, so severity cannot drift from `config/qc-rules.v1.json`. The `registry` fixture loads the real file, so a config change that breaks the code fails the tests.

- [ ] **Step 1: Write the failing test `tests/unit/conftest.py`**

```python
import json
from pathlib import Path

import pytest

from sequence_vault.domain.qc.registry import QcRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registry() -> QcRegistry:
    """The real draft registry, so tests fail if the config and code drift apart."""
    data = json.loads((REPO_ROOT / "config/qc-rules.v1.json").read_text(encoding="utf-8"))
    return QcRegistry.from_dict(data)
```

- [ ] **Step 2: Write the failing test `tests/unit/test_qc_registry.py`**

```python
import pytest

from sequence_vault.domain.qc.registry import QcRegistry, Severity


def test_loads_the_v1_registry(registry: QcRegistry) -> None:
    assert registry.version == "1.0"
    assert set(registry.rules) == {f"QC{number:02}" for number in range(1, 12)}
    assert registry.rules["QC05"].severity is Severity.BLOCK
    assert "register_fragment" in registry.rules["QC05"].allowed_resolutions


def test_issue_severity_always_comes_from_the_registry(registry: QcRegistry) -> None:
    assert registry.issue("QC04", "extended residue").severity is Severity.REVIEW


def test_refuses_a_registry_that_allows_generic_block_overrides() -> None:
    with pytest.raises(ValueError, match="generic override"):
        QcRegistry.from_dict(
            {"qc_version": "x", "generic_block_override_allowed": True, "rules": []}
        )


def test_refuses_rules_without_resolutions() -> None:
    data = {
        "qc_version": "x",
        "generic_block_override_allowed": False,
        "rules": [{"rule_id": "QC01", "severity": "BLOCK", "allowed_resolutions": []}],
    }
    with pytest.raises(ValueError, match="no resolutions"):
        QcRegistry.from_dict(data)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_qc_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.qc'`

- [ ] **Step 4: Implement `services/backend/src/sequence_vault/domain/qc/__init__.py`**

```python
"""Deterministic quality control: rule registry, character checks and evaluation."""
```

- [ ] **Step 5: Implement `services/backend/src/sequence_vault/domain/qc/registry.py`**

```python
"""QC rule definitions loaded from the versioned registry (config/qc-rules.v*.json)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sequence_vault.domain.spans import BlockSpan


class Severity(StrEnum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    severity: Severity
    allowed_resolutions: frozenset[str]


@dataclass(frozen=True, slots=True)
class Issue:
    rule_id: str
    severity: Severity
    message: str
    evidence: tuple[BlockSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class QcRegistry:
    version: str
    rules: Mapping[str, RuleDefinition]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QcRegistry":
        if data.get("generic_block_override_allowed") is not False:
            raise ValueError("The registry must forbid a generic override for BLOCK issues.")
        rules: dict[str, RuleDefinition] = {}
        for item in data["rules"]:
            rule = RuleDefinition(
                rule_id=item["rule_id"],
                severity=Severity(item["severity"]),
                allowed_resolutions=frozenset(item["allowed_resolutions"]),
            )
            if rule.rule_id in rules:
                raise ValueError(f"Duplicate rule {rule.rule_id}")
            if not rule.allowed_resolutions:
                raise ValueError(f"Rule {rule.rule_id} lists no resolutions")
            rules[rule.rule_id] = rule
        return cls(version=str(data["qc_version"]), rules=rules)

    def issue(self, rule_id: str, message: str, evidence: Iterable[BlockSpan] = ()) -> Issue:
        """Create an issue whose severity always comes from the registry."""
        return Issue(rule_id, self.rules[rule_id].severity, message, tuple(evidence))
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_qc_registry.py -v`
Expected: `4 passed`

- [ ] **Step 7: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `20 passed`

- [ ] **Step 8: Commit**

```bash
git add services/backend/src/sequence_vault/domain/qc/__init__.py services/backend/src/sequence_vault/domain/qc/registry.py tests/unit/conftest.py tests/unit/test_qc_registry.py
git commit -m "feat(qc): load the QC rule registry"
```

## Task 5: Character classes (QC03–QC06)

**Files:**
- Create: `services/backend/src/sequence_vault/domain/qc/characters.py`
- Test: `tests/unit/test_qc_characters.py`

Runs of two or more dots and the `…`/`⋯` characters are ellipses (QC05, BLOCK); a single dot, `*` or `-` is a gap or stop (QC06, REVIEW); `BZJXUO` are extended residues (QC04); everything else outside the standard alphabet, including digits and look-alikes such as Cyrillic `А`, is QC03. `describe` prints code points so reviewers can see look-alikes.

- [ ] **Step 1: Write the failing test `tests/unit/test_qc_characters.py`**

```python
from sequence_vault.domain.qc.characters import describe, scan


def test_standard_residues_raise_nothing() -> None:
    found = scan("ACDEFGHIKLMNPQRSTVWY")
    assert (found.invalid, found.extended, found.ellipsis, found.gaps_and_stops) == ((), (), (), ())


def test_classifies_each_character_family() -> None:
    found = scan("MX1А*-.K...…⋯")
    assert found.extended == (1,)
    assert found.invalid == (2, 3)  # digit and Cyrillic A look-alike
    assert found.gaps_and_stops == (4, 5, 6)  # a single dot is a gap
    assert found.ellipsis == (8, 9, 10, 11, 12)


def test_describe_shows_code_points_for_look_alikes() -> None:
    assert describe("АA", (0,)) == "'А' (U+0410)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_qc_characters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.qc.characters'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/qc/characters.py`**

```python
"""Character classes behind QC03-QC06, applied to a normalized sequence."""

from dataclasses import dataclass

STANDARD_RESIDUES = frozenset("ACDEFGHIKLMNPQRSTVWY")
EXTENDED_RESIDUES = frozenset("BZJXUO")
ELLIPSIS_CHARACTERS = frozenset("…⋯")  # … and ⋯ (common in Chinese documents)
GAP_OR_STOP_CHARACTERS = frozenset("*-")


@dataclass(frozen=True, slots=True)
class CharacterFindings:
    """Positions in the normalized sequence, grouped by the rule they trigger."""

    invalid: tuple[int, ...]  # QC03
    extended: tuple[int, ...]  # QC04
    ellipsis: tuple[int, ...]  # QC05
    gaps_and_stops: tuple[int, ...]  # QC06


def scan(sequence: str) -> CharacterFindings:
    """Classify every non-standard character. Two or more dots in a row are an ellipsis;
    a single dot is treated as an alignment gap."""
    invalid: list[int] = []
    extended: list[int] = []
    ellipsis: list[int] = []
    gaps: list[int] = []
    index = 0
    while index < len(sequence):
        character = sequence[index]
        if character == ".":
            end = index
            while end < len(sequence) and sequence[end] == ".":
                end += 1
            (ellipsis if end - index >= 2 else gaps).extend(range(index, end))
            index = end
            continue
        if character in EXTENDED_RESIDUES:
            extended.append(index)
        elif character in ELLIPSIS_CHARACTERS:
            ellipsis.append(index)
        elif character in GAP_OR_STOP_CHARACTERS:
            gaps.append(index)
        elif character not in STANDARD_RESIDUES:
            invalid.append(index)
        index += 1
    return CharacterFindings(tuple(invalid), tuple(extended), tuple(ellipsis), tuple(gaps))


def describe(sequence: str, positions: tuple[int, ...]) -> str:
    """List distinct characters with code points so look-alikes are visible to reviewers."""
    seen = dict.fromkeys(sequence[position] for position in positions)
    return ", ".join(f"{character!r} (U+{ord(character):04X})" for character in seen)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_qc_characters.py -v`
Expected: `3 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `23 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/qc/characters.py tests/unit/test_qc_characters.py
git commit -m "feat(qc): classify sequence characters"
```

## Task 6: QC engine

**Files:**
- Create: `services/backend/src/sequence_vault/domain/qc/engine.py`
- Test: `tests/unit/test_qc_engine.py`

`evaluate_spans` handles extracted evidence; `evaluate_typed` handles a reviewer's typed correction, whose issues have no block evidence. Context rules turn observations and coverage into QC05, QC07 and QC08. `classify` only returns `protein` when the letters prove it and nothing suggests nucleic acid (spec section 6: `ACGT` alone never proves protein).

- [ ] **Step 1: Write the failing test `tests/unit/test_qc_engine.py`**

```python
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    classify,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import Issue, QcRegistry, Severity
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

CLEAN = ExtractionContext(
    name_count=1,
    association_status="unambiguous",
    observation_kinds=frozenset(),
    molecule_type_hint=MoleculeType.PROTEIN,
    coverage_risk=False,
)


def rules(issues: tuple[Issue, ...]) -> list[str]:
    return [issue.rule_id for issue in issues]


def test_clean_protein_has_no_issues(registry: QcRegistry) -> None:
    result = evaluate_spans(
        registry, {"p1": "ACDEFGHIKLMNPQRSTVWY"}, [SequenceSpan("p1", 0, 20, 1)], CLEAN
    )
    assert result.issues == ()
    assert result.molecule_type is MoleculeType.PROTEIN
    assert result.normalized is not None and result.normalized.sequence == "ACDEFGHIKLMNPQRSTVWY"


def test_bad_references_block_with_qc01(registry: QcRegistry) -> None:
    result = evaluate_spans(registry, {"p1": "MKT"}, [SequenceSpan("p1", 0, 9, 1)], CLEAN)
    assert rules(result.issues) == ["QC01"]
    assert result.blocked


def test_issues_point_at_the_offending_source_characters(registry: QcRegistry) -> None:
    blocks = {"p1": "1 MKTAYIAK", "p2": "QRQ...K"}
    spans = [SequenceSpan("p1", 0, 10, 1), SequenceSpan("p2", 0, 7, 2)]
    result = evaluate_spans(registry, blocks, spans, CLEAN)
    by_rule = {issue.rule_id: issue for issue in result.issues}
    assert set(by_rule) == {"QC02", "QC03", "QC05"}
    assert by_rule["QC03"].evidence == (BlockSpan("p1", 0, 1),)
    assert by_rule["QC05"].evidence == (BlockSpan("p2", 3, 6),)
    assert by_rule["QC02"].severity is Severity.INFO
    assert result.blocked


def test_nucleotide_only_sequence_needs_type_confirmation(registry: QcRegistry) -> None:
    result = evaluate_typed(registry, "ACGTACGT", CLEAN)
    assert rules(result.issues) == ["QC11"]
    assert result.molecule_type is MoleculeType.UNCERTAIN


def test_context_raises_mapping_coverage_and_truncation_issues(registry: QcRegistry) -> None:
    context = ExtractionContext(
        name_count=2,
        association_status="conflicting",
        observation_kinds=frozenset({"possible_truncation"}),
        molecule_type_hint=MoleculeType.PROTEIN,
        coverage_risk=True,
    )
    result = evaluate_typed(registry, "MKTAYIAK", context)
    assert rules(result.issues) == ["QC05", "QC07", "QC08"]


def test_declared_fragment_is_not_blocked_by_a_truncation_report(registry: QcRegistry) -> None:
    context = ExtractionContext(
        name_count=1,
        association_status="unambiguous",
        observation_kinds=frozenset({"possible_truncation"}),
        molecule_type_hint=MoleculeType.PROTEIN,
        coverage_risk=False,
        declared_fragment=True,
    )
    assert evaluate_typed(registry, "MKTAYIAK", context).issues == ()


def test_classify_needs_letter_evidence_and_agreement() -> None:
    assert classify("MKTAYIAK", MoleculeType.PROTEIN, frozenset()) is MoleculeType.PROTEIN
    assert classify("ACGTN", MoleculeType.PROTEIN, frozenset()) is MoleculeType.UNCERTAIN
    assert classify("MKTAYIAK", MoleculeType.NUCLEIC_ACID, frozenset()) is MoleculeType.UNCERTAIN
    assert (
        classify("MKTAYIAK", MoleculeType.PROTEIN, frozenset({"possible_nucleic_acid"}))
        is MoleculeType.UNCERTAIN
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_qc_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.qc.engine'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/qc/engine.py`**

```python
"""Run every QC rule against one candidate and report issues with block evidence."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.domain.normalization import Normalized, normalize
from sequence_vault.domain.qc.characters import describe, scan
from sequence_vault.domain.qc.registry import Issue, QcRegistry, Severity
from sequence_vault.domain.spans import (
    BlockSpan,
    Reconstruction,
    SequenceSpan,
    check_spans,
    reconstruct,
    typed_text,
)

NUCLEOTIDE_LETTERS = frozenset("ACGTUN")


class MoleculeType(StrEnum):
    PROTEIN = "protein"
    NUCLEIC_ACID = "nucleic_acid"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Facts about a candidate that QC needs besides its characters."""

    name_count: int
    association_status: str
    observation_kinds: frozenset[str]
    molecule_type_hint: MoleculeType
    coverage_risk: bool
    """True when the document has unresolved blocks or coverage warnings, or any span
    comes from OCR or manual transcription."""
    declared_fragment: bool = False


@dataclass(frozen=True, slots=True)
class QcResult:
    qc_version: str
    raw_text: str
    normalized: Normalized | None
    molecule_type: MoleculeType
    issues: tuple[Issue, ...]

    @property
    def blocked(self) -> bool:
        return any(issue.severity is Severity.BLOCK for issue in self.issues)

    def rule_ids(self, severity: Severity) -> frozenset[str]:
        return frozenset(issue.rule_id for issue in self.issues if issue.severity is severity)


def classify(sequence: str, hint: MoleculeType, observation_kinds: frozenset[str]) -> MoleculeType:
    """Protein only when letters prove it and nothing suggests nucleic acid (QC11)."""
    letters = {character for character in sequence if character.isalpha()}
    if not letters or letters <= NUCLEOTIDE_LETTERS:
        return MoleculeType.UNCERTAIN
    if hint is not MoleculeType.PROTEIN or "possible_nucleic_acid" in observation_kinds:
        return MoleculeType.UNCERTAIN
    return MoleculeType.PROTEIN


def evaluate_spans(
    registry: QcRegistry,
    blocks: Mapping[str, str],
    spans: Sequence[SequenceSpan],
    context: ExtractionContext,
) -> QcResult:
    problems = check_spans(blocks, spans)
    if problems:
        issues = [registry.issue("QC01", "; ".join(problems))]
        issues.extend(_context_issues(registry, context))
        return QcResult(registry.version, "", None, MoleculeType.UNCERTAIN, tuple(issues))
    return _evaluate(registry, reconstruct(blocks, spans), context)


def evaluate_typed(registry: QcRegistry, text: str, context: ExtractionContext) -> QcResult:
    """QC for a manually typed sequence; issues carry no block evidence."""
    return _evaluate(registry, typed_text(text), context)


def _evaluate(
    registry: QcRegistry, rebuilt: Reconstruction, context: ExtractionContext
) -> QcResult:
    normalized = normalize(rebuilt.text)
    sequence = normalized.sequence

    def evidence(positions: Iterable[int]) -> tuple[BlockSpan, ...]:
        return rebuilt.evidence_for(normalized.raw_positions[position] for position in positions)

    issues: list[Issue] = []
    if not sequence:
        issues.append(registry.issue("QC01", "The referenced text contains no residues."))
    for change in normalized.transformations:
        issues.append(
            registry.issue(
                "QC02",
                f"{change.operation}: {len(change.positions)} position(s). {change.reason}",
                rebuilt.evidence_for(change.positions),
            )
        )
    found = scan(sequence)
    if found.invalid:
        issues.append(
            registry.issue(
                "QC03",
                "Characters outside the protein alphabet: " + describe(sequence, found.invalid),
                evidence(found.invalid),
            )
        )
    if found.extended:
        issues.append(
            registry.issue(
                "QC04",
                "Extended residue codes need confirmation: " + describe(sequence, found.extended),
                evidence(found.extended),
            )
        )
    if found.ellipsis:
        issues.append(
            registry.issue("QC05", "Ellipsis marks omitted residues.", evidence(found.ellipsis))
        )
    if found.gaps_and_stops:
        issues.append(
            registry.issue(
                "QC06",
                "Stop or gap characters need an explicit transformation: "
                + describe(sequence, found.gaps_and_stops),
                evidence(found.gaps_and_stops),
            )
        )
    issues.extend(_context_issues(registry, context))
    molecule_type = classify(sequence, context.molecule_type_hint, context.observation_kinds)
    if sequence and molecule_type is not MoleculeType.PROTEIN:
        issues.append(
            registry.issue("QC11", "Confirm the molecule type; only proteins can be published.")
        )
    return QcResult(registry.version, rebuilt.text, normalized, molecule_type, tuple(issues))


def _context_issues(registry: QcRegistry, context: ExtractionContext) -> list[Issue]:
    kinds = context.observation_kinds
    issues: list[Issue] = []
    if "possible_truncation" in kinds and not context.declared_fragment:
        issues.append(registry.issue("QC05", "Extraction reported possible truncation."))
    if (
        context.name_count != 1
        or context.association_status != "unambiguous"
        or kinds & {"name_conflict", "unclear_mapping"}
    ):
        issues.append(
            registry.issue(
                "QC07",
                f"Name mapping is {context.association_status} "
                f"with {context.name_count} candidate name(s).",
            )
        )
    if context.coverage_risk or "unsupported_content" in kinds:
        issues.append(
            registry.issue("QC08", "Parts of the source were not fully read; check the original.")
        )
    return issues
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_qc_engine.py -v`
Expected: `7 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `30 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/qc/engine.py tests/unit/test_qc_engine.py
git commit -m "feat(qc): evaluate candidates against QC rules"
```

## Task 7: Extraction cross-checks

**Files:**
- Create: `services/backend/src/sequence_vault/domain/extraction.py`
- Test: `tests/unit/test_extraction.py`

JSON Schema cannot check that a name's evidence spells the name, that spans fit their blocks, or that two records claim the same residues. A non-empty result triggers the gateway's single repair attempt, then human handling.

- [ ] **Step 1: Write the failing test `tests/unit/test_extraction.py`**

```python
from sequence_vault.domain.extraction import ExtractedRecord, Name, check_extraction
from sequence_vault.domain.qc.engine import MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

BLOCKS = {"h1": ">RSPO3_C07 heavy chain", "p1": "MKTAYIAKQR"}


def record(names: tuple[Name, ...], spans: tuple[SequenceSpan, ...]) -> ExtractedRecord:
    return ExtractedRecord(names, MoleculeType.PROTEIN, spans, "unambiguous", frozenset())


def test_accepts_name_evidence_inside_a_longer_header() -> None:
    name = Name("RSPO3_C07", "fasta_header", BlockSpan("h1", 1, 10))
    assert check_extraction(BLOCKS, [record((name,), (SequenceSpan("p1", 0, 10, 1),))]) == ()


def test_filename_names_and_pending_content_need_no_evidence() -> None:
    assert check_extraction(BLOCKS, [record((Name("RSPO3", "filename", None),), ())]) == ()


def test_reports_name_that_does_not_match_its_evidence() -> None:
    name = Name("RSPO3_C08", "fasta_header", BlockSpan("h1", 1, 10))
    (problem,) = check_extraction(BLOCKS, [record((name,), ())])
    assert "does not match its evidence" in problem


def test_reports_two_records_claiming_the_same_residues() -> None:
    first = record((), (SequenceSpan("p1", 0, 6, 1),))
    second = record((), (SequenceSpan("p1", 4, 10, 1),))
    (problem,) = check_extraction(BLOCKS, [first, second])
    assert "records 0 and 1 claim overlapping text" in problem
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.extraction'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/extraction.py`**

```python
"""Extracted records and the cross-field checks JSON Schema cannot express."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sequence_vault.domain.qc.engine import MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan, check_spans


@dataclass(frozen=True, slots=True)
class Name:
    value: str
    source: str
    evidence: BlockSpan | None


@dataclass(frozen=True, slots=True)
class ExtractedRecord:
    names: tuple[Name, ...]
    molecule_type_hint: MoleculeType
    spans: tuple[SequenceSpan, ...]
    association_status: str
    observation_kinds: frozenset[str]


def check_extraction(
    blocks: Mapping[str, str], records: Sequence[ExtractedRecord]
) -> tuple[str, ...]:
    """Problems that make an extraction result unusable; an empty tuple means usable.

    Callers allow one controlled repair attempt, then route to human handling.
    """
    problems: list[str] = []
    claimed: list[tuple[int, SequenceSpan]] = []
    for index, record in enumerate(records):
        for name in record.names:
            if name.evidence is None:
                continue
            text = blocks.get(name.evidence.block_id)
            if text is None:
                problems.append(
                    f"record {index}: name evidence block {name.evidence.block_id!r} does not exist"
                )
            elif text[name.evidence.start : name.evidence.end] != name.value:
                problems.append(f"record {index}: name {name.value!r} does not match its evidence")
        if record.spans:
            problems.extend(
                f"record {index}: {problem}" for problem in check_spans(blocks, record.spans)
            )
        claimed.extend((index, span) for span in record.spans)
    for position, (first_index, first) in enumerate(claimed):
        for second_index, second in claimed[position + 1 :]:
            if (
                first_index != second_index
                and first.block_id == second.block_id
                and first.start < second.end
                and second.start < first.end
            ):
                problems.append(
                    f"records {first_index} and {second_index} claim overlapping text "
                    f"in block {first.block_id!r}"
                )
    return tuple(problems)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_extraction.py -v`
Expected: `4 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `34 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/extraction.py tests/unit/test_extraction.py
git commit -m "feat(domain): check extraction results"
```

## Task 8: Name keys

**Files:**
- Create: `services/backend/src/sequence_vault/domain/naming.py`
- Test: `tests/unit/test_naming.py`

Spec section 7: trim and case-fold. `str.strip` also removes the ideographic space U+3000. NFKC folding is proposed in ADR 0004 and deliberately not implemented yet.

- [ ] **Step 1: Write the failing test `tests/unit/test_naming.py`**

```python
import pytest

from sequence_vault.domain.naming import name_key


def test_trims_and_case_folds() -> None:
    assert name_key("  RSPO3_C07_v2　") == "rspo3_c07_v2"


def test_rejects_blank_names() -> None:
    with pytest.raises(ValueError, match="blank"):
        name_key(" \t ")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.naming'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/naming.py`**

```python
"""Project-scoped record name keys (design section 7)."""


def name_key(display_name: str) -> str:
    """Trim and case-fold; the original spelling is kept separately for display."""
    key = display_name.strip().casefold()
    if not key:
        raise ValueError("A record name cannot be blank.")
    return key
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_naming.py -v`
Expected: `2 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `36 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/naming.py tests/unit/test_naming.py
git commit -m "feat(domain): add record name keys"
```

## Task 9: Candidate lifecycle

**Files:**
- Create: `services/backend/src/sequence_vault/domain/candidate.py`
- Test: `tests/unit/test_candidate.py`

Every change goes through `_next_revision`, which voids approval and resolutions. `resolve` refuses BLOCK issues and any resolution not in the rule's allowlist. `mark_committed` is the last guard inside the commit transaction. `validated` marks a candidate `complete` only when every span is a whole parser-delimited sequence block, such as a FASTA body.

- [ ] **Step 1: Write the failing test `tests/unit/test_candidate.py`**

```python
import pytest

from sequence_vault.domain.candidate import (
    Candidate,
    CandidateError,
    CandidateStatus,
    InvalidTransition,
    ResolutionNotAllowed,
    RevisionConflict,
    UnresolvedIssues,
)
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    QcResult,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

BLOCKS = {"h1": "RSPO3_C07", "p1": "MKTAYIAKQR", "p2": "MKXAYIAKQR"}
NAME = Name("RSPO3_C07", "fasta_header", BlockSpan("h1", 0, 9))
CONTEXT = ExtractionContext(1, "unambiguous", frozenset(), MoleculeType.PROTEIN, False)


def qc_for(registry: QcRegistry, block_id: str) -> QcResult:
    return evaluate_spans(registry, BLOCKS, [SequenceSpan(block_id, 0, 10, 1)], CONTEXT)


def in_review(registry: QcRegistry, block_id: str = "p1") -> Candidate:
    draft = Candidate.extracted("c1", "run1", (NAME,), (SequenceSpan(block_id, 0, 10, 1),))
    return draft.validated(qc_for(registry, block_id), parser_delimited=True)


def test_validation_moves_a_clean_draft_to_review_as_complete(registry: QcRegistry) -> None:
    candidate = in_review(registry)
    assert (candidate.status, candidate.revision, candidate.completeness) == (
        CandidateStatus.NEEDS_REVIEW,
        1,
        "complete",
    )


def test_name_without_sequence_waits_for_content(registry: QcRegistry) -> None:
    draft = Candidate.extracted("c1", "run1", (NAME,), ())
    qc = evaluate_spans(registry, BLOCKS, [], CONTEXT)
    pending = draft.validated(qc, parser_delimited=False)
    assert pending.status is CandidateStatus.PENDING_CONTENT
    assert pending.archive(1).status is CandidateStatus.ARCHIVED


def test_approval_needs_every_review_issue_resolved(registry: QcRegistry) -> None:
    candidate = in_review(registry, "p2")  # X raises QC04 (REVIEW)
    with pytest.raises(UnresolvedIssues, match="QC04"):
        candidate.approve(1, "reviewer")
    resolved = candidate.resolve(1, registry, "QC04", "confirm_residue_semantics")
    approved = resolved.approve(1, "reviewer")
    assert (approved.status, approved.approved_revision) == (CandidateStatus.APPROVED, 1)


def test_resolutions_must_come_from_the_rule_allowlist(registry: QcRegistry) -> None:
    candidate = in_review(registry, "p2")
    with pytest.raises(ResolutionNotAllowed, match="not allowed"):
        candidate.resolve(1, registry, "QC04", "ignore")


def test_block_issues_cannot_be_resolved_away(registry: QcRegistry) -> None:
    blocked = Candidate.extracted("c1", "run1", (NAME,), (SequenceSpan("p1", 0, 99, 1),))
    qc = evaluate_spans(registry, BLOCKS, list(blocked.spans), CONTEXT)
    blocked = blocked.validated(qc, parser_delimited=False)
    assert blocked.status is CandidateStatus.BLOCKED
    fixed = blocked.revise_sequence(
        1,
        qc_for(registry, "p1"),
        reason="Span ran past the block",
        spans=(SequenceSpan("p1", 0, 10, 1),),
    )
    assert (fixed.status, fixed.revision, fixed.origin) == (
        CandidateStatus.NEEDS_REVIEW,
        2,
        "manual_revision",
    )


def test_edits_void_approval_and_stale_revisions_conflict(registry: QcRegistry) -> None:
    approved = in_review(registry).approve(1, "reviewer")
    renamed = approved.rename(1, Name("RSPO3 C07", "manual", None))
    assert (renamed.status, renamed.revision, renamed.approved_revision) == (
        CandidateStatus.NEEDS_REVIEW,
        2,
        None,
    )
    with pytest.raises(RevisionConflict):
        renamed.approve(1, "reviewer")


def test_typed_sequence_edits_need_a_reason(registry: QcRegistry) -> None:
    candidate = in_review(registry)
    typed_qc = evaluate_typed(registry, "MKTAYIAKQW", CONTEXT)
    with pytest.raises(CandidateError, match="reason"):
        candidate.revise_sequence(1, typed_qc, reason=" ", typed_sequence="MKTAYIAKQW")
    edited = candidate.revise_sequence(
        1, typed_qc, reason="Source scan shows W", typed_sequence="MKTAYIAKQW"
    )
    assert (edited.typed_sequence, edited.completeness) == ("MKTAYIAKQW", "unknown")


def test_commit_requires_the_approved_revision(registry: QcRegistry) -> None:
    approved = in_review(registry).approve(1, "reviewer")
    assert approved.mark_committed(1).status is CandidateStatus.COMMITTED
    with pytest.raises(InvalidTransition):
        in_review(registry).mark_committed(1)


def test_reextraction_supersedes_open_candidates_only(registry: QcRegistry) -> None:
    assert in_review(registry).supersede().status is CandidateStatus.SUPERSEDED
    committed = in_review(registry).approve(1, "reviewer").mark_committed(1)
    with pytest.raises(InvalidTransition):
        committed.supersede()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_candidate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.candidate'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/candidate.py`**

```python
"""Candidate lifecycle: revisions, issue resolutions, approval and commitment."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from sequence_vault.domain.extraction import Name
from sequence_vault.domain.qc.engine import QcResult
from sequence_vault.domain.qc.registry import QcRegistry, Severity
from sequence_vault.domain.spans import SequenceSpan


class CandidateStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    PENDING_CONTENT = "PENDING_CONTENT"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


TERMINAL = frozenset(
    {
        CandidateStatus.COMMITTED,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
        CandidateStatus.SUPERSEDED,
    }
)
EDITABLE = frozenset(
    {
        CandidateStatus.NEEDS_REVIEW,
        CandidateStatus.BLOCKED,
        CandidateStatus.APPROVED,
        CandidateStatus.PENDING_CONTENT,
    }
)


class CandidateError(Exception):
    """Base class for rejected candidate operations."""


class RevisionConflict(CandidateError):
    """The caller acted on an older revision (HTTP 409)."""


class InvalidTransition(CandidateError):
    pass


class ResolutionNotAllowed(CandidateError):
    pass


class UnresolvedIssues(CandidateError):
    pass


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    run_id: str
    revision: int
    status: CandidateStatus
    name: Name | None
    extracted_names: tuple[Name, ...]
    spans: tuple[SequenceSpan, ...]
    typed_sequence: str | None
    completeness: str
    origin: str
    qc: QcResult | None
    resolutions: Mapping[str, str] = field(default_factory=dict)
    approved_revision: int | None = None
    approved_by: str | None = None

    @classmethod
    def extracted(
        cls,
        candidate_id: str,
        run_id: str,
        names: tuple[Name, ...],
        spans: tuple[SequenceSpan, ...],
    ) -> "Candidate":
        """A new DRAFT. A single name is preselected; several names wait for the reviewer."""
        return cls(
            candidate_id=candidate_id,
            run_id=run_id,
            revision=1,
            status=CandidateStatus.DRAFT,
            name=names[0] if len(names) == 1 else None,
            extracted_names=names,
            spans=spans,
            typed_sequence=None,
            completeness="unknown",
            origin="extracted",
            qc=None,
        )

    def validated(self, qc: QcResult, *, parser_delimited: bool) -> "Candidate":
        """Leave DRAFT after QC. ``parser_delimited`` means every span is a whole sequence
        block delimited by the parser (a FASTA body), the only case treated as complete."""
        self._require(CandidateStatus.DRAFT)
        complete = parser_delimited and "QC05" not in qc.rule_ids(Severity.BLOCK)
        return replace(
            self,
            qc=qc,
            completeness="complete" if complete else "unknown",
            status=self._status_after_qc(qc, has_sequence=bool(self.spans)),
        )

    def rename(self, expected_revision: int, name: Name) -> "Candidate":
        self._check_editable(expected_revision)
        return self._next_revision(name=name)

    def revise_sequence(
        self,
        expected_revision: int,
        qc: QcResult,
        *,
        reason: str,
        spans: tuple[SequenceSpan, ...] = (),
        typed_sequence: str | None = None,
        fragment: bool = False,
    ) -> "Candidate":
        """Replace the evidence spans, or type a sequence by hand. Both need a reason."""
        self._check_editable(expected_revision)
        if not reason.strip():
            raise CandidateError("A sequence change needs a reason.")
        if bool(spans) == (typed_sequence is not None):
            raise CandidateError("Provide either evidence spans or a typed sequence.")
        return self._next_revision(
            spans=spans,
            typed_sequence=typed_sequence,
            qc=qc,
            completeness="fragment" if fragment else "unknown",
            origin="manual_revision",
            status=self._status_after_qc(qc, has_sequence=True),
        )

    def resolve(
        self, expected_revision: int, registry: QcRegistry, rule_id: str, resolution: str
    ) -> "Candidate":
        """Record a reviewer decision for a REVIEW or INFO issue on this revision."""
        self._check_revision(expected_revision)
        if self.status is not CandidateStatus.NEEDS_REVIEW or self.qc is None:
            raise InvalidTransition(f"Issues can only be resolved in review, not {self.status}.")
        if rule_id not in {issue.rule_id for issue in self.qc.issues}:
            raise ResolutionNotAllowed(f"{rule_id} is not an issue on revision {self.revision}.")
        rule = registry.rules[rule_id]
        if rule.severity is Severity.BLOCK:
            raise ResolutionNotAllowed(f"{rule_id} blocks; change the candidate to clear it.")
        if resolution not in rule.allowed_resolutions:
            raise ResolutionNotAllowed(f"{resolution!r} is not allowed for {rule_id}.")
        return replace(self, resolutions={**self.resolutions, rule_id: resolution})

    def approve(self, expected_revision: int, reviewer_id: str) -> "Candidate":
        self._check_revision(expected_revision)
        self._require(CandidateStatus.NEEDS_REVIEW)
        assert self.qc is not None
        unresolved = sorted(self.qc.rule_ids(Severity.REVIEW) - self.resolutions.keys())
        if unresolved:
            raise UnresolvedIssues(f"Resolve before approving: {', '.join(unresolved)}")
        if self.name is None:
            raise UnresolvedIssues("Select a name before approving.")
        return replace(
            self,
            status=CandidateStatus.APPROVED,
            approved_revision=self.revision,
            approved_by=reviewer_id,
        )

    def reject(self, expected_revision: int) -> "Candidate":
        self._check_editable(expected_revision)
        return replace(self, status=CandidateStatus.REJECTED)

    def archive(self, expected_revision: int) -> "Candidate":
        self._check_revision(expected_revision)
        self._require(CandidateStatus.PENDING_CONTENT)
        return replace(self, status=CandidateStatus.ARCHIVED)

    def supersede(self) -> "Candidate":
        """Called for every open candidate of an older run when a file is re-extracted."""
        if self.status in TERMINAL:
            raise InvalidTransition(f"{self.status} candidates cannot be superseded.")
        return replace(self, status=CandidateStatus.SUPERSEDED)

    def mark_committed(self, approved_revision: int) -> "Candidate":
        """Only inside the commit transaction, after every recheck has passed."""
        self._require(CandidateStatus.APPROVED)
        if not approved_revision == self.approved_revision == self.revision:
            raise RevisionConflict("The approval does not match the current revision.")
        return replace(self, status=CandidateStatus.COMMITTED)

    @staticmethod
    def _status_after_qc(qc: QcResult, *, has_sequence: bool) -> CandidateStatus:
        if not has_sequence:
            return CandidateStatus.PENDING_CONTENT
        return CandidateStatus.BLOCKED if qc.blocked else CandidateStatus.NEEDS_REVIEW

    def _next_revision(self, **changes: object) -> "Candidate":
        """Every edit bumps the revision and voids approval and resolutions."""
        updated = replace(
            self,
            revision=self.revision + 1,
            resolutions={},
            approved_revision=None,
            approved_by=None,
            **changes,  # type: ignore[arg-type]
        )
        if "status" in changes or updated.qc is None:
            return updated
        has_sequence = bool(updated.spans) or updated.typed_sequence is not None
        return replace(updated, status=self._status_after_qc(updated.qc, has_sequence=has_sequence))

    def _check_editable(self, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if self.status not in EDITABLE:
            raise InvalidTransition(f"{self.status} candidates cannot be changed.")

    def _check_revision(self, expected_revision: int) -> None:
        if expected_revision != self.revision:
            raise RevisionConflict(
                f"Revision {expected_revision} is stale; the current revision is {self.revision}."
            )

    def _require(self, status: CandidateStatus) -> None:
        if self.status is not status:
            raise InvalidTransition(f"Expected {status}, found {self.status}.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_candidate.py -v`
Expected: `9 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `45 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/candidate.py tests/unit/test_candidate.py
git commit -m "feat(domain): add candidate lifecycle"
```

## Task 10: File task lifecycle

**Files:**
- Create: `services/backend/src/sequence_vault/domain/task.py`
- Test: `tests/unit/test_task.py`

`advance(finished_stage)` names the stage the worker just finished, so a duplicate or late queue delivery raises `StaleStage` and is dropped instead of skipping a stage.

- [ ] **Step 1: Write the failing test `tests/unit/test_task.py`**

```python
import pytest

from sequence_vault.domain.candidate import CandidateStatus
from sequence_vault.domain.task import FileTask, ItemsPending, StaleStage, TaskError, TaskStatus


def test_advances_one_stage_at_a_time() -> None:
    task = FileTask("t1")
    for stage in (TaskStatus.UPLOADED, TaskStatus.SCANNING, TaskStatus.PARSING):
        task = task.advance(stage)
    assert task.status is TaskStatus.EXTRACTING


def test_duplicate_delivery_is_detected() -> None:
    task = FileTask("t1").advance(TaskStatus.UPLOADED)
    with pytest.raises(StaleStage):
        task.advance(TaskStatus.UPLOADED)


def test_completes_only_when_every_candidate_is_settled() -> None:
    task = FileTask("t1", status=TaskStatus.REVIEW_READY)
    with pytest.raises(ItemsPending, match="1 candidate"):
        task.complete([CandidateStatus.COMMITTED, CandidateStatus.PENDING_CONTENT])
    done = task.complete([CandidateStatus.COMMITTED, CandidateStatus.ARCHIVED])
    assert done.status is TaskStatus.COMPLETED


def test_terminal_tasks_cannot_be_cancelled_or_failed() -> None:
    cancelled = FileTask("t1").cancel()
    with pytest.raises(TaskError):
        cancelled.fail("parser_crash")


def test_unsupported_is_decided_while_scanning() -> None:
    scanning = FileTask("t1", status=TaskStatus.SCANNING)
    assert scanning.mark_unsupported().status is TaskStatus.UNSUPPORTED
    with pytest.raises(TaskError):
        FileTask("t1").mark_unsupported()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_task.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.task'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/task.py`**

```python
"""File task lifecycle (design section 3)."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from sequence_vault.domain.candidate import CandidateStatus


class TaskStatus(StrEnum):
    UPLOADED = "UPLOADED"
    SCANNING = "SCANNING"
    PARSING = "PARSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    REVIEW_READY = "REVIEW_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"


PIPELINE = (
    TaskStatus.UPLOADED,
    TaskStatus.SCANNING,
    TaskStatus.PARSING,
    TaskStatus.EXTRACTING,
    TaskStatus.VALIDATING,
    TaskStatus.REVIEW_READY,
)
TERMINAL = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.UNSUPPORTED}
)
SETTLED_CANDIDATES = frozenset(
    {CandidateStatus.COMMITTED, CandidateStatus.REJECTED, CandidateStatus.ARCHIVED}
)


class TaskError(Exception):
    pass


class StaleStage(TaskError):
    """Another worker already moved the task on; drop the duplicate delivery."""


class ItemsPending(TaskError):
    pass


@dataclass(frozen=True, slots=True)
class FileTask:
    task_id: str
    status: TaskStatus = TaskStatus.UPLOADED
    failure_code: str | None = None

    def advance(self, finished_stage: TaskStatus) -> "FileTask":
        """Move past ``finished_stage``. A mismatch means a duplicate or late delivery."""
        if self.status is not finished_stage:
            raise StaleStage(f"Task is {self.status}, not {finished_stage}.")
        if finished_stage is TaskStatus.REVIEW_READY:
            raise TaskError("Review-ready tasks complete through complete().")
        return replace(self, status=PIPELINE[PIPELINE.index(finished_stage) + 1])

    def mark_unsupported(self) -> "FileTask":
        if self.status is not TaskStatus.SCANNING:
            raise TaskError("Format support is decided while scanning.")
        return replace(self, status=TaskStatus.UNSUPPORTED)

    def fail(self, failure_code: str) -> "FileTask":
        self._require_open()
        return replace(self, status=TaskStatus.FAILED, failure_code=failure_code)

    def cancel(self) -> "FileTask":
        self._require_open()
        return replace(self, status=TaskStatus.CANCELLED)

    def complete(self, candidate_statuses: Iterable[CandidateStatus]) -> "FileTask":
        """Complete only when every current-run candidate is committed, rejected or archived."""
        if self.status is not TaskStatus.REVIEW_READY:
            raise TaskError(f"Only review-ready tasks complete, not {self.status}.")
        pending = [status for status in candidate_statuses if status not in SETTLED_CANDIDATES]
        if pending:
            raise ItemsPending(f"{len(pending)} candidate(s) still need a decision.")
        return replace(self, status=TaskStatus.COMPLETED)

    def _require_open(self) -> None:
        if self.status in TERMINAL:
            raise TaskError(f"Task is already {self.status}.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_task.py -v`
Expected: `5 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `50 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/task.py tests/unit/test_task.py
git commit -m "feat(domain): add file task lifecycle"
```

## Task 11: Publication decisions (QC09, QC10)

**Files:**
- Create: `services/backend/src/sequence_vault/domain/publication.py`
- Test: `tests/unit/test_publication.py`

The repository finds entities by `(tenant, type, sha256)`; this function compares full content before reusing one, guarding against hash collisions. A same-name, different-sequence commit needs the reviewer's QC09 resolution; without it the plan is `NEEDS_DECISION`, which the commit service reports as `CONFLICT`.

- [ ] **Step 1: Write the failing test `tests/unit/test_publication.py`**

```python
from sequence_vault.domain.publication import (
    RecordAction,
    StoredEntity,
    StoredRecord,
    plan_publication,
    sequence_sha256,
)
from sequence_vault.domain.qc.registry import QcRegistry


def test_new_name_and_new_sequence_create_a_record(registry: QcRegistry) -> None:
    plan = plan_publication(registry, "MKTAY", [], None, None)
    assert (plan.reuse_entity_id, plan.record_action, plan.issues) == (
        None,
        RecordAction.CREATE_RECORD,
        (),
    )


def test_reuses_an_entity_only_after_full_content_comparison(registry: QcRegistry) -> None:
    collision = StoredEntity("e-old", "DIFFERENT")
    identical = StoredEntity("e-same", "MKTAY")
    plan = plan_publication(registry, "MKTAY", [collision, identical], None, None)
    assert plan.reuse_entity_id == "e-same"
    assert [issue.rule_id for issue in plan.issues] == ["QC10"]


def test_same_name_same_sequence_only_adds_provenance(registry: QcRegistry) -> None:
    record = StoredRecord("r1", 1, "MKTAY")
    assert plan_publication(registry, "MKTAY", [], record, None).record_action is (
        RecordAction.ADD_PROVENANCE
    )


def test_same_name_new_sequence_needs_an_explicit_decision(registry: QcRegistry) -> None:
    record = StoredRecord("r1", 3, "MKTAY")
    undecided = plan_publication(registry, "MKTAW", [], record, None)
    assert undecided.record_action is RecordAction.NEEDS_DECISION
    assert [issue.rule_id for issue in undecided.issues] == ["QC09"]
    decided = plan_publication(registry, "MKTAW", [], record, "create_new_version")
    assert decided.record_action is RecordAction.NEW_VERSION


def test_sequence_hash_is_stable() -> None:
    assert sequence_sha256("ACDEFGHIKLMNPQRSTVWY") == (
        "5a52efc76a4a4ceb3c992ff17426b3545634646080bb6acec132c47c278c9846"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_publication.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.domain.publication'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/domain/publication.py`**

```python
"""Deduplication and version decisions for committing one approved candidate (QC09, QC10)."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.domain.qc.registry import Issue, QcRegistry


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredEntity:
    """A sequence entity found by (tenant, type, sha256); its content is compared in full."""

    entity_id: str
    sequence: str


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """The project's record with the candidate's name_key, and its current version."""

    record_id: str
    current_version_no: int
    current_sequence: str


class RecordAction(StrEnum):
    CREATE_RECORD = "create_record"
    ADD_PROVENANCE = "add_provenance"
    NEW_VERSION = "new_version"
    NEEDS_DECISION = "needs_decision"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    reuse_entity_id: str | None
    record_action: RecordAction
    issues: tuple[Issue, ...]


def plan_publication(
    registry: QcRegistry,
    sequence: str,
    hash_matches: Sequence[StoredEntity],
    record: StoredRecord | None,
    qc09_resolution: str | None,
) -> PublicationPlan:
    """Decide what committing ``sequence`` writes. Never overwrites a published version."""
    reuse = next((entity.entity_id for entity in hash_matches if entity.sequence == sequence), None)
    issues: list[Issue] = []
    if reuse is not None:
        issues.append(registry.issue("QC10", "An identical sequence is stored; it will be reused."))
    if record is None:
        action = RecordAction.CREATE_RECORD
    elif record.current_sequence == sequence:
        action = RecordAction.ADD_PROVENANCE
    else:
        issues.append(
            registry.issue(
                "QC09",
                f"This name already has version {record.current_version_no} "
                "with a different sequence.",
            )
        )
        action = {
            "create_new_version": RecordAction.NEW_VERSION,
            "cancel": RecordAction.CANCEL,
        }.get(qc09_resolution or "", RecordAction.NEEDS_DECISION)
    return PublicationPlan(reuse, action, tuple(issues))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_publication.py -v`
Expected: `5 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `55 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/domain/publication.py tests/unit/test_publication.py
git commit -m "feat(domain): plan dedup and version decisions"
```

## Task 12: Contract mapping and round trip

**Files:**
- Create: `services/backend/src/sequence_vault/application/contract_mapping.py`
- Test: `tests/unit/test_contract_mapping.py`

This test ties the domain to the published contracts: the synthetic DocumentIR and extraction result must produce exactly `packages/contracts/examples/candidate.json`, which must also validate against `candidate.schema.json`.

- [ ] **Step 1: Write the failing test `tests/unit/test_contract_mapping.py`**

```python
"""The domain must reproduce the synthetic contract examples exactly."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from sequence_vault.application.contract_mapping import (
    blocks_from_document_ir,
    candidate_to_wire,
    context_for,
    parser_delimited,
    records_from_extraction,
)
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.extraction import check_extraction
from sequence_vault.domain.qc.engine import evaluate_spans
from sequence_vault.domain.qc.registry import QcRegistry

CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts"


def load(relative: str) -> Any:
    return json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))


def candidate_validator() -> Draft202012Validator:
    schemas = {
        path.name: load(f"schemas/v1/{path.name}") for path in (CONTRACTS / "schemas/v1").iterdir()
    }
    registry: Registry[Any] = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return Draft202012Validator(schemas["candidate.schema.json"], registry=registry)


def test_synthetic_fasta_example_round_trips(registry: QcRegistry) -> None:
    document = load("examples/document-ir.json")
    extraction = load("examples/extraction-result.json")
    expected = load("examples/candidate.json")

    blocks = blocks_from_document_ir(document)
    records = records_from_extraction(extraction)
    assert check_extraction(blocks, records) == ()

    index = expected["extraction_record_index"]
    record = records[index]
    qc = evaluate_spans(registry, blocks, record.spans, context_for(record, document))
    candidate = Candidate.extracted(
        expected["candidate_id"], extraction["run_id"], record.names, record.spans
    ).validated(qc, parser_delimited=parser_delimited(record, document))

    wire = candidate_to_wire(candidate, index)
    candidate_validator().validate(wire)
    assert wire == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_contract_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sequence_vault.application.contract_mapping'`

- [ ] **Step 3: Implement `services/backend/src/sequence_vault/application/contract_mapping.py`**

```python
"""Translate between the JSON contracts in packages/contracts and domain objects.

Input documents must already have passed JSON Schema validation.
"""

from collections.abc import Mapping
from typing import Any

from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.extraction import ExtractedRecord, Name
from sequence_vault.domain.qc.engine import ExtractionContext, MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

Json = Mapping[str, Any]


def blocks_from_document_ir(document: Json) -> dict[str, str]:
    return {block["block_id"]: block["raw_text"] for block in document["blocks"]}


def records_from_extraction(result: Json) -> tuple[ExtractedRecord, ...]:
    return tuple(
        ExtractedRecord(
            names=tuple(_name(item) for item in record["names"]),
            molecule_type_hint=MoleculeType(record["molecule_type"]),
            spans=tuple(
                SequenceSpan(span["block_id"], span["start"], span["end"], span["order"])
                for span in record["sequence_spans"]
            ),
            association_status=record["association_status"],
            observation_kinds=frozenset(item["kind"] for item in record["observations"]),
        )
        for record in result["records"]
    )


def context_for(record: ExtractedRecord, document: Json) -> ExtractionContext:
    coverage = document["coverage"]
    methods = {block["block_id"]: block["extraction_method"] for block in document["blocks"]}
    coverage_risk = (
        bool(coverage["unresolved_blocks"])
        or coverage["truncated"]
        or bool(coverage.get("warnings"))
        or any(methods[span.block_id] != "text_parser" for span in record.spans)
    )
    return ExtractionContext(
        name_count=len(record.names),
        association_status=record.association_status,
        observation_kinds=record.observation_kinds,
        molecule_type_hint=record.molecule_type_hint,
        coverage_risk=coverage_risk,
    )


def parser_delimited(record: ExtractedRecord, document: Json) -> bool:
    """True when every span covers a whole parser-delimited sequence block."""
    blocks = {block["block_id"]: block for block in document["blocks"]}
    return bool(record.spans) and all(
        blocks[span.block_id]["type"] == "sequence"
        and span.start == 0
        and span.end == len(blocks[span.block_id]["raw_text"])
        for span in record.spans
    )


def candidate_to_wire(candidate: Candidate, extraction_record_index: int | None) -> dict[str, Any]:
    qc = candidate.qc
    if qc is None:
        raise ValueError("Only validated candidates have a wire representation.")
    wire: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": candidate.candidate_id,
        "run_id": candidate.run_id,
    }
    if extraction_record_index is not None:
        wire["extraction_record_index"] = extraction_record_index
    wire |= {
        "revision": candidate.revision,
        "name": _name_to_wire(candidate.name) if candidate.name else None,
        "extracted_names": [_name_to_wire(name) for name in candidate.extracted_names],
        "sequence_spans": [
            {"block_id": s.block_id, "start": s.start, "end": s.end, "order": s.order}
            for s in candidate.spans
        ],
        "raw_text": qc.raw_text,
        "normalized_sequence": qc.normalized.sequence if qc.normalized else "",
        "molecule_type": qc.molecule_type.value,
        "completeness": candidate.completeness,
        "status": candidate.status.value,
        "origin": candidate.origin,
        "transformation_log": [
            {
                "rule_id": change.rule_id,
                "operation": change.operation,
                "reason": change.reason,
                "positions": list(change.positions),
            }
            for change in (qc.normalized.transformations if qc.normalized else ())
        ],
        "issues": [
            {
                "rule_id": issue.rule_id,
                "severity": issue.severity.value,
                "message": issue.message,
                "evidence": [_span_to_wire(span) for span in issue.evidence],
            }
            for issue in qc.issues
        ],
        "qc_version": qc.qc_version,
    }
    return wire


def _name(item: Json) -> Name:
    evidence = item["evidence"]
    span = None if evidence is None else BlockSpan(**evidence)
    return Name(item["value"], item["source"], span)


def _name_to_wire(name: Name) -> dict[str, Any]:
    evidence = None if name.evidence is None else _span_to_wire(name.evidence)
    return {"value": name.value, "source": name.source, "evidence": evidence}


def _span_to_wire(span: BlockSpan) -> dict[str, Any]:
    return {"block_id": span.block_id, "start": span.start, "end": span.end}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_contract_mapping.py -v`
Expected: `1 passed`

- [ ] **Step 5: Run lint, import contracts, types and the whole suite**

Run: `make lint typecheck test`
Expected: `All checks passed!`, both contracts `KEPT`, mypy `Success`, `56 passed`

- [ ] **Step 6: Commit**

```bash
git add services/backend/src/sequence_vault/application/contract_mapping.py tests/unit/test_contract_mapping.py
git commit -m "feat(application): map contracts to domain"
```

## Task 13: Document the domain core

**Files:**
- Modify: `services/backend/README.md`

- [ ] **Step 1: Update the first paragraph of `services/backend/README.md`**

Replace the first paragraph with:

```markdown
`src/sequence_vault` is the shared package for the API and processing workers. `domain` holds the tested, framework-free core: span reconstruction, normalization, QC rules, candidate and task lifecycles, and publication decisions. No server, persistence, queue or parser is implemented yet.
```

- [ ] **Step 2: Run every check**

Run: `make check`
Expected: `Scaffold checks passed`, `All checks passed!`, both contracts `KEPT`, mypy `Success: no issues found in 38 source files`, `56 passed`.

- [ ] **Step 3: Commit**

```bash
git add services/backend/README.md
git commit -m "docs(backend): describe the domain core"
```

## Done when

- `make check` passes locally and in CI with 56 tests.
- `uv run lint-imports` shows the domain importing nothing from `application`, `adapters`, `api`, `workers` or any framework.
- `tests/unit/test_contract_mapping.py` reproduces `packages/contracts/examples/candidate.json` exactly.

## Not in this plan

These are left to later plans on purpose (see `docs/implementation-plan.md`):

- Persistence, the commit transaction and idempotency keys (P2).
- Splitting one candidate into two and joining two into one: these create and supersede candidates through application use cases (P5). This plan covers editing one candidate's spans.
- Automatic-acceptance eligibility in shadow mode (spec section 6): it depends on benchmarked parser and policy versions (P6).
- Parsers, scanning, storage and the worker loop (P3).
- HTTP, sign-in and the web app (P4, P5).
- ADR 0004 normalization changes: they need the data owner's decision and a new QC registry version.
