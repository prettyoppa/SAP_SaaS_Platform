# -*- coding: utf-8 -*-
"""Docker/Railway 빌드: 제안서 PDF용 Noto Sans KR 폰트를 app/static/fonts/ 에 받습니다."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "app" / "static" / "fonts"
FONTS = (
    (
        "NotoSansCJKkr-Regular.otf",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf",
    ),
    (
        "NotoSansCJKkr-Bold.otf",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Bold.otf",
    ),
)


def _fetch(name: str, url: str) -> None:
    dest = FONT_DIR / name
    if dest.is_file() and dest.stat().st_size > 50_000:
        print(f"skip {dest.name} ({dest.stat().st_size} bytes)")
        return
    print(f"download {url}")
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")


def main() -> int:
    for name, url in FONTS:
        try:
            _fetch(name, url)
        except Exception as exc:
            print(f"FAIL {name}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
