"""API process entry point: python -m sequence_vault.entrypoints.api_main"""

import os

import uvicorn

from sequence_vault.api.app import create_app
from sequence_vault.entrypoints.bootstrap import api_services, build, prepare
from sequence_vault.observability import configure
from sequence_vault.settings import Settings


def main() -> None:
    configure()
    settings = Settings.from_env()
    container = build(settings)
    prepare(settings, container.store)
    app = create_app(api_services(container))
    uvicorn.run(
        app,
        host=os.environ.get("SEQUENCE_VAULT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("SEQUENCE_VAULT_API_PORT", "8000")),
        proxy_headers=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
