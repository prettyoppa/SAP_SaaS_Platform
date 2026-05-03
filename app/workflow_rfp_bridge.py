"""분석·연동 요청 → 신규 개발(RFP) 워크플로 연결: 제안서 생성용 시드 및 RFP 생성."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from . import models
from .attachment_context import build_attachment_llm_digest
from .rfp_reference_code import normalize_reference_code_payload

if TYPE_CHECKING:
    pass


def _pick_default_module_devtype_codes(db: Session) -> tuple[str, str]:
    """모듈·개발유형 미선택 RFP 제출용: 활성 목록 첫 항목."""
    mod = (
        db.query(models.SAPModule)
        .filter(models.SAPModule.is_active == True)
        .order_by(models.SAPModule.sort_order)
        .first()
    )
    dt = (
        db.query(models.DevType)
        .filter(models.DevType.is_active == True)
        .order_by(models.DevType.sort_order)
        .first()
    )
    mc = (getattr(mod, "code", None) or "MM").strip()
    dc = (getattr(dt, "code", None) or "Report_ALV").strip()
    return mc, dc


def _first_slot_program_meta(payload_raw: str | None) -> tuple[str, str]:
    raw = normalize_reference_code_payload(payload_raw)
    if not raw:
        return "", ""
    try:
        data = json.loads(raw)
    except Exception:
        return "", ""
    slots = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots, list) or not slots:
        return "", ""
    s0 = slots[0] if isinstance(slots[0], dict) else {}
    return (str(s0.get("program_id") or "").strip()[:40], str(s0.get("transaction_code") or "").strip()[:40])


def _requirement_analysis_text_for_seed(analysis_json_raw: str | None, limit: int = 8000) -> str:
    """analysis_json 내 requirement_analysis 블록을 제안서 시드용 텍스트로 축약."""
    if not analysis_json_raw or not str(analysis_json_raw).strip():
        return ""
    try:
        data = json.loads(analysis_json_raw)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    ra = data.get("requirement_analysis")
    if not isinstance(ra, dict):
        return ""
    chunks: list[str] = []
    order = [
        ("interpretation", "요구사항 해석"),
        ("mapping", "코드와의 연관"),
        ("suspected_areas", "살펴볼 만한 위치"),
        ("hypotheses", "가설"),
        ("verification_suggestions", "검증 제안"),
        ("open_questions", "추가 확인 질문"),
    ]
    for key, title in order:
        val = ra.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            body = "\n".join(f"- {str(x).strip()}" for x in val if str(x).strip())
        else:
            body = str(val).strip()
        if body:
            chunks.append(f"#### {title}\n{body}")
    if not chunks:
        return ""
    text = "\n\n".join(chunks)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…(이하 생략)…"


def _trim_analysis_json(raw: str | None, limit: int = 28_000) -> str:
    if not raw or not str(raw).strip():
        return "(분석 JSON 없음)"
    s = str(raw).strip()
    return s if len(s) <= limit else s[:limit] + "\n…(이하 생략)…"


def _followup_pairs_for_seed(messages: list) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = (getattr(m, "role", None) or "").strip().lower()
        if role == "user":
            u = (getattr(m, "content", None) or "").strip()
            a = ""
            if i + 1 < len(messages) and (getattr(messages[i + 1], "role", "") or "").strip().lower() == "assistant":
                a = (getattr(messages[i + 1], "content", None) or "").strip()
                i += 2
            else:
                i += 1
            if u:
                out.append((u, a))
        else:
            i += 1
    return out


def build_workflow_seed_answer_abap(
    *,
    requirement_text: str,
    analysis_json_raw: str | None,
    followup_messages: list,
    improvement_text: str,
) -> str:
    lines: list[str] = []
    lines.append("## [SAP ABAP 분석·개선] 제안서 작성용 통합 요약")
    lines.append("")
    lines.append("### 원본 요구사항")
    lines.append((requirement_text or "").strip() or "—")
    lines.append("")
    lines.append("### 에이전트 분석 결과(JSON)")
    lines.append(_trim_analysis_json(analysis_json_raw))
    ra_txt = _requirement_analysis_text_for_seed(analysis_json_raw)
    if ra_txt:
        lines.append("")
        lines.append("### 요구사항 연계 분석 (에이전트 요약)")
        lines.append(ra_txt)
    pairs = _followup_pairs_for_seed(followup_messages)
    if pairs:
        lines.append("")
        lines.append("### 후속 질의응답(인터뷰)")
        for qi, (uq, ua) in enumerate(pairs, start=1):
            lines.append(f"- **Q{qi} (회원)**: {uq}")
            if ua:
                lines.append(f"  **A (어시스턴트)**: {ua}")
    lines.append("")
    lines.append("### 개선 제안 요청 (회원 제출)")
    lines.append((improvement_text or "").strip())
    return "\n".join(lines)


def build_workflow_seed_answer_integration(
    *,
    title: str,
    impl_types: str,
    sap_touchpoints: str | None,
    environment_notes: str | None,
    security_notes: str | None,
    description: str | None,
    followup_messages: list,
    improvement_text: str,
) -> str:
    lines: list[str] = []
    lines.append("## [SAP 연동 개발] 제안서 작성용 통합 요약")
    lines.append("")
    lines.append("### 요청 개요")
    lines.append(f"- **제목**: {(title or '').strip()}")
    lines.append(f"- **구현 형태**: {(impl_types or '').strip() or '—'}")
    lines.append("")
    lines.append("### SAP 터치포인트")
    lines.append((sap_touchpoints or "").strip() or "—")
    lines.append("")
    lines.append("### 실행 환경")
    lines.append((environment_notes or "").strip() or "—")
    lines.append("")
    lines.append("### 보안·권한")
    lines.append((security_notes or "").strip() or "—")
    lines.append("")
    lines.append("### 상세 설명")
    lines.append((description or "").strip() or "—")
    pairs = _followup_pairs_for_seed(followup_messages)
    if pairs:
        lines.append("")
        lines.append("### 후속 질의응답(인터뷰)")
        for qi, (uq, ua) in enumerate(pairs, start=1):
            lines.append(f"- **Q{qi} (회원)**: {uq}")
            if ua:
                lines.append(f"  **A (어시스턴트)**: {ua}")
    lines.append("")
    lines.append("### 개선 제안 요청 (회원 제출)")
    lines.append((improvement_text or "").strip())
    return "\n".join(lines)


def build_workflow_description_abap(row: models.AbapAnalysisRequest, improvement_text: str) -> str:
    header = "[워크플로: 분석·개선 → 신규 개발 제안서]"
    parts = [header, "", "**개선 제안 요청**", improvement_text.strip(), "", "**원본 요구사항**", (row.requirement_text or "").strip()]
    return "\n".join(parts)


def build_workflow_description_integration(ir: models.IntegrationRequest, improvement_text: str) -> str:
    lines = [
        "[워크플로: 연동 개발 → 신규 개발 제안서]",
        "",
        "**개선 제안 요청**",
        improvement_text.strip(),
        "",
        "**연동 요청 요약**",
        f"제목: {ir.title}",
        f"구현 형태: {ir.impl_types or '—'}",
        "",
        (ir.description or "").strip(),
    ]
    return "\n".join(lines)


def create_workflow_rfp_from_abap_analysis(
    db: Session,
    *,
    row: models.AbapAnalysisRequest,
    improvement_text: str,
    owner_user_id: int,
    followup_messages: list | None = None,
) -> models.RFP:
    mc, dc = _pick_default_module_devtype_codes(db)
    pid, tcode = _first_slot_program_meta(getattr(row, "reference_code_payload", None))
    pid_row = (getattr(row, "program_id", None) or "").strip()
    tcode_row = (getattr(row, "transaction_code", None) or "").strip()
    sm_row = (getattr(row, "sap_modules", None) or "").strip()
    dt_row = (getattr(row, "dev_types", None) or "").strip()
    if pid_row:
        pid = pid_row
    if tcode_row:
        tcode = tcode_row
    if sm_row:
        mc = sm_row
    if dt_row:
        dc = dt_row
    title_base = (row.title or "").strip() or f"ABAP 분석 개선 #{row.id}"
    title = (title_base + " · 개선제안")[:512]

    fmsgs = followup_messages if followup_messages is not None else list(row.followup_messages or [])
    seed = build_workflow_seed_answer_abap(
        requirement_text=row.requirement_text or "",
        analysis_json_raw=row.analysis_json,
        followup_messages=fmsgs,
        improvement_text=improvement_text,
    )

    rfp = models.RFP(
        user_id=owner_user_id,
        program_id=pid or None,
        transaction_code=tcode or None,
        title=title,
        sap_modules=mc,
        dev_types=dc,
        description=build_workflow_description_abap(row, improvement_text),
        attachments_json=getattr(row, "attachments_json", None),
        reference_code_payload=getattr(row, "reference_code_payload", None),
        status="submitted",
        workflow_origin="abap_analysis",
        interview_status="generating_proposal",
    )
    db.add(rfp)
    db.flush()

    msg = models.RFPMessage(
        rfp_id=rfp.id,
        round_number=1,
        questions_json=json.dumps(["[분석·후속 대화 기반] 제안서 작성용 요약"], ensure_ascii=False),
        answers_text=seed,
        is_answered=True,
        source_label="workflow_abap_analysis",
    )
    db.add(msg)

    row.workflow_rfp_id = rfp.id
    row.improvement_request_text = improvement_text.strip()
    db.add(row)
    db.commit()
    db.refresh(rfp)
    return rfp


def create_workflow_rfp_from_integration(
    db: Session,
    *,
    ir: models.IntegrationRequest,
    improvement_text: str,
    owner_user_id: int,
    followup_messages: list | None = None,
) -> models.RFP:
    mc, dc = _pick_default_module_devtype_codes(db)
    pid, tcode = _first_slot_program_meta(getattr(ir, "reference_code_payload", None))
    title = ((ir.title or "").strip() + " · 연동개선제안")[:512]

    fmsgs = followup_messages if followup_messages is not None else list(ir.followup_messages or [])
    seed = build_workflow_seed_answer_integration(
        title=ir.title or "",
        impl_types=ir.impl_types or "",
        sap_touchpoints=ir.sap_touchpoints,
        environment_notes=ir.environment_notes,
        security_notes=ir.security_notes,
        description=ir.description,
        followup_messages=fmsgs,
        improvement_text=improvement_text,
    )

    rfp = models.RFP(
        user_id=owner_user_id,
        program_id=pid or None,
        transaction_code=tcode or None,
        title=title,
        sap_modules=mc,
        dev_types=dc,
        description=build_workflow_description_integration(ir, improvement_text),
        attachments_json=getattr(ir, "attachments_json", None),
        reference_code_payload=getattr(ir, "reference_code_payload", None),
        status="submitted",
        workflow_origin="integration",
        interview_status="generating_proposal",
    )
    db.add(rfp)
    db.flush()

    msg = models.RFPMessage(
        rfp_id=rfp.id,
        round_number=1,
        questions_json=json.dumps(["[연동·후속 대화 기반] 제안서 작성용 요약"], ensure_ascii=False),
        answers_text=seed,
        is_answered=True,
        source_label="workflow_integration",
    )
    db.add(msg)

    ir.workflow_rfp_id = rfp.id
    ir.improvement_request_text = improvement_text.strip()
    db.add(ir)
    db.commit()
    db.refresh(rfp)
    return rfp
