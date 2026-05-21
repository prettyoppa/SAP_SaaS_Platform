# -*- coding: utf-8 -*-
"""docs/ → app/data/content_drafts/ (Docker 번들 갱신)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "app" / "data" / "content_drafts"
PAIRS = [
    (ROOT / "docs" / "legal" / "terms_of_service_ko.txt", BUNDLE / "terms_of_service_ko.txt"),
    (ROOT / "docs" / "legal" / "privacy_policy_ko.txt", BUNDLE / "privacy_policy_ko.txt"),
    (ROOT / "docs" / "user_guide" / "user_guide_ko.md", BUNDLE / "user_guide_ko.txt"),
    (ROOT / "docs" / "user_guide" / "user_guide_en.md", BUNDLE / "user_guide_en.txt"),
]


def main() -> int:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    for src, dst in PAIRS:
        if not src.is_file():
            print(f"skip missing {src}")
            continue
        shutil.copy2(src, dst)
        print(f"copied {dst.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
