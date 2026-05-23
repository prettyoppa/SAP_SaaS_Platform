"""개발 제안서 Markdown → PDF (화면 proposal-body와 동일 HTML 렌더링)."""

from __future__ import annotations

import io
import logging
import re
import urllib.request
from pathlib import Path

from fastapi.responses import Response

from .agent_display import prepare_member_facing_proposal_markdown
from .proposal_markdown_html import markdown_to_html
from .rfp_download_names import content_disposition_attachment, sanitize_path_component

_log = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
_FONT_SPECS: tuple[tuple[str, str], ...] = (
    (
        "NotoSansCJKkr-Regular.otf",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf",
    ),
    (
        "NotoSansCJKkr-Bold.otf",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Bold.otf",
    ),
)

# proposal-body (style.css) 인쇄용 — fpdf2 / pymupdf 공통
_PROPOSAL_PDF_CSS = """
body {
  font-family: Ko, sans-serif;
  font-size: 10pt;
  color: #0f172a;
  line-height: 1.65;
}
h1 {
  font-size: 16pt;
  font-weight: bold;
  color: #0f172a;
  border-bottom: 2px solid #6366f1;
  padding-bottom: 6pt;
  margin: 0 0 14pt 0;
}
h2 {
  font-size: 13pt;
  font-weight: bold;
  color: #6366f1;
  margin: 20pt 0 8pt 0;
  padding-left: 8pt;
  border-left: 3pt solid #6366f1;
}
h3 {
  font-size: 11pt;
  font-weight: bold;
  color: #0f172a;
  margin: 12pt 0 6pt 0;
}
p { margin: 0 0 8pt 0; }
ul, ol { margin: 0 0 10pt 14pt; padding: 0; }
li { margin-bottom: 3pt; }
strong { color: #6366f1; }
code {
  font-size: 9pt;
  color: #0284c7;
  background-color: #f1f5f9;
}
hr { border: none; border-top: 1px solid #cbd5e1; margin: 14pt 0; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 10pt 0;
  font-size: 9.5pt;
}
th, td {
  border: 1px solid #cbd5e1;
  padding: 5pt 6pt;
  vertical-align: top;
}
thead th {
  background-color: #f1f5f9;
  font-weight: bold;
  color: #334155;
}
"""


class ProposalPdfUnavailable(RuntimeError):
    """한글 PDF 폰트를 찾을 수 없을 때."""


class ProposalPdfGenerationFailed(RuntimeError):
    """HTML→PDF 변환 실패."""


def _korean_pdf_font_path() -> Path | None:
    root = Path(__file__).resolve().parent
    for p in (
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        _FONT_DIR / "NotoSansCJKkr-Regular.otf",
        root / "static" / "fonts" / "NotoSansKR-Regular.ttf",
        root / "static" / "fonts" / "NotoSansKR-Regular.otf",
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ):
        if p.is_file():
            return p
    return None


def ensure_proposal_pdf_fonts() -> bool:
    """배포 환경에서 폰트가 없으면 다운로드 시도. 성공 시 True."""
    existing = _korean_pdf_font_path()
    if existing:
        _log.info("proposal pdf font ready: %s", existing)
        return True
    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in _FONT_SPECS:
        dest = _FONT_DIR / name
        if dest.is_file() and dest.stat().st_size > 50_000:
            continue
        try:
            _log.warning("proposal pdf: downloading font %s", name)
            urllib.request.urlretrieve(url, dest)
            _log.info("proposal pdf: wrote %s (%s bytes)", dest, dest.stat().st_size)
        except Exception:
            _log.exception("proposal pdf: font download failed for %s", name)
    ok = _korean_pdf_font_path()
    if ok:
        _log.info("proposal pdf font ready after download: %s", ok)
    else:
        _log.error("proposal pdf: korean font still missing under %s", _FONT_DIR)
    return ok is not None


def _korean_pdf_font_bold_path(regular: Path) -> Path | None:
    name = regular.name.lower()
    parent = regular.parent
    if name == "malgun.ttf":
        bold = parent / "malgunbd.ttf"
        return bold if bold.is_file() else None
    if name.startswith("notosanscjkkr") or name.startswith("notosanskr"):
        for cand in (
            parent / "NotoSansCJKkr-Bold.otf",
            parent / "NotoSansKR-Bold.ttf",
            parent / "NotoSansKR-Bold.otf",
        ):
            if cand.is_file():
                return cand
    if name == "nanumgothic.ttf":
        bold = parent / "NanumGothicBold.ttf"
        return bold if bold.is_file() else None
    return None


