# API implementation catalog

Draft transport contract from design v1.0, section 8. Implement OpenAPI from the selected API framework and check it against this catalog.

| Method | Path | Required behavior |
| --- | --- | --- |
| POST | `/v1/uploads` | Authorize project and create upload session with file ID |
| POST | `/v1/uploads/{id}/complete` | Verify byte count/hash; idempotently enqueue; return 202 |
| GET | `/v1/jobs/{id}` | Stage/status/counts and safe error summary |
| GET | `/v1/jobs/{id}/candidates` | Authorized, paginated candidates with issues |
| PATCH | `/v1/candidates/{id}` | `If-Match` revision; increment revision, invalidate approval, revalidate |
| POST | `/v1/reviews` | Reviewer permission and explicit approved/rejected revision |
| POST | `/v1/commits` | Approved revisions and `Idempotency-Key`; atomic per-item results |
| GET | `/v1/records` | Authorized filters and cursor pagination |
| GET | `/v1/records/{id}/export` | Explicit version, authorized FASTA, escaped header |

Errors include `code`, `message`, `request_id`, `details`, and `retryable`. Use 400 malformed, 403 forbidden, 409 revision/business conflict, 413 limits, 422 unacceptable content, and 429 rate limit. Batch commits return COMMITTED, ALREADY_COMMITTED, CONFLICT, or FAILED per item. Reauthorize originals and evidence before issuing short-lived links.
