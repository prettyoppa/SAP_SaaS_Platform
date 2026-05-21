# -*- coding: utf-8 -*-
"""docs/ 초안 → DB 강제 반영 + user-guide.pdf 재생성."""
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

    pdf_script = ROOT / "scripts" / "build_user_guide_pdf.py"
    print("Rebuilding user-guide.pdf …")
    return subprocess.call([sys.executable, str(pdf_script)], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
