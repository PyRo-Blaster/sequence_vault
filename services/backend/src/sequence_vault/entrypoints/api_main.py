"""API process entry point: python -m sequence_vault.entrypoints.api_main"""

import os

import uvicorn

from sequence_vault.api.app import create_app
from sequence_vault.entrypoints.bootstrap import api_services, build
from sequence_vault.settings import Settings


def main() -> None:
    app = create_app(api_services(build(Settings.from_env())))
    uvicorn.run(
        app,
        host=os.environ.get("SEQUENCE_VAULT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("SEQUENCE_VAULT_API_PORT", "8000")),
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
