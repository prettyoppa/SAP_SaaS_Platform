"""
Code Library Router – SAP Dev Hub
회원이 ABAP 소스를 업로드하고, Hannah+Mia 에이전트가 분석합니다.
회원은 본인 코드만, Admin은 전체를 볼 수 있습니다.
"""

import json
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from .. import models, auth
from ..agents.free_crew import analyze_code_for_library
from ..database import get_db
from ..templates_config import templates

router = APIRouter()


def _parse_source_sections(source_code: str) -> list[dict]:
    """*&==== 구분자로 업로드된 멀티섹션 소스를 파싱합니다."""
    if "*&====" not in source_code:
        return [{"label": "전체 소스", "code": source_code}]

    sections = []
    current_label = ""
    current_lines = []

    for line in source_code.splitlines():
        if line.startswith("*&===="):
            if current_lines:
                code_text = "\n".join(current_lines).strip()
                if code_text:
                    sections.append({"label": current_label or "섹션", "code": code_text})
            current_lines = []
            current_label = ""
        elif line.startswith("*& ["):
            current_label = line[3:].strip()
        else:
            current_lines.append(line)

    if current_lines:
        code_text = "\n".join(current_lines).strip()
        if code_text:
            sections.append({"label": current_label or "섹션", "code": code_text})

    return sections if sections else [{"label": "전체 소스", "code": source_code}]


def _get_modules_devtypes(db: Session):
    modules = db.query(models.SAPModule).filter(models.SAPModule.is_active == True).order_by(models.SAPModule.sort_order).all()
    devtypes = db.query(models.DevType).filter(models.DevType.is_active == True).order_by(models.DevType.sort_order).all()
    return modules, devtypes


# ── 목록 ──────────────────────────────────────────────────────
@router.get("/codelib", response_class=HTMLResponse)
def codelib_list(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(models.ABAPCode)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.ABAPCode.title.ilike(like)) |
            (models.ABAPCode.program_id.ilike(like)) |
            (models.ABAPCode.sap_modules.ilike(like))
        )

    codes = query.order_by(models.ABAPCode.created_at.desc()).all()

    total = len(codes)
    analyzed = sum(1 for c in codes if c.is_analyzed)
    draft = sum(1 for c in codes if c.is_draft)

    return templates.TemplateResponse(request, "codelib_list.html", {
        "request": request,
        "user": user,
        "codes": codes,
        "q": q,
        "counts": {"total": total, "analyzed": analyzed, "draft": draft},
    })


# ── 업로드 폼 ──────────────────────────────────────────────────
@router.get("/codelib/upload", response_class=HTMLResponse)
def codelib_upload_form(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    return templates.TemplateResponse(request, "codelib_upload.html", {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "error": None,
    })


# ── 업로드 처리 ────────────────────────────────────────────────
@router.post("/codelib/upload")
def codelib_upload(
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: list[str] = Form(default=[]),
    dev_types: list[str] = Form(default=[]),
    source_code: str = Form(...),
    is_draft: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)

    if not sap_modules or not dev_types:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "SAP 모듈과 개발 유형을 하나 이상 선택해 주세요.",
        })

    if len(source_code.strip()) < 50:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "ABAP 소스 코드가 너무 짧습니다.",
        })

    save_as_draft = (is_draft == "1")

    # 임시 저장이 아닐 경우 Hannah + Mia 에이전트 분석 실행
    analysis = {}
    analyzed = False
    if not save_as_draft:
        try:
            analysis = analyze_code_for_library(
                source_code=source_code,
                title=title,
                modules=sap_modules,
                dev_types=dev_types,
            )
            analyzed = not bool(analysis.get("error"))
        except Exception as e:
            analysis = {"error": str(e)}
            analyzed = False

    code = models.ABAPCode(
        uploaded_by=user.id,
        program_id=program_id.strip().upper() if program_id else None,
        transaction_code=transaction_code.strip().upper() if transaction_code else None,
        title=title,
        sap_modules=",".join(sap_modules),
        dev_types=",".join(dev_types),
        source_code=source_code,
        analysis_json=json.dumps(analysis, ensure_ascii=False) if analysis else None,
        is_analyzed=analyzed,
        is_draft=save_as_draft,
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return RedirectResponse(url=f"/codelib/{code.id}", status_code=302)


# ── 상세 보기 ──────────────────────────────────────────────────
@router.get("/codelib/{code_id}", response_class=HTMLResponse)
def codelib_detail(code_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)

    code = query.first()
    if not code:
        return RedirectResponse(url="/codelib", status_code=302)

    analysis = {}
    if code.analysis_json:
        try:
            analysis = json.loads(code.analysis_json)
        except Exception:
            pass

    return templates.TemplateResponse(request, "codelib_detail.html", {
        "request": request,
        "user": user,
        "code": code,
        "analysis": analysis,
        "source_sections": _parse_source_sections(code.source_code),
    })


# ── 재분석 ─────────────────────────────────────────────────────
@router.post("/codelib/{code_id}/reanalyze")
def codelib_reanalyze(code_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if not code:
        return RedirectResponse(url="/codelib", status_code=302)

    try:
        analysis = analyze_code_for_library(
            source_code=code.source_code,
            title=code.title,
            modules=code.sap_modules.split(","),
            dev_types=code.dev_types.split(","),
        )
    except Exception as e:
        analysis = {"error": f"에이전트 실행 오류: {e}"}

    code.analysis_json = json.dumps(analysis, ensure_ascii=False)
    code.is_analyzed = not bool(analysis.get("error"))
    code.is_draft = False
    db.commit()

    return RedirectResponse(url=f"/codelib/{code_id}", status_code=302)


# ── 삭제 ───────────────────────────────────────────────────────
@router.post("/codelib/{code_id}/delete")
def codelib_delete(code_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if code:
        db.delete(code)
        db.commit()
    return RedirectResponse(url="/codelib", status_code=302)
