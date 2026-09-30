# ADR 0003: Parser isolation and transactional task enqueue

Status: proposed; confirm when queue and deployment are selected. Basis: design v1.0, sections 3 and 9.

Section 9 requires limiting parser memory, time, network and filesystem access. The scaffold places parsers as adapters inside the worker process, which also holds database, object-storage and model credentials. A parser exploit in a DOCX, XLSX or PDF library would then run with those credentials, and in-process limits cannot be enforced per file.

Section 8 requires `POST /v1/uploads/{id}/complete` to create the processing task idempotently. Writing the database row and publishing to an external queue are two systems; a crash between them loses or duplicates work.

Decisions:

- Run each parse in a separate sandboxed process (or container) with no credentials, no network, a read-only copy of one source file, and CPU, memory, time and output-size limits. It returns DocumentIR through a bounded channel; the worker validates the result against the schema before persisting it. The `adapters/parsers` package holds the parser code and the sandbox launcher; only the launcher runs in the worker.
- Enqueue through a transactional outbox: the completion request writes the task and an outbox row in one PostgreSQL transaction, keyed by file ID, and a relay publishes to the existing queue. Workers treat delivery as at-least-once and claim tasks through the database lease. At the design's initial load (10 concurrent extraction tasks), a PostgreSQL job table with `SKIP LOCKED` leases is an acceptable queue if no existing reliable queue is available.

Consequences: parser crashes and limit violations become explicit `FAILED` stage results rather than worker failures. Deployment must provide a sandbox runtime. Queue selection no longer affects the idempotency guarantee.
