# Workflow diagrams

Visual companion to the [design specification](design/Protein_Sequence_App_Design_v1.0_EN.md) and [architecture](architecture.md). Diagrams reflect [ADR 0002](decisions/0002-extraction-contract-boundaries.md) and the proposed [ADR 0003](decisions/0003-parser-isolation-and-task-enqueue.md). The specification remains the source of truth.

## 1. System flow and trust boundaries

Files move from the browser through isolated storage, a sandboxed parser and a narrow model gateway before anything reaches the review screen. Each box is a separate process or store, and each arrow is the only data that crosses that boundary.

```mermaid
flowchart TB
  subgraph Browser["Browser (Chinese UI)"]
    UPL[Upload page]
    REV[Review workspace]
    SRCH[Search and export]
  end
  subgraph API["API process"]
    US[Upload service]
    RS[Review service]
    CS[Commit service]
    QS[Search service]
  end
  subgraph Store["Storage"]
    OBJ[("Object storage: originals, evidence")]
    PG[("PostgreSQL: runs, blocks, candidates, published records")]
  end
  subgraph Worker["Worker process"]
    ORC[Stage orchestrator]
    QC[Reconstruction and QC]
  end
  Q{{Existing queue}}
  SB[["Parser sandbox: no credentials, no network"]]
  GW[["Model gateway: blocks in, spans out"]]
  UPL -->|file bytes| US
  US -->|generated object key| OBJ
  US -->|task and outbox row in one transaction| PG
  PG -->|outbox relay| Q
  Q -->|at-least-once delivery| ORC
  ORC -->|one source file| SB
  SB -->|DocumentIR| ORC
  ORC -->|authorized blocks| GW
  GW -->|names, spans, observations| ORC
  ORC --> QC
  QC -->|candidates and issues| PG
  REV <-->|edit, resolve, approve| RS
  RS <--> PG
  REV -->|commit approved revisions| CS
  CS -->|per-item transaction| PG
  SRCH --> QS
  QS -->|authorized records only| PG
```

- Only the commit service writes published records. The model gateway has no database, shell, search or URL access.
- The parser sandbox and transactional outbox come from ADR 0003, which is still a proposal.

## 2. File task lifecycle

Every uploaded file is one task. It moves forward one stage at a time and ends in exactly one terminal state. A task stays in review while any candidate is still waiting for content.

```mermaid
stateDiagram-v2
  [*] --> UPLOADED
  UPLOADED --> SCANNING: byte count and hash verified
  SCANNING --> UNSUPPORTED: detected type not allowed
  SCANNING --> FAILED: infected or scanner unavailable
  SCANNING --> PARSING: clean
  PARSING --> FAILED: corrupt or over limit
  PARSING --> EXTRACTING: DocumentIR stored
  EXTRACTING --> VALIDATING: extraction result stored
  VALIDATING --> REVIEW_READY: candidates created
  REVIEW_READY --> COMPLETED: all items committed, rejected or archived
  COMPLETED --> [*]
  UNSUPPORTED --> [*]
  FAILED --> [*]
  note right of REVIEW_READY
    Any stage can move to CANCELLED.
    Late results after cancellation cannot commit.
  end note
```

- Transient errors retry up to 3 times with exponential backoff and jitter. Deterministic parse failures are not retried.
- Workers hold a lease with heartbeats, so a crashed worker's task is picked up again and duplicate delivery is harmless.

## 3. Two-step extraction

Rules find the obvious structure first. The model only decides which name goes with which span, and answers with locations. Software then copies the characters out of the immutable document, so a sequence is never typed by the model.

```mermaid
sequenceDiagram
  participant W as Worker
  participant P as Parser sandbox
  participant R as Rules
  participant M as Model gateway
  participant V as Output validator
  participant C as Reconstruction and QC
  W->>P: source file and parse options
  P-->>W: DocumentIR blocks with code-point offsets
  W->>R: blocks
  R-->>W: FASTA records, residue runs, table regions
  W->>M: authorized blocks, chunked by record boundaries
  M-->>W: names, block spans, order, observations
  W->>V: extraction result
  alt schema or reference check fails
    V->>M: one controlled repair
    M-->>V: repaired result
    V-->>W: still invalid, route to human handling
  end
  W->>C: validated spans
  C->>C: copy characters from IR, join by order
  C-->>W: raw text, normalized sequence, QC issues
```

- The model never assigns candidate IDs, QC rules or severities (ADR 0002). Its self-reported confidence is not an acceptance signal.
- If the model endpoint is not approved, the AI step is disabled and rules plus manual entry still work.

## 4. Quality control

Every rule runs on every candidate. The worst severity found sets the candidate's status. BLOCK issues can only be cleared by one of the rule's listed resolutions; there is no Ignore button.

