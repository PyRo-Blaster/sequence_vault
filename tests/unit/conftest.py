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
