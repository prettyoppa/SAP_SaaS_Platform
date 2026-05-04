"""RFP 납품 ABAP — JSON 패키지(slots + 가이드 + 테스트) 파싱·검증·레거시 마크다운."""

from __future__ import annotations

import json
import re
from typing import Any

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
