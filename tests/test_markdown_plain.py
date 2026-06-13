"""markdown_to_plain_text — 목록·타일용 평문 변환."""

from app.home_hero_guide import markdown_to_plain_text


def test_strips_bold_and_headings():
    assert markdown_to_plain_text("## **공지**") == "공지"


def test_strips_task_list_syntax():
    assert markdown_to_plain_text("- [ ] 할 일") == "할 일"
    assert markdown_to_plain_text("- [x] 완료") == "완료"


def test_single_line_joins():
    assert markdown_to_plain_text("**A**\n- [ ] B", single_line=True) == "A B"


def test_preserves_multiline_when_not_single_line():
    text = markdown_to_plain_text("줄1\n\n줄2", single_line=False)
    assert "줄1" in text
    assert "줄2" in text
