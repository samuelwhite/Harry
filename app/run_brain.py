from __future__ import annotations

import os

import uvicorn
from app.main import app


def main() -> None:
    host = os.environ.get("HARRY_HOST", "0.0.0.0")
    port = int(os.environ.get("HARRY_PORT", "8787"))
    uvicorn.run(app, host=host, port=port, workers=1)


if __name__ == "__main__":
    main()