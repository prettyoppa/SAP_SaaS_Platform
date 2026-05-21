# -*- coding: utf-8 -*-
"""docs/ Markdown → app/data/content_drafts/ (Docker 번들)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "app" / "data" / "content_drafts"
FILES = [
    "terms_of_service_ko.md",
    "terms_of_service_en.md",
    "privacy_policy_ko.md",
    "privacy_policy_en.md",
    "user_guide_ko.md",
    "user_guide_en.md",
]


def main() -> int:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if name.startswith("user_guide"):
            src = ROOT / "docs" / "user_guide" / name
        else:
            src = ROOT / "docs" / "legal" / name
        if not src.is_file():
            print(f"skip missing {src}")
            continue
        shutil.copy2(src, BUNDLE / name)
        print(f"copied {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
