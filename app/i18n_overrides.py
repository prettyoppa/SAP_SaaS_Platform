"""UI i18n baseline (i18n.js 추출본) + EN 오버라이드 캐시 — 관리자 EN 편집·프론트 병합."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal

_BASELINE_PATH = Path(__file__).resolve().parent / "data" / "i18n_baseline.json"
_BASELINE_CACHE: dict[str, Any] | None = None

# (prefix, group_slug, group_title_ko, ai_context_ko) — 긴 prefix 우선 매칭
_GROUP_RULES: list[tuple[str, str, str, str]] = [
    ("nav.", "nav", "내비게이션", "상단 메뉴·로그인/로그아웃 링크 라벨"),
    ("footer.", "footer", "푸터", "사이트 하단 태그라인·저작권"),
    ("brand.", "brand", "브랜드명", "로고 옆 서비스 이름"),
    ("theme.", "theme", "테마", "다크/라이트 전환 접근성 문구"),
    ("hero.", "home_hero", "홈 히어로", "랜딩 상단 헤드라인·CTA"),
    ("how.", "home_how", "홈 이용 방법", "3단계 소개"),
    ("home.", "home", "홈·공지·리뷰", "홈 탭·타일·공지/FAQ/리뷰"),
    ("cta.", "home_cta", "홈 하단 CTA", "가입 유도 블록"),
    ("modules.", "home_modules", "홈 SAP 모듈", "지원 모듈 제목"),
    ("login.", "login", "로그인", "로그인 폼 라벨·오류"),
    ("register.", "register", "회원가입", "가입 폼 라벨·약관"),
    ("rfp.", "rfp", "신규 개발(RFP) 요청", "ABAP 개발 의뢰 작성 마법사"),
    ("mod.", "rfp_modules", "SAP 모듈 옵션", "RFP 폼 모듈 선택지"),
    ("dt.", "rfp_devtypes", "개발 유형 옵션", "RFP 폼 개발 유형 선택지"),
    ("dash.", "dashboard", "대시보드", "나의 요청 목록·필터·정렬"),
    ("status.", "status", "요청 상태", "상태 배지"),
    ("success.", "success", "제출 완료", "RFP 제출 직후 안내"),
    ("svcAbap.", "svc_abap", "ABAP 서비스 허브", "신규 개발 목록·검색 랜딩"),
    ("analysis.", "analysis", "ABAP 분석", "분석·개선 서비스·본문·메타"),
    ("integration.", "integration", "연동 개발", "연동 요청 랜딩"),
    ("common.", "common", "공통 버튼", "뒤로·저장·삭제 등"),
    ("listView.", "list_view", "목록/타일 보기", "표시 형식 전환"),
    ("phase.", "phase", "진행 단계", "요청 카드 단계 라벨"),
    ("badge.", "badge", "배지", "상태·종류 배지"),
    ("list.", "list_cols", "목록 컬럼", "테이블 헤더"),
    ("codelib.", "codelib", "코드 갤러리", "ABAP 코드 라이브러리"),
    ("hub.", "hub", "통합 허브(신규 개발)", "RFP 단계별 허브"),
    ("reqPanel.", "req_panel", "요청 패널", "통합 뷰 요약 패널"),
    ("detail.", "detail", "요청 상세", "분석·연동·RFP 상세 화면"),
    ("chat.", "chat", "AI 채팅", "후속 질문·문의 패널"),
    ("analysis.fold.", "analysis_fold", "분석 접기 블록", "분석 결과 섹션 제목"),
    ("landing.", "landing", "서비스 랜딩", "로그인 유도 한 줄"),
    ("plans.", "plans", "구독 플랜", "플랜 페이지 통화·접근성"),
    ("form.", "form", "작성 가이드", "가이드 패널"),
    ("app.", "app", "앱 공통", "확인 모달"),
    ("index.", "index", "홈 폴백", "설정 미로드 시 헤드라인"),
]

_DEFAULT_GROUP = (
    "misc",
    "기타",
    "기타 화면·공통 키",
)

_EN_OVERRIDE_CACHE: dict[str, str] | None = None
_EN_OVERRIDE_CACHE_AT: float = 0.0
_REVALIDATE_SEC = 60.0


def load_i18n_baseline() -> dict[str, dict[str, str]]:
    global _BASELINE_CACHE
    if _BASELINE_CACHE is None:
        raw = _BASELINE_PATH.read_text(encoding="utf-8")
        _BASELINE_CACHE = json.loads(raw)
        if "en" not in _BASELINE_CACHE or "ko" not in _BASELINE_CACHE:
            raise ValueError("i18n_baseline.json must contain en and ko")
    return _BASELINE_CACHE


_GROUP_RULES_LONGEST_FIRST = sorted(_GROUP_RULES, key=lambda t: len(t[0]), reverse=True)

# base.html 상단 바와 직접 연결되는 키는 접두사와 무관하게 한 그룹으로 묶음
_TOPNAV_GROUP = (
    "topnav",
    "상단 메인 메뉴 (base.html)",
    "홈·요청 Console·신규 개발·분석·연동·Admin 링크와 브랜드명. 이전에는 HTML에만 있어 i18n 목록에 안 나왔음.",
)
_MANUAL_KEY_GROUP: dict[str, tuple[str, str, str]] = {
    "brand.name": _TOPNAV_GROUP,
    "nav.home": _TOPNAV_GROUP,
    "nav.menuRequestConsole": _TOPNAV_GROUP,
    "nav.menuRequestConsoleHint": _TOPNAV_GROUP,
    "nav.menuNewDevelopment": _TOPNAV_GROUP,
    "nav.menuAnalysisImprove": _TOPNAV_GROUP,
    "nav.menuIntegration": _TOPNAV_GROUP,
    "nav.admin": _TOPNAV_GROUP,
}


def admin_group_for_key(key: str) -> tuple[str, str, str]:
    """(group_slug, group_title_ko, ai_blurb_ko)"""
    if key in _MANUAL_KEY_GROUP:
        return _MANUAL_KEY_GROUP[key]
    for prefix, slug, title, blurb in _GROUP_RULES_LONGEST_FIRST:
        if key.startswith(prefix):
            return slug, title, blurb
    return _DEFAULT_GROUP[0], _DEFAULT_GROUP[1], _DEFAULT_GROUP[2]


def build_admin_rows(db: Session) -> list[dict[str, Any]]:
    baseline = load_i18n_baseline()
    en_b = baseline.get("en") or {}
    ko_b = baseline.get("ko") or {}
    keys = sorted(set(en_b) | set(ko_b))
    ov: dict[str, str] = {}
    for r in db.query(models.UiI18nEnOverride).all():
        ov[r.key] = r.en_text or ""
    rows: list[dict[str, Any]] = []
    for k in keys:
        slug, title, blurb = admin_group_for_key(k)
        rows.append(
            {
                "key": k,
                "group_slug": slug,
                "group_title": title,
                "group_blurb": blurb,
                "ko": ko_b.get(k, ""),
                "en_builtin": en_b.get(k, ""),
                "en_override": ov.get(k, ""),
            }
        )
    rows.sort(key=lambda r: (r["group_slug"], r["key"]))
    return rows


def build_admin_grouped(db: Session) -> list[dict[str, Any]]:
    """관리자 화면용: 그룹 헤더 + 해당 키 행 목록."""
    rows = build_admin_rows(db)
    out: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for r in rows:
        s = r["group_slug"]
        if s not in index:
            index[s] = len(out)
            out.append(
                {
                    "group_slug": s,
                    "group_title": r["group_title"],
                    "group_blurb": r["group_blurb"],
                    "rows": [],
                }
            )
        out[index[s]]["rows"].append(r)
    return out


def get_en_overrides_for_client() -> dict[str, str]:
    """미들웨어용: 비어 있지 않은 오버라이드만. 짧은 TTL 캐시."""
    global _EN_OVERRIDE_CACHE, _EN_OVERRIDE_CACHE_AT
    now = time.monotonic()
    if _EN_OVERRIDE_CACHE is not None and (now - _EN_OVERRIDE_CACHE_AT) < _REVALIDATE_SEC:
        return _EN_OVERRIDE_CACHE
    db = SessionLocal()
    try:
        rows = db.query(models.UiI18nEnOverride).all()
        m = {r.key: (r.en_text or "").strip() for r in rows if (r.en_text or "").strip()}
        _EN_OVERRIDE_CACHE = m
        _EN_OVERRIDE_CACHE_AT = now
        return m
    finally:
        db.close()


def invalidate_en_overrides_cache() -> None:
    global _EN_OVERRIDE_CACHE
    _EN_OVERRIDE_CACHE = None
