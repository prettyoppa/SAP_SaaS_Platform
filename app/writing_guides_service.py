"""
요청 폼 「작성 가이드」 — 언어별(ko/en) 기본값 + SiteSettings(writing_guide.{lang}.{logical_key}).
레거시 키 writing_guide.{logical_key} (언어 없음)은 한국어 오버레이로 취급한다.
관리자는 각 폼 화면에서 인라인 편집 후 /admin/api/writing-guide 로 저장한다.
"""

from __future__ import annotations

import re
from functools import lru_cache

import markdown
from markdownify import markdownify as html_to_markdown
from sqlalchemy.orm import Session

from . import models

SITE_PREFIX = "writing_guide."

_LANG_KEY_RE = re.compile(r"^writing_guide\.(ko|en)\.(.+)$")

# 논리 키 → 한국어 HTML 기본
WRITING_GUIDE_DEFAULTS_KO: dict[str, str] = {
    "integration.s01_header": (
        "<p class='mb-0'>구현 형태(칩)를 먼저 고른 뒤, 외부 시스템·SAP와 어떻게 맞물리는지 한 문장이라도 "
        "제목에 드러나도록 적어 주시면 라우팅·검토가 수월합니다.</p>"
    ),
    "integration.s02_intro": (
        "<p class='mb-2'>아래 항목은 <strong>역할 분리</strong>를 위한 것입니다. "
        "한 칸에만 몰아 적어도 되고, 빈 칸은 그대로 두셔도 됩니다.</p>"
        "<ul class='mb-0 ps-3'><li>SAP 접점 / 인터페이스: 데이터가 오가는 경로·주기</li>"
        "<li>실행 환경: OS, 런타임(Excel·Python 등), 배치/대화형 여부</li>"
        "<li>상세 설명: 목표·제약·예외 처리·기한</li></ul>"
    ),
    "integration.guide_touch": (
        "<p class='mb-2'>RFC/BAPI/IDoc·파일 배치·DB 링크·화면 연동 등 <strong>연결 방식</strong>과 "
        "<strong>대표 트랜잭션·객체명</strong>을 적어 주세요. 정확한 기술명이 없으면 업무 절차 기준으로 서술해도 됩니다.</p>"
        "<ul class='mb-0 ps-3'><li>입력·출력 데이터 범위(마스터/트랜잭션)</li>"
        "<li>동기/비동기, 실시간 vs 야간 배치</li>"
        "<li>UI·샘플 파일은 03절 첨부로 제공</li></ul>"
    ),
    "integration.guide_env": (
        "<p class='mb-2'>배포·운영 시 기준이 되는 <strong>실행 주체</strong>(사용자 PC, 전용 서버, 클라우드 등)와 "
        "<strong>버전·비트수·권한 상승 필요 여부</strong>를 명시해 주세요.</p>"
        "<ul class='mb-0 ps-3'><li>개발/검증/운영 환경이 다르면 구분 기재</li>"
        "<li>SAP GUI·Office·런타임 버전</li>"
        "<li>방화벽·프록시·VPN 등 네트워크 제약이 있으면 요약</li></ul>"
    ),
    "integration.guide_desc": (
        "<p class='mb-2'>현재(as-is)와 목표(to-be), <strong>오류·재처리·감사</strong> 요구를 중심으로 서술해 주세요. "
        "에이전트·검토자가 맥락을 잃지 않도록 식별 가능한 업무명·문서 번호가 있으면 함께 적습니다.</p>"
        "<ul class='mb-0 ps-3'><li>처리량·피크 시간·허용 지연</li>"
        "<li>데이터 보존·마스킹·로그 정책</li>"
        "<li>레거시 대체 범위 vs 단기 우회</li></ul>"
    ),
    "integration.s03_attach": (
        "<p class='mb-0'>스펙·와이어프레임·기존 매크로/스크립트, 샘플 입·출력 파일을 첨부하면 "
        "모호한 서술을 보완할 수 있습니다. 파일명 규칙이 있으면 본문에 한 줄로 안내해 주세요.</p>"
    ),
    "integration.s04_ref_policy": (
        "<p class='mb-2'>회원이 제출하는 코드·스크립트는 <strong class=\"text-primary\">해당 요청의 이해·검토·"
        "제안·분석</strong> 목적으로만 활용됩니다. "
        "<strong class=\"text-danger\">광고, 제3자 제공, 생성형 AI 모델의 학습·재학습</strong> 등 그 밖의 용도로는 사용하지 않습니다.</p>"
        "<p class='mb-0'>회원이 직접 삭제하신 경우 <strong class=\"text-warning\">지체 없이 복구 불가능한 방식으로 "
        "삭제</strong>합니다.</p>"
    ),
    "shared.s01_header": (
        "<p class='mb-0'>프로그램 ID·T-code·모듈·개발 유형은 이후 자동 분석·제안 파이프라인의 "
        "<strong>식별·분류</strong>에 쓰입니다. 조직 표준 네이밍이 있으면 그에 맞춰 주세요.</p>"
    ),
    "shared.field_title": (
        "<p class='mb-0'>요구 범위가 드러나도록 <strong>대상 프로그램·업무</strong>를 한 줄로 요약합니다.</p>"
    ),
    "shared.s02_rfp_body": (
        "<p class='mb-2'>기능 범위, 입력·출력, 검증 규칙, 권한, 성능·배치 조건을 "
        "<strong>재현 가능한 수준</strong>으로 적어 주세요. 화면 ID·테이블·메시지 번호가 있으면 병기합니다.</p>"
        "<p class='mb-0 text-muted small'>상세할수록 인터뷰·제안서 품질에 유리합니다.</p>"
    ),
    "shared.s02_abap_body": (
        "<p class='mb-2'>개선 목표, 재현 절차, 증상(덤프·오류 메시지·데이터 이상), "
        "기대 동작·비기능 요구(성능·권한)를 구분해 서술해 주세요.</p>"
        "<p class='mb-0 text-muted small'>임시저장 시 본문은 비워 둘 수 있으나, 제출·분석 전에는 충분한 분량이 필요합니다.</p>"
    ),
    "shared.s03_attach": (
        "<p class='mb-2'>명세서, 스크린샷, 샘플 데이터, 기존 운영 문서 등을 첨부하면 요구 해석의 정확도가 올라갑니다. "
        "민감 정보는 마스킹 후 업로드해 주세요.</p>"
        "<p class='mb-0 text-muted small'>업로드 후 목록에서 파일마다 한 줄 설명을 달 수 있으며, 드래그로 여러 번 추가할 수 있습니다.</p>"
    ),
    "shared.s04_ref_policy_rfp": (
        "<p class='mb-2'>회원이 제출하는 참고 ABAP는 <strong class=\"text-primary\">해당 요청 이해 및 "
        "제안서 작성</strong>에만 사용됩니다. "
        "<strong class=\"text-danger\">광고, 제3자 제공, AI 모델 학습·재학습</strong> 등에는 사용하지 않습니다.</p>"
        "<p class='mb-0'>회원이 직접 삭제하신 경우 <strong class=\"text-warning\">지체 없이 복구 불가능한 방식으로 "
        "삭제</strong>합니다.</p>"
    ),
    "shared.s04_ref_policy_abap": (
        "<p class='mb-2'>회원이 제출하는 참고 ABAP는 <strong class=\"text-primary\">해당 요청 이해 및 "
        "분석·제안</strong>에만 사용됩니다. "
        "<strong class=\"text-danger\">광고, 제3자 제공, AI 모델 학습·재학습</strong> 등에는 사용하지 않습니다.</p>"
        "<p class='mb-0'>회원이 직접 삭제하신 경우 <strong class=\"text-warning\">지체 없이 복구 불가능한 방식으로 "
        "삭제</strong>합니다.</p>"
    ),
    "shared.field_program_id": (
        "<p class='mb-0'>SAP 네임스페이스 규칙을 준수하는 <strong>영문·숫자·밑줄</strong> 위주의 ID를 입력합니다. "
        "한글·전각 기호 등 IME 입력은 허용되지 않습니다.</p>"
    ),
    "shared.field_transaction": (
        "<p class='mb-0'>대표 진입 트랜잭션이 있으면 기재합니다. 없거나 불명확하면 비워 두어도 됩니다.</p>"
    ),
    "shared.field_modules": (
        "<p class='mb-0'>업무 도메인을 대표하는 모듈을 <strong>최대 3개</strong>까지 선택합니다. "
        "복합 업무면 주·부 모듈 순으로 고릅니다.</p>"
    ),
    "shared.field_devtypes": (
        "<p class='mb-0'>Report/ALV, 인터페이스, 배치, Fiori 연동 등 <strong>최대 3개</strong> 유형을 선택합니다.</p>"
    ),
    "shared.ref_slot_agent_note": (
        "<p class='mb-0'>01절에서 입력한 프로그램 ID·T-code·모듈·개발 유형과 본 소스를 함께 보고 "
        "에이전트가 맥락을 파악합니다. 여기서는 <strong>참고할 소스 구조</strong>만 정리하면 됩니다.</p>"
    ),
}

