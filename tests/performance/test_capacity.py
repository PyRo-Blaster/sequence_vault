"""P7 capacity budgets (design, "Proposed Initial Capacity and Service Targets").

- Search: p95 below 1 second with 100,000 record versions and 10 concurrent queries.
- Processing: excluding queue time, p95 below 60 seconds for a 1 MB text file with 100
  records.

Results are printed and written to ``$SEQUENCE_VAULT_PERF_REPORT`` (default
``capacity-report.json`` in the pytest temporary directory), so they are recorded, not
assumed. Run with ``make performance``.
"""

import json
import os
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from sequence_vault.adapters.persistence.queries import SqlReadModel, decode_cursor
from sequence_vault.adapters.persistence.repositories import SqlUnitOfWorkFactory
from sequence_vault.adapters.storage.local import LocalObjectStore
from sequence_vault.application.authorization import Actor
from sequence_vault.application.queries import QueryService
from tests.integration.test_pipeline import Env
from tests.integration.world import load_registry

RECORDS = 50_000  # two versions each: 100,000 record versions
PROJECTS = 5
SEARCH_P95_BUDGET = 1.0
PROCESSING_P95_BUDGET = 60.0

SEED = """
INSERT INTO tenant VALUES ('perf', 'Capacity');
INSERT INTO app_user VALUES ('perf-user', 'perf', 'perf@corp', 'Perf');
INSERT INTO project (id, tenant_id, name)
    SELECT 'perf-p' || g, 'perf', 'Project ' || g FROM generate_series(1, :projects) g;
INSERT INTO project_member SELECT 'perf-p' || g, 'perf-user', 'viewer'
    FROM generate_series(1, :projects) g;
INSERT INTO sequence_entity (id, tenant_id, molecule_type, canonical_sequence, length, sha256)
    SELECT 'perf-e' || g, 'perf', 'protein', s, length(s),
           encode(sha256(convert_to(s, 'UTF8')), 'hex')
    FROM generate_series(1, 2 * :records) g,
         LATERAL (SELECT repeat('MKTAYIAKQR', 5 + g % 50)
                         || translate(g::text, '0123456789', 'ACDEFGHIKL') AS s) seq;
INSERT INTO record (id, tenant_id, project_id, name_key, display_name)
    SELECT 'perf-r' || g, 'perf', 'perf-p' || (1 + g % :projects),
           'antibody-' || g || '-' || (ARRAY['heavy', 'light', 'scfv', 'vhh'])[1 + g % 4],
           'Antibody-' || g || '-' || (ARRAY['Heavy', 'Light', 'scFv', 'VHH'])[1 + g % 4]
    FROM generate_series(1, :records) g;
INSERT INTO record_version (id, record_id, version_no, sequence_entity_id, is_current, created_by)
    SELECT 'perf-v' || g || '-1', 'perf-r' || g, 1, 'perf-e' || (2 * g - 1), false, 'perf-user'
    FROM generate_series(1, :records) g;
INSERT INTO record_version
    (id, record_id, version_no, sequence_entity_id, previous_version_id, is_current, created_by)
    SELECT 'perf-v' || g || '-2', 'perf-r' || g, 2, 'perf-e' || (2 * g), 'perf-v' || g || '-1',
           true, 'perf-user'
    FROM generate_series(1, :records) g;
ANALYZE;
"""


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100, method="inclusive")[94]


def record_result(tmp_path: Path, name: str, result: dict[str, Any]) -> None:
    path = Path(os.environ.get("SEQUENCE_VAULT_PERF_REPORT", tmp_path / "capacity-report.json"))
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing[name] = result
    path.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"\n{name}: {json.dumps(result)}")


