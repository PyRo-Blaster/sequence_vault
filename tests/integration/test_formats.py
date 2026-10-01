"""P6 acceptance: Word, Excel, CSV and PDF through the worker (T03, T04, T06, T07, T16)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.application.model_assist import ModelAnswer
from tests.fixtures import builders
from tests.integration.test_pipeline import Env

HEAVY = "EVQLVESGGGLVQPGGSLRLSCAASGFTFS"
LIGHT = "DIQMTQSPSSLSASVGDRVTITCRASQ"


@pytest.fixture
def env(engine: Engine, tmp_path: Path) -> Env:
    return Env(engine, tmp_path)


def summary(env: Env, task_id: str) -> list[tuple[str | None, str, list[str]]]:
    return [(c["name"], str(c["status"]), list(c["rules"])) for c in env.candidates(task_id)]


def test_t03_word_document_with_several_sequences(env: Env) -> None:
    data = builders.docx(["Antibody A1:", HEAVY[:15], HEAVY[15:], "", "Antibody B2", LIGHT])
    task_id = env.upload("results.docx", data)
    env.worker.run_until_idle()
    assert env.task(task_id) == ("REVIEW_READY", None)
    assert summary(env, task_id) == [
        ("Antibody A1", "NEEDS_REVIEW", ["QC08"]),  # joined across paragraphs: confirm continuity
        ("Antibody B2", "NEEDS_REVIEW", []),
    ]


def test_t04_chains_in_a_spreadsheet_need_a_chain_label(env: Env) -> None:
    data = builders.xlsx(
        {"Sheet1": [["Clone", "Heavy chain", "Light chain"], ["Ab1", HEAVY, LIGHT]]}
    )
    task_id = env.upload("chains.xlsx", data)
    env.worker.run_until_idle()
    assert summary(env, task_id) == [
        ("Ab1", "NEEDS_REVIEW", ["QC07"]),
        ("Ab1", "NEEDS_REVIEW", ["QC07"]),
    ]


def test_t07_tracked_changes_view_can_be_chosen_and_reparsed(env: Env) -> None:
    data = builders.docx(["Construct", [("t", "MKTAYIAKQRQISF"), ("ins", "VKSH"), ("del", "WWWW")]])
    task_id = env.upload("Construct.docx", data)
    env.worker.run_until_idle()
    (accepted,) = env.candidates(task_id)
    assert accepted["rules"] == ["QC08"]
    with env.app.uow() as uow:
        row = uow.candidates.get(str(accepted["id"]))
    assert row is not None and row.candidate.qc is not None
    assert row.candidate.qc.normalized is not None
    assert row.candidate.qc.normalized.sequence == "MKTAYIAKQRQISFVKSH"
    env.app.tasks.reprocess(env.alice, task_id, tracked_changes_view="original")
    env.worker.run_until_idle()
    (original,) = env.candidates(task_id)
    with env.app.uow() as uow:
        row = uow.candidates.get(str(original["id"]))
        task = uow.tasks.get(task_id)
    assert row is not None and row.candidate.qc is not None and row.candidate.qc.normalized
    assert row.candidate.qc.normalized.sequence == "MKTAYIAKQRQISFWWWW"
    assert task is not None and task.parse_options == {"tracked_changes_view": "original"}
    with env.app.engine.connect() as c:
        views: list[dict[str, str]] = list(
            c.execute(
                select(t.extraction_run.c.parse_options).order_by(t.extraction_run.c.generation)
            ).scalars()
        )
    assert [v["tracked_changes_view"] for v in views] == ["changes_accepted", "original"]


def test_t06_pdf_numbering_is_blocked_until_corrected(env: Env) -> None:
    page = [
        (72, 800, "Confidential draft - page 1"),
        (72, 700, "RSPO3 heavy chain"),
        (72, 686, "1 EVQLVESGGG LVQPGGSLRL"),
        (72, 672, "21 SCAASGFTFS SYAMS"),
    ]
    task_id = env.upload("RSPO3 heavy chain.pdf", builders.pdf([page]))
    env.worker.run_until_idle()
    ((name, status, rules),) = summary(env, task_id)
    assert (name, status) == ("RSPO3 heavy chain", "BLOCKED") and "QC03" in rules


def test_csv_upload_reaches_review(env: Env) -> None:
    task_id = env.upload("table.csv", f"name,sequence\nA1,{HEAVY}\n".encode())
    env.worker.run_until_idle()
    assert summary(env, task_id) == [("A1", "NEEDS_REVIEW", [])]


class Model:
    prompt_version = "extraction-v1"

    def answer(
        self, request: dict[str, Any], *, previous: str | None = None, repair: str | None = None
    ) -> ModelAnswer:
        span = next(c["id"] for c in request["span_candidates"] if c["preview"].startswith("EVQ"))
        name = next(c["id"] for c in request["name_candidates"] if c["value"] == "Ab7")
        return ModelAnswer(
            {
                "records": [
                    {
                        "span_ids": [span],
                        "name_ids": [name],
                        "molecule_type": "protein",
                        "association_status": "unambiguous",
                        "observations": [],
                    }
                ],
                "unresolved_block_ids": [],
            },
            None,
            "claude-opus-5-5",
        )


def test_model_assistance_is_recorded_on_the_run(env: Env) -> None:
    env.app.pipeline.model = Model()
    data = builders.docx(["Ab7", f"The heavy chain is {HEAVY} as expressed."])
    task_id = env.upload("notes.docx", data)
    env.worker.run_until_idle()
    assert summary(env, task_id) == [("Ab7", "NEEDS_REVIEW", [])]
    with env.app.engine.connect() as c:
        run = c.execute(select(t.extraction_run)).one()
    assert (run.model_version, run.prompt_version) == ("claude-opus-5-5", "extraction-v1")
