# Database migrations

Store ordered, reviewed PostgreSQL migrations here after selecting migration tooling. No tables have been created by the scaffold.

Model tenants, projects and permissions; source_file; extraction_run; immutable document_block; candidate revisions; qc_issue; review; sequence_entity; record/version; provenance; and audit. Add unique constraints on `(tenant_id, type, sha256)`, `(project_id, name_key)`, and `(record_id, version_no)`. Compare full canonical content after hash matching. Never overwrite a published sequence version.

Review authorization boundaries, transaction rollback, idempotency storage, foreign keys, and concurrent name/version creation alongside every relevant migration. Include a safe rollout and rollback/data-preservation plan.
