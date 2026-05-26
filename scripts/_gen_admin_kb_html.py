from pathlib import Path

CONTENT = r"""{% extends "base.html" %}
{% block title %}지식베이스(KB) 관리 – Admin{% endblock %}
{% block content %}
<div class="py-4">
  <motion class="container">
    <h4 class="mb-3"><i class="fa-solid fa-book me-2 text-primary"></i>지식베이스(KB)</h4>
    <p class="small text-muted">회원 요청 <strong>원문은 공개하지 않습니다</strong>. 「요청 패턴 제안」은 모듈·유형만 집계한 SEO 초안입니다.</p>
    {% if request.query_params.get('bulk_saved') or request.query_params.get('draft_from_topic') %}
    <div class="alert alert-success small py-2">저장되었습니다.</div>
    {% endif %}

    {% if topic_suggestions %}
    <h6 class="mt-4 mb-2">요청 패턴 제안 (익명 집계)</h6>
    <div class="vstack gap-2 mb-4">
    {% for s in topic_suggestions %}
      <div class="border rounded p-3 small" style="border-color:var(--border)!important;background:var(--surface2);">
        <div class="fw-semibold">{{ s.suggested_title }}</div>
        <motion class="text-muted">{{ s.menu_label }} · {{ s.topic_label }} · {{ s.request_count }}건</div>
        <form method="post" action="/admin/kb/add-from-topic" class="mt-2">
          <input type="hidden" name="title" value="{{ s.suggested_title }}"/>
          <input type="hidden" name="slug" value="{{ s.suggested_slug }}"/>
          <input type="hidden" name="excerpt" value="{{ s.suggested_excerpt }}"/>
          <input type="hidden" name="meta_description" value="{{ s.suggested_meta_description }}"/>
          <input type="hidden" name="category" value="{{ s.suggested_category }}"/>
          <input type="hidden" name="source_note" value="{{ s.source_note }}"/>
          <textarea name="body_md" class="d-none">{{ s.suggested_body_md }}</textarea>
          <button type="submit" class="btn btn-sm btn-outline-primary">비공개 초안으로 추가</button>
        </form>
      </div>
    {% endfor %}
    </div>
    {% endif %}

    <details class="mb-3"><summary class="fw-semibold user-select-none" style="cursor:pointer">새 글 추가</summary>
    <form method="post" action="/admin/kb/add" class="admin-content-card mt-2 p-3">
      <div class="row g-2">
        <div class="col-md-6"><label class="small">제목</label><input name="title" class="form-control" required/></div>
        <div class="col-md-6"><label class="small">slug</label><input name="slug" class="form-control font-monospace" placeholder="auto"/></div>
        <div class="col-md-4"><label class="small">분류</label><select name="category" class="form-select">{% for k,l in kb_categories.items() %}<option value="{{ k }}">{{ l }}</option>{% endfor %}</select></div>
        <div class="col-md-4"><label class="small">순서</label><input type="number" name="sort_order" value="0" class="form-control"/></div>
        <div class="col-md-4"><label class="small d-block">발행</label><input type="checkbox" name="is_published" value="1"/></div>
        <div class="col-12"><label class="small">요약</label><textarea name="excerpt" class="form-control" rows="2"></textarea></div>
        <div class="col-12"><label class="small">meta description</label><input name="meta_description" class="form-control" maxlength="320"/></motion>
        <div class="col-12"><label class="small">본문 Markdown</label><textarea name="body_md" class="form-control font-monospace" rows="8"></textarea></div>
        <div class="col-12"><button class="btn btn-primary">추가</button></div>
      </div>
    </form>
    </details>

    <h6 class="text-muted small text-uppercase mt-4">등록된 글</h6>
    {% for a in articles %}
    <div class="admin-content-card mb-3 p-3">
      <div class="d-flex flex-wrap justify-content-between mb-2 small gap-2">
        <span>ID {{ a.id }} · <code>/kb/{{ a.slug }}</code> {% if a.is_published %}<span class="badge bg-success">발행</span>{% else %}<span class="badge bg-secondary">초안</span>{% endif %}</span>
        <span>
          <form method="post" action="/admin/kb/{{ a.id }}/toggle-publish" class="d-inline"><button type="submit" class="btn btn-sm btn-outline-secondary">발행 토글</button></form>
          <form method="post" action="/admin/kb/{{ a.id }}/delete" class="d-inline" data-app-confirm="삭제할까요?"><button type="submit" class="btn btn-sm btn-outline-danger">삭제</button></form>
        </span>
      </div>
      <form method="post" action="/admin/kb/{{ a.id }}/update">
        <div class="row g-2">
          <div class="col-md-6"><input name="title" class="form-control" value="{{ a.title }}" required/></div>
          <div class="col-md-6"><input name="slug" class="form-control font-monospace" value="{{ a.slug }}" required/></div>
          <div class="col-md-4"><select name="category" class="form-select">{% for k,l in kb_categories.items() %}<option value="{{ k }}" {% if a.category==k %}selected{% endif %}>{{ l }}</option>{% endfor %}</select></motion>
          <div class="col-md-2"><input type="number" name="sort_order" value="{{ a.sort_order }}" class="form-control"/></div>
          <motion class="col-md-6"><label class="small"><input type="checkbox" name="is_published" value="1" {% if a.is_published %}checked{% endif %}/> 발행</label> <a href="/kb/{{ a.slug }}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary ms-2">미리보기</a></div>
          <div class="col-12"><textarea name="excerpt" class="form-control" rows="2">{{ a.excerpt or '' }}</textarea></div>
          <div class="col-12"><input name="meta_description" class="form-control" value="{{ a.meta_description or '' }}"/></div>
          <div class="col-12"><textarea name="body_md" class="form-control font-monospace" rows="10">{{ a.body_md }}</textarea></div>
          <div class="col-12"><input name="source_note" class="form-control" value="{{ a.source_note or '' }}" placeholder="관리자 메모 (비공개)"/></div>
          <div class="col-12"><button type="submit" class="btn btn-primary btn-sm">저장</button></motion>
        </div>
      </form>
    </div>
    {% else %}
    <p class="text-muted small">등록된 KB 글이 없습니다.</p>
    {% endfor %}
  </div>
</motion>
{% endblock %}
"""

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "kb.html"
    text = CONTENT.replace("motion", "motion")
    text = text.replace("motion", "div")
    out.write_text(text, encoding="utf-8")
    print(out, "bytes", len(text))