```mermaid
flowchart LR
  S[Reconstructed sequence] --> ALL[Run every QC rule]
  ALL --> BLK["BLOCK: QC01 empty or out of range, QC03 invalid characters, QC05 truncation"]
  ALL --> REV["REVIEW: QC04 extended residues, QC06 asterisks and gaps, QC07 name mapping, QC08 coverage risk, QC09 same name new sequence, QC11 molecule type"]
  ALL --> INF["INFO: QC02 whitespace and case, QC10 identical sequence exists"]
  BLK --> SB[Candidate BLOCKED]
  REV --> SN[Candidate NEEDS_REVIEW]
  INF --> SN
```

| Rule | Severity | Allowed resolutions |
| --- | --- | --- |
| QC01 | BLOCK | `correct_evidence_reference`, `mark_pending_content` |
| QC02 | INFO | `automatic_normalization` |
| QC03 | BLOCK | `correct_input`, `apply_position_numbering_rule`, `provide_source` |
| QC04 | REVIEW | `confirm_residue_semantics` |
| QC05 | BLOCK | `re_extract`, `provide_source`, `register_fragment` |
| QC06 | REVIEW | `apply_explicit_transformation`, `correct_input` |
| QC07 | REVIEW | `select_name`, `split_candidate`, `reassociate_name` |
| QC08 | REVIEW | `confirm_source_reviewed`, `reparse_with_selected_view`, `correct_input` |
| QC09 | REVIEW | `create_new_version`, `rename`, `cancel` |
| QC10 | INFO | `reuse_entity` |
| QC11 | REVIEW | `confirm_molecule_type`, `reject` |

Resolutions come from `config/qc-rules.v1.json`.

## 5. Candidate lifecycle

A candidate is one name and sequence found in one extraction run. Approval belongs to a specific revision, so any edit sends the candidate back through QC and review.

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> BLOCKED: any BLOCK issue
  DRAFT --> NEEDS_REVIEW: no BLOCK issue
  BLOCKED --> NEEDS_REVIEW: edit or allowed resolution
  NEEDS_REVIEW --> APPROVED: reviewer approves this revision
  APPROVED --> NEEDS_REVIEW: edited, approval void
  APPROVED --> BLOCKED: edit adds BLOCK issue
  APPROVED --> COMMITTED: commit transaction succeeds
  BLOCKED --> PENDING_CONTENT: name found, sequence missing
  PENDING_CONTENT --> ARCHIVED: explicitly archived
  NEEDS_REVIEW --> REJECTED
  BLOCKED --> REJECTED
  COMMITTED --> [*]
  REJECTED --> [*]
  ARCHIVED --> [*]
  note right of APPROVED
    Re-extraction moves every uncommitted
    candidate of the old run to SUPERSEDED.
    Approvals never carry over to a new run.
  end note
```

- Editing a sequence needs a reason and shows a character-level diff. The candidate's origin becomes manual_revision.
- A fragment can be registered only for the continuous sequence visible in the source, with completeness set to fragment.

## 6. Review and commit

Edits use optimistic locking on the revision number. Commits run one transaction per candidate, and every check is repeated inside that transaction, so a stale approval or a revoked permission cannot slip through.

```mermaid
sequenceDiagram
  actor U as Uploader
  actor V as Reviewer
  participant A as API
  participant D as PostgreSQL
  U->>A: PATCH candidate, If-Match revision 3
  A->>D: is revision still 3?
  alt someone saved first
    A-->>U: 409 conflict, refresh and compare
  else revision matches
    A->>D: save revision 4, void approval, rerun QC
    A-->>U: revision 4 with current issues
  end
  V->>A: POST reviews, approve revision 4
  A->>D: store approver and approved revision
  V->>A: POST commits with Idempotency-Key
  loop each candidate in its own transaction
    A->>D: recheck permission, scan status, cancellation, revision, approval, QC version
    A->>D: find or create sequence entity, add record version, provenance, audit
    A-->>V: COMMITTED, ALREADY_COMMITTED, CONFLICT or FAILED
  end
```

- The idempotency key is bound to the candidate ID and approved revision, so a retry returns the same result instead of a second version.
- Any failed check rolls back that one item only. The screen shows partial success as partial.

## 7. Duplicate and version decisions

Sequence entities are shared within a tenant; records and names belong to a project. Nothing published is ever overwritten.

```mermaid
flowchart TD
  A[Approved candidate] --> B{"Sequence with same tenant, type and SHA-256?"}
  B -- no --> N[Create sequence entity]
  B -- hash match --> C{Full sequence identical?}
  C -- yes --> E[Reuse sequence entity, QC10]
  C -- no --> N
  E --> F{"Record with this name_key in the project?"}
  N --> F
  F -- no --> G[Create record, version 1]
  F -- yes --> H{Current version has the same sequence?}
  H -- yes --> I[Attach provenance, no new version]
  H -- no --> J{"Reviewer's QC09 decision"}
  J -- new version --> K[Add next version, mark previous superseded]
  J -- rename --> G
  J -- cancel --> L[Nothing written]
```

- name_key is the trimmed, case-folded name. Original capitalization is kept for display.
- Reusing an entity across projects never reveals that another project holds it. Access follows the project's own record.
- A version is never inferred from v2 in a filename.
