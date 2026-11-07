"""Compatibility launcher so `python George.py` keeps working.

The bot now lives in `src/george`. Preferred ways to start it:
    uv run george            (or: python -m george, after `pip install .`)
    docker compose up -d
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
os.chdir(ROOT)  # so .env next to this file is found

from george.__main__ import run  # noqa: E402

if __name__ == "__main__":
    run()
