"""SE38/SE93 등 SAP GUI에서 납품 ABAP을 올리기 위한 상세 구현 가이드 프롬프트."""

from __future__ import annotations

from typing import Any


def build_se38_guide_task_description(
    *,
    program_id: str,
    transaction_code: str,
    slots_summary: str,
    fs_excerpt: str,
    coder_notes: str,
    member_safe_suffix: str,
) -> str:
    """납품 패키지 JSON·FS를 바탕으로 SE38 구현 가이드만 쓰도록 하는 Crew task 본문."""
    pid = (program_id or "").strip() or "(패키지 program_id 참고)"
    tcode = (transaction_code or "").strip()
    tcode_line = (
        f"고객 지정 T-Code: `{tcode}` — SE93 절에 반드시 이 코드를 사용한다."
        if tcode
        else "RFP에 T-Code가 없다. program_id와 동일한 이름으로 SE93 트랜잭션을 생성하는 절을 포함하되, 임의의 다른 코드는 만들지 않는다."
    )
    notes = (coder_notes or "").strip() or "(없음)"

    return f"""당신은 SAP ABAP 이행 컨설턴트다. 컨설턴트가 **로컬 ZIP의 .abap 파일**을 **SE38·SE93**에서 직접 붙여넣어 구현할 수 있도록,
**매우 구체적인 한국어 마크다운 가이드**만 작성하라.

운영·권한·배포·모니터링 일반론은 이 문서에 넣지 말고, `IMPLEMENTATION_GUIDE.md`를 참고하라고 한 줄만 안내한다.
ABAP 소스 전체를 반복 붙여넣지 말고, **파일명·객체명·수정 위치**를 가리킨다.

### 프로그램 ID
`{pid}`

### T-Code
{tcode_line}

### coder_notes (코더가 남긴 미결·주의)
{notes}

### 기능명세(FS) 발췌
{fs_excerpt}

### 납품 패키지 JSON (slots[].filename, role, title_ko, source 포함)
{slots_summary}

---

## 출력 형식 (필수)

- **마크다운 본문만**. 첫 제목: `# SE38 구현 가이드 — {pid}` (program_id가 있으면 그 값 사용).
- 상단 2~3문장: 이 문서 목적 + 운영·권한은 [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md), 테스트는 [TEST_SCENARIOS.md](TEST_SCENARIOS.md) 참고.
- 표·목록·번호 절을 사용한다. `---` 구분선 연속 나열 금지.

## 반드시 포함할 절 (번호·제목은 유사하면 됨)

1. **개요** — SAP 객체명 ↔ 로컬 `slots[].filename` 매핑 표, 기능 요약 3~6줄.
2. **사전 준비** — 개발 클라이언트, 패키지/오더, 최소 권한(S_DEVELOP 등), 로컬 파일 복사 준비.
3. **구현 순서(권장)** — 백그라운드/서브 프로그램 → Include → 메인 → Generate → SE93 → 테스트. ASCII 또는 mermaid 흐름도 1개.
4. **SE38 단계** — 슬롯 **role·filename 순**으로:
   - 프로그램 Create(Executable / Include 유형 명시)
   - 어느 `.abap` 파일 내용을 붙여넣는지
   - Activate / Syntax Check (Ctrl+F3 / Ctrl+F2) 안내
5. **텍스트 요소** — SE38 Goto → Text elements; FS·소스에서 보이는 TEXT-xxx, Selection texts, Message-ID 예시 표.
6. **SE38 구현 시 필수 수정(납품 소스 보완)** — JSON `source`를 읽고 **실제로 깨질 수 있는 불일치**를 찾아 기술:
   - MODULE vs PERFORM, Include 연결, MODIF ID, PF-STATUS, 화면 번호, JOB_SUBMIT 대상명 등.
   - 각 항목: 증상 → 조치 → 수정 전후 **짧은 ABAP 스니펫**(10~25줄 이내).
   - 문제가 없으면 해당 소스는 "그대로 사용 가능"이라고 명시.
7. **SE93 — 트랜잭션** — Report transaction, Program, Selection screen 번호.
8. **활성화·구문 점검 체크리스트** — 표(순서 | 작업 | 트랜잭션).
9. **단위 테스트(개발 시스템)** — [TEST_SCENARIOS.md](TEST_SCENARIOS.md) 참조 + 실행 5~10단계 요약 + 실패 시 빠른 원인 표.
10. **트랜스포트** — 포함할 객체 목록(Programs, Includes, Transaction).
11. **소스 파일 ↔ SAP 객체 매핑 요약** — 코드 블록 트리.

## 작성 규칙

- 슬롯에 없는 프로그램·Include는 **쓰지 말 것**. filename·REPORT/INCLUDE 문 두 줄이 실제 `source`와 맞는지 확인.
- `main_report` 외 role(top, pbo, pai, forms, screen, other)은 SAP Include/서브오브젝트 생성 순서를 논리적으로 배치.
- 백그라운드·JOB·AL11·SM37·FILE 등 FS/소스에 나오는 트랜잭션은 절차에 반드시 언급.
- 추측으로 표준 테이블·권한 객체를 지어내지 말고, 소스·FS에 근거가 있을 때만 적는다.
{member_safe_suffix}"""


def slots_program_id_hint(slots_obj: dict[str, Any]) -> str:
    return (str(slots_obj.get("program_id") or "")).strip()
