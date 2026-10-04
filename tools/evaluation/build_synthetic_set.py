"""Regenerate the synthetic evaluation set in tests/fixtures/evaluation.

uv run python tools/evaluation/build_synthetic_set.py
"""

import json
import sys

from sequence_vault.settings import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))  # the fixture builders live with the tests
from tests.fixtures import builders

OUT = REPO_ROOT / "tests/fixtures/evaluation"
HEAVY = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVS"
LIGHT = "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIY"
ENZYME = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQ"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "standard_multi.fasta": (
            f">Ab1_heavy\n{HEAVY}\n>Ab1_light\n{LIGHT}\n>Enzyme_7\n{ENZYME}\n"
        ).encode(),
        "wrapped.fasta": (
            ">Enzyme_8 lowercase and wrapped\n"
            + "\n".join(ENZYME.lower()[i : i + 20] for i in range(0, len(ENZYME), 20))
            + "\n"
        ).encode(),
        "Ab2_heavy.txt": f"{HEAVY[:25]}\n{HEAVY[25:]}\n".encode(),
        "notes.txt": f"名称：Ab3_light\n{LIGHT}\n\nAb4 heavy:\n{HEAVY}\n".encode(),
        "truncated.txt": f"Ab5 partial\n{HEAVY[:30]}...\n".encode(),
        "report.docx": builders.docx(
            ["Antibody Ab6:", HEAVY[:24], HEAVY[24:], "", "Enzyme 9", ENZYME]
        ),
        "clones.xlsx": builders.xlsx(
            {"克隆": [["名称", "氨基酸序列"], ["Ab7", LIGHT], ["Ab8", HEAVY]]}
        ),
        "clones.csv": f"name,sequence\nAb9,{ENZYME}\n".encode(),
        "summary.pdf": builders.pdf(
            [[(72, 760, "Enzyme 10"), (72, 746, ENZYME[:40]), (72, 732, ENZYME[40:])]]
        ),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    manifest = {
        "set": "synthetic-dev",
        "files": [
            {
                "path": "standard_multi.fasta",
                "format": "fasta",
                "standard": True,
                "records": [
                    {"name": "Ab1_heavy", "sequence": HEAVY},
                    {"name": "Ab1_light", "sequence": LIGHT},
                    {"name": "Enzyme_7", "sequence": ENZYME},
                ],
            },
            {
                "path": "wrapped.fasta",
                "format": "fasta",
                "standard": True,
                "records": [{"name": "Enzyme_8", "sequence": ENZYME}],
            },
            {
                "path": "Ab2_heavy.txt",
                "format": "txt",
                "records": [{"name": "Ab2_heavy", "sequence": HEAVY}],
            },
            {
                "path": "notes.txt",
                "format": "txt",
                "records": [
                    {"name": "Ab3_light", "sequence": LIGHT},
                    {"name": "Ab4 heavy", "sequence": HEAVY},
                ],
            },
            {
                "path": "truncated.txt",
                "format": "txt",
                "records": [
                    {
                        "name": "Ab5 partial",
                        "sequence": HEAVY[:30] + "...",
                        "blocking_rules": ["QC05"],
                    }
                ],
            },
            {
                "path": "report.docx",
                "format": "docx",
                "records": [
                    {"name": "Antibody Ab6", "sequence": HEAVY},
                    {"name": "Enzyme 9", "sequence": ENZYME},
                ],
            },
            {
                "path": "clones.xlsx",
                "format": "xlsx",
                "records": [{"name": "Ab7", "sequence": LIGHT}, {"name": "Ab8", "sequence": HEAVY}],
            },
            {
                "path": "clones.csv",
                "format": "csv",
                "records": [{"name": "Ab9", "sequence": ENZYME}],
            },
            {
                "path": "summary.pdf",
                "format": "text_pdf",
                "records": [{"name": "Enzyme 10", "sequence": ENZYME}],
            },
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
