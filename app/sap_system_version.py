"""신규개발·분석개선 요청 — 대상 SAP 시스템 버전(S/4HANA, ECC 7.40, 기타)."""

from __future__ import annotations

ALLOWED_SAP_SYSTEM_VERSIONS = frozenset({"s4hana", "ecc740", "other"})

LABEL_KO = {
    "s4hana": "S/4HANA",
    "ecc740": "ECC 7.40",
    "other": "기타",
}
LABEL_EN = {
    "s4hana": "S/4HANA",
    "ecc740": "ECC 7.40",
    "other": "Other",
}

NOTE_MAX_LEN = 120


def normalize_sap_system_version(code: str | None) -> str:
    return (code or "").strip().lower()


def normalize_sap_system_version_note(note: str | None) -> str:
    return (note or "").strip()[:NOTE_MAX_LEN]


def sap_system_version_missing_labels(
    code: str | None,
    note: str | None,
    *,
    required: bool,
) -> list[str]:
    """제출 시 필수 검증 라벨(한국어, core_fields_incomplete용)."""
    c = normalize_sap_system_version(code)
    n = normalize_sap_system_version_note(note)
    if not required:
        if not c:
            return []
        if c not in ALLOWED_SAP_SYSTEM_VERSIONS:
            return ["SAP 시스템 버전(올바른 선택)"]
        if c == "other" and not n:
            return ["SAP 시스템 버전(기타 설명)"]
        return []
    if not c:
        return ["SAP 시스템 버전"]
    if c not in ALLOWED_SAP_SYSTEM_VERSIONS:
        return ["SAP 시스템 버전(올바른 선택)"]
    if c == "other" and not n:
        return ["SAP 시스템 버전(기타 설명)"]
    return []


def apply_sap_system_version_to_row(
    row,
    code: str | None,
    note: str | None,
    *,
    required: bool,
) -> str | None:
    """
    row에 sap_system_version / sap_system_version_note 저장.
    실패 시 error code: sap_system_version_invalid | sap_system_version_note_required
    """
    c = normalize_sap_system_version(code)
    n = normalize_sap_system_version_note(note)
    if not required and not c:
        row.sap_system_version = None
        row.sap_system_version_note = None
        return None
    miss = sap_system_version_missing_labels(c, n, required=required)
    if miss:
        if not c:
            return "sap_system_version_required"
        if c not in ALLOWED_SAP_SYSTEM_VERSIONS:
            return "sap_system_version_invalid"
        return "sap_system_version_note_required"
    row.sap_system_version = c
    row.sap_system_version_note = n if c == "other" else None
    return None


def display_label_ko(code: str | None, note: str | None = None) -> str:
    c = normalize_sap_system_version(code)
    if not c:
        return "—"
    base = LABEL_KO.get(c, c)
    n = normalize_sap_system_version_note(note)
    if c == "other" and n:
        return f"{base} ({n})"
    return base


def display_label_en(code: str | None, note: str | None = None) -> str:
    c = normalize_sap_system_version(code)
    if not c:
        return "—"
    base = LABEL_EN.get(c, c)
    n = normalize_sap_system_version_note(note)
    if c == "other" and n:
        return f"{base} ({n})"
    return base


def agent_prompt_lines(rfp_data: dict) -> str:
    """FS·납품 ABAP·인터뷰 프롬프트용 한 줄+ABAP 지침."""
    code = normalize_sap_system_version(rfp_data.get("sap_system_version"))
    note = normalize_sap_system_version_note(rfp_data.get("sap_system_version_note"))
    label = display_label_ko(code, note) if code else "(미입력 — 고객에게 확인)"
    lines = [f"- SAP 시스템(대상 환경): {label}"]
    if code == "s4hana":
        lines.append(
            "- ABAP·설계는 **S/4HANA** 관례를 따른다(7.5x+, RAP/CDS 등은 FS 범위에 있을 때만). "
            "ECC 7.40 전용·구식 패턴만 있는 코드는 지양한다."
        )
    elif code == "ecc740":
        lines.append(
            "- ABAP·설계는 **ECC 7.40** 호환 문법·API만 사용한다. "
            "S/4 전용 RAP/임베디드 CDS 등은 FS에 명시되지 않으면 넣지 않는다."
        )
    elif code == "other" and note:
        lines.append(f"- 고객 지정 SAP 환경: **{note}** — 이 환경에 맞는 ABAP·API만 사용한다.")
    return "\n".join(lines) + "\n"
