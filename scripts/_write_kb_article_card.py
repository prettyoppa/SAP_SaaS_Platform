# -*- coding: utf-8 -*-
from pathlib import Path

CONTENT = r'''{# expects loop variable `a`; kb_categories; status_labels_ko; status_labels_en; wf_pending; wf_published #}
{% set kb_live = (a.workflow_status == wf_published and a.is_published) %}
<div class="admin-content-card mb-3 p-3" id="kb-article-{{ a.id }}">
  <div class="d-flex flex-wrap justify-content-between mb-2 small gap-2">
    <span>
      ID {{ a.id }} · <code>/kb/{{ a.slug }}</code>
      <span class="badge bg-secondary ms-1">
        <span class="nav-ko">{{ status_labels_ko.get(a.workflow_status, a.workflow_status) }}</span>
        <span class="nav-en" style="display:none">{{ status_labels_en.get(a.workflow_status, a.workflow_status) }}</span>
      </span>
      {% if a.source_kind %}<span class="text-muted">· {{ a.source_kind }}</span>{% endif %}
    </span>
    <span class="d-flex flex-wrap gap-1 align-items-center">
      <a href="/admin/kb/{{ a.id }}/preview" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary" data-no-busy="true">
        <span class="nav-ko">미리보기</span><span class="nav-en" style="display:none">Preview</span>
      </a>
      {% if a.workflow_status == wf_pending %}
      <form method="post" action="/admin/kb/{{ a.id }}/approve" class="d-inline">
        <button type="submit" class="btn btn-sm btn-success" data-app-confirm-i18n="admin.kb.confirmApprove">
          <span class="nav-ko">발행</span><span class="nav-en" style="display:none">Publish</span>
        </button>
      </form>
      <form method="post" action="/admin/kb/{{ a.id }}/reject" class="d-inline">
        <button type="submit" class="btn btn-sm btn-outline-warning" data-app-confirm-i18n="admin.kb.confirmReject">
          <span class="nav-ko">반려</span><span class="nav-en" style="display:none">Reject</span>
        </button>
      </form>
      {% endif %}
      {% if a.workflow_status != wf_pending and a.workflow_status != wf_published %}
      <form method="post" action="/admin/kb/{{ a.id }}/submit-review" class="d-inline">
        <button type="submit" class="btn btn-sm btn-outline-primary">
          <span class="nav-ko">검수 대기로</span><span class="nav-en" style="display:none">To review queue</span>
        </button>
      </form>
      {% endif %}
      {% if a.workflow_status != wf_pending %}
      <form method="post" action="/admin/kb/{{ a.id }}/set-publish" class="d-inline-flex align-items-center gap-1 kb-publish-switch-form border rounded px-2 py-1" data-no-busy="true">
        <input type="hidden" name="published" value="{{ '1' if kb_live else '0' }}"/>
        <motion class="form-check form-switch mb-0 d-flex align-items-center gap-1">
          <input class="form-check-input kb-publish-switch" type="checkbox" role="switch"
            id="kb-publish-switch-{{ a.id }}"
            {% if kb_live %}checked{% endif %}
            aria-labelledby="kb-publish-switch-label-{{ a.id }}"/>
          <label class="form-check-label small mb-0 user-select-none" id="kb-publish-switch-label-{{ a.id }}">
            <span class="nav-ko kb-publish-switch-label-on{% if not kb_live %} d-none{% endif %}">공개</span>
            <span class="nav-ko kb-publish-switch-label-off{% if kb_live %} d-none{% endif %}">비공개</span>
            <span class="nav-en kb-publish-switch-label-on{% if not kb_live %} d-none{% endif %}" style="display:none">Public</span>
            <span class="nav-en kb-publish-switch-label-off{% if kb_live %} d-none{% endif %}" style="display:none">Private</span>
          </label>
        </div>
      </form>
      {% endif %}
      <form method="post" action="/admin/kb/{{ a.id }}/delete" class="d-inline" data-app-confirm-i18n="admin.kb.confirmDelete">
        <button type="submit" class="btn btn-sm btn-outline-danger">
          <span class="nav-ko">삭제</span><span class="nav-en" style="display:none">Delete</span>
        </button>
      </form>
    </span>
  </div>
  {% if a.seed_keyword %}
  <div class="small text-muted mb-1">
    <span class="nav-ko">시드 키워드: <strong>{{ a.seed_keyword }}</strong></span>
    <span class="nav-en" style="display:none">Seed keyword: <strong>{{ a.seed_keyword }}</strong></span>
  </div>
  {% endif %}
  {% if a.source_note %}
  <div class="small text-muted mb-2">source_note: {{ a.source_note }}</div>
  {% endif %}
  {% if a.research_summary %}
  <details class="small mb-2"><summary style="cursor:pointer" class="user-select-none fw-semibold">
    <span class="nav-ko">검색·리서치 메모 (관리자)</span>
    <span class="nav-en" style="display:none">Search / research notes (admin)</span>
  </summary>
  <pre class="small kb-research-notes-pre p-2 rounded mt-2 mb-0 text-wrap">{{ a.research_summary }}</pre>
  </details>
  {% endif %}
  <form method="post" action="/admin/kb/{{ a.id }}/update">
    <div class="row g-2">
      <div class="col-md-6">
        <label class="small"><span class="nav-ko">제목</span><span class="nav-en" style="display:none">Title</span></label>
        <input name="title" class="form-control" value="{{ a.title }}" required/>
      </div>
      <div class="col-md-6">
        <label class="small">slug</label>
        <input name="slug" class="form-control font-monospace" value="{{ a.slug }}" required/>
      </div>
      <div class="col-md-4">
        <label class="small"><span class="nav-ko">분류</span><span class="nav-en" style="display:none">Category</span></label>
        <select name="category" class="form-select">{% for k,l in kb_categories.items() %}<option value="{{ k }}" {% if a.category==k %}selected{% endif %}>{{ l }}</option>{% endfor %}</select>
      </div>
      <div class="col-md-2">
        <label class="small"><span class="nav-ko">순서</span><span class="nav-en" style="display:none">Order</span></label>
        <input type="number" name="sort_order" value="{{ a.sort_order }}" class="form-control"/>
      </div>
      <div class="col-md-6">
        <label class="small d-block">
          <input type="checkbox" name="is_published" value="1" {% if kb_live %}checked{% endif %}/>
          <span class="nav-ko">저장 시 공개</span>
          <span class="nav-en" style="display:none">Public on save</span>
        </label>
        <span class="small text-muted d-block">
          <span class="nav-ko">위 스위치는 저장 없이 즉시 반영됩니다.</span>
          <span class="nav-en" style="display:none">The switch above applies immediately without saving.</span>
        </span>
        {% if kb_live %}
        <a href="/kb/{{ a.slug }}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary ms-0 ms-md-2 mt-1 mt-md-0" data-no-busy="true">
          <span class="nav-ko">공개 페이지</span><span class="nav-en" style="display:none">Public page</span>
        </a>
        {% endif %}
      </div>
      <motion class="col-12">
        <label class="small"><span class="nav-ko">태그 (쉼표)</span><span class="nav-en" style="display:none">Tags (comma)</span></label>
        <input name="tags" class="form-control" value="{{ a.tags or '' }}"/>
      </div>
      <div class="col-12">
        <label class="small"><span class="nav-ko">요약</span><span class="nav-en" style="display:none">Excerpt</span></label>
        <textarea name="excerpt" class="form-control" rows="2">{{ a.excerpt or '' }}</textarea>
      </div>
      <div class="col-12">
        <label class="small">meta description</label>
        <input name="meta_description" class="form-control" value="{{ a.meta_description or '' }}"/>
      </div>
      <div class="col-12">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-1">
          <label class="small mb-0"><span class="nav-ko">본문 Markdown</span><span class="nav-en" style="display:none">Body (Markdown)</span></label>
          <button type="button" class="btn btn-sm btn-outline-secondary kb-inline-preview-btn" data-kb-preview-for="body-md-{{ a.id }}">
            <span class="nav-ko">미리보기 토글</span><span class="nav-en" style="display:none">Toggle preview</span>
          </button>
        </div>
        <textarea id="body-md-{{ a.id }}" name="body_md" class="form-control font-monospace kb-body-md-input" rows="10">{{ a.body_md }}</textarea>
        <div id="kb-preview-{{ a.id }}" class="kb-admin-preview border rounded p-3 mt-2 d-none markdown-body text-break" data-kb-article-id="{{ a.id }}" aria-hidden="true"></div>
      </div>
      <div class="col-12">
        <label class="small"><span class="nav-ko">관리자 메모 (비공개)</span><span class="nav-en" style="display:none">Admin note (private)</span></label>
        <input name="source_note" class="form-control" value="{{ a.source_note or '' }}"/>
      </div>
      <div class="col-12"><button type="submit" class="btn btn-primary btn-sm"><span class="nav-ko">저장</span><span class="nav-en" style="display:none">Save</span></button></div>
    </div>
  </form>
</div>
'''

CONTENT = CONTENT.replace("<motion", "<div").replace("</motion>", "</div>")

out = Path(__file__).resolve().parents[1] / "app/templates/admin/partials/kb_article_card.html"
out.write_text(CONTENT, encoding="utf-8")
print("wrote", out)
