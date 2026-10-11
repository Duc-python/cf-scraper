"""Run the server:  python -m cf_scraper"""
from __future__ import annotations

import uvicorn

from .app import create_app
from .config import PORT


def main() -> None:
    uvicorn.run(create_app(), host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
