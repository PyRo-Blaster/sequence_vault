"""Composition root: build adapters and services from Settings."""

from dataclasses import dataclass
from functools import partial

from sqlalchemy import Engine, create_engine

from sequence_vault.adapters.ai.gateway import AnthropicLocator, build_client
from sequence_vault.adapters.contracts import Policy, load_policy, load_registry, schema_errors
from sequence_vault.adapters.parsers.registry import enabled_formats
from sequence_vault.adapters.parsers.sandbox import SandboxedParser
from sequence_vault.adapters.persistence.jobs import JobQueue
from sequence_vault.adapters.persistence.queries import SqlReadModel
from sequence_vault.adapters.persistence.repositories import SqlUnitOfWorkFactory
from sequence_vault.adapters.security.clamd import ClamdScanner, DevelopmentScanner
from sequence_vault.adapters.security.filetype import ContentTypeDetector
from sequence_vault.adapters.storage.local import LocalObjectStore
from sequence_vault.adapters.storage.s3 import S3ObjectStore
from sequence_vault.api.app import ApiServices
from sequence_vault.application.commit import CommitService
from sequence_vault.application.model_assist import LocatorModel
from sequence_vault.application.ports import ObjectStore, Scanner
from sequence_vault.application.processing import Pipeline, PipelineLimits, TaskService
from sequence_vault.application.queries import QueryService
from sequence_vault.application.review import ReviewService
from sequence_vault.application.uploads import UploadService, accepted_extensions
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.settings import Settings


@dataclass
class Container:
    settings: Settings
    engine: Engine
    uow: SqlUnitOfWorkFactory
    registry: QcRegistry
    policy: Policy
    store: ObjectStore
    scanner: Scanner
    queue: JobQueue
    pipeline: Pipeline
    uploads: UploadService
    reviews: ReviewService
    commits: CommitService
    tasks: TaskService


def build_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "local":
        return LocalObjectStore(settings.local_storage_dir)
    if not settings.s3_bucket:
        raise ValueError("SEQUENCE_VAULT_OBJECT_STORAGE_BUCKET is required for S3 storage.")
    return S3ObjectStore(
        settings.s3_bucket,
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
    )


def build_scanner(settings: Settings) -> Scanner:
    if settings.scanner == "development":
        return DevelopmentScanner()
    if not settings.clamd_address:
        raise ValueError("SEQUENCE_VAULT_CLAMD_ADDRESS is required for the ClamAV scanner.")
    return ClamdScanner(settings.clamd_address)


def api_services(container: Container) -> ApiServices:
    read = SqlReadModel(container.engine)
    return ApiServices(
        settings=container.settings,
        policy=container.policy,
        read=read,
        queries=QueryService(read, container.uow, container.registry, container.store),
        uploads=container.uploads,
        reviews=container.reviews,
        commits=container.commits,
        tasks=container.tasks,
    )


def build_model(settings: Settings) -> LocatorModel | None:
    """The model gateway, or None while the organization has not approved one."""
    if not settings.ai_enabled:
        return None
    client = build_client(
        settings.ai_provider,
        region=settings.ai_region,
        project=settings.ai_project,
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
    )
    model = settings.ai_model
    if settings.ai_provider == "bedrock" and not model.startswith("anthropic."):
        model = f"anthropic.{model}"
    return AnthropicLocator(
        client,
        model=model,
        prompt_dir=settings.prompts_dir,
        effort=settings.ai_effort,
        server_fallback=settings.ai_provider == "anthropic",
    )


def build(settings: Settings, *, engine: Engine | None = None) -> Container:
    engine = engine or create_engine(settings.database_url, pool_pre_ping=True)
    uow = SqlUnitOfWorkFactory(engine)
    registry = load_registry(settings.config_dir)
    policy = load_policy(settings.config_dir)
    store = build_store(settings)
    scanner = build_scanner(settings)
    pipeline = Pipeline(
        uow,
        store,
        scanner,
        ContentTypeDetector(),
        SandboxedParser(),
        registry,
        enabled_formats(),
        partial(schema_errors, settings.contracts_dir),
        PipelineLimits(
            max_candidates=policy.limits.max_candidates_per_file,
            max_residues=policy.limits.max_residues_per_sequence,
        ),
        model=build_model(settings),
    )
    return Container(
        settings=settings,
        engine=engine,
        uow=uow,
        registry=registry,
        policy=policy,
        store=store,
        scanner=scanner,
        queue=JobQueue(engine),
        pipeline=pipeline,
        uploads=UploadService(
            uow, store, policy.limits.max_file_bytes, accepted_extensions(enabled_formats())
        ),
        reviews=ReviewService(uow, registry),
        commits=CommitService(uow, registry),
        tasks=TaskService(uow),
    )
