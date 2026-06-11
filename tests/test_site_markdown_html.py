"""사이트 공지·팝업 마크다운 렌더."""

from app.site_markdown_html import site_markdown_to_html


def test_bold_and_list():
    html = site_markdown_to_html("**bold**\n\n* one\n* two")
    assert "<strong>bold</strong>" in html
    assert "<li>one</li>" in html
    assert "<li>two</li>" in html


def test_heading():
    html = site_markdown_to_html("## Section\n\nParagraph.")
    assert "<h2>Section</h2>" in html
    assert "<p>Paragraph.</p>" in html


def test_task_list():
    html = site_markdown_to_html("- [ ] unchecked\n- [x] checked")
    assert 'class="task-list"' in html
    assert 'type="checkbox" disabled/> unchecked' in html
    assert 'type="checkbox" disabled checked/> checked' in html
    assert "[ ]" not in html
