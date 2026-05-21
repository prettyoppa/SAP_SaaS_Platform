# -*- coding: utf-8 -*-
"""이용약관·개인정보 DB 반영 + user-guide.pdf 재생성 (로컬·CI·배포 전 수동 실행용)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.site_legal_seed import LEGAL_CONTENT_REVISION, seed_legal_site_content


def main() -> int:
    db = SessionLocal()
    try:
        seed_legal_site_content(db)
        print(f"Legal content applied (revision {LEGAL_CONTENT_REVISION}).")
    finally:
        db.close()

    pdf_script = ROOT / "scripts" / "build_user_guide_pdf.py"
    print("Rebuilding user-guide.pdf …")
    return subprocess.call([sys.executable, str(pdf_script)], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
