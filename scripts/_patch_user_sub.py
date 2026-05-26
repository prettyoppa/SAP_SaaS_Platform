from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "user_subscription.html"
text = p.read_text(encoding="utf-8")
marker = "    <div class=\"rfp-section p-3 mb-4\">\n      <h5 class=\"mb-3\">이번 달 사용량"
if "ai_usage_total_usd" in text:
    print("already patched")
    raise SystemExit(0)
insert = r'''    <motion class="rfp-section p-3 mb-4">
      <h5 class="mb-2">추정 AI 이용 비용 <span class="text-muted small fw-normal">(누적, 참고용)</span></h5>
      <p class="small text-muted">{{ ai_usage_disclaimer }}</p>
      <p class="mb-3">
        합계 <strong>{{ ai_usage_total_usd }}</strong>
        <span class="text-muted">(약 {{ ai_usage_total_krw }})</span>
        · 이벤트 {{ ai_usage_event_count }}건
      </p>
      {% if ai_usage_stage_rows|length > 0 %}
      <div class="ai-usage-stage-chart mb-0">
        {% for row in ai_usage_stage_rows %}
        <div class="ai-usage-stage-row mb-2">
          <div class="d-flex justify-content-between small mb-1">
            <span>{{ row.label }} <code class="text-muted">{{ row.stage }}</code></span>
            <span class="font-monospace">{{ row.usd }} <span class="text-muted">({{ row.pct }}%)</span></span>
          </div>
          <div class="progress" style="height: 8px;" role="presentation">
            <div class="progress-bar bg-primary" style="width: {% if row.pct > 100 %}100{% else %}{{ row.pct }}{% endif %}%;"></div>
          </div>
        </motion>
        {% endfor %}
      </div>
      {% else %}
      <p class="text-muted small mb-0">아직 기록된 AI 호출이 없습니다.</p>
      {% endif %}
    </div>

    {% if payment_claims|length > 0 %}
    <div class="rfp-section p-3 mb-4">
      <h5 class="mb-3">입금 신청 이력</h5>
      <div class="table-responsive">
        <table class="table table-sm">
          <thead><tr><th>일시</th><th>플랜</th><th>금액</th><th>상태</th></tr></thead>
          <tbody>
            {% for c in payment_claims %}
            <tr>
              <td class="small text-muted">{{ c.created_at|local_dt_span }}</td>
              <td><code>{{ c.plan_code }}</code></td>
              <td class="font-monospace small">{{ c.currency }} {{ "{:,}".format(c.amount_minor) }}</td>
              <td>{{ c.status }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <a href="/admin/payment-claims" class="btn btn-outline-secondary btn-sm">입금 신청 큐</a>
    </div>
    {% endif %}

'''
insert = insert.replace("motion", "div")
text = text.replace(marker, insert + marker, 1)
p.write_text(text, encoding="utf-8", newline="\n")
print("ok")
