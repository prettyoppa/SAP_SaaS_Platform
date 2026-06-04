"""테스트 시나리오 마크다운 — 구분선 행이 표 본문으로 노출되지 않음."""

from app.delivered_code_package import sanitize_test_scenarios_markdown
from app.proposal_markdown_html import markdown_to_html


def test_sanitize_drops_duplicate_md_table_separator_rows():
    md = """# 테스트 시나리오

| 케이스 ID | 목적 |
| --- | --- |
| :--- | :--- |
| --- | --- |
| TC01 | 프로그램 ID 확인 |
"""
    cleaned = sanitize_test_scenarios_markdown(md)
    assert "| :--- | :--- |" not in cleaned
    assert "| --- | --- |" not in cleaned
    assert "TC01" in cleaned


def test_markdown_html_skips_separator_only_table_rows():
    md = """# 테스트 시나리오

| 케이스 ID | 목적 | 사전 조건 |
| --- | --- | --- |
| :--- | :--- | :--- |
| TC01 | 프로그램 ID | REPNAM |
"""
    html = markdown_to_html(md)
    assert "TC01" in html
    assert "<td>---</td>" not in html
    assert "<td>:---</td>" not in html
    assert html.count("<tbody>") == 1
    assert html.count("<tr>") >= 2


def test_markdown_fenced_code_renders_chat_pre_block():
    md = """설명입니다.

```abap
IF lv_x IS INITIAL.
  CONCATENATE 'a' 'b' INTO lv_y.
ENDIF.
```

끝.
"""
    html = markdown_to_html(md)
    assert "chat-md-pre" in html
    assert "CONCATENATE" in html
    assert "```abap" not in html
