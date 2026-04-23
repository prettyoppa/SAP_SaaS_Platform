"""
Code Library Router – SAP Dev Hub
관리자가 ABAP 소스를 업로드하고 Hannah+Mia 에이전트가 분석합니다.
일반 회원은 코드 라이브러리에 접근할 수 없으며, 신규 요청의 「참고 코드 정보」는 브라우저 로컬에만 저장됩니다.
"""

import json
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session, joinedload
from .. import models, auth, sap_fields
from ..database import get_db
from ..templates_config import templates

router = APIRouter()


def _safe_next_url(next_raw: str | None) -> str:
    """오픈 리다이렉트 방지: 동일 사이트 상대 경로만 허용."""
    if not next_raw or not isinstance(next_raw, str):
        return "/codelib"
    n = next_raw.strip()
    if not n.startswith("/") or n.startswith("//"):
        return "/codelib"
    return n


def require_code_library_access(request: Request, db: Session = Depends(get_db)) -> models.User:
    """로그인 관리자만 코드 라이브러리 접근 (일반 회원은 신규 요청 내 로컬 참고 코드 사용)."""
    user = auth.get_current_user(request, db)
    if not user:
        nu = quote(request.url.path + ("?" + request.url.query if request.url.query else ""), safe="")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={nu}"},
        )
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/dashboard"},
        )
    return user


def _enforce_code_access(user: models.User, code: models.ABAPCode | None) -> bool:
    """쿼리 필터 외 이중 확인: 타인 행 접근 차단."""
    if not code:
        return False
    if user.is_admin:
        return True
    return code.uploaded_by == user.id


def _codelib_pid_error_msg(perr: str) -> str:
    return {
        "too_long": "프로그램 ID는 40자 이내로 입력해 주세요.",
        "no_ime_chars": "프로그램 ID에는 한글·일본어·중국어 입력을 사용할 수 없습니다. 영문·숫자·기호(공백 제외)만 입력해 주세요.",
        "invalid_chars": "프로그램 ID에는 인쇄되는 영문·숫자·기호만 사용할 수 있습니다.",
    }[perr]


def _codelib_tcode_error_msg(terr: str) -> str:
    return {
        "too_long": "트랜잭션 코드는 20자 이내로 입력해 주세요.",
        "no_ime_chars": "트랜잭션 코드에는 한글 등 IME 입력을 사용할 수 없습니다.",
        "invalid_chars": "트랜잭션 코드에 허용되지 않는 문자가 있습니다.",
    }[terr]


def _normalize_program_id_stored(program_id: str | None) -> str | None:
    """DB 저장용: 앞뒤 공백만 제거. SAP 관례상 대문자는 사용자 입력 존중(기호·혼합 허용)."""
    if not program_id:
        return None
    s = program_id.strip()
    return s if s else None


