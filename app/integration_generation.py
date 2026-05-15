"""연동 개발 — FS·구현 산출물(비 ABAP) 백그라운드 생성."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

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
from .delivered_code_package import (
    _integration_pkg_needs_slot_expansion,
    ensure_python_script_delivery_package,
    expand_integration_monolithic_slots,
    integration_delivered_search_blurb,
    integration_delivered_package_has_body,
    integration_package_from_legacy_markdown,
)
from .devtype_catalog import format_integration_impl_types_for_llm
from .integration_crew_adapter import integration_request_to_crew_rfp_dict
from .routers.interview_router import _conversation_list_for_llm

_MAX_JOB_LOG_CHARS = 48_000


def integration_deliverable_job_stale(ir: models.IntegrationRequest, *, minutes: int = 10) -> bool:
    """generating 상태인데 로그가 오래 갱신되지 않으면 이전 작업이 멈춘 것으로 본다."""
    log = (getattr(ir, "delivered_job_log", None) or "").strip()
    if not log:
        return True
    matches = re.findall(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\]", log)
    if not matches:
        return True
    try:
        last_dt = datetime.strptime(matches[-1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return age_sec > minutes * 60
    except Exception:
        return True


def maybe_fail_stale_integration_deliverable(
    db,
    ir: models.IntegrationRequest,
    *,
    minutes: int = 10,
) -> models.IntegrationRequest:
    """generating 이 오래 지속되면 failed 로 전환해 UI·재시도가 가능하게 한다."""
    if (getattr(ir, "delivered_code_status", None) or "").strip() != "generating":
        return ir
    if not integration_deliverable_job_stale(ir, minutes=minutes):
        return ir
    ir.delivered_code_status = "failed"
    ir.delivered_code_error = (
        "구현 산출물 생성이 제한 시간 내에 완료되지 않았습니다. "
        "아래 「구현 산출물 재생성」을 다시 시도하세요."
    )
    append_integration_job_log(
        int(ir.id),
        "delivered_job_log",
        f"자동 중단: {minutes}분 이상 로그 갱신 없음",
    )
    db.commit()
    db.refresh(ir)
    return ir


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
    db = SessionLocal()
    ir: models.IntegrationRequest | None = None
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
        append_integration_job_log(ir_id, "delivered_job_log", "구현 산출물 생성 시작(파일 슬롯 패턴)")
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
        conv_txt = _fmt_conv_short(ir)
        rfp_dict = integration_request_to_crew_rfp_dict(db, ir)

        from .agents.integration_deliverable_crew import generate_integration_deliverable_artifact

        impl_codes = [x.strip() for x in (ir.impl_types or "").split(",") if x.strip()]
        pkg, legacy_md = generate_integration_deliverable_artifact(
            rfp_dict,
            fs_body,
            (ir.proposal_text or ""),
            conv_txt,
            impl,
            playbook_addon=_pb_g,
            phase_log=lambda m: append_integration_job_log(ir_id, "delivered_job_log", m),
            impl_type_codes=impl_codes,
        )
        if pkg:
            if _integration_pkg_needs_slot_expansion(pkg):
                pkg = expand_integration_monolithic_slots(pkg)
            pkg = ensure_python_script_delivery_package(
                pkg,
                request_title=(ir.title or "").strip(),
                impl_codes=impl_codes,
            )
        elif legacy_md:
            recovered = integration_package_from_legacy_markdown(
                legacy_md,
                program_id=(ir.title or "integration")[:48],
            )
            if recovered and integration_delivered_package_has_body(recovered):
                if _integration_pkg_needs_slot_expansion(recovered):
                    pkg = expand_integration_monolithic_slots(recovered)
                pkg = ensure_python_script_delivery_package(
                    pkg,
                    request_title=(ir.title or "").strip(),
                    impl_codes=impl_codes,
                )
                append_integration_job_log(
                    ir_id,
                    "delivered_job_log",
                    "레거시 마크다운에서 파일 슬롯 패키지 복구",
                )
        if pkg and integration_delivered_package_has_body(pkg):
            ir.delivered_code_payload = json.dumps(pkg, ensure_ascii=False)
            ir.delivered_code_text = integration_delivered_search_blurb(pkg)
        else:
            ir.delivered_code_payload = None
            ir.delivered_code_text = (legacy_md or "").strip()
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
        try:
            ir_fin = db.query(models.IntegrationRequest).filter(models.IntegrationRequest.id == ir_id).first()
            if ir_fin and (ir_fin.delivered_code_status or "").strip() == "generating":
                ir_fin.delivered_code_status = "failed"
                ir_fin.delivered_code_error = (
                    ir_fin.delivered_code_error or "작업이 비정상 종료되었습니다. 재생성을 시도하세요."
                )
                db.commit()
        except Exception:
            pass
        db.close()
