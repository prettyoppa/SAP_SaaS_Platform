from pathlib import Path

D = "d" + "iv"

p = Path(__file__).resolve().parents[1] / "app/templates/account_ai_credits.html"
t = p.read_text(encoding="utf-8")
start = t.index(f'      <{D} class="row g-2 mb-3 account-ai-credits-usage-summary">')
end = t.index("      {% if ai_usage_stage_rows|length > 0 %}")
new = (
    f'      <{D} class="row g-2 mb-3 account-ai-credits-usage-summary">\n'
    f'        <{D} class="col-md-6">\n'
    f'          <{D} class="account-ai-credits-stat p-2 rounded">\n'
    f'            <{D} class="small text-muted"><span class="nav-ko">누적 추정 사용</span><span class="nav-en" style="display:none">Estimated usage (total)</span></{D}>\n'
    f'            <{D} class="font-monospace fw-semibold">₩{{ "{{:,}}".format(ai_usage_total_krw_int) }}</{D}>\n'
)
# simpler: read template snippet from file
snippet = Path(__file__).with_name("_usage_summary_snippet.html").read_text(encoding="utf-8")
p.write_text(t[:start] + snippet + t[end:], encoding="utf-8", newline="\n")
print("patched", p)
