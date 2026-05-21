# -*- coding: utf-8 -*-
"""홈 이용 안내 PDF — docs/user_guide/user_guide_ko.md 와 동일 평문 구조.

한글 폰트: Windows 맑은 고딕 또는 app/static/fonts/NotoSansKR-Regular.ttf
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.content_drafts import markdown_to_plain_document, user_guide_file_path

OUT = ROOT / "app" / "static" / "docs" / "user-guide.pdf"


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


def main() -> int:
    try:
        from fpdf import FPDF
    except ImportError:
        print("pip install fpdf2 로 패키지를 설치한 뒤 다시 실행하세요.", file=sys.stderr)
        return 1

    if not USER_GUIDE_KO_PATH.is_file():
        print(f"Missing {USER_GUIDE_KO_PATH}", file=sys.stderr)
        return 1

    font_path = _find_korean_font()
    if not font_path:
        print("한글 폰트를 찾을 수 없습니다.", file=sys.stderr)
        return 1

    md = guide_path.read_text(encoding="utf-8")
    plain = markdown_to_plain_document(md)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_font("Ko", "", str(font_path))
    pdf.add_page()
    pdf.set_font("Ko", size=10)
    epw = pdf.epw
    for line in plain.splitlines():
        if not line.strip():
            pdf.ln(3)
            continue
        text = line.replace("\t", " ")
        try:
            pdf.multi_cell(epw, 5.5, text)
        except Exception:
            chunk = 42
            for i in range(0, len(text), chunk):
                pdf.multi_cell(epw, 5.5, text[i : i + chunk])
    pdf.ln(2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"Wrote {OUT} ({len(plain)} chars from {guide_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