WRITING_GUIDE_DEFAULTS_EN: dict[str, str] = {
    "integration.s01_header": (
        "<p class='mb-0'>Pick implementation types first, then make the title reflect how the external system "
        "interfaces with SAP so routing and review stay efficient.</p>"
    ),
    "integration.s02_intro": (
        "<p class='mb-2'>The fields below are <strong>separated by concern</strong>. You may concentrate content "
        "in one field; empty optional fields are fine.</p>"
        "<ul class='mb-0 ps-3'><li>SAP touchpoints / interfaces: data paths and cadence</li>"
        "<li>Runtime: OS, Excel/Python/etc., batch vs interactive</li>"
        "<li>Description: goals, constraints, exceptions, deadlines</li></ul>"
    ),
    "integration.guide_touch": (
        "<p class='mb-2'>Describe the <strong>integration style</strong> (RFC/BAPI/IDoc, file batch, DB link, UI automation) "
        "and <strong>representative transactions or object names</strong>. Business-level wording is acceptable if technical names are unknown.</p>"
        "<ul class='mb-0 ps-3'><li>Input/output scope (master vs transactional)</li>"
        "<li>Sync/async, real-time vs overnight batch</li>"
        "<li>Place UI mock-ups and samples under attachments (section 03)</li></ul>"
    ),
    "integration.guide_env": (
        "<p class='mb-2'>State the <strong>execution host</strong> (user PC, dedicated server, cloud) and "
        "<strong>versions, bitness, elevation requirements</strong> that matter for deployment.</p>"
        "<ul class='mb-0 ps-3'><li>Split dev/test/prod if they differ</li>"
        "<li>SAP GUI, Office, runtime versions</li>"
        "<li>Summarize firewall/proxy/VPN constraints if any</li></ul>"
    ),
    "integration.guide_desc": (
        "<p class='mb-2'>Focus on as-is vs to-be, plus <strong>errors, reprocessing, and audit</strong> expectations. "
        "Include traceable business names or document IDs when available.</p>"
        "<ul class='mb-0 ps-3'><li>Volume, peak windows, latency tolerance</li>"
        "<li>Retention, masking, logging policies</li>"
        "<li>Legacy replacement scope vs short-term workaround</li></ul>"
    ),
    "integration.s03_attach": (
        "<p class='mb-0'>Specs, wireframes, existing macros/scripts, and sample I/O files reduce ambiguity. "
        "Add a one-line naming convention in the narrative if your organization uses one.</p>"
    ),
    "integration.s04_ref_policy": (
        "<p class='mb-2'>Submitted code/scripts are used only to <strong class=\"text-primary\">understand, review, "
        "propose, and analyze</strong> this request. "
        "They are <strong class=\"text-danger\">not</strong> used for advertising, third-party sharing, or training/fine-tuning generative AI models.</p>"
        "<p class='mb-0'>If you delete them yourself, we remove the content <strong class=\"text-warning\">promptly and irrecoverably</strong>.</p>"
    ),
    "shared.s01_header": (
        "<p class='mb-0'>Program ID, T-code, modules, and dev types feed downstream <strong>identification and "
        "classification</strong>. Follow your organization’s naming standards when applicable.</p>"
    ),
    "shared.field_title": (
        "<p class='mb-0'>Summarize the <strong>target program and business scope</strong> in one clear line.</p>"
    ),
    "shared.s02_rfp_body": (
        "<p class='mb-2'>Describe functional scope, inputs/outputs, validation rules, authorizations, and performance/batch "
        "constraints at a <strong>reproducible</strong> level. Add screen IDs, tables, or message numbers when helpful.</p>"
        "<p class='mb-0 text-muted small'>More detail generally improves interview and proposal quality.</p>"
    ),
    "shared.s02_abap_body": (
        "<p class='mb-2'>Separate improvement goals, reproduction steps, symptoms (dumps, messages, data anomalies), "
        "expected behaviour, and non-functional needs (performance, authority).</p>"
        "<p class='mb-0 text-muted small'>Drafts may leave this empty, but substantive text is required before submit/analysis.</p>"
    ),
    "shared.s03_attach": (
        "<p class='mb-2'>Specifications, screenshots, sample data, and runbooks improve interpretation accuracy. "
        "Mask sensitive data before upload.</p>"
        "<p class='mb-0 text-muted small'>After upload you can add a one-line note per file and append files via drag-and-drop.</p>"
    ),
    "shared.s04_ref_policy_rfp": (
        "<p class='mb-2'>Submitted reference ABAP is used only to <strong class=\"text-primary\">understand the request and "
        "author the proposal</strong>. "
        "It is <strong class=\"text-danger\">not</strong> used for ads, third-party sharing, or AI model training/retraining.</p>"
        "<p class='mb-0'>If you delete it yourself, we remove it <strong class=\"text-warning\">promptly and irrecoverably</strong>.</p>"
    ),
    "shared.s04_ref_policy_abap": (
        "<p class='mb-2'>Submitted reference ABAP is used only for <strong class=\"text-primary\">request understanding and "
        "analysis/proposal</strong>. "
        "It is <strong class=\"text-danger\">not</strong> used for ads, third-party sharing, or AI model training/retraining.</p>"
        "<p class='mb-0'>If you delete it yourself, we remove it <strong class=\"text-warning\">promptly and irrecoverably</strong>.</p>"
    ),
    "shared.field_program_id": (
        "<p class='mb-0'>Use an ID aligned with SAP namespace rules—primarily <strong>letters, digits, underscore</strong>. "
        "IME scripts for CJK input are not allowed in this field.</p>"
    ),
    "shared.field_transaction": (
        "<p class='mb-0'>Provide the main entry transaction if known; otherwise leave blank.</p>"
    ),
    "shared.field_modules": (
        "<p class='mb-0'>Select up to <strong>three</strong> modules that best represent the domain. Order primary then secondary.</p>"
    ),
    "shared.field_devtypes": (
        "<p class='mb-0'>Choose up to <strong>three</strong> types such as Report/ALV, interface, batch, or Fiori-related work.</p>"
    ),
    "shared.ref_slot_agent_note": (
        "<p class='mb-0'>Agents combine section 01 identifiers with this source. Organize only the <strong>reference "
        "source structure</strong> here.</p>"
    ),
}

