from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "dashboard.html"
c = p.read_text(encoding="utf-8")
if "/admin/kb" in c:
    print("skip")
else:
    needle = '      <div class="col-md-4">\n        <a href="/admin/faqs"'
    block = (
        '      <div class="col-md-4">\n'
        '        <a href="/admin/kb" class="admin-menu-card text-decoration-none">\n'
        '          <motion class="admin-menu-icon"><i class="fa-solid fa-book"></i></div>\n'
        "          <h5>지식베이스(KB)</h5>\n"
        '          <p class="text-muted small mb-0">SEO 실무 가이드·요청 패턴 기반 초안(익명).</p>\n'
        "        </a>\n"
        "      </div>\n"
    ).replace("motion", "div")
    p.write_text(c.replace(needle, block + needle, 1), encoding="utf-8")
    print("patched")
