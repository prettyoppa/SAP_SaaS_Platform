# -*- coding: utf-8 -*-
"""Rewrite admin/kb.html as valid UTF-8 (fixes UnicodeDecodeError on deploy)."""
from pathlib import Path

CONTENT = r"""{% extends "base.html" %}
{% block title %}SAP 지식갤러리 – Admin{% endblock %}
{% block content %}
<div class="py-4">
  <div class="container">
    <h4 class="mb-2">
      <i class="fa-solid fa-book me-2 text-primary"></i>
      <span class="nav-ko">SAP 지식갤러리</span>
      <span class="nav-en" style="display:none">SAP Knowledge Gallery</span>
    </h4>
    <p class="small text-muted mb-3">
      <span class="nav-ko">URL은 <code>/kb</code> 입니다. <strong>발행</strong>된 글만 회원·비회원에게 공개되며, 검색(sitemap)에도 포함됩니다. 회원 요청 <strong>원문은 저장·공개하지 않습니다</strong>.</span>
      <span class="nav-en" style="display:none">Public URL: <code>/kb</code>. Only published articles are visible to everyone and included in the sitemap. Member request text is never stored or shown.</span>
    </p>

    {% if generate_ok or generate_fail %}
    <div class="alert {% if generate_ok and not generate_fail %}alert-success{% elif generate_ok %}alert-warning{% else %}alert-danger{% endif %} small py-2">
      <span class="nav-ko">생성 완료 {{ generate_ok }}건{% if generate_fail %} · 실패 {{ generate_fail }}건{% endif %}</span>
      <span class="nav-en" style="display:none">Generated {{ generate_ok }}{% if generate_fail %} · failed {{ generate_fail }}{% endif %}</span>
      {% if generate_errors %}
      <div class="mt-1 font-monospace" style="white-space:pre-wrap">{{ generate_errors }}</div>
      {% endif %}
    </div>
    {% endif %}

    {% if request.query_params.get('review') == 'approved' %}
    <div class="alert alert-success small py-2"><span class="nav-ko">발행되었습니다.</span><span class="nav-en" style="display:none">Published.</span></div>
    {% elif request.query_params.get('review') == 'rejected' %}
    <div class="alert alert-warning small py-2"><span class="nav-ko">반려 처리되었습니다.</span><span class="nav-en" style="display:none">Rejected.</span></div>
    {% elif request.query_params.get('review') == 'submitted' %}
    <div class="alert alert-info small py-2"><span class="nav-ko">검수 대기로 이동했습니다.</span><span class="nav-en" style="display:none">Moved to review queue.</span></div>
    {% endif %}

    {% if request.query_params.get('bulk_saved') %}
    <div class="alert alert-success small py-2"><span class="nav-ko">저장되었습니다.</span><span class="nav-en" style="display:none">Saved.</span></div>
    {% endif %}

    {% if batch_job_active %}
    <div class="alert alert-info small py-2 d-flex flex-wrap align-items-center gap-2">
      <span class="nav-ko">AI 초안 생성이 백그라운드에서 진행 중입니다.</span>
      <span class="nav-en" style="display:none">AI draft generation is running in the background.</span>
      <button type="button" class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#kbGalleryBatchModal" data-no-busy="true">
        <span class="nav-ko">진행 창 열기</span><span class="nav-en" style="display:none">Open progress</span>
      </button>
    </div>
    {% endif %}

    <div class="admin-content-card p-3 mb-4">
      <h6 class="fw-semibold mb-2">
        <i class="fa-solid fa-wand-magic-sparkles me-1 text-primary"></i>
        <span class="nav-ko">AI 초안 생성 (Google 검색 연동)</span>
        <span class="nav-en" style="display:none">AI draft generation (Google Search grounding)</span>
      </h6>
      <p class="small text-muted mb-2">
        <span class="nav-ko">키워드 최대 5개(줄당 1개). 생성된 글은 <strong>검수 대기</strong> 상태이며 공개·검색에 노출되지 않습니다. 제출 후 백그라운드에서 처리됩니다.</span>
        <span class="nav-en" style="display:none">Up to 5 keywords (one per line). Drafts go to <strong>pending review</strong> (not public). Requires <code>GOOGLE_API_KEY</code>.</span>
      </p>
      <form method="post" action="/admin/kb/generate-drafts" data-app-confirm-i18n="admin.kb.confirmGenerate"
            data-busy-title-ko="요청 접수 중…" data-busy-title-en="Submitting…"
            data-busy-hint-ko="잠시 후 백그라운드에서 키워드별 초안이 생성됩니다."
            data-busy-hint-en="Per-keyword drafts will generate in the background shortly."
            data-busy-agents='[{"agentKo":"「지식갤러리」","doingKo":"키워드별 초안 생성 작업을 서버에 등록하고 있습니다","agentEn":"「Gallery」","doingEn":"queueing per-keyword draft jobs on the server"}]'>
        <div class="row g-2">
          <div class="col-md-8">
            <label class="small"><span class="nav-ko">키워드 (줄당 1개, 최대 5)</span><span class="nav-en" style="display:none">Keywords (one per line, max 5)</span></label>
            <textarea name="keywords" class="form-control font-monospace" rows="5" placeholder="S/4HANA OData&#10;ABAP RESTful Application Programming"></textarea>
          </div>
          <div class="col-md-4">
            <label class="small"><span class="nav-ko">기본 분류</span><span class="nav-en" style="display:none">Default category</span></label>
            <select name="category_default" class="form-select mb-2">{% for k,l in kb_categories.items() %}<option value="{{ k }}">{{ l }}</option>{% endfor %}</select>
            <label class="small"><span class="nav-ko">참고 메모 (선택)</span><span class="nav-en" style="display:none">Reference notes (optional)</span></label>
            <textarea name="reference_notes" class="form-control small" rows="3" placeholder=""></textarea>
          </div>
          <div class="col-12">
            <button type="submit" class="btn btn-primary">
              <span class="nav-ko">초안 생성 → 검수 대기</span>
              <span class="nav-en" style="display:none">Generate drafts → review queue</span>
            </button>
          </div>
        </div>
      </form>
    </div>

    <h6 class="text-muted small text-uppercase mb-2">
      <span class="nav-ko">검수 대기 ({{ review_queue|length }})</span>
      <span class="nav-en" style="display:none">Pending review ({{ review_queue|length }})</span>
    </h6>
    {% for a in review_queue %}
      {% include 'admin/partials/kb_article_card.html' %}
    {% else %}
    <p class="text-muted small mb-4"><span class="nav-ko">검수 대기 글이 없습니다.</span><span class="nav-en" style="display:none">No articles pending review.</span></p>
    {% endfor %}

    <details class="mb-3">
      <summary class="fw-semibold user-select-none" style="cursor:pointer">
        <span class="nav-ko">수동으로 새 글 추가</span>
        <span class="nav-en" style="display:none">Add article manually</span>
      </summary>
      <form method="post" action="/admin/kb/add" class="admin-content-card mt-2 p-3">
        <div class="row g-2">
          <div class="col-md-6"><label class="small"><span class="nav-ko">제목</span><span class="nav-en" style="display:none">Title</span></label><input name="title" class="form-control" required/></div>
          <div class="col-md-6"><label class="small">slug</label><input name="slug" class="form-control font-monospace" placeholder="auto"/></div>
          <div class="col-md-4"><label class="small"><span class="nav-ko">분류</span><span class="nav-en" style="display:none">Category</span></label><select name="category" class="form-select">{% for k,l in kb_categories.items() %}<option value="{{ k }}">{{ l }}</option>{% endfor %}</select></div>
          <div class="col-md-4"><label class="small"><span class="nav-ko">순서</span><span class="nav-en" style="display:none">Order</span></label><input type="number" name="sort_order" value="0" class="form-control"/></div>
          <div class="col-md-4"><label class="small d-block"><span class="nav-ko">즉시 발행</span><span class="nav-en" style="display:none">Publish now</span></label><input type="checkbox" name="is_published" value="1"/></div>
          <div class="col-12"><label class="small"><span class="nav-ko">요약</span><span class="nav-en" style="display:none">Excerpt</span></label><textarea name="excerpt" class="form-control" rows="2"></textarea></div>
          <div class="col-12"><label class="small">meta description</label><input name="meta_description" class="form-control" maxlength="320"/></div>
          <div class="col-12"><label class="small"><span class="nav-ko">본문 Markdown</span><span class="nav-en" style="display:none">Body (Markdown)</span></label><textarea name="body_md" class="form-control font-monospace" rows="8"></textarea></div>
          <div class="col-12"><button class="btn btn-primary"><span class="nav-ko">추가</span><span class="nav-en" style="display:none">Add</span></button></div>
        </div>
      </form>
    </details>

    <h6 class="text-muted small text-uppercase mt-4 mb-2">
      <span class="nav-ko">발행됨 ({{ published_articles|length }})</span>
      <span class="nav-en" style="display:none">Published ({{ published_articles|length }})</span>
    </h6>
    {% for a in published_articles %}
      {% include 'admin/partials/kb_article_card.html' %}
    {% else %}
    <p class="text-muted small mb-4"><span class="nav-ko">발행된 글이 없습니다.</span><span class="nav-en" style="display:none">No published articles.</span></p>
    {% endfor %}

    {% if other_articles %}
    <h6 class="text-muted small text-uppercase mt-4 mb-2">
      <span class="nav-ko">초안·반려 ({{ other_articles|length }})</span>
      <span class="nav-en" style="display:none">Draft / rejected ({{ other_articles|length }})</span>
    </h6>
    {% for a in other_articles %}
      {% include 'admin/partials/kb_article_card.html' %}
    {% endfor %}
    {% endif %}
  </div>
</div>
{% include 'admin/partials/kb_batch_generating_modal.html' %}
<script src="/static/js/kb_admin_preview.js?v=1"></script>
<script src="/static/js/kb_admin_publish_switch.js?v=1"></script>
{% endblock %}
"""

CONTENT = CONTENT.replace("<div", "<div").replace("</motion>", "</motion>")
CONTENT = CONTENT.replace("<div", "<div").replace("</motion>", "</motion>")
CONTENT = CONTENT.replace("<div", "<div").replace("</motion>", "</div>")

out = Path(__file__).resolve().parents[1] / "app/templates/admin/kb.html"
out.write_text(CONTENT, encoding="utf-8")
# verify
out.read_text(encoding="utf-8")
print("wrote", out, "chars", len(CONTENT))
