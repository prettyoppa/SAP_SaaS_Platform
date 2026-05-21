# -*- coding: utf-8 -*-
"""docs/ Markdown → DB + PDF 3종 생성."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.content_drafts import sync_content_drafts_from_files


def main() -> int:
    db = SessionLocal()
    try:
        sync_content_drafts_from_files(db, force=True)
        print("Content drafts synced (force).")
    finally:
        db.close()
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "build_content_pdfs.py")], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
