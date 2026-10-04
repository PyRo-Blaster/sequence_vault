import json

from sequence_vault.api.auth import RateLimiter
from sequence_vault.application.queries import fasta_header, to_fasta
from sequence_vault.entrypoints.admin import openapi
from sequence_vault.settings import REPO_ROOT


def test_rate_limiter_refills_over_time() -> None:
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")


def test_fasta_output_is_wrapped_and_headers_are_single_line() -> None:
    assert fasta_header("x\n>y z", "r1", 3) == ">x_y_z record=r1 version=3"
    assert to_fasta(">h", "A" * 130) == ">h\n" + "A" * 60 + "\n" + "A" * 60 + "\nAAAAAAAAAA\n"


def test_committed_openapi_matches_the_application() -> None:
    committed = json.loads((REPO_ROOT / "packages/contracts/api/openapi.json").read_text())
    assert committed == openapi(), "Regenerate: python -m sequence_vault.entrypoints.admin openapi"