def _sanitize_abap_filename_base(raw: str, code_id: int) -> str:
    """Windows 금지 문자만 치환."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip()
    if not safe:
        safe = f"SOURCE_{code_id}"
    if len(safe) > 120:
        safe = safe[:120]
    return safe


def _extract_include_name_from_section_label(inner: str) -> str | None:
    """
    '*& [1] 메인 프로그램 – ZXXX_TOP' 라인에서 Include명(– 뒤)만 추출.
    업로드 폼의 section-name-input 값.
    """
    s = inner.strip()
    m = re.match(r"^\[\d+\]\s*(.+)$", s)
    if not m:
        return None
    rest = m.group(1).strip()
    for sep in (" – ", " — ", " - "):
        if sep in rest:
            right = rest.split(sep, 1)[1].strip()
            return right if right else None
    return None


def _abap_download_filename(
    top_program_id: str | None,
    section_include_name: str | None,
    code_id: int,
    section_idx: int,
    n_sections: int,
) -> str:
    """
    섹션별 Include명(등록 시 각 박스 위 입력)이 있으면 그 이름으로 저장.
    없으면 상단 프로그램 ID + 멀티 섹션일 때만 _Sn 접미사.
    """
    per = _normalize_program_id_stored(section_include_name)
    top = _normalize_program_id_stored(top_program_id)
    if per:
        base = _sanitize_abap_filename_base(per, code_id)
        return f"{base}.abap"
    raw = top or f"SOURCE_{code_id}"
    if n_sections > 1:
        raw = f"{raw}_S{section_idx + 1}"
    base = _sanitize_abap_filename_base(raw, code_id)
    return f"{base}.abap"


def _parse_source_sections(source_code: str) -> list[dict]:
    """
    업로드 JS가 만든 *&==== / *& [n] 유형 – Include명 / *&==== / 코드 형식을 파싱합니다.
    기존 한 줄 파서는 두 번째 *&====에서 라벨이 지워져 '섹션'만 남던 버그가 있었습니다.
    """
    text = (source_code or "").replace("\r\n", "\n")
    if "*& [" not in text:
        c = text.strip()
        return [{"label": "전체 소스", "code": c, "include_name": None}]

    lines = text.split("\n")
    sections: list[dict] = []
    i, n = 0, len(lines)

    while i < n:
        st = lines[i].strip()
        if not (st.startswith("*& [") and "]" in st):
            i += 1
            continue
        inner = st[3:].strip() if st.startswith("*& ") else st
        i += 1
        if i < n and "*&=" in lines[i] and "====" in lines[i]:
            i += 1
        body: list[str] = []
        while i < n:
            t = lines[i].strip()
            if t.startswith("*& [") and "]" in t:
                break
            if t.startswith("*&") and "====" in t:
                break
            body.append(lines[i])
            i += 1
        code_text = "\n".join(body).strip()
        if code_text:
            inc = _extract_include_name_from_section_label(inner)
            sections.append({"label": inner, "code": code_text, "include_name": inc})
    return sections if sections else [{"label": "전체 소스", "code": text.strip(), "include_name": None}]


def _normalize_section_type_for_edit(typ: str) -> str:
    """역파싱된 유형 문자열을 폼 select value 와 맞춥니다."""
    t = (typ or "").strip()
    if t.startswith("Form Subroutines"):
        return "Form Subroutines"
    if "Selection Screen" in t:
        return "Selection Screen"
    if t.startswith("Class"):
        return "Class"
    return t


def _parse_upload_sections_for_edit(source_code: str) -> list[dict]:
    """
    업로드 폼 JS가 만든 *&==== / *& [n] 라벨 / *&==== / 코드 블록 형식을
    편집 화면용 {type, name, code} 목록으로 역파싱합니다.
    """
    lines = source_code.replace("\r\n", "\n").split("\n")
    sections: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip().startswith("*&===="):
            i += 1
            if i >= n:
                break
            hdr = lines[i].strip()
            if hdr.startswith("*& ["):
                inner = hdr[3:].strip()
                i += 1
                if i < n and lines[i].strip().startswith("*&===="):
                    i += 1
                body: list[str] = []
                while i < n and not lines[i].strip().startswith("*&===="):
                    body.append(lines[i])
                    i += 1
                m = re.match(r"^\[\d+\]\s*(.+)$", inner)
                label_rest = (m.group(1).strip() if m else inner)
                if " – " in label_rest:
                    typ, name = label_rest.split(" – ", 1)
                    typ, name = typ.strip(), name.strip()
                else:
                    typ, name = label_rest, ""
                typ = _normalize_section_type_for_edit(typ)
                sections.append({"type": typ, "name": name, "code": "\n".join(body).rstrip("\n")})
                continue
        i += 1
    if not sections:
        return [{"type": "메인 프로그램", "name": "", "code": source_code.strip()}]
    return sections


def _get_modules_devtypes(db: Session):
    modules = db.query(models.SAPModule).filter(models.SAPModule.is_active == True).order_by(models.SAPModule.sort_order).all()
    devtypes = db.query(models.DevType).filter(models.DevType.is_active == True).order_by(models.DevType.sort_order).all()
    return modules, devtypes


# ── 코드 라이브러리 2차 확인 (일반 회원) ─────────────────────────
@router.get("/codelib/unlock", response_class=HTMLResponse)
def codelib_unlock_page(request: Request, next: str = "/codelib", db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        nu = quote(f"/codelib/unlock?next={_safe_next_url(next)}", safe="")
        return RedirectResponse(url=f"/login?next={nu}", status_code=302)
    if not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url=_safe_next_url(next), status_code=302)


@router.post("/codelib/unlock")
def codelib_unlock_post(
    request: Request,
    next: str = Form("/codelib"),
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url=_safe_next_url(next), status_code=302)


# ── 목록 ──────────────────────────────────────────────────────
@router.get("/codelib", response_class=HTMLResponse)
def codelib_list(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).options(joinedload(models.ABAPCode.uploader))
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
def codelib_upload_form(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    modules, devtypes = _get_modules_devtypes(db)
    return templates.TemplateResponse(request, "codelib_upload.html", {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "error": None,
        "edit_code": None,
        "edit_sections": None,
        "selected_modules": [],
        "selected_devtypes": [],
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
    user: models.User = Depends(require_code_library_access),
):
    modules, devtypes = _get_modules_devtypes(db)

    if not sap_modules or not dev_types:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "SAP 모듈과 개발 유형을 하나 이상 선택해 주세요.",
            "edit_code": None,
            "edit_sections": None,
            "selected_modules": [],
            "selected_devtypes": [],
        })

    if len(source_code.strip()) < 50:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "ABAP 소스 코드가 너무 짧습니다.",
            "edit_code": None,
            "edit_sections": None,
            "selected_modules": [],
            "selected_devtypes": [],
        })

    pid_norm, perr = sap_fields.validate_program_id(program_id, required=False)
    if perr:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": _codelib_pid_error_msg(perr),
            "form_program_id": program_id,
            "form_transaction_code": transaction_code,
            "edit_code": None,
            "edit_sections": None,
            "selected_modules": [],
            "selected_devtypes": [],
        })
    tc_norm, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": _codelib_tcode_error_msg(terr),
            "form_program_id": program_id,
            "form_transaction_code": transaction_code,
            "edit_code": None,
            "edit_sections": None,
            "selected_modules": [],
            "selected_devtypes": [],
        })

    save_as_draft = (is_draft == "1")

    analysis = {}
    analyzed = False
    if not save_as_draft:
        try:
            from ..agents.free_crew import analyze_code_for_library

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
        program_id=pid_norm,
        transaction_code=tc_norm,
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


# ── 임시저장 항목 수정 ───────────────────────────────────────────
@router.get("/codelib/{code_id}/edit", response_class=HTMLResponse)
def codelib_edit_form(
    code_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if not code or not _enforce_code_access(user, code) or not code.is_draft:
        return RedirectResponse(url=f"/codelib/{code_id}", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)
    sections = _parse_upload_sections_for_edit(code.source_code or "")
    return templates.TemplateResponse(request, "codelib_upload.html", {
        "request": request,
        "user": user,
        "modules": modules,
        "devtypes": devtypes,
        "error": None,
        "edit_code": code,
        "edit_sections": sections,
        "selected_modules": [x.strip() for x in code.sap_modules.split(",") if x.strip()],
        "selected_devtypes": [x.strip() for x in code.dev_types.split(",") if x.strip()],
    })


@router.post("/codelib/{code_id}/edit")
def codelib_edit_save(
    code_id: int,
    request: Request,
    program_id: str = Form(""),
    transaction_code: str = Form(""),
    title: str = Form(...),
    sap_modules: list[str] = Form(default=[]),
    dev_types: list[str] = Form(default=[]),
    source_code: str = Form(...),
    is_draft: str = Form(""),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if not code or not _enforce_code_access(user, code) or not code.is_draft:
        return RedirectResponse(url=f"/codelib/{code_id}", status_code=302)

    modules, devtypes = _get_modules_devtypes(db)

    if not sap_modules or not dev_types:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "SAP 모듈과 개발 유형을 하나 이상 선택해 주세요.",
            "edit_code": code,
            "edit_sections": _parse_upload_sections_for_edit(source_code),
            "selected_modules": list(sap_modules),
            "selected_devtypes": list(dev_types),
        })

    if len(source_code.strip()) < 50:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": "ABAP 소스 코드가 너무 짧습니다.",
            "edit_code": code,
            "edit_sections": _parse_upload_sections_for_edit(source_code),
            "selected_modules": list(sap_modules),
            "selected_devtypes": list(dev_types),
        })

    pid_norm, perr = sap_fields.validate_program_id(program_id, required=False)
    if perr:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": _codelib_pid_error_msg(perr),
            "form_program_id": program_id,
            "form_transaction_code": transaction_code,
            "edit_code": code,
            "edit_sections": _parse_upload_sections_for_edit(source_code),
            "selected_modules": list(sap_modules),
            "selected_devtypes": list(dev_types),
        })
    tc_norm, terr = sap_fields.validate_transaction_code(transaction_code)
    if terr:
        return templates.TemplateResponse(request, "codelib_upload.html", {
            "request": request, "user": user,
            "modules": modules, "devtypes": devtypes,
            "error": _codelib_tcode_error_msg(terr),
            "form_program_id": program_id,
            "form_transaction_code": transaction_code,
            "edit_code": code,
            "edit_sections": _parse_upload_sections_for_edit(source_code),
            "selected_modules": list(sap_modules),
            "selected_devtypes": list(dev_types),
        })

    save_as_draft = (is_draft == "1")

    code.program_id = pid_norm
    code.transaction_code = tc_norm
    code.title = title
    code.sap_modules = ",".join(sap_modules)
    code.dev_types = ",".join(dev_types)
    code.source_code = source_code

    if save_as_draft:
        code.is_draft = True
        code.is_analyzed = False
        code.analysis_json = None
    else:
        try:
            from ..agents.free_crew import analyze_code_for_library

            analysis = analyze_code_for_library(
                source_code=source_code,
                title=title,
                modules=sap_modules,
                dev_types=dev_types,
            )
            code.analysis_json = json.dumps(analysis, ensure_ascii=False) if analysis else None
            code.is_analyzed = not bool(analysis.get("error")) if analysis else False
        except Exception as e:
            code.analysis_json = json.dumps({"error": str(e)}, ensure_ascii=False)
            code.is_analyzed = False
        code.is_draft = False

    db.commit()
    return RedirectResponse(url=f"/codelib/{code_id}", status_code=302)


# ── 원본 소스 다운로드 (섹션별) ─────────────────────────────────
@router.get("/codelib/{code_id}/download")
def codelib_download(
    code_id: int,
    request: Request,
    section: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if not code or not _enforce_code_access(user, code):
        return RedirectResponse(url="/codelib", status_code=302)

    sections = _parse_source_sections(code.source_code or "")
    n = len(sections)
    if section >= n:
        return RedirectResponse(url=f"/codelib/{code_id}", status_code=302)

    body = sections[section]["code"]
    inc = sections[section].get("include_name")
    filename = _abap_download_filename(code.program_id, inc, code_id, section, n)
    ascii_name = filename.encode("ascii", "ignore").decode() or f"{code_id}.abap"
    cd = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": cd},
    )


# ── 상세 보기 ──────────────────────────────────────────────────
@router.get("/codelib/{code_id}", response_class=HTMLResponse)
def codelib_detail(
    code_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = (
        db.query(models.ABAPCode)
        .options(joinedload(models.ABAPCode.uploader))
        .filter(models.ABAPCode.id == code_id)
    )
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)

    code = query.first()
    if not code or not _enforce_code_access(user, code):
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
def codelib_reanalyze(
    code_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if not code or not _enforce_code_access(user, code):
        return RedirectResponse(url="/codelib", status_code=302)

    try:
        from ..agents.free_crew import analyze_code_for_library

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
def codelib_delete(
    code_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_code_library_access),
):
    query = db.query(models.ABAPCode).filter(models.ABAPCode.id == code_id)
    if not user.is_admin:
        query = query.filter(models.ABAPCode.uploaded_by == user.id)
    code = query.first()
    if code and _enforce_code_access(user, code):
        db.delete(code)
        db.commit()
    return RedirectResponse(url="/codelib", status_code=302)
