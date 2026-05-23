"""개발 제안서 Markdown → PDF (화면 proposal-body와 동일 HTML 렌더링)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi.responses import Response

from .agent_display import prepare_member_facing_proposal_markdown
from .proposal_markdown_html import markdown_to_html
from .rfp_download_names import content_disposition_attachment, sanitize_path_component

_log = logging.getLogger(__name__)

# proposal-body (style.css) 인쇄용 — fpdf2 write_html 지원 CSS
_PROPOSAL_PDF_CSS = """
body {
  font-family: Ko;
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
  color: #818cf8;
  margin: 20pt 0 8pt 0;
  padding-left: 8pt;
  border-left: 3px solid #6366f1;
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
strong { color: #818cf8; }
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
        root / "static" / "fonts" / "NotoSansCJKkr-Regular.otf",
        root / "static" / "fonts" / "NotoSansKR-Regular.ttf",
        root / "static" / "fonts" / "NotoSansKR-Regular.otf",
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ):
        if p.is_file():
            return p
    return None


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


def _register_pdf_fonts(pdf) -> None:
    regular = _korean_pdf_font_path()
    if not regular:
        raise ProposalPdfUnavailable()
    pdf.add_font("Ko", "", str(regular))
    bold = _korean_pdf_font_bold_path(regular)
    pdf.add_font("Ko", "B", str(bold or regular))


def proposal_markdown_to_pdf_bytes(markdown_text: str, *, document_title: str = "") -> bytes:
    from fpdf import FPDF

    md = prepare_member_facing_proposal_markdown(markdown_text or "")
    body_html = markdown_to_html(md)
    html = (
        f"<style>{_PROPOSAL_PDF_CSS}</style>"
        f'<div class="proposal-body">{body_html}</div>'
    )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    _register_pdf_fonts(pdf)
    pdf.add_page()
    pdf.set_font("Ko", size=10)
    pdf.write_html(html)
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def proposal_download_filename(
    request_kind: str, request_id: int, *, title: str | None = None
) -> str:
    base = sanitize_path_component((title or "").strip(), 40) or "proposal"
    kind = sanitize_path_component((request_kind or "rfp").strip().lower(), 16) or "rfp"
    return f"{base}_{kind}_{request_id}.pdf"


def proposal_pdf_download_body(markdown_text: str, *, document_title: str = "") -> bytes:
    del document_title  # 파일명용; 본문은 제안서 MD 제목·구조 그대로
    try:
        return proposal_markdown_to_pdf_bytes(markdown_text)
    except ProposalPdfUnavailable:
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
