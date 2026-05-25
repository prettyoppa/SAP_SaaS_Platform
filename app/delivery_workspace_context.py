"""납품 작업실 — AI 제안 시 패키지 내 다른 슬롯 소스(읽기 전용 컨텍스트)."""

from __future__ import annotations

from .delivery_workspace_validation import MAIN_SLOT_ROLES

_ABAP_SKIP_ROLES = frozenset({"doc", "requirements", "env_sample", "package_init"})

_DEFAULT_MAX_TOTAL = 32_000
_DEFAULT_MAX_PER_SLOT = 10_000


def _is_abap_peer_slot(sl: dict) -> bool:
    role = (sl.get("role") or "other").strip().lower()
    return role not in _ABAP_SKIP_ROLES


def peer_abap_slot_indices(slots: list[dict], *, active_index: int) -> list[int]:
    out: list[int] = []
    for i, sl in enumerate(slots):
        if i == active_index or not isinstance(sl, dict):
            continue
        if not _is_abap_peer_slot(sl):
            continue
        if not (sl.get("source") or "").strip():
            continue
        out.append(i)

    def _sort_key(i: int) -> tuple[int, int]:
        role = (slots[i].get("role") or "other").strip().lower()
        if role in MAIN_SLOT_ROLES:
            return (0, i)
        return (1, i)

    out.sort(key=_sort_key)
    return out


def build_peer_sources_context(
    slots: list[dict],
    *,
    active_index: int,
    max_total_chars: int = _DEFAULT_MAX_TOTAL,
    max_per_slot: int = _DEFAULT_MAX_PER_SLOT,
) -> tuple[str, int]:
    """
    현재 슬롯을 제외한 ABAP 슬롯 소스를 프롬프트용 문자열로 묶음.
    Returns (context_text, peer_count_included).
    """
    indices = peer_abap_slot_indices(slots, active_index=active_index)
    if not indices:
        return "(다른 ABAP 슬롯 소스 없음)", 0

    parts: list[str] = []
    budget = max_total_chars
    included = 0
    for i in indices:
        sl = slots[i]
        fn = (sl.get("filename") or f"slot_{i + 1}.abap").strip()
        role = (sl.get("role") or "other").strip()
        source = (sl.get("source") or "").strip()
        chunk = source[:max_per_slot]
        truncated = len(source) > max_per_slot
        if truncated:
            chunk += "\n* ... (이 슬롯은 컨텍스트 길이 제한으로 일부만 포함) ..."
        block = f"### {fn} (role={role})\n```abap\n{chunk}\n```"
        if len(block) > budget:
            if budget > 200:
                parts.append(
                    block[: budget - 80]
                    + "\n* ... (패키지 컨텍스트 총량 제한으로 이하 생략) ...\n```"
                )
                included += 1
            break
        parts.append(block)
        budget -= len(block)
        included += 1

    if not parts:
        return "(다른 ABAP 슬롯 소스 없음)", 0
    header = (
        f"아래 {included}개 파일은 **읽기 전용 참고**입니다. "
        "INCLUDE·메인 관계와 SE38 오류를 함께 보고 수정 위치를 판단하세요. "
        "출력·수정 제안은 규칙에 따라 **현재 슬롯만** 합니다.\n\n"
    )
    return header + "\n\n".join(parts), included
