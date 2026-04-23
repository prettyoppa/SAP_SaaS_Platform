"""
RFP 참고 ABAP — 서버에 본 RFP 행에만 저장(코드 라이브러리 테이블 미사용), 에이전트 프롬프트용 서식.
"""
from __future__ import annotations

import json
import re

# 전체 JSON UTF-8 기준 상한 (대략 512KB)
MAX_REFERENCE_CODE_BYTES = 512 * 1024
# 슬롯당 ABAP 섹션 코드 최대 길이
MAX_SECTION_CODE_CHARS = 120_000


def normalize_reference_code_payload(raw: str | None) -> str | None:
    """
    클라이언트 JSON을 검증·정규화해 저장용 문자열로 반환.
    비어 있거나 유효하지 않으면 None.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s.encode("utf-8")) > MAX_REFERENCE_CODE_BYTES:
        raise ValueError("reference_code_too_large")
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    slots_in = data.get("slots")
    if not isinstance(slots_in, list):
        return None
    slots_out: list[dict] = []
    for i, slot in enumerate(slots_in[:3]):
        if not isinstance(slot, dict):
            continue
        pid = _clean_str(slot.get("program_id"), 40)
        tc = _clean_str(slot.get("transaction_code"), 20)
        title = _clean_str(slot.get("title"), 200)
        sm = _clean_str_list(slot.get("sap_modules"), 3, 32)
        dt = _clean_str_list(slot.get("dev_types"), 3, 32)
        sections_in = slot.get("sections")
        sections_out: list[dict] = []
        if isinstance(sections_in, list):
            for sec in sections_in[:50]:
                if not isinstance(sec, dict):
                    continue
                typ = _clean_str(sec.get("type"), 80)
                name = _clean_str(sec.get("name"), 200)
                code = _clean_str(sec.get("code"), MAX_SECTION_CODE_CHARS)
                if typ or name or code:
                    sections_out.append({"type": typ or "메인 프로그램", "name": name, "code": code})
        if not sections_out:
            sections_out = [{"type": "메인 프로그램", "name": "", "code": ""}]
        slots_out.append({
            "program_id": pid,
            "transaction_code": tc,
            "title": title,
            "sap_modules": sm,
            "dev_types": dt,
            "sections": sections_out,
        })
    while len(slots_out) < 3:
        slots_out.append({
            "program_id": "",
            "transaction_code": "",
            "title": "",
            "sap_modules": [],
            "dev_types": [],
            "sections": [{"type": "메인 프로그램", "name": "", "code": ""}],
        })
    vis = data.get("visibleSlotCount")
    if isinstance(vis, int) and 1 <= vis <= 3:
        vsc = vis
    else:
        vsc = _infer_visible_slots(slots_out)
    out = {"v": 1, "slots": slots_out, "visibleSlotCount": vsc}
    blob = json.dumps(out, ensure_ascii=False)
    if len(blob.encode("utf-8")) > MAX_REFERENCE_CODE_BYTES:
        raise ValueError("reference_code_too_large")
    if not _slots_have_any_content(slots_out, vsc):
        return None
    return blob


def _clean_str(val, max_len: int) -> str:
    if val is None:
        return ""
    t = str(val).strip()
    if len(t) > max_len:
        t = t[:max_len]
    return t


def _clean_str_list(val, max_n: int, max_each: int) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val[:max_n]:
        s = _clean_str(x, max_each)
        if s and s not in out:
            out.append(s)
    return out


def _infer_visible_slots(slots: list[dict]) -> int:
    n = 1
    for i, sl in enumerate(slots[:3]):
        if _slot_nonempty(sl):
            n = i + 1
    return min(3, max(1, n))


def _slot_nonempty(sl: dict) -> bool:
    if (sl.get("program_id") or "").strip():
        return True
    if (sl.get("transaction_code") or "").strip():
        return True
    if (sl.get("title") or "").strip():
        return True
    if sl.get("sap_modules"):
        return True
    if sl.get("dev_types"):
        return True
    for sec in sl.get("sections") or []:
        if (sec.get("code") or "").strip():
            return True
        if (sec.get("name") or "").strip():
            return True
    return False


def _slots_have_any_content(slots: list[dict], visible: int) -> bool:
    for i in range(min(visible, len(slots))):
        if _slot_nonempty(slots[i]):
            return True
    return False


def format_reference_code_for_llm(payload: str | None) -> str:
    """에이전트 프롬프트에 넣을 한국어 텍스트. (회원 UI 용어와 분리)"""
    if not payload or not str(payload).strip():
        return ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    slots = data.get("slots")
    if not isinstance(slots, list):
        return ""
    vis = data.get("visibleSlotCount")
    if isinstance(vis, int) and 1 <= vis <= 3:
        n_vis = vis
    else:
        n_vis = _infer_visible_slots(slots)
    parts: list[str] = []
    shown = 0
    for i, sl in enumerate(slots[:n_vis]):
        if not isinstance(sl, dict):
            continue
        if not _slot_nonempty(sl):
            continue
        shown += 1
        block: list[str] = [f"=== 참고 ABAP #{shown} ==="]
        if (sl.get("program_id") or "").strip():
            block.append(f"프로그램 ID: {sl['program_id'].strip()}")
        if (sl.get("transaction_code") or "").strip():
            block.append(f"트랜잭션: {sl['transaction_code'].strip()}")
        if (sl.get("title") or "").strip():
            block.append(f"설명: {sl['title'].strip()}")
        sm = sl.get("sap_modules") or []
        if sm:
            block.append(f"표시 모듈 태그: {', '.join(sm)}")
        dt = sl.get("dev_types") or []
        if dt:
            block.append(f"표시 개발유형 태그: {', '.join(dt)}")
        secs = sl.get("sections") or []
        for j, sec in enumerate(secs, start=1):
            if not isinstance(sec, dict):
                continue
            code = (sec.get("code") or "").strip()
            if not code and not (sec.get("name") or "").strip():
                continue
            label = (sec.get("type") or "섹션").strip()
            name = (sec.get("name") or "").strip()
            head = f"[섹션 {j}] {label}" + (f" – {name}" if name else "")
            block.append(head)
            if code:
                c = code
                if len(c) > 24_000:
                    c = c[:24_000] + "\n… (이하 생략)"
                block.append(c)
        parts.append("\n".join(block))
    if not parts:
        return ""
    intro = (
        "아래는 회원이 본 개발 요청에 첨부한 참고 ABAP입니다. "
        "요청 이해·개발 제안서 작성에만 활용하고, RFP·인터뷰 내용과 모순되면 RFP·인터뷰를 우선합니다.\n"
    )
    return intro + "\n\n".join(parts)


def strip_for_display_log(payload: str | None, max_chars: int = 200) -> str:
    """로그용 초간단 표시 (내용 노출 최소)."""
    if not payload:
        return ""
    t = re.sub(r"\s+", " ", payload).strip()
    return t[:max_chars] + ("…" if len(t) > max_chars else "")
