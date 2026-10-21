"""PyInstaller entry point for the one-file release build.

Runs the FastAPI app under uvicorn so the frozen executable serves both the
API and the bundled frontend (production mode). Host/port come from the
environment, matching the behaviour of start-prod scripts.
"""
import os

import uvicorn

from app.main import app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("BACKEND_PORT", "12002"))
    except ValueError:
        port = 12002
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
