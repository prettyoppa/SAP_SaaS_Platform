"""연동 개발 — FS·구현 산출물(비 ABAP) 백그라운드 생성."""

from __future__ import annotations

import json
from datetime import datetime

from crewai import Agent, Crew, Process, Task
from sqlalchemy.orm import joinedload

from . import models
from .agent_playbook import (
    PlaybookContext,
    STAGE_INTEGRATION_DELIVERABLE,
    STAGE_INTEGRATION_FS,
    build_playbook_addon,
    playbook_prompt_wrap,
)
from .database import SessionLocal
from .devtype_catalog import format_integration_impl_types_for_llm
from .integration_crew_adapter import integration_request_to_crew_rfp_dict
from .routers.interview_router import _conversation_list_for_llm

_MAX_JOB_LOG_CHARS = 48_000


def append_integration_job_log(ir_id: int, field: str, line: str) -> None:
    db = SessionLocal()
    try:
        ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == ir_id).first()
        if not ir:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts} UTC] {line}\n"
        cur = getattr(ir, field, None) or ""
        new = cur + entry
        if len(new) > _MAX_JOB_LOG_CHARS:
            new = new[-_MAX_JOB_LOG_CHARS:]
        setattr(ir, field, new)
        db.commit()
    finally:
        db.close()


def _ir_as_fake_rfp_for_conv(ir: models.IntegrationRequest):
    class _M:
        def __init__(self, m):
            self.id = m.id
            self.round_number = m.round_number
            self.questions_json = m.questions_json
            self.answers_text = m.answers_text
            self.is_answered = m.is_answered
            self.intra_state_json = m.intra_state_json

    class _F:
        messages: list

    f = _F()
    f.messages = [_M(m) for m in sorted(ir.interview_messages or [], key=lambda x: (x.round_number, x.id))]
    return f


def _fmt_conv_short(ir: models.IntegrationRequest) -> str:
    fake = _ir_as_fake_rfp_for_conv(ir)
    conv = _conversation_list_for_llm(fake)  # type: ignore[arg-type]
    if not conv:
        return "(인터뷰 없음)"
    parts = []
    for m in conv:
        parts.append(f"\n[{m['round_number']}라운드]")
        for i, q in enumerate(m.get("questions") or [], 1):
            parts.append(f"  Q{i}. {q}")
        if m.get("answers_text"):
            parts.append(f"  답변:\n  {m['answers_text']}")
    return "\n".join(parts)[:52000]


def run_integration_fs_job(ir_id: int) -> None:
    from .agents.free_crew import _get_llm

    db = SessionLocal()
    try:
        ir = (
            db.query(models.IntegrationRequest)
            .options(joinedload(models.IntegrationRequest.interview_messages))
            .filter(models.IntegrationRequest.id == ir_id)
            .first()
        )
        if not ir:
            append_integration_job_log(ir_id, "fs_job_log", "연동 요청을 찾을 수 없음")
            return
        append_integration_job_log(ir_id, "fs_job_log", "연동 FS 생성 시작")
        llm = _get_llm()
        impl = format_integration_impl_types_for_llm(db, ir.impl_types or "")
        rfp_dict = integration_request_to_crew_rfp_dict(db, ir)
        conv_txt = _fmt_conv_short(ir)
        prop = (ir.proposal_text or "").strip()[:72000]
        pb_fs = build_playbook_addon(
            db,
            PlaybookContext(
                entity="integration",
                stage=STAGE_INTEGRATION_FS,
                workflow_origin="integration_native",
            ),
        )
        _pb_fs = playbook_prompt_wrap(pb_fs)
        agent = Agent(
            role="비 ABAP 연동 기능명세(FS) 설계자",
            goal="VBA·Python·API·배치 등 외부 연동의 상세 설계 문서를 마크다운으로 작성한다",
            backstory="""당신은 SI에서 인터페이스·자동화·소규모 애플리케이션의 FS를 다수 작성한 설계자다.
SAP ABAP 소스 작성 지시가 아니라, **외부 런타임** 기준의 흐름·데이터·오류·보안·운영을 구체화한다.""",
            verbose=False,
            llm=llm,
            allow_delegation=False,
        )
        task = Task(
            description=f"""다음은 **SAP 연동(비 ABAP)** 요청과 인터뷰·제안서 맥락이다. 한국어 마크다운으로 **기능명세(FS)** 를 작성하라.
구현 형태: {impl or '—'}

### 요청 요약
{json.dumps(rfp_dict, ensure_ascii=False)[:12000]}

### 인터뷰 요약
{conv_txt}

### 제안서(참고)
{prop or '(없음)'}

필수 섹션: 범위·용어, 이해관계자/시나리오, 데이터 흐름, 인터페이스·인증, 예외·재시도, 로깅·모니터링, 배포·환경, 테스트·완료 기준, 오픈 이슈.
ABAP Report/Function 모듈 작성 지시는 쓰지 말고, 외부 코드·스크립트·서비스 관점으로만 기술한다.{_pb_fs}""",
            agent=agent,
            expected_output="마크다운 본문",
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        raw = str(crew.kickoff())
        ir.fs_text = raw.strip()
        ir.fs_status = "ready"
        ir.fs_generated_at = datetime.utcnow()
        ir.fs_error = None
        db.commit()
        append_integration_job_log(ir_id, "fs_job_log", "FS 저장 완료")
    except Exception as ex:
        ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == ir_id).first()
        if ir:
            ir.fs_status = "failed"
            ir.fs_error = str(ex)
            db.commit()
        append_integration_job_log(ir_id, "fs_job_log", f"실패: {type(ex).__name__}: {ex}")
    finally:
        db.close()


