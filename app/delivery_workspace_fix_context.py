"""SE38 납품 작업실 — FS·가이드·전체 ABAP 패키지 컨텍스트 (수정 AI용)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .delivery_fs_supplements import KIND_ANALYSIS, KIND_RFP, resolved_delivery_fs_for_codegen
from .delivery_workspace_context import peer_abap_slot_indices
from .delivery_workspace_validation import MAIN_SLOT_ROLES

# codegen·SE38 가이드와 유사한 예산 (탭 선택 = 오류 위치 앵커, 분석은 패키지 전체)
_PACKAGE_ABAP_MAX = 180_000
_FS_MAX = 72_000
_SE38_GUIDE_MAX = 48_000
_IMPL_GUIDE_MAX = 24_000
_CODER_NOTES_MAX = 12_000

_KIND_FOR_FS = {
    "rfp": KIND_RFP,
    "analysis": KIND_ANALYSIS,
}


def resolved_fs_for_workspace_fix(
    db: Session,
    row: Any,
    request_kind: str,
) -> str:
    rk = _KIND_FOR_FS.get((request_kind or "").strip().lower())
    if not rk:
        return ""
    agent_fs = (getattr(row, "fs_text", None) or "").strip()
    body, _err = resolved_delivery_fs_for_codegen(
        db,
        request_kind=rk,
        request_id=int(row.id),
        agent_fs_text=agent_fs,
    )
    return (body or "").strip()


def build_package_guides_block(pkg: dict[str, Any] | None) -> str:
    if not pkg or not isinstance(pkg, dict):
        return ""
    parts: list[str] = []
    notes = (str(pkg.get("coder_notes") or "")).strip()
    if notes:
        parts.append("### coder_notes (생성 시)\n" + notes[:_CODER_NOTES_MAX])
    se38 = (str(pkg.get("se38_implementation_guide_md") or "")).strip()
    if se38:
        parts.append(
            "### SE38_IMPLEMENTATION_GUIDE (생성 시)\n" + se38[:_SE38_GUIDE_MAX]
        )
    impl = (str(pkg.get("implementation_guide_md") or "")).strip()
    if impl:
        parts.append("### IMPLEMENTATION_GUIDE (발췌)\n" + impl[:_IMPL_GUIDE_MAX])
    if not parts:
        return ""
    return "## 납품 패키지 가이드·메모\n" + "\n\n".join(parts)


def _slot_order_for_analysis(slots: list[dict], active_index: int) -> list[int]:
    """활성(오류 보고) 슬롯 → 메인 → 기타."""
    n = len(slots)
    seen: set[int] = set()
    order: list[int] = []

    def _add(i: int) -> None:
        if 0 <= i < n and i not in seen and isinstance(slots[i], dict):
            if (slots[i].get("source") or "").strip():
                order.append(i)
                seen.add(i)

    _add(active_index)
    for i in peer_abap_slot_indices(slots, active_index=active_index):
        role = (slots[i].get("role") or "").strip().lower()
        if role in MAIN_SLOT_ROLES:
            _add(i)
    for i in peer_abap_slot_indices(slots, active_index=active_index):
        _add(i)
    for i in range(n):
        if i != active_index:
            sl = slots[i]
            if isinstance(sl, dict) and (sl.get("source") or "").strip():
                role = (sl.get("role") or "other").strip().lower()
                if role not in {"doc", "requirements", "env_sample", "package_init"}:
                    _add(i)
    return order


def build_full_package_abap_context(
    slots: list[dict],
    *,
    active_index: int,
    active_filename: str = "",
    max_total_chars: int = _PACKAGE_ABAP_MAX,
) -> tuple[str, int]:
    """
    패키지 ABAP 전체(가능한 한 전문) — SE38 오류 분석용.
    선택 탭은 **오류가 SE38에 보고된 위치**이지, 이 블록만 보라는 뜻이 아님.
    Returns (context_text, slot_count_included).
    """
    if not slots:
        return "(ABAP 슬롯 없음)", 0

    order = _slot_order_for_analysis(slots, active_index)
    if not order:
        return "(ABAP 슬롯 소스 없음)", 0

    afn = (active_filename or "").strip().lower()
    parts: list[str] = [
        "## 패키지 ABAP 전체 (분석용 — FS·SE38 오류와 대조)",
        "- UI에서 선택한 탭은 **SE38에서 오류가 표시된 파일(위치 앵커)** 입니다.",
        "- 수정 위치는 메인·다른 INCLUDE일 수 있습니다. **아래 모든 슬롯**을 읽고 판단하세요.",
        "",
    ]
    budget = max_total_chars
    included = 0
    for i in order:
        sl = slots[i]
        fn = (sl.get("filename") or f"slot_{i + 1}.abap").strip()
        role = (sl.get("role") or "other").strip()
        source = (sl.get("source") or "").strip()
        marker = ""
        if i == active_index or fn.lower() == afn:
            marker = " ← **SE38 오류 보고 위치(현재 탭)**"
        if len(source) > budget - 200:
            chunk = source[: max(0, budget - 200)]
            if chunk:
                chunk += "\n* ... (패키지 ABAP 총량 제한으로 이 슬롯 일부만 포함) ..."
        else:
            chunk = source
        block = f"### {fn} (role={role}, index={i}){marker}\n```abap\n{chunk}\n```"
        if len(block) > budget:
            if budget > 300:
                parts.append(
                    block[: budget - 80]
                    + "\n* ... (총량 제한으로 이하 슬롯 생략) ...\n```"
                )
                included += 1
            break
        parts.append(block)
        budget -= len(block)
        included += 1

    return "\n\n".join(parts), included