LOGICAL_KEYS: frozenset[str] = frozenset(WRITING_GUIDE_DEFAULTS_KO.keys())

assert LOGICAL_KEYS == frozenset(WRITING_GUIDE_DEFAULTS_EN.keys())


@lru_cache(maxsize=1)
def _defaults_markdown_ko() -> dict[str, str]:
    return {
        k: html_to_markdown(html, heading_style="ATX").strip()
        for k, html in WRITING_GUIDE_DEFAULTS_KO.items()
    }


@lru_cache(maxsize=1)
def _defaults_markdown_en() -> dict[str, str]:
    return {
        k: html_to_markdown(html, heading_style="ATX").strip()
        for k, html in WRITING_GUIDE_DEFAULTS_EN.items()
    }


def site_key_for(lang: str, logical_key: str) -> str:
    return f"{SITE_PREFIX}{lang}.{logical_key}"


def _looks_like_legacy_html(s: str) -> bool:
    t = (s or "").strip()
    if not t.startswith("<"):
        return False
    head = t[:1200].lower()
    return any(
        tag in head
        for tag in ("<p", "<div", "<ul", "<ol", "<h1", "<h2", "<h3", "<section", "<table", "<blockquote")
    )


def normalize_guide_value_to_markdown(raw: str | None) -> str:
    """DB에 HTML로 남아 있던 값은 Markdown으로 정규화."""
    s = (raw or "").strip()
    if not s:
        return ""
    if _looks_like_legacy_html(s):
        return html_to_markdown(s, heading_style="ATX").strip()
    return s


