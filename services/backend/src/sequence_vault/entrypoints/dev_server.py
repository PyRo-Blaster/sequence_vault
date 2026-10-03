"""Development only: the API and one worker in a single process.

python -m sequence_vault.entrypoints.dev_server
"""

import os
import threading

import uvicorn

from sequence_vault.api.app import create_app
from sequence_vault.entrypoints.bootstrap import api_services, build
from sequence_vault.observability import configure
from sequence_vault.settings import Settings
from sequence_vault.workers.worker import Worker


def main() -> None:
    settings = Settings.from_env()
    if not settings.is_development:
        raise SystemExit("dev_server only runs with SEQUENCE_VAULT_ENV=development")
    configure()
    container = build(settings)
    stop = threading.Event()
    worker = Worker(container.queue, container.pipeline, worker_id="dev-worker", lease_seconds=30)
    threading.Thread(target=worker.run_forever, args=(stop, 0.3), daemon=True).start()
    try:
        uvicorn.run(
            create_app(api_services(container)),
            host="127.0.0.1",
            port=int(os.environ.get("SEQUENCE_VAULT_API_PORT", "8000")),
        )
    finally:
        stop.set()


if __name__ == "__main__":
    main()