def run_integration_deliverable_job(ir_id: int) -> None:
    from .agents.free_crew import _get_llm

    db = SessionLocal()
    try:
        ir = (
            db.query(models.IntegrationRequest)
            .options(joinedload(models.IntegrationRequest.interview_messages))
            .filter(models.IntegrationRequest.id == ir_id)
            .first()
        )
        if not ir:
            append_integration_job_log(ir_id, "delivered_job_log", "연동 요청을 찾을 수 없음")
            return
        fs_body = (ir.fs_text or "").strip()
        if not fs_body:
            ir.delivered_code_status = "failed"
            ir.delivered_code_error = "FS가 없습니다."
            db.commit()
            return
        append_integration_job_log(ir_id, "delivered_job_log", "구현 산출물 생성 시작")
        llm = _get_llm()
        impl = format_integration_impl_types_for_llm(db, ir.impl_types or "")
        pb_g = build_playbook_addon(
            db,
            PlaybookContext(
                entity="integration",
                stage=STAGE_INTEGRATION_DELIVERABLE,
                workflow_origin="integration_native",
            ),
        )
        _pb_g = playbook_prompt_wrap(pb_g)
        agent = Agent(
            role="비 ABAP 연동 구현 가이드 작성자",
            goal="FS를 바탕으로 구현 체크리스트·폴더 구조·핵심 의사코드·설정 예시를 마크다운으로 제공한다",
            backstory="""실무 개발자가 바로 착수할 수 있도록 단계별 가이드를 쓴다.
완전한 프로덕션 코드 한 파일을 통째로 넣기보다는, 모듈 경계·시그니처·주의점·샘플 스니펫을 제공한다.""",
            verbose=False,
            llm=llm,
            allow_delegation=False,
        )
        task = Task(
            description=f"""구현 형태: {impl or '—'}

### 기능명세(FS)
{fs_body[:100000]}

### 제안서 요약
{(ir.proposal_text or '')[:24000]}

마크다운으로 **구현 가이드**를 작성하라. (제목에 [연동 구현 가이드] 포함)
포함: 디렉터리/패키지 제안, 주요 함수·클래스 스켈레톤, 환경변수·설정 예, 단위 테스트 포인트, SAP 측과의 계약(IDoc/RFC/REST 등)에서 주의할 점.
순수 ABAP 소스 전체를 요구하지 말고, 연동 대상 언어/런타임에 맞춘다.{_pb_g}""",
            agent=agent,
            expected_output="마크다운 본문",
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        raw = str(crew.kickoff())
        ir.delivered_code_text = raw.strip()
        ir.delivered_code_status = "ready"
        ir.delivered_code_generated_at = datetime.utcnow()
        ir.delivered_code_error = None
        db.commit()
        append_integration_job_log(ir_id, "delivered_job_log", "구현 산출물 저장 완료")
    except Exception as ex:
        ir = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == ir_id).first()
        if ir:
            ir.delivered_code_status = "failed"
            ir.delivered_code_error = str(ex)
            db.commit()
        append_integration_job_log(ir_id, "delivered_job_log", f"실패: {type(ex).__name__}: {ex}")
    finally:
        db.close()