def render_markdown_to_display_html(md: str | None) -> str:
    if not (md or "").strip():
        return ""
    return markdown.markdown(
        (md or "").strip(),
        extensions=["fenced_code", "tables", "nl2br"],
    )


def _defaults_md_for(lang: str) -> dict[str, str]:
    if lang == "en":
        return dict(_defaults_markdown_en())
    return dict(_defaults_markdown_ko())


def _apply_row_md(out: dict[str, str], site_key: str, value: str | None, target_lang: str) -> None:
    m = _LANG_KEY_RE.match(site_key or "")
    if m:
        lang, logical = m.group(1), m.group(2)
        if lang != target_lang:
            return
        if logical in out and (value or "").strip():
            out[logical] = normalize_guide_value_to_markdown(value)
        return
    if target_lang != "ko":
        return
    if (site_key or "").startswith(SITE_PREFIX):
        legacy = site_key[len(SITE_PREFIX) :]
        if legacy in ("ko", "en"):
            return
        if legacy.startswith("ko.") or legacy.startswith("en."):
            return
        if legacy in out and (value or "").strip():
            out[legacy] = normalize_guide_value_to_markdown(value)


def get_writing_guides_md_for_lang(db: Session, lang: str) -> dict[str, str]:
    """논리 키 → Markdown 원문(관리자 편집·저장 기준)."""
    lang = "en" if (lang or "").lower().startswith("en") else "ko"
    out = _defaults_md_for(lang)
    rows = db.query(models.SiteSettings).filter(models.SiteSettings.key.startswith(SITE_PREFIX)).all()
    for r in rows:
        _apply_row_md(out, r.key or "", r.value, lang)
    return out


