"""FastAPI application factory and /v1 routes (packages/contracts/api/README.md)."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from sequence_vault.adapters.contracts import Policy
from sequence_vault.adapters.persistence.queries import decode_cursor, encode_cursor
from sequence_vault.api import errors
from sequence_vault.api.auth import Authenticator, Principal, RateLimiter, guard
from sequence_vault.api.errors import ApiError
from sequence_vault.application.commit import CommitItem, CommitService
from sequence_vault.application.processing import TaskService
from sequence_vault.application.queries import QueryService, ReadModel
from sequence_vault.application.review import ReviewService
from sequence_vault.application.uploads import UploadService
from sequence_vault.domain.spans import SequenceSpan
from sequence_vault.settings import Settings

Json = dict[str, Any]


class UploadRequest(BaseModel):
    project_id: str
    file_name: str = Field(min_length=1, max_length=255)
    byte_count: int = Field(ge=0)
    sha256: str


class SpanModel(BaseModel):
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    order: int = Field(ge=1)


class SequenceEdit(BaseModel):
    reason: str = Field(min_length=1)
    spans: list[SpanModel] | None = None
    typed_sequence: str | None = None
    fragment: bool = False


class CandidatePatch(BaseModel):
    name: str | None = None
    sequence: SequenceEdit | None = None


class ResolutionRequest(BaseModel):
    revision: int = Field(ge=1)
    rule_id: str
    resolution: str


class RevisionRequest(BaseModel):
    revision: int = Field(ge=1)


class ReviewRequest(BaseModel):
    candidate_id: str
    revision: int = Field(ge=1)
    decision: Literal["approved", "rejected"]


class CommitItemModel(BaseModel):
    candidate_id: str
    revision: int = Field(ge=1)


class CommitRequest(BaseModel):
    items: list[CommitItemModel] = Field(min_length=1, max_length=1000)


def _revision(if_match: str | None) -> int:
    value = (if_match or "").strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise ApiError(428, "revision_required", 'Send the candidate revision as If-Match: "<n>".')
    return int(value)


def _cursor(value: str | None) -> list[Any] | None:
    try:
        return decode_cursor(value)
    except ValueError as error:
        raise ApiError(400, "malformed_request", str(error)) from error


@dataclass(frozen=True)
class ApiServices:
    settings: Settings
    policy: Policy
    read: ReadModel
    queries: QueryService
    uploads: UploadService
    reviews: ReviewService
    commits: CommitService
    tasks: TaskService


def create_app(container: ApiServices) -> FastAPI:
    queries = container.queries
    authenticate = Authenticator(container.settings, container.read)
    max_bytes = container.policy.limits.max_file_bytes

    app = FastAPI(
        title="Sequence Vault API",
        version="1.0.0",
        description="Protein sequence import, evidence review and quality control.",
    )
    errors.install(app)
    app.middleware("http")(guard(authenticate, RateLimiter()))

    User = Annotated[Principal, Depends(authenticate)]

    @app.get("/v1/health", tags=["system"])
    def health() -> Json:
        return {"status": "ok"}

    @app.get("/v1/me", tags=["system"])
    def me(user: User) -> Json:
        return queries.me(user.actor, user.display_name) | {
            "limits": {
                "max_file_bytes": max_bytes,
                "max_files_per_batch": container.policy.limits.max_files_per_batch,
            },
            "accepted_extensions": sorted(container.uploads.extensions),
        }

    # -- uploads ----------------------------------------------------------------------

    @app.post("/v1/uploads", status_code=201, tags=["uploads"])
    def create_upload(body: UploadRequest, user: User) -> Json:
        row = container.uploads.create(
            user.actor, body.project_id, body.file_name, body.byte_count, body.sha256
        )
        return {
            "file_id": row.file_id,
            "upload_url": f"/v1/uploads/{row.file_id}/content",
            "file_name": row.original_name,
        }

    @app.put("/v1/uploads/{file_id}/content", status_code=204, tags=["uploads"])
    async def upload_content(file_id: str, request: Request, user: User) -> Response:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ApiError(413, "file_too_large", f"Files are limited to {max_bytes} bytes.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                raise ApiError(413, "file_too_large", f"Files are limited to {max_bytes} bytes.")
            chunks.append(chunk)
        await run_in_threadpool(
            container.uploads.put_content, user.actor, file_id, b"".join(chunks)
        )
        return Response(status_code=204)

    @app.post("/v1/uploads/{file_id}/complete", status_code=202, tags=["uploads"])
    def complete_upload(file_id: str, user: User) -> Json:
        row = container.uploads.complete(user.actor, file_id)
        return {"task_id": row.task.task_id, "status": row.task.status.value}

    @app.get("/v1/files/{file_id}/content", tags=["uploads"])
    def original(file_id: str, user: User) -> Response:
        data, name = queries.original(user.actor, file_id)
        safe = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in name)
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{safe}"'},
        )

    # -- jobs -------------------------------------------------------------------------

    @app.get("/v1/jobs", tags=["jobs"])
    def list_jobs(
        user: User,
        project_id: str,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> Json:
        items, next_cursor = queries.tasks(user.actor, project_id, _cursor(cursor), limit)
        return {"items": items, "next_cursor": next_cursor}

    @app.get("/v1/jobs/{task_id}", tags=["jobs"])
    def get_job(task_id: str, user: User) -> Json:
        return queries.task(user.actor, task_id)

    @app.post("/v1/jobs/{task_id}/cancel", tags=["jobs"])
    def cancel_job(task_id: str, user: User) -> Json:
        row = container.tasks.cancel(user.actor, task_id)
        return {"task_id": task_id, "status": row.task.status.value}

    @app.post("/v1/jobs/{task_id}/reprocess", status_code=202, tags=["jobs"])
    def reprocess_job(task_id: str, user: User) -> Json:
        row = container.tasks.reprocess(user.actor, task_id)
        return {"task_id": task_id, "status": row.task.status.value, "generation": row.generation}

    @app.get("/v1/jobs/{task_id}/candidates", tags=["candidates"])
    def list_candidates(
        task_id: str,
        user: User,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> Json:
        decoded = _cursor(cursor)
        offset = int(decoded[0]) if decoded else 0
        items, next_offset = queries.candidates(user.actor, task_id, offset, limit)
        return {
            "items": items,
            "next_cursor": None if next_offset is None else encode_cursor([next_offset]),
        }

    @app.get("/v1/jobs/{task_id}/document", tags=["candidates"])
    def document(task_id: str, user: User) -> Json:
        return queries.document(user.actor, task_id)

    # -- candidates and reviews ---------------------------------------------------------

    @app.get("/v1/candidates/{candidate_id}", tags=["candidates"])
    def get_candidate(candidate_id: str, user: User, response: Response) -> Json:
        result = queries.candidate(user.actor, candidate_id)
        response.headers["ETag"] = f'"{result["candidate"]["revision"]}"'
        return result

    @app.patch("/v1/candidates/{candidate_id}", tags=["candidates"])
    def patch_candidate(
        candidate_id: str,
        body: CandidatePatch,
        user: User,
        response: Response,
        if_match: Annotated[str | None, Header()] = None,
    ) -> Json:
        revision = _revision(if_match)
        if (body.name is None) == (body.sequence is None):
            raise ApiError(422, "invalid_request", "Change either the name or the sequence.")
        if body.name is not None:
            container.reviews.rename(user.actor, candidate_id, revision, body.name)
        else:
            edit = body.sequence
            assert edit is not None
            spans = tuple(
                SequenceSpan(s.block_id, s.start, s.end, s.order) for s in edit.spans or []
            )
            container.reviews.revise_sequence(
                user.actor,
                candidate_id,
                revision,
                reason=edit.reason,
                spans=spans,
                typed_sequence=edit.typed_sequence,
                fragment=edit.fragment,
            )
        result = queries.candidate(user.actor, candidate_id)
        response.headers["ETag"] = f'"{result["candidate"]["revision"]}"'
        return result

    @app.post("/v1/candidates/{candidate_id}/resolutions", tags=["candidates"])
    def resolve(candidate_id: str, body: ResolutionRequest, user: User) -> Json:
        container.reviews.resolve(
            user.actor, candidate_id, body.revision, body.rule_id, body.resolution
        )
        return queries.candidate(user.actor, candidate_id)

    @app.post("/v1/candidates/{candidate_id}/archive", tags=["candidates"])
    def archive(candidate_id: str, body: RevisionRequest, user: User) -> Json:
        container.reviews.archive(user.actor, candidate_id, body.revision)
        return queries.candidate(user.actor, candidate_id)

    @app.post("/v1/reviews", tags=["candidates"])
    def review(body: ReviewRequest, user: User) -> Json:
        container.reviews.decide(
            user.actor, body.candidate_id, body.revision, approve=body.decision == "approved"
        )
        return queries.candidate(user.actor, body.candidate_id)

    @app.post("/v1/commits", tags=["records"])
    def commit(
        body: CommitRequest, user: User, idempotency_key: Annotated[str | None, Header()] = None
    ) -> Json:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ApiError(400, "idempotency_key_required", "Send an Idempotency-Key header.")
        outcomes = container.commits.commit(
            user.actor,
            idempotency_key,
            [CommitItem(item.candidate_id, item.revision) for item in body.items],
        )
        results = [
            {
                "candidate_id": o.candidate_id,
                "status": o.status.value,
                "reason": o.reason,
                "record_id": o.record_id,
                "record_version_id": o.record_version_id,
            }
            for o in outcomes
        ]
        counts: dict[str, int] = {}
        for outcome in outcomes:
            counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
        return {"results": results, "counts": counts}

    # -- records ----------------------------------------------------------------------

    @app.get("/v1/records", tags=["records"])
    def list_records(
        user: User,
        project_id: str | None = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        sequence: Annotated[str | None, Query(max_length=200_000)] = None,
        min_length: Annotated[int | None, Query(ge=0)] = None,
        max_length: Annotated[int | None, Query(ge=0)] = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> Json:
        items, next_cursor = queries.records(
            user.actor,
            project_id=project_id,
            q=q,
            sequence=sequence,
            min_length=min_length,
            max_length=max_length,
            cursor=_cursor(cursor),
            limit=limit,
        )
        return {"items": items, "next_cursor": next_cursor}

    @app.get("/v1/records/{record_id}", tags=["records"])
    def get_record(record_id: str, user: User) -> Json:
        record = queries.record(user.actor, record_id)
        record.pop("tenant_id", None)
        return record

    @app.get("/v1/records/{record_id}/export", tags=["records"])
    def export(record_id: str, user: User, version: Annotated[int, Query(ge=1)]) -> Response:
        text, filename = queries.export_fasta(user.actor, record_id, version)
        return Response(
            text,
            media_type="text/x-fasta; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app
