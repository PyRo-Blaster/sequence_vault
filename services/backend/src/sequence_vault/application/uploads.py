"""Upload sessions: declare, upload bytes, complete (design section 8, /v1/uploads)."""

import hashlib
import re
import uuid
from dataclasses import replace
from pathlib import PurePath

from sequence_vault.application.authorization import Action, Actor, authorize
from sequence_vault.application.errors import Conflict, InvalidRequest, LimitExceeded, NotFound
from sequence_vault.application.ports import (
    ConcurrentUpdate,
    FileRow,
    ObjectStore,
    TaskRow,
    UnitOfWork,
    UnitOfWorkFactory,
)
from sequence_vault.domain.task import FileTask, TaskStatus

FORMAT_EXTENSIONS: dict[str, frozenset[str]] = {
    "fasta": frozenset({".fasta", ".fa", ".faa", ".fas"}),
    "txt": frozenset({".txt", ".seq"}),
    "csv": frozenset({".csv", ".tsv"}),
    "xlsx": frozenset({".xlsx"}),
    "docx": frozenset({".docx"}),
    "text_pdf": frozenset({".pdf"}),
}


def accepted_extensions(enabled_formats: frozenset[str]) -> frozenset[str]:
    """Extensions offered for upload. Content detection still decides the real format."""
    extensions = {ext for fmt in enabled_formats for ext in FORMAT_EXTENSIONS.get(fmt, ())}
    if "fasta" in enabled_formats or "txt" in enabled_formats:
        extensions |= FORMAT_EXTENSIONS["fasta"] | FORMAT_EXTENSIONS["txt"]
    return frozenset(extensions)


_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_file_name(name: str) -> str:
    """Display-only file name: last path component, no control characters."""
    base = PurePath(name.replace("\\", "/")).name.strip()
    if not base or _CONTROL.search(base) or len(base) > 255:
        raise InvalidRequest("The file name is not acceptable.", code="invalid_file_name")
    return base


class UploadService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        store: ObjectStore,
        max_bytes: int,
        extensions: frozenset[str],
    ) -> None:
        self.uow_factory = uow_factory
        self.store = store
        self.max_bytes = max_bytes
        self.extensions = extensions

    def create(
        self, actor: Actor, project_id: str, file_name: str, byte_count: int, sha256: str
    ) -> FileRow:
        name = clean_file_name(file_name)
        if PurePath(name).suffix.lower() not in self.extensions:
            raise InvalidRequest(
                "This file type is not accepted. Supported: " + ", ".join(sorted(self.extensions)),
                code="unsupported_format",
            )
        if byte_count < 1:
            raise InvalidRequest("The file is empty.", code="empty_file")
        if byte_count > self.max_bytes:
            raise LimitExceeded(
                f"Files are limited to {self.max_bytes} bytes.", code="file_too_large"
            )
        if not _SHA256.match(sha256):
            raise InvalidRequest("sha256 must be 64 lowercase hex characters.")
        with self.uow_factory() as uow:
            authorize(uow.members.roles(actor.user_id, project_id), Action.UPLOAD)
            file_id = f"file_{uuid.uuid4().hex}"
            row = FileRow(
                file_id=file_id,
                tenant_id=actor.tenant_id,
                project_id=project_id,
                uploaded_by=actor.user_id,
                original_name=name,
                declared_bytes=byte_count,
                declared_sha256=sha256,
                byte_count=None,
                sha256=None,
                object_key=f"sources/{actor.tenant_id}/{file_id}",
                detected_type=None,
                security_status="awaiting_upload",
            )
            uow.files.create(row)
            uow.audit.record(
                actor.tenant_id,
                actor.user_id,
                "file.declared",
                "file",
                file_id,
                {"bytes": byte_count},
            )
            uow.commit()
            return row

    def _file(self, uow: UnitOfWork, actor: Actor, file_id: str, action: Action) -> FileRow:
        row = uow.files.get(file_id)
        if row is None or row.tenant_id != actor.tenant_id:
            raise NotFound("File not found.")
        authorize(uow.members.roles(actor.user_id, row.project_id), action)
        return row

    def put_content(self, actor: Actor, file_id: str, data: bytes) -> FileRow:
        with self.uow_factory() as uow:
            row = self._file(uow, actor, file_id, Action.UPLOAD)
        if row.security_status not in {"awaiting_upload", "uploaded"}:
            raise Conflict("The upload is already complete.", code="upload_complete")
        if len(data) > row.declared_bytes or len(data) > self.max_bytes:
            raise LimitExceeded("The content is larger than declared.", code="file_too_large")
        self.store.put(row.object_key, data)
        digest = hashlib.sha256(data).hexdigest()
        with self.uow_factory() as uow:
            uow.files.mark_uploaded(file_id, len(data), digest)
            uow.commit()
        return replace(row, byte_count=len(data), sha256=digest, security_status="uploaded")

    def complete(self, actor: Actor, file_id: str) -> TaskRow:
        """Verify the bytes and enqueue scanning. Repeating it returns the same task."""
        try:
            return self._complete(actor, file_id)
        except ConcurrentUpdate:
            with self.uow_factory() as uow:
                existing = uow.tasks.get_by_file(file_id)
            if existing is None:
                raise
            return existing

    def _complete(self, actor: Actor, file_id: str) -> TaskRow:
        with self.uow_factory() as uow:
            row = self._file(uow, actor, file_id, Action.UPLOAD)
            existing = uow.tasks.get_by_file(file_id)
            if existing is not None:
                return existing
            if row.security_status != "uploaded" or row.sha256 is None:
                raise Conflict("Upload the file content first.", code="content_missing")
            if row.byte_count != row.declared_bytes or row.sha256 != row.declared_sha256:
                raise InvalidRequest(
                    "The uploaded bytes do not match the declared size and SHA-256.",
                    code="checksum_mismatch",
                )
            task = FileTask(f"task_{uuid.uuid4().hex}").advance(TaskStatus.UPLOADED)
            task_row = TaskRow(task=task, file_id=file_id, current_run_id=None, generation=1)
            uow.tasks.create(task_row)
            uow.jobs.enqueue(task.task_id, 1, TaskStatus.SCANNING.value)
            uow.audit.record(
                actor.tenant_id,
                actor.user_id,
                "file.uploaded",
                "file",
                file_id,
                {"task_id": task.task_id},
            )
            uow.commit()
            return task_row
