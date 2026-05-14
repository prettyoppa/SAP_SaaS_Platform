"""납품 코드 패키지 — RFP(ABAP) JSON 슬롯 + 연동 개발(비 ABAP) JSON 슬롯, 가이드·테스트, 레거시 마크다운."""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from .rfp_download_names import sanitize_path_component

PACKAGE_VERSION = 1

_ALLOWED_ROLES = frozenset(
    {"main_report", "include", "top", "pbo", "pai", "forms", "screen", "other"}
)


def sanitize_test_scenarios_markdown(md: str) -> str:
    """테스트 시나리오 마크다운에서 과도한 구분선·빈 줄을 줄인다."""
    s = (md or "").strip()
    if not s:
        return ""
    lines = s.splitlines()
    out: list[str] = []
    dash_run = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[\s\-:|]+$", stripped) and set(stripped) <= {"-", " ", "|", ":"}:
            dash_run += 1
            if dash_run > 2:
                continue
        else:
            dash_run = 0
        if len(line) > 500:
            line = line[:497] + "…"
        out.append(line)
    return "\n".join(out).strip()


def _safe_filename(name: str, fallback: str) -> str:
    raw = (name or "").strip() or fallback
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip("._") or fallback
    if len(raw) > 120:
        raw = raw[:120].rstrip("._")
    if not raw.lower().endswith(".abap"):
        raw = f"{raw}.abap"
    return raw


def _normalize_slot(slot: Any, idx: int) -> dict[str, str] | None:
    if not isinstance(slot, dict):
        return None
    role = (str(slot.get("role") or "other")).strip().lower()
    if role not in _ALLOWED_ROLES:
        role = "other"
    title_ko = (str(slot.get("title_ko") or slot.get("title") or "")).strip() or f"슬롯 {idx + 1}"
    fn = _safe_filename(str(slot.get("filename") or ""), f"slot_{idx + 1}.abap")
    source = str(slot.get("source") or "")
    return {"role": role, "filename": fn, "title_ko": title_ko, "source": source}


def normalize_delivered_package(data: dict[str, Any]) -> dict[str, Any] | None:
    """LLM JSON을 패키지 스키마로 정규화. ABAP가 하나도 없으면 None."""
    if not isinstance(data, dict):
        return None
    pid = (str(data.get("program_id") or "")).strip()
    raw_slots = data.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        return None
    slots: list[dict[str, str]] = []
    for i, s in enumerate(raw_slots):
        ns = _normalize_slot(s, i)
        if ns:
            slots.append(ns)
    if not any((sl.get("source") or "").strip() for sl in slots):
        return None
    notes = (str(data.get("coder_notes") or data.get("notes") or "")).strip()
    return {
        "version": PACKAGE_VERSION,
        "program_id": pid,
        "slots": slots,
        "coder_notes": notes,
        "implementation_guide_md": (str(data.get("implementation_guide_md") or "")).strip(),
        "test_scenarios_md": sanitize_test_scenarios_markdown(
            str(data.get("test_scenarios_md") or "")
        ),
    }


def parse_delivered_code_payload(raw: str | None) -> dict[str, Any] | None:
    """DB TEXT(JSON) → dict. 파싱 실패 시 None."""
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return normalize_delivered_package(data) if isinstance(data, dict) else None


def delivered_package_has_body(pkg: dict[str, Any] | None) -> bool:
    if not pkg or not isinstance(pkg, dict):
        return False
    slots = pkg.get("slots")
    if not isinstance(slots, list):
        return False
    return any((isinstance(s, dict) and (s.get("source") or "").strip()) for s in slots)


def rfp_delivered_body_ready(rfp: Any) -> bool:
    """랜딩 버킷 등: ready 이고 패키지 또는 레거시 텍스트가 있음."""
    if (getattr(rfp, "delivered_code_status", None) or "").strip() != "ready":
        return False
    if delivered_package_has_body(parse_delivered_code_payload(getattr(rfp, "delivered_code_payload", None))):
        return True
    return bool((getattr(rfp, "delivered_code_text", None) or "").strip())