def get_writing_guides_by_lang_bundle(db: Session) -> dict[str, dict[str, dict[str, str]]]:
    """ko/en 각각 { md: 논리키→Markdown, display: 논리키→HTML(회원용) }."""
    ko = get_writing_guides_md_for_lang(db, "ko")
    en = get_writing_guides_md_for_lang(db, "en")
    return {
        "ko": {
            "md": ko,
            "display": {k: render_markdown_to_display_html(v) for k, v in ko.items()},
        },
        "en": {
            "md": en,
            "display": {k: render_markdown_to_display_html(v) for k, v in en.items()},
        },
    }


def save_writing_guide_bilingual(
    db: Session,
    *,
    logical_key: str,
    md_ko: str | None,
    md_en: str | None,
) -> None:
    if logical_key not in LOGICAL_KEYS:
        raise ValueError("unknown_writing_guide_key")

    def _upsert(lang: str, body: str | None):
        sk = site_key_for(lang, logical_key)
        row = db.query(models.SiteSettings).filter(models.SiteSettings.key == sk).first()
        val = (body or "").strip()
        if not val:
            if row:
                db.delete(row)
            return
        if row:
            row.value = val
        else:
            db.add(models.SiteSettings(key=sk, value=val))

    _upsert("ko", md_ko)
    _upsert("en", md_en)
    db.commit()
