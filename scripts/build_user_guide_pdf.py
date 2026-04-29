# -*- coding: utf-8 -*-
"""홈 [사용 안내] 타일용 user-guide.pdf 생성 (테스트·배포 전 재생성 가능).

한글 폰트: Windows 맑은 고딕(malgun.ttf) 또는 app/static/fonts/NotoSansKR-Regular.ttf
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "docs" / "user-guide.pdf"


def _find_korean_font() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.ttf",
        ROOT / "app" / "static" / "fonts" / "NotoSansKR-Regular.otf",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def main() -> int:
    try:
        from fpdf import FPDF
    except ImportError:
        print("pip install fpdf2 로 패키지를 설치한 뒤 다시 실행하세요.", file=sys.stderr)
        return 1

    font_path = _find_korean_font()
    if not font_path:
        print(
            "한글 폰트를 찾을 수 없습니다. "
            "Windows에서는 보통 C:\\Windows\\Fonts\\malgun.ttf 가 있습니다.",
            file=sys.stderr,
        )
        return 1

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_font("Ko", "", str(font_path))
    pdf.set_font("Ko", size=11)

    sections: list[tuple[str, str]] = [
        (
            "1. 이 서비스는 무엇인가요?",
            """본 사이트는 SAP ABAP 개발 요청을 정리하고, AI 에이전트가 인터뷰를 진행한 뒤 개발 제안서(Development Proposal) 초안을 만들어 주는 허브입니다.
회원가입 후 로그인하면 개발 요청 제출, 인터뷰 참여, 제안서 확인 등 무료 기능을 이용할 수 있습니다.""",
        ),
        (
            "2. 시작하기",
            """· 회원가입 / 로그인: 상단 메뉴에서 진행합니다.
· 환경: AI 인터뷰·제안서 생성에는 서버에 설정된 Google Gemini(API 키 등)가 필요합니다.""",
        ),
        (
            "3. 홈 화면",
            """· 사용 안내: 이용 방법 PDF(본 문서) 또는 관리자가 지정한 URL로 연결됩니다.
· 신규 개발 · 분석&개선 · 연동 개발: 각 서비스 안내 페이지로 이동합니다.
· 로그인 시 타일 하단에 진행 상태(납품·제안·분석·진행중·임시저장 등) 건수가 표시될 수 있습니다.""",
        ),
        (
            "4. 신규 개발 (요약)",
            """SAP 모듈·개발 유형을 선택하고 요구사항과 참고 ABAP·첨부를 제출합니다(RFP).
제출 후 AI 인터뷰(여러 라운드)를 거친 뒤 제안서가 생성되며, 필요하면 수정·재생성할 수 있습니다.""",
        ),
        (
            "5. 분석&개선",
            """기존 ABAP 코드와 요구사항을 제출하면 코드 구조 분석과 요구사항 연계 해석을 제공합니다.
여러 프로그램을 올린 경우 프로그램별로 구분되어 표시되고, 프로그램 안에서는 서브프로그램(섹션)별 탭으로 코드를 볼 수 있습니다.""",
        ),
        (
            "6. 연동 개발",
            """VBA·배치·API 등 SAP 외부와의 연동 요청을 접수합니다.
업로드한 참고 ABAP도 프로그램·서브프로그램 구조로 조회됩니다.""",
        ),
        (
            "7. 코드 갤러리",
            """관리자가 등록한 ABAP 예제를 검색·열람할 수 있습니다.
인터뷰 1라운드 등에서 코드 라이브러리와 매칭되면 질문 생성에 활용될 수 있습니다.""",
        ),
        (
            "8. 공지 · FAQ · 이용후기",
            """홈 상단 탭에서 공지사항, FAQ, 이용후기를 확인합니다.""",
        ),
        (
            "9. 유료 영역 (예정)",
            """상세 기능 명세(FS) 작성, 최종 ABAP 코드 납품 등은 서비스 정책에 따라 유료 단계로 제공될 수 있습니다.""",
        ),
        (
            "10. 문의",
            """관리자 기능·사이트 설정은 운영 정책에 따릅니다.
본 문서는 테스트용 안내이며, 실제 서비스 명칭·메뉴는 배포 버전에 맞게 변경될 수 있습니다.""",
        ),
    ]

    pdf.add_page()
    pdf.set_font("Ko", size=18)
    pdf.multi_cell(0, 10, "SAP 개발 파트너 · 이용 안내 (테스트용)")
    pdf.ln(4)
    pdf.set_font("Ko", size=9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, "본 문서는 개발·테스트 목적으로 자동 생성되었습니다.")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    pdf.set_font("Ko", size=11)
    for title, body in sections:
        pdf.set_font("Ko", size=12)
        pdf.multi_cell(0, 7, title)
        pdf.ln(1)
        pdf.set_font("Ko", size=11)
        pdf.multi_cell(0, 6, body)
        pdf.ln(5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
