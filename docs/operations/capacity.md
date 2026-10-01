# Capacity measurements

Budgets come from the design ("Proposed Initial Capacity and Service Targets"). `make performance` runs `tests/performance/test_capacity.py`. The tests fail when a budget is missed and print their measurements; set `SEQUENCE_VAULT_PERF_REPORT=path.json` to keep them. CI runs them on every push.

| Budget | Target | Measured |
|---|---|---|
| Record search | p95 < 1 s with 100,000 record versions and 10 concurrent queries | p95 **0.29 s** (p50 0.09 s, max 0.80 s), 400 queries |
| Processing, excluding queue time | p95 < 60 s for a 1 MB text file with 100 records | p95 **2.8 s** (5 runs, 998 KB, 100 candidates each) |

**Environment.** Measured 2026-10-01 on a 4-vCPU x86_64 container with PostgreSQL 16 (`fsync=off`, defaults otherwise), with the API's query layer called directly. The parser sandbox, rule extraction and QC are included in processing time; the model is not (disabled by default).

## Search workload

The data set is 50,000 records in 5 projects, each with 2 versions (100,000 versions), and 100,000 sequence entities of 50–500 residues. Five query kinds run in equal shares across all of the user's projects, with a page size of 50:

| Query | p95 |
|---|---|
| Name substring (`body-12345`, trigram index) | 0.05 s |
| Common name word (`heavy`, a quarter of all records) | 0.19 s |
| Exact sequence (normalized, hashed) | 0.14 s |
| Length range (200–260) | 0.40 s |
| One project, first two pages | 0.06 s |

## Headroom and follow-ups

- **Length range** is the slowest query: it joins every current version before ordering by name. If production data or concurrency grows, add an index on `sequence_entity (length)`, or a covering index on current versions. Measure again before and after.
- **Exact sequence search** filters on `sequence_entity.sha256`, which is only the third column of the unique index. A `(sha256)` index would make it a point lookup. It is not needed at this size.
- **Before the pilot**, repeat both tests on production-like hardware, with `fsync` on, and through the HTTP API behind the proxy. Then update this table.
