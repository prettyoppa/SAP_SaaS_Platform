# -*- coding: utf-8 -*-
"""Backward-compatible wrapper — use build_content_pdfs.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(
        subprocess.call([sys.executable, str(ROOT / "scripts" / "build_content_pdfs.py")], cwd=str(ROOT))
    )