def _simplify_html_for_pdf(fragment: str) -> str:
    """fpdf2/pymupdf 호환 — Bootstrap class·wrapper div 제거."""
    s = re.sub(r'\sclass="[^"]*"', "", fragment)
    s = re.sub(r'<div class="proposal-table-wrap[^"]*">', "", s)
    return s


def _register_fpdf_fonts(pdf) -> Path:
    regular = _korean_pdf_font_path()
    if not regular:
        raise ProposalPdfUnavailable()
    pdf.add_font("Ko", "", str(regular))
    bold = _korean_pdf_font_bold_path(regular)
    pdf.add_font("Ko", "B", str(bold or regular))
    return regular


def _pdf_bytes_fpdf(html_doc: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    _register_fpdf_fonts(pdf)
    pdf.add_page()
    pdf.set_font("Ko", size=10)
    pdf.write_html(html_doc)
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def _pdf_bytes_pymupdf(html_doc: str, font_regular: Path) -> bytes:
    import pymupdf as fitz

    font_bold = _korean_pdf_font_bold_path(font_regular) or font_regular
    css = (
        _PROPOSAL_PDF_CSS
        + f"""
@font-face {{ font-family: Ko; src: url({font_regular.name}); }}
@font-face {{ font-family: Ko; font-weight: bold; src: url({font_bold.name}); }}
"""
    )
    wrapped = f"<html><head><meta charset='utf-8'></head><body>{html_doc}</body></html>"
    arch = fitz.Archive(str(font_regular.parent))
    story = fitz.Story(html=wrapped, user_css=css, archive=arch)
    bio = io.BytesIO()
    writer = fitz.DocumentWriter(bio)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + fitz.Rect(50, 50, -50, -50)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return bio.getvalue()


def proposal_markdown_to_pdf_bytes(markdown_text: str, *, document_title: str = "") -> bytes:
    del document_title
    ensure_proposal_pdf_fonts()
    md = prepare_member_facing_proposal_markdown(markdown_text or "")
    body_html = _simplify_html_for_pdf(markdown_to_html(md))
    html_doc = f"<style>{_PROPOSAL_PDF_CSS}</style><div class='proposal-body'>{body_html}</div>"

    font = _korean_pdf_font_path()
    if not font:
        raise ProposalPdfUnavailable()

    try:
        return _pdf_bytes_fpdf(html_doc)
    except Exception as fpdf_err:
        _log.warning("proposal pdf fpdf2 failed (%s), trying pymupdf", fpdf_err)
        try:
            return _pdf_bytes_pymupdf(html_doc, font)
        except Exception as mupdf_err:
            _log.exception("proposal pdf pymupdf failed")
            raise ProposalPdfGenerationFailed() from mupdf_err


def proposal_download_filename(
    request_kind: str, request_id: int, *, title: str | None = None
) -> str:
    base = sanitize_path_component((title or "").strip(), 40) or "proposal"
    kind = sanitize_path_component((request_kind or "rfp").strip().lower(), 16) or "rfp"
    return f"{base}_{kind}_{request_id}.pdf"


def proposal_pdf_download_body(markdown_text: str, *, document_title: str = "") -> bytes:
    del document_title
    try:
        return proposal_markdown_to_pdf_bytes(markdown_text)
    except ProposalPdfUnavailable:
        raise
    except ProposalPdfGenerationFailed:
        raise
    except Exception as exc:
        _log.exception("proposal pdf generation failed")
        raise ProposalPdfGenerationFailed() from exc


def proposal_pdf_error_http_response(*, reason: str = "unavailable") -> Response:
    """PDF 실패 시 HTML 리다이렉트 대신 503 — download 속성으로 .htm 저장되는 것 방지."""
    if reason == "generation":
        body = (
            "Proposal PDF could not be generated. Please try again later or contact support.\n"
            "제안서 PDF를 생성하지 못했습니다. 잠시 후 다시 시도하거나 문의해 주세요."
        )
        fname = "proposal-pdf-error.txt"
    else:
        body = (
            "Proposal PDF is unavailable (Korean font missing on server).\n"
            "PDF 다운로드를 사용할 수 없습니다(서버에 한글 폰트 없음)."
        )
        fname = "proposal-pdf-unavailable.txt"
    return Response(
        content=body.encode("utf-8"),
        status_code=503,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(fname)},
    )
