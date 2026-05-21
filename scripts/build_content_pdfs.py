# -*- coding: utf-8 -*-
"""이용안내·이용약관·개인정보 PDF 생성 (Markdown → app/static/docs/)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.content_drafts import DocKind, markdown_file_path, markdown_to_plain_document

OUT_DIR = ROOT / "app" / "static" / "docs"
BUILDS: list[tuple[DocKind, str, str, str]] = [
    ("user_guide", "ko", "user-guide.pdf", "SAP 개발 파트너 · 이용 안내"),
    ("terms", "ko", "terms-of-service.pdf", "이용약관"),
    ("privacy", "ko", "privacy-policy.pdf", "개인정보처리방침"),
]


def _find_korean_font() -> Path | None:
    for p in (
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.ttf",
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.otf",
    ):
        if p.is_file():
            return p
    return None


def _write_pdf(md: str, out: Path, title: str, font_path: Path) -> None:
    from fpdf import FPDF

    plain = markdown_to_plain_document(md)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_font("Ko", "", str(font_path))
    pdf.add_page()
    pdf.set_font("Ko", size=14)
    pdf.multi_cell(pdf.epw, 8, title)
    pdf.ln(4)
    pdf.set_font("Ko", size=10)
    epw = pdf.epw
    for line in plain.splitlines():
        if not line.strip():
            pdf.ln(3)
            continue
        try:
            pdf.multi_cell(epw, 5.5, line)
        except Exception:
            for i in range(0, len(line), 42):
                pdf.multi_cell(epw, 5.5, line[i : i + 42])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))


def main() -> int:
    font = _find_korean_font()
    if not font:
        print("한글 폰트 없음", file=sys.stderr)
        return 1
    for kind, lang, filename, title in BUILDS:
        path = markdown_file_path(kind, lang)
        if not path:
            print(f"skip {kind} (no md)", file=sys.stderr)
            continue
        md = path.read_text(encoding="utf-8")
        out = OUT_DIR / filename
        _write_pdf(md, out, title, font)
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