def legacy_markdown_from_package(pkg: dict[str, Any]) -> str:
    """검색·미리보기 호환용 단일 마크다운(슬롯별 펜스 + 가이드 + 테스트)."""
    lines: list[str] = [
        f"# 납품 ABAP 패키지 (v{pkg.get('version', PACKAGE_VERSION)})",
        "",
        f"**프로그램 ID:** `{pkg.get('program_id') or '—'}`",
        "",
    ]
    if (pkg.get("coder_notes") or "").strip():
        lines.extend(["## 생성 메모", "", str(pkg["coder_notes"]).strip(), ""])
    for sl in pkg.get("slots") or []:
        if not isinstance(sl, dict):
            continue
        title = (sl.get("title_ko") or sl.get("filename") or "소스").strip()
        role = (sl.get("role") or "").strip()
        lines.append(f"## {title}" + (f" (`{role}`)" if role else ""))
        lines.append("")
        lines.append("```abap")
        lines.append((sl.get("source") or "").rstrip())
        lines.append("```")
        lines.append("")
    ig = (pkg.get("implementation_guide_md") or "").strip()
    if ig:
        lines.extend(["## 구현·운영 가이드", "", ig, ""])
    ts = (pkg.get("test_scenarios_md") or "").strip()
    if ts:
        lines.extend(["## 테스트 시나리오", "", ts, ""])
    return "\n".join(lines).strip()


