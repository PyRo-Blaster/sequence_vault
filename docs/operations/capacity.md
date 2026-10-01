# Capacity measurements

Budgets come from the design ("Proposed Initial Capacity and Service Targets"). `make performance` runs `tests/performance/test_capacity.py`. The tests fail when a budget is missed and print their measurements; set `SEQUENCE_VAULT_PERF_REPORT=path.json` to keep them. CI runs them on every push.

| Budget | Target | Measured |
|---|---|---|
| Record search | p95 < 1 s with 100,000 record versions and 10 concurrent queries | p95 **0.10 s** (p50 0.05 s, max 0.29 s), 400 queries |
| Processing, excluding queue time | p95 < 60 s for a 1 MB text file with 100 records | p95 **2.9 s** (5 runs, 998 KB, 100 candidates each) |

**Environment.** Measured 2026-10-01 on a 4-vCPU x86_64 container with PostgreSQL 16 (`fsync=off`, defaults otherwise), with the API's query layer called directly. The parser sandbox, rule extraction and QC are included in processing time; the model is not (disabled by default).

## Search workload

The data set is 50,000 records in 5 projects, each with 2 versions (100,000 versions), and 100,000 sequence entities of 50–500 residues. Five query kinds run in equal shares across all of the user's projects, with a page size of 50.

| Query | p95 before 0004 (4 vCPU) | p95 before 0004 (CI, 2 vCPU) | p95 after 0004 (4 vCPU) |
|---|---|---|---|
| Name substring (`body-12345`, trigram index) | 0.05 s | 0.08 s | 0.07 s |
| Common name word (`heavy`, a quarter of all records) | 0.19 s | 0.59 s | 0.06 s |
| Exact sequence (normalized, hashed) | 0.14 s | 0.29 s | 0.08 s |
| Length range (200–260) | 0.40 s | **1.39 s** | 0.07 s |
| One project, first two pages | 0.06 s | 0.04 s | 0.13 s |
| **All queries** | 0.29 s | **1.21 s (budget missed)** | **0.10 s** |

**What changed.** The first CI run missed the budget on a 2-vCPU runner. Search orders by `(name_key, id)` across several projects, and the only name index was `(project_id, name_key)`, which cannot serve that order. So every match was joined, sorted (spilling to disk) and then cut to one page. Migration 0004 adds two indexes:

- `record (name_key, id)`: the planner walks records in result order and stops after one page (`EXPLAIN ANALYZE`: 65 ms → 1.2 ms for the length range, 34 ms → 0.3 ms for a common word);
- `sequence_entity (sha256)`: exact-sequence search becomes a point lookup.

## Follow-ups

- **Before the pilot**, repeat both tests on production-like hardware, with `fsync` on, and through the HTTP API behind the proxy. Then update this table.
- **Rare filters.** A filter that matches very few records (for example, a length range nobody uses) makes the in-order walk read many records before it fills a page. If such queries matter, add a partial index or a dedicated plan.
