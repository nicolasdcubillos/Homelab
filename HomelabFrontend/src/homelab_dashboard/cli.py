"""Punto de entrada CLI: arranca uvicorn programáticamente."""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
