# -*- coding: utf-8 -*-
"""홈 [사용 안내] 타일용 user-guide.pdf 생성.

본문 소스: docs/user_guide/user_guide_ko.md (## 제목 단위)
한글 폰트: Windows 맑은 고딕(malgun.ttf) 또는 app/static/fonts/NotoSansKR-Regular.ttf
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "docs" / "user-guide.pdf"
SOURCE_MD = ROOT / "docs" / "user_guide" / "user_guide_ko.md"


def _find_korean_font() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.ttf",
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.otf",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_sections_from_markdown(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"\n(?=## )", text.strip())
    sections: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("# "):
            continue
        if chunk.startswith("## "):
            lines = chunk.split("\n", 1)
            title = lines[0].replace("## ", "", 1).strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            body = re.sub(r"^#+\s+", "", body, flags=re.MULTILINE)
            body = body.replace("**", "").replace("|", " ")
            if title and title not in ("SAP 개발 파트너 · 이용 안내 (초안)",):
                sections.append((title, body))
    if not sections:
        raise ValueError(f"No ## sections found in {path}")
    return sections


def main() -> int:
    try:
        from fpdf import FPDF
    except ImportError:
        print("pip install fpdf2 로 패키지를 설치한 뒤 다시 실행하세요.", file=sys.stderr)
        return 1

    if not SOURCE_MD.is_file():
        print(f"Missing {SOURCE_MD}", file=sys.stderr)
        return 1

    font_path = _find_korean_font()
    if not font_path:
        print(
            "한글 폰트를 찾을 수 없습니다. "
            "Windows에서는 보통 C:\\Windows\\Fonts\\malgun.ttf 가 있습니다.",
            file=sys.stderr,
        )
        return 1

    sections = _load_sections_from_markdown(SOURCE_MD)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_font("Ko", "", str(font_path))
    pdf.set_font("Ko", size=11)

    pdf.add_page()
    pdf.set_font("Ko", size=18)
    pdf.multi_cell(0, 10, "SAP 개발 파트너 · 이용 안내")
    pdf.ln(4)
    pdf.set_font("Ko", size=9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, "초안 — docs/user_guide/user_guide_ko.md 기준 자동 생성")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    pdf.set_font("Ko", size=11)
    for title, body in sections:
        pdf.set_font("Ko", size=12)
        pdf.multi_cell(0, 7, title)
        pdf.ln(1)
        pdf.set_font("Ko", size=10)
        pdf.multi_cell(0, 5.5, body)
        pdf.ln(4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"Wrote {OUT} ({len(sections)} sections from {SOURCE_MD.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
