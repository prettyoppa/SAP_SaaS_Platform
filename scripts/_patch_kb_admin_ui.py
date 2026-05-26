# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "kb.html"
c = p.read_text(encoding="utf-8")

c = re.sub(
    r"\s*\{% if topic_suggestions %\}.*?\{% endif %\}\s*",
    "\n",
    c,
    count=1,
    flags=re.DOTALL,
)

c = c.replace(
    "승인·발행된 글만 회원·비회원에게 공개되며",
    "<strong>발행</strong>된 글만 회원·비회원에게 공개되며",
)
c = c.replace(
    "Only approved &amp; published articles are visible to everyone and included in the sitemap. Member request <strong>text is never stored or shown</strong>.",
    "Only published articles are visible to everyone and included in the sitemap.",
)
c = c.replace("승인·발행되었습니다.", "발행되었습니다.")
c = c.replace("Approved and published.", "Published.")
c = c.replace(
    "{% if request.query_params.get('bulk_saved') or request.query_params.get('draft_from_topic') %}",
    "{% if request.query_params.get('bulk_saved') %}",
)

batch_alert = """
    {% if batch_job_active %}
    <motion class="alert alert-info small py-2 d-flex flex-wrap align-items-center gap-2">
      <span class="nav-ko">AI 초안 생성이 백그라운드에서 진행 중입니다.</span>
      <span class="nav-en" style="display:none">AI draft generation is running in the background.</span>
      <button type="button" class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#kbGalleryBatchModal" data-no-busy="true">
        <span class="nav-ko">진행 창 열기</span><span class="nav-en" style="display:none">Open progress</span>
      </button>
    </div>
    {% endif %}
"""
batch_alert = batch_alert.replace("<motion ", "<div ")

if "batch_job_active" not in c:
    c = c.replace(
        "\n    <div class=\"admin-content-card p-3 mb-4\">",
        batch_alert + "\n    <div class=\"admin-content-card p-3 mb-4\">",
        1,
    )

c = c.replace(
    '      <form method="post" action="/admin/kb/generate-drafts" data-app-confirm-i18n="admin.kb.confirmGenerate">',
    """      <form method="post" action="/admin/kb/generate-drafts" data-app-confirm-i18n="admin.kb.confirmGenerate"
            data-busy-title-ko="요청 접수 중…" data-busy-title-en="Submitting…"
            data-busy-hint-ko="잠시 후 백그라운드에서 키워드별 초안이 생성됩니다."
            data-busy-hint-en="Per-keyword drafts will generate in the background shortly."
            data-busy-agents='[{"agentKo":"「지식갤러리」","doingKo":"키워드별 초안 생성 작업을 서버에 등록하고 있습니다","agentEn":"「Gallery」","doingEn":"queueing per-keyword draft jobs on the server"}]'>""",
)

c = c.replace(
    "공개·검색에 노출되지 않습니다. <code>GOOGLE_API_KEY</code> 필요.",
    "공개·검색에 노출되지 않습니다. 제출 후 백그라운드에서 처리됩니다.",
)

if "kb_batch_generating_modal" not in c:
    c = c.replace(
        "\n{% endblock %}\n",
        "\n    {% include 'admin/partials/kb_batch_generating_modal.html' %}\n"
        "<script src=\"/static/js/kb_admin_preview.js?v=1\"></script>\n{% endblock %}\n",
    )

p.write_text(c, encoding="utf-8")
print("ok", p)
