"""Worker process entry point: python -m sequence_vault.entrypoints.worker_main"""

import signal
import socket
import threading
import uuid

from sequence_vault.entrypoints.bootstrap import build
from sequence_vault.observability import configure
from sequence_vault.settings import Settings
from sequence_vault.workers.worker import Worker


def main() -> None:
    configure()
    container = build(Settings.from_env())
    worker = Worker(
        container.queue,
        container.pipeline,
        worker_id=f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}",
        max_transient_retries=container.policy.max_transient_retries,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    worker.run_forever(stop)


if __name__ == "__main__":
    main()
