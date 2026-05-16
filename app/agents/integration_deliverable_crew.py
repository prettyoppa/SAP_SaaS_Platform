"""
연동 개발 — 납품 구현 산출물(비 ABAP).

RFP 납품 ABAP과 동일한 **다단계** 패턴: JSON 슬롯(파일 단위) → 검수 → 구현·운영 가이드 → 테스트 시나리오.
JSON이 실패하면 기존 단일 마크다운(단일 Crew)으로 폴백한다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from crewai import Agent, Crew, Process, Task

from ..agent_display import agent_label_ko
from ..agent_playbook import playbook_prompt_wrap
from ..delivered_code_package import (
    extract_json_object_from_llm_text,
    integration_delivered_package_has_body,
    legacy_markdown_from_integration_package,
    merge_integration_slots_json_with_extras,
    sanitize_test_scenarios_markdown,
)
from ..gemini_model import get_gemini_model_id
from ..ai_usage_recorder import logged_crew_kickoff
from .free_crew import _get_llm
from .paid_crew import _truncate

_INTEGRATION_MANIFEST_SOURCE_PREVIEW = 600


def _integration_slots_manifest_json(data: dict[str, Any], *, source_preview_chars: int = _INTEGRATION_MANIFEST_SOURCE_PREVIEW) -> str:
    """가이드·테스트 LLM용: 전체 source 대신 파일 목록·앞부분만 (토큰·지연 절감)."""
    slots_out: list[dict[str, Any]] = []
    for s in data.get("slots") or []:
        if not isinstance(s, dict):
            continue
        src = str(s.get("source") or "")
        preview = src[:source_preview_chars]
        if len(src) > source_preview_chars:
            preview += "\n…(이하 생략)"
        slots_out.append(
            {
                "role": s.get("role"),
                "filename": s.get("filename"),
                "title_ko": s.get("title_ko"),
                "source_chars": len(src),
                "source_preview": preview,
            }
        )
    return json.dumps(
        {
            "package_kind": data.get("package_kind") or "integration",
            "program_id": data.get("program_id"),
            "coder_notes": data.get("coder_notes"),
            "slots": slots_out,
        },
        ensure_ascii=False,
    )


def _monolithic_integration_markdown(
    *,
    fs_body: str,
    proposal_text: str,
    impl_disp: str,
    playbook_addon: str,
) -> str:
    """레거시: 단일 마크다운 구현 가이드(코드 펜스 남발 지양)."""
    llm = _get_llm()
    agent = Agent(
        role="비 ABAP 연동 구현 가이드 작성자",
        goal="FS를 바탕으로 구현 체크리스트·폴더 구조·핵심 의사코드·설정 예시를 마크다운으로 제공한다",
        backstory="""실무 개발자가 바로 착수할 수 있도록 단계별 가이드를 쓴다.