def test_search_p95_with_100k_versions_and_10_concurrent_queries(
    engine: Engine, tmp_path: Path
) -> None:
    started = time.perf_counter()
    with engine.begin() as connection:
        for statement in SEED.split(";\n"):
            if statement.strip():
                connection.execute(text(statement), {"records": RECORDS, "projects": PROJECTS})
    seeded = time.perf_counter() - started
    with engine.connect() as connection:
        versions: int = connection.execute(text("SELECT count(*) FROM record_version")).scalar_one()
    assert versions == 2 * RECORDS

    queries = QueryService(
        SqlReadModel(engine),
        SqlUnitOfWorkFactory(engine),
        load_registry(),
        LocalObjectStore(tmp_path / "objects"),
    )
    actor = Actor("perf-user", "perf")
    rng = random.Random(7)

    def sequence_of(n: int) -> str:
        return "MKTAYIAKQR" * (5 + n % 50) + str(n).translate(
            str.maketrans("0123456789", "ACDEFGHIKL")
        )

    kinds = ("name_substring", "name_word", "exact_sequence", "length_range", "two_pages")

    def one_query(i: int) -> tuple[str, float]:
        kind = i % 5
        n = rng.randint(1, RECORDS)
        args: dict[str, Any] = {
            "project_id": None,
            "q": None,
            "sequence": None,
            "min_length": None,
            "max_length": None,
            "cursor": None,
            "limit": 50,
        }
        if kind == 0:
            args["q"] = f"body-{n}"
        elif kind == 1:
            args["q"] = rng.choice(["heavy", "vhh", "scfv"])
        elif kind == 2:
            args["sequence"] = sequence_of(2 * n)
        elif kind == 3:
            args["min_length"], args["max_length"] = 200, 260
        else:
            args["project_id"] = f"perf-p{1 + n % PROJECTS}"
        begin = time.perf_counter()
        items, cursor = queries.records(actor, **args)
        if kind == 4 and cursor:
            args["cursor"] = decode_cursor(cursor)
            queries.records(actor, **args)
        elapsed = time.perf_counter() - begin
        if kind == 2:
            assert [item["record_id"] for item in items] == [f"perf-r{n}"]
        return kinds[kind], elapsed

    for i in range(20):  # warm the cache and connection pool
        one_query(i)
    with ThreadPoolExecutor(max_workers=10) as pool:
        timed = list(pool.map(one_query, range(400)))
    samples = [elapsed for _, elapsed in timed]
    search_p95 = round(p95(samples), 4)
    result: dict[str, Any] = {
        "record_versions": versions,
        "concurrency": 10,
        "queries": len(samples),
        "p50_seconds": round(statistics.median(samples), 4),
        "p95_seconds": search_p95,
        "max_seconds": round(max(samples), 4),
        "budget_seconds": SEARCH_P95_BUDGET,
        "seed_seconds": round(seeded, 1),
        "p95_by_kind": {kind: round(p95([e for k, e in timed if k == kind]), 4) for kind in kinds},
    }
    record_result(tmp_path, "search", result)
    assert search_p95 < SEARCH_P95_BUDGET


def text_file(records: int, target_bytes: int) -> bytes:
    """Named sequences in a plain text file, about ``target_bytes`` long."""
    rng = random.Random(11)
    residues = "ACDEFGHIKLMNPQRSTVWY"
    per_record = (target_bytes // records - 40) * 60 // 61  # leave room for line breaks
    lines: list[str] = []
    for i in range(records):
        sequence = "".join(rng.choice(residues) for _ in range(per_record))
        lines += [
            f"Name: Construct-{i:03d}",
            *(sequence[k : k + 60] for k in range(0, per_record, 60)),
            "",
        ]
    return "\n".join(lines).encode()


@pytest.mark.parametrize("runs", [5])
def test_processing_p95_for_1mb_text_with_100_records(
    engine: Engine, tmp_path: Path, runs: int
) -> None:
    env = Env(engine, tmp_path)
    data = text_file(100, 1_000_000)
    assert 950_000 <= len(data) <= 1_000_000
    samples: list[float] = []
    for run in range(runs):
        task_id = env.upload(f"capacity-{run}.txt", data)
        begin = time.perf_counter()
        while env.worker.run_once():
            pass
        samples.append(time.perf_counter() - begin)
        assert env.task(task_id) == ("REVIEW_READY", None)
        with env.app.uow() as uow:
            row = uow.tasks.get(task_id)
            assert row is not None and row.current_run_id is not None
            assert len(uow.candidates.list_for_run(row.current_run_id)) == 100
    result = {
        "file_bytes": len(data),
        "records": 100,
        "runs": runs,
        "p50_seconds": round(statistics.median(samples), 2),
        "p95_seconds": round(p95(samples), 2),
        "max_seconds": round(max(samples), 2),
        "budget_seconds": PROCESSING_P95_BUDGET,
    }
    record_result(tmp_path, "processing", result)
    assert result["p95_seconds"] < PROCESSING_P95_BUDGET