def extract_json_object_from_llm_text(text: str) -> dict[str, Any] | None:
    """펜스·전후 잡음에서 JSON object 추출."""
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t, re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        c = t[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = t[start : i + 1]
                try:
                    obj = json.loads(chunk)
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def merge_slots_json_with_extras(
    slots_obj: dict[str, Any],
    *,
    implementation_guide_md: str,
    test_scenarios_md: str,
) -> dict[str, Any] | None:
    """코더/검수 JSON에 가이드·테스트 필드를 붙여 최종 패키지 dict 생성."""
    base = dict(slots_obj)
    base["implementation_guide_md"] = (implementation_guide_md or "").strip()
    base["test_scenarios_md"] = sanitize_test_scenarios_markdown(test_scenarios_md or "")
    return normalize_delivered_package(base)


# --- 연동 개발(비 ABAP): 파일·역할 단위 슬롯 패키지 ---

INTEGRATION_PACKAGE_VERSION = 1

_INTEGRATION_ROLES = frozenset(
    {
        "entry_script",
        "main_script",
        "module",
        "library",
        "package_init",
        "config",
        "env_sample",
        "sql",
        "shell",
        "vba",
        "requirements",
        "manifest",
        "test",
        "doc",
        "other",
    }
)

_INTEGRATION_EXT = (
    ".py",
    ".ps1",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
    ".sh",
    ".bash",
    ".bat",
    ".cmd",
    ".vba",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".md",
    ".toml",
    ".ini",
    ".txt",
    ".xml",
    ".properties",
    ".gradle",
    ".kts",
    ".cs",
    ".go",
    ".rb",
    ".php",
    ".html",
    ".css",
    ".http",
    ".env",
)


def _safe_filename_integration(name: str, idx: int) -> str:
    tail = (name or "").strip().replace("\\", "/").split("/")[-1] or f"artifact_{idx + 1}.py"
    # strip("._") 은 ".env.example", "__init__.py" 를 망가뜨리므로 알려진 이름은 별도 처리
    if tail in (".env.example", ".env.sample", "__init__.py"):
        raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", tail)
        if len(raw) > 120:
            raw = raw[:120]
        return raw or f"artifact_{idx + 1}.py"
    raw = tail or f"artifact_{idx + 1}.py"
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip() or f"artifact_{idx + 1}.py"
    if len(raw) > 120:
        if "." in raw:
            stem, ext = raw.rsplit(".", 1)
            raw = stem[:110].rstrip(".") + "." + ext[:8]
        else:
            raw = raw[:120]
    lower = raw.lower()
    if not any(lower.endswith(ext) for ext in _INTEGRATION_EXT):
        base = raw.rsplit(".", 1)[0] if "." in raw else raw
        raw = f"{base or f'module_{idx + 1}'}.py"
    return raw


def _normalize_integration_slot(slot: Any, idx: int) -> dict[str, str] | None:
    if not isinstance(slot, dict):
        return None
    role = (str(slot.get("role") or "other")).strip().lower()
    if role == "main_script":
        role = "entry_script"
    if role not in _INTEGRATION_ROLES:
        role = "other"
    title_ko = (str(slot.get("title_ko") or slot.get("title") or "")).strip() or f"파일 {idx + 1}"
    fn = _safe_filename_integration(str(slot.get("filename") or ""), idx)
    source = str(slot.get("source") or "")
    return {"role": role, "filename": fn, "title_ko": title_ko, "source": source}


def normalize_integration_delivered_package(data: dict[str, Any]) -> dict[str, Any] | None:
    """연동 납품 JSON을 스키마로 정규화. 본문이 있는 슬롯이 하나도 없으면 None."""
    if not isinstance(data, dict):
        return None
    if (str(data.get("package_kind") or "").strip().lower() or "") != "integration":
        return None
    raw_slots = data.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        return None
    slots: list[dict[str, str]] = []
    for i, s in enumerate(raw_slots):
        ns = _normalize_integration_slot(s, i)
        if ns:
            slots.append(ns)
    if not any((sl.get("source") or "").strip() for sl in slots):
        return None
    pid = (str(data.get("program_id") or data.get("delivery_id") or "")).strip() or "integration"
    notes = (str(data.get("coder_notes") or data.get("notes") or "")).strip()
    return {
        "version": int(data.get("version") or INTEGRATION_PACKAGE_VERSION),
        "package_kind": "integration",
        "program_id": pid,
        "slots": slots,
        "coder_notes": notes,
        "implementation_guide_md": (str(data.get("implementation_guide_md") or "")).strip(),
        "test_scenarios_md": sanitize_test_scenarios_markdown(str(data.get("test_scenarios_md") or "")),
    }


def parse_integration_delivered_payload(raw: str | None) -> dict[str, Any] | None:
    """DB TEXT(JSON) → 연동 패키지 dict. ABAP 패키지와 구분(package_kind)."""
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return normalize_integration_delivered_package(data)


def integration_delivered_package_has_body(pkg: dict[str, Any] | None) -> bool:
    if not pkg or not isinstance(pkg, dict):
        return False
    if (pkg.get("package_kind") or "").strip().lower() != "integration":
        return False
    slots = pkg.get("slots")
    if not isinstance(slots, list):
        return False
    return any((isinstance(s, dict) and (s.get("source") or "").strip()) for s in slots)


def integration_delivered_body_ready(entity: Any) -> bool:
    """연동 요청: ready 이고 연동 패키지 또는 레거시 단일 마크다운."""
    if (getattr(entity, "delivered_code_status", None) or "").strip() != "ready":
        return False
    if integration_delivered_package_has_body(
        parse_integration_delivered_payload(getattr(entity, "delivered_code_payload", None))
    ):
        return True
    return bool((getattr(entity, "delivered_code_text", None) or "").strip())


def _fence_lang_for_integration_filename(fn: str) -> str:
    ext = (fn or "").rsplit(".", 1)[-1].lower() if "." in (fn or "") else ""
    return {
        "py": "python",
        "ps1": "powershell",
        "sql": "sql",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "sh": "bash",
        "bash": "bash",
        "bat": "bat",
        "cmd": "bat",
        "js": "javascript",
        "ts": "typescript",
        "tsx": "tsx",
        "jsx": "jsx",
        "vba": "vbnet",
        "xml": "xml",
        "md": "markdown",
        "toml": "toml",
        "ini": "ini",
        "html": "html",
        "css": "css",
        "http": "http",
        "php": "php",
        "rb": "ruby",
        "go": "go",
        "cs": "csharp",
        "gradle": "gradle",
        "kts": "kotlin",
    }.get(ext, "text")


def legacy_markdown_from_integration_package(pkg: dict[str, Any]) -> str:
    """검색·미리보기 호환 단일 마크다운(슬롯별 펜스 + 가이드 + 테스트)."""
    lines: list[str] = [
        f"# 연동 개발 납품 패키지 (v{pkg.get('version', INTEGRATION_PACKAGE_VERSION)})",
        "",
        f"**납품 ID:** `{pkg.get('program_id') or '—'}`",
        "",
    ]
    if (pkg.get("coder_notes") or "").strip():
        lines.extend(["## 생성 메모", "", str(pkg["coder_notes"]).strip(), ""])
    for sl in pkg.get("slots") or []:
        if not isinstance(sl, dict):
            continue
        title = (sl.get("title_ko") or sl.get("filename") or "파일").strip()
        role = (sl.get("role") or "").strip()
        fn = (sl.get("filename") or "").strip()
        lang = _fence_lang_for_integration_filename(fn)
        lines.append(f"## {title}" + (f" (`{role}` · `{fn}`)" if role or fn else ""))
        lines.append("")
        lines.append(f"```{lang}")
        lines.append((sl.get("source") or "").rstrip())
        lines.append("```")
        lines.append("")
    ig = (pkg.get("implementation_guide_md") or "").strip()
    if ig:
        lines.extend(["## 구현·운영 가이드", "", ig, ""])
    ts = (pkg.get("test_scenarios_md") or "").strip()
    if ts:
        lines.extend(["## 테스트 시나리오", "", ts, ""])
    return "\n".join(lines).strip()


def merge_integration_slots_json_with_extras(
    slots_obj: dict[str, Any],
    *,
    implementation_guide_md: str,
    test_scenarios_md: str,
) -> dict[str, Any] | None:
    """연동 JSON 슬롯 초안에 가이드·테스트·package_kind를 붙여 최종 패키지 dict 생성."""
    base = dict(slots_obj)
    base["package_kind"] = "integration"
    base["implementation_guide_md"] = (implementation_guide_md or "").strip()
    base["test_scenarios_md"] = sanitize_test_scenarios_markdown(test_scenarios_md or "")
    return normalize_integration_delivered_package(base)


# --- Python 스크립트 연동 납품: 슬롯 보강 + ZIP 프로젝트 레이아웃 ---

INTEGRATION_IMPL_PYTHON_SCRIPT = "python_script"


def integration_impl_codes_include_python(impl_codes: list[str] | None) -> bool:
    if not impl_codes:
        return False
    return any((c or "").strip().lower() == INTEGRATION_IMPL_PYTHON_SCRIPT for c in impl_codes)


def _integration_slot_filenames_lower(slots: list[Any]) -> set[str]:
    out: set[str] = set()
    for sl in slots or []:
        if not isinstance(sl, dict):
            continue
        fn = (str(sl.get("filename") or "")).strip().lower()
        if not fn:
            continue
        out.add(fn)
        out.add(fn.replace("\\", "/").split("/")[-1])
    return out


def _default_python_readme_ko(*, request_title: str, program_id: str) -> str:
    t = (request_title or "").strip() or "연동 개발 요청"
    pid = (program_id or "").strip() or "project"
    return (
        f"# {t}\n\n"
        "이 폴더는 **Catchy(연동 개발)** 납품 자동생성 결과입니다. "
        f"(`program_id`: `{pid}`)\n\n"
        "## 사전 요구 사항\n\n"
        "- **OS:** Windows 권장 (SAP GUI Scripting / `pywin32` 기준).\n"
        "- **Python:** 3.10 이상 (3.11·3.12 호환 권장).\n"
        "- **SAP GUI for Windows** 설치 및, 고객사 정책에 따른 Scripting 활성화.\n"
        "- 64비트 Python과 64비트 SAP GUI 조합을 맞추세요.\n\n"
        "## 설치\n\n"
        "1. 이 ZIP을 원하는 경로에 풉니다.\n"
        "2. 가상환경(선택, 권장):\n\n"
        "```text\n"
        "python -m venv .venv\n"
        ".venv/Scripts/activate\n"
        "```\n\n"
        "3. 의존성 설치:\n\n"
        "```text\n"
        "pip install -r requirements.txt\n"
        "```\n\n"
        "4. 환경 변수: `.env.example`을 참고해 **`.env`** 파일을 만들고 값을 채웁니다. "
        "(저장소에 **비밀번호를 커밋하지 마세요**.)\n\n"
        "## 실행\n\n"
        "진입 스크립트는 보통 `src` 아래의 `main.py` 등입니다. 예:\n\n"
        "```text\n"
        "python -m src.main\n"
        "```\n\n"
        "또는 `docs/IMPLEMENTATION_GUIDE.md`에 적힌 명령을 따르세요.\n\n"
        "## 배치·주기 실행\n\n"
        "- **Windows 작업 스케줄러:** `python` 경로·스크립트·시작 위치(작업 폴더)를 지정합니다.\n"
        "- **Linux:** `cron` 등록 시 해당 OS에서의 SAP 연동 방식(GUI 유무)을 별도 검토합니다.\n\n"
        "## SAP Script / GUI 자동화\n\n"
        "- 로그온·트랜잭션·변형(Variant)·다운로드는 고객사에서 허용한 방식을 따릅니다.\n"
        "- **Script Recording** 산출물은 보안 정책에 맞게 별도 보관하고, 코드에서는 경로·로딩 방식만 다루는 것을 권장합니다.\n"
        "- 미결 사항은 `docs/IMPLEMENTATION_GUIDE.md`의 오픈 이슈를 확인하세요.\n"
    )


def _default_python_requirements_txt() -> str:
    return (
        "# Catchy 연동 납품(파이썬) — 예시 의존성. FS 및 구현 가이드에 맞게 추가·삭제하세요.\n"
        "# SAP GUI Windows 자동화에 흔히 사용됩니다.\n"
        'pywin32>=306; platform_system=="Windows"\n'
    )


def _default_python_env_example() -> str:
    return (
        "# SAP 로그온 (예시 — 실제 비밀은 .env에만 두고 Git에 올리지 마세요)\n"
        "SAP_CLIENT=100\n"
        "SAP_USER=\n"
        "SAP_PASSWORD=\n"
        "\n"
        "# 예: 리포트 변형(Variant)\n"
        "SAP_REPORT_VARIANT=\n"
        "\n"
        "# 출력 디렉터리 (다운로드 파일 등)\n"
        "OUTPUT_DIR=./out\n"
    )


def ensure_python_script_delivery_package(
    pkg: dict[str, Any],
    *,
    request_title: str,
    impl_codes: list[str] | None,
) -> dict[str, Any]:
    """
    python_script 구현 형태일 때 README / requirements.txt / .env.example 슬롯을 보강한다.
    동일 파일명이 이미 있으면 덮어쓰지 않는다.
    """
    if not pkg or not isinstance(pkg, dict):
        return pkg
    if (pkg.get("package_kind") or "").strip().lower() != "integration":
        return pkg
    if not integration_impl_codes_include_python(impl_codes):
        return pkg

    slots_in = pkg.get("slots")
    if not isinstance(slots_in, list):
        return pkg
    slots: list[dict[str, str]] = [dict(s) for s in slots_in if isinstance(s, dict)]  # type: ignore[arg-type]

    names = _integration_slot_filenames_lower(slots)

    def _has(*candidates: str) -> bool:
        for c in candidates:
            if c.lower() in names:
                return True
        return False

    if not _has("readme.md"):
        slots.insert(
            0,
            {
                "role": "doc",
                "filename": "README.md",
                "title_ko": "프로젝트 안내 및 실행 방법",
                "source": _default_python_readme_ko(
                    request_title=request_title,
                    program_id=str(pkg.get("program_id") or ""),
                ),
            },
        )
        names = _integration_slot_filenames_lower(slots)

    if not _has("requirements.txt"):
        slots.append(
            {
                "role": "requirements",
                "filename": "requirements.txt",
                "title_ko": "의존성 목록",
                "source": _default_python_requirements_txt(),
            }
        )
        names = _integration_slot_filenames_lower(slots)

    if not _has(".env.example", "env.example"):
        slots.append(
            {
                "role": "env_sample",
                "filename": ".env.example",
                "title_ko": "환경 변수 예시",
                "source": _default_python_env_example(),
            }
        )

    has_pkg_init = any(
        (str(s.get("filename") or "").replace("\\", "/").lower().endswith("__init__.py"))
        for s in slots
    )
    if not has_pkg_init:
        slots.append(
            {
                "role": "package_init",
                "filename": "__init__.py",
                "title_ko": "패키지 초기화",
                "source": '"""Generated delivery package (src is a Python package)."""\n',
            }
        )

    base = dict(pkg)
    base["slots"] = slots
    normalized = normalize_integration_delivered_package(base)
    return normalized if normalized is not None else pkg


def _zip_inner_path_for_python_project(root: str, role: str, filename: str) -> str:
    """납품 ZIP 내 상대 경로 (항상 / 구분)."""
    r = (root or "").strip().strip("/\\") or "python_project"
    fn = (filename or "").strip().replace("\\", "/").lstrip("/")
    if not fn:
        fn = "artifact.py"
    role_l = (role or "other").strip().lower()
    if fn.lower().startswith("src/"):
        return f"{r}/{fn}"

    base_name = fn.split("/")[-1]
    if base_name.lower() == "readme.md":
        return f"{r}/README.md"
    if base_name.lower() == "requirements.txt":
        return f"{r}/requirements.txt"
    if base_name.lower() in (".env.example", "env.example"):
        return f"{r}/.env.example"

    if role_l == "requirements":
        return f"{r}/requirements.txt"
    if role_l == "env_sample":
        return f"{r}/.env.example"
    if role_l == "doc":
        if base_name.lower() == "readme.md":
            return f"{r}/README.md"
        return f"{r}/docs/{base_name}"
    if role_l in ("entry_script", "module", "library", "package_init", "main_script"):
        return f"{r}/src/{base_name}"
    if role_l in ("config", "manifest"):
        return f"{r}/config/{base_name}"
    if role_l == "shell":
        return f"{r}/scripts/{base_name}"
    if role_l == "sql":
        return f"{r}/sql/{base_name}"
    if role_l == "test":
        return f"{r}/tests/{base_name}"
    return f"{r}/{base_name}"


def iter_integration_delivered_zip_members(
    pkg: dict[str, Any],
    *,
    impl_codes: list[str] | None,
) -> list[tuple[str, bytes]]:
    """
    ZIP에 넣을 (아카이브 내 경로, UTF-8 bytes) 목록.
    python_script 포함 시 `{program_id}/` 프로젝트 트리; 그 외는 기존 평면 구조.
    """
    out: list[tuple[str, bytes]] = []
    ig = (pkg.get("implementation_guide_md") or "").encode("utf-8")
    ts = (pkg.get("test_scenarios_md") or "").encode("utf-8")
    slots = [s for s in (pkg.get("slots") or []) if isinstance(s, dict)]

    if integration_impl_codes_include_python(impl_codes):
        root = sanitize_path_component(str(pkg.get("program_id") or "python_project"), 48) or "python_project"
        out.append((f"{root}/docs/IMPLEMENTATION_GUIDE.md", ig))
        out.append((f"{root}/docs/TEST_SCENARIOS.md", ts))
        used: set[str] = set()
        for idx, sl in enumerate(slots):
            role = str(sl.get("role") or "other")
            base_fn = (str(sl.get("filename") or f"slot_{idx + 1}.txt")).strip() or f"slot_{idx + 1}.txt"
            inner = _zip_inner_path_for_python_project(root, role, base_fn)
            if inner in used:
                stem = base_fn.rsplit(".", 1)[0] if "." in base_fn else base_fn
                ext = base_fn.rsplit(".", 1)[-1] if "." in base_fn else "txt"
                inner = f"{root}/src/{idx + 1:02d}_{stem}.{ext}"
            used.add(inner)
            out.append((inner, (str(sl.get("source") or "")).encode("utf-8")))
        return out

    out.append(("IMPLEMENTATION_GUIDE.md", ig))
    out.append(("TEST_SCENARIOS.md", ts))
    used_names: set[str] = set()
    for idx, sl in enumerate(slots):
        base_fn = (str(sl.get("filename") or f"slot_{idx + 1}.txt")).strip() or f"slot_{idx + 1}.txt"
        fn = base_fn
        if fn in used_names:
            stem = base_fn.rsplit(".", 1)[0] if "." in base_fn else base_fn
            ext = base_fn.rsplit(".", 1)[-1] if "." in base_fn else "txt"
            fn = f"{idx + 1:02d}_{stem}.{ext}"
        used_names.add(fn)
        out.append((fn, (str(sl.get("source") or "")).encode("utf-8")))
    return out


def build_integration_delivered_zip_bytes(pkg: dict[str, Any], *, impl_codes: list[str] | None) -> bytes:
    """연동 납품 패키지 dict → ZIP 바이트."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, raw in iter_integration_delivered_zip_members(pkg, impl_codes=impl_codes):
            zf.writestr(path.replace("\\", "/"), raw)
    return buf.getvalue()