여러 파일로 나눌 내용이 있으면 마크다운 섹션과 소규모 펜스로 구분하되, 전체 프로젝트를 한 블록에 붙여 넣지 않는다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    _pb = playbook_prompt_wrap(playbook_addon)
    task = Task(
        description=f"""구현 형태: {impl_disp or '—'}

### 기능명세(FS)
{_truncate(fs_body, 100000)}

### 제안서 요약
{_truncate(proposal_text, 24000)}

마크다운으로 **구현 가이드**를 작성하라. (제목에 [연동 구현 가이드] 포함)
포함: 디렉터리/패키지 제안, 주요 모듈 경계, 환경변수·설정 예, 단위 테스트 포인트, SAP 측 계약에서 주의할 점.
순수 ABAP 전체 소스를 요구하지 말고, 연동 대상 언어/런타임에 맞춘다.{_pb}""",
        agent=agent,
        expected_output="마크다운 본문",
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return str(logged_crew_kickoff(crew, stage="integration_deliverable", agent_key="p_coder")).strip()


def generate_integration_deliverable_artifact(
    rfp_dict: dict[str, Any],
    fs_text: str,
    proposal_text: str,
    conv_text: str,
    impl_disp: str,
    *,
    playbook_addon: str = "",
    phase_log: Callable[[str], None] | None = None,
    impl_type_codes: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """
    연동 납품: JSON 슬롯 패키지 + 구현 가이드 + 테스트 (실패 시 단일 마크다운).
    """
    llm = _get_llm()

    def _ph(msg: str) -> None:
        if phase_log:
            phase_log(msg)

    fs_block = _truncate(fs_text or "", 96000)
    prop_snip = _truncate(proposal_text or "", 16000)
    conv_snip = _truncate(conv_text or "", 24000)
    req_title = (rfp_dict.get("title") or "integration").strip()
    desc_snip = _truncate((rfp_dict.get("description") or ""), 12000)
    ref_snip = _truncate((rfp_dict.get("reference_code_for_agents") or ""), 8000)
    _pb = playbook_prompt_wrap(playbook_addon)

    impl_lc = [x.strip().lower() for x in (impl_type_codes or []) if x.strip()]
    py_addon = ""
    if "python_script" in impl_lc:
        py_addon = """
### Python 스크립트 납품(구현 형태에 **python_script** 포함 — 추가 준수)
- **README.md** (**doc** 슬롯, 한국어): ZIP 해제 위치, `python -m venv`, `pip install -r requirements.txt`, 환경 변수 로딩, **실행 명령 한 줄**, Windows 작업 스케줄러·배치 실행 시 주의사항.
- **requirements.txt** (**requirements** 슬롯): FS에 맞는 패키지·최소 버전. SAP GUI 자동화(Windows) 시 `pywin32` 등이 필요할 수 있음을 반영.
- **.env.example** (**env_sample** 슬롯): `SAP_CLIENT`, `SAP_USER` 등 **키만** 두고 비밀 값은 비우거나 placeholder.
- **진입점**: `main.py` 등 **entry_script** 1개 이상. SAP Script Recording 적용·세션 제어·리포트 실행·파일 저장 로직은 **module** 슬롯으로 분리.
- 고객 비밀번호·내부 URL·절대 경로를 소스에 하드코딩하지 말 것. FS·인터뷰의 프로그램명·변형·경로와 일치시킬 것.
"""

    json_coder = Agent(
        role="비 ABAP 연동 시니어 개발자",
        goal="FS에 맞춰 파일 단위 산출물을 JSON 슬롯으로 납품한다",
        backstory="""풀스택·스크립트·API 연동 경험이 많다. 납품은 **파일(또는 논리 단위)별 슬롯**으로 나눈다.
하나의 슬롯에 src 전체를 몰아넣지 않는다. 진입 스크립트·모듈·설정·SQL·요구사항 목록 등으로 분리한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    guide_agent = Agent(
        role="연동 구현·운영 컨설턴트",
        goal="슬롯별 산출물을 설명하는 구현·운영 가이드를 한국어 마크다운으로 쓴다",
        backstory="""배포·비밀 관리·로깅·장애 대응을 실무 관점에서 정리한다. 소스 전체를 반복 붙여넣지 않는다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    test_agent = Agent(
        role="연동 테스트 설계자",
        goal="통합·회귀 테스트 시나리오를 한국어 마크다운으로 작성한다",
        backstory="""경계·오류·재시도·데이터 검증을 표로 정리한다.""",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )

    slot_task = Task(
        description=f"""다음 FS·요청·인터뷰를 근거로 **연동 개발 납품 패키지**를 JSON으로만 출력하라.
요청 제목: {req_title}

### 요청 본문(발췌)
{desc_snip}

### 인터뷰·맥락(발췌)
{conv_snip}

### 참고 코드·첨부(발췌, 원본이 아닌 힌트)
{ref_snip or '(없음)'}

### 제안서(발췌)
{prop_snip}

### 기능명세(FS)
{fs_block}

**필수 분리 규칙(위반 금지):**
- **절대** 여러 파일·모듈을 하나의 `source` 문자열에 합치지 말 것. `src/` 트리 전체를 한 슬롯에 넣지 말 것.
- **entry_script** 역할 슬롯 1개 이상: 실행·진입점(예: main.py, run.ps1).
- 모듈·라이브러리는 **module** / **library** 로 **파일별** 슬롯.
- 설정 예시는 **config** 또는 **env_sample**, 의존성 목록은 **requirements** (예: requirements.txt 내용).
- SQL 마이그레이션·쿼리는 **sql** 슬롯.
- 짧은 README 성격은 **doc** 슬롯(내용이 길면 여러 doc 슬롯으로 분할 가능).

출력: **JSON 한 개만** (앞뒤 설명 문장 금지). ```json 펜스 허용.

스키마:
{{
  "package_kind": "integration",
  "program_id": "짧은_식별자_영문_소문자_및_숫자",
  "slots": [
    {{
      "role": "entry_script",
      "filename": "main.py",
      "title_ko": "실행 진입점",
      "source": "#!/usr/bin/env python3\\n..."
    }}
  ],
  "coder_notes": "가정·미결 사항"
}}

`role`은 반드시 다음 중 하나:
entry_script, module, library, package_init, config, env_sample, sql, shell, vba,
requirements, manifest, test, doc, other

`filename`: 영문·숫자·언더스코어·점·하이픈; **실제 확장자** (.py .ps1 .sql .json .yaml .sh .md 등).
`source`: 해당 파일 **전체** 내용(UTF-8 텍스트). JSON 문자열 이스케이프 준수.
**구현 가이드·테스트 시나리오는 JSON에 넣지 않는다.**
{py_addon}
{_pb}""",
        agent=json_coder,
        expected_output="유효한 JSON 한 덩어리",
    )

    _ph(f"{agent_label_ko('p_coder')} — 연동 납품 JSON 슬롯 Gemini({get_gemini_model_id()}) 호출 시작")
    crew_slots = Crew(agents=[json_coder], tasks=[slot_task], process=Process.sequential, verbose=False)
    out_slots = str(logged_crew_kickoff(crew_slots, stage="integration_deliverable", agent_key="p_coder")).strip()
    _ph(f"{agent_label_ko('p_coder')} JSON 초안 완료 · 약 {len(out_slots)}자")

    # 검수 LLM은 3만+자 JSON 재출력 시 지연·멈춤이 잦아, 코더 초안을 직접 파싱한다.
    data = extract_json_object_from_llm_text(out_slots)
    if data:
        _ph("연동 JSON — 코더 초안 파싱 성공(검수 LLM 생략)")
    if not data:
        _ph("연동 JSON 파싱 실패 — 단일 마크다운 폴백")
        return None, _monolithic_integration_markdown(
            fs_body=fs_text,
            proposal_text=proposal_text,
            impl_disp=impl_disp,
            playbook_addon=playbook_addon,
        )

    if not (str(data.get("program_id") or "")).strip():
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in req_title.lower())[:48].strip("_") or "integration"
        data["program_id"] = safe

    slots_summary = _integration_slots_manifest_json(data)

    guide_task = Task(
        description=f"""아래 FS 발췌와 **연동 납품 JSON**(slots의 파일명·역할·소스 일부 맥락)을 읽고,
운영·이행 담당자를 위한 **구현·운영 가이드**만 작성하라.

### FS (발췌)
{_truncate(fs_block, 72_000)}

### 패키지 JSON
{slots_summary}

출력: **마크다운 본문만**. 첫 제목은 `# 구현·운영 가이드` 로 시작.
슬롯 파일명을 참조하되 소스 전체를 반복하지 마라.
""",
        agent=guide_agent,
        expected_output="구현·운영 가이드 마크다운",
    )
    _ph("연동 구현·운영 가이드 생성 — Gemini 호출")
    crew_g = Crew(agents=[guide_agent], tasks=[guide_task], process=Process.sequential, verbose=False)
    guide_md = str(logged_crew_kickoff(crew_g, stage="integration_deliverable", agent_key="p_coder")).strip()
    _ph("연동 구현·운영 가이드 완료")

    test_task = Task(
        description=f"""아래 FS 발췌와 연동 납품 JSON(slots)을 바탕으로 **테스트 시나리오**만 작성하라.

### FS (발췌)
{_truncate(fs_block, 56_000)}

### 패키지 JSON
{slots_summary}

출력: **마크다운 본문만**. 첫 제목은 `# 테스트 시나리오` 로 시작.
케이스 ID, 목적, 사전 조건, 단계, 기대 결과를 **하나의 마크다운 표**로 정리한다 (최대 18행).
표 위아래로 `---` 구분선을 연속 나열하지 마라.
""",
        agent=test_agent,
        expected_output="테스트 시나리오 마크다운",
    )
    _ph(f"{agent_label_ko('p_tester')} — 연동 테스트 시나리오 Gemini 호출 시작")
    crew_t = Crew(agents=[test_agent], tasks=[test_task], process=Process.sequential, verbose=False)
    test_md = sanitize_test_scenarios_markdown(
        str(logged_crew_kickoff(crew_t, stage="integration_deliverable", agent_key="p_tester")).strip()
    )
    _ph(f"{agent_label_ko('p_tester')} 연동 테스트 시나리오 완료")

    pkg = merge_integration_slots_json_with_extras(
        data,
        implementation_guide_md=guide_md,
        test_scenarios_md=test_md,
    )
    if not pkg or not integration_delivered_package_has_body(pkg):
        _ph("연동 패키지 정규화 후 본문 없음 — 단일 마크다운 폴백")
        return None, _monolithic_integration_markdown(
            fs_body=fs_text,
            proposal_text=proposal_text,
            impl_disp=impl_disp,
            playbook_addon=playbook_addon,
        )

    return pkg, legacy_markdown_from_integration_package(pkg)
