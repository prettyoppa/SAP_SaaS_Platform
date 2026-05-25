"""신규개발·분석개선 요청 — 대상 SAP 시스템 버전(자유 입력)."""

from __future__ import annotations

NOTE_MAX_LEN = 120
VERSION_MAX_LEN = 120

# 초기 드롭다운·코드 저장값 → 화면 표시용
_LEGACY_LABEL_KO: dict[str, str] = {
    "s4hana": "SAP S/4HANA",
    "s4_2023": "SAP S/4HANA 2023",
    "s4_2022": "SAP S/4HANA 2022",
    "s4_2020": "SAP S/4HANA 2020",
    "s4_1909": "SAP S/4HANA 1909",
    "ecc740": "SAP ECC 6.0 (NetWeaver 7.40)",
    "ecc_ehp8_740": "SAP ECC 6.0 EHP8 (NetWeaver 7.40)",
    "ecc_ehp7_731": "SAP ECC 6.0 EHP7 (NetWeaver 7.31)",
    "ecc_ehp6": "SAP ECC 6.0 EHP6 이하",
    "nw_750": "NetWeaver 7.50",
    "nw_740": "NetWeaver 7.40",
    "nw_731": "NetWeaver 7.31",
    "nw_702": "NetWeaver 7.02 / 7.03",
    "unsure": "아직 확인 중",
    "custom": "기타",
    "other": "기타",
}

_LEGACY_LABEL_EN: dict[str, str] = {
    "s4hana": "SAP S/4HANA",
    "s4_2023": "SAP S/4HANA 2023",
    "s4_2022": "SAP S/4HANA 2022",
    "s4_2020": "SAP S/4HANA 2020",
    "s4_1909": "SAP S/4HANA 1909",
    "ecc740": "SAP ECC 6.0 (NetWeaver 7.40)",
    "ecc_ehp8_740": "SAP ECC 6.0 EHP8 (NetWeaver 7.40)",
    "ecc_ehp7_731": "SAP ECC 6.0 EHP7 (NetWeaver 7.31)",
    "ecc_ehp6": "SAP ECC 6.0 EHP6 or older",
    "nw_750": "NetWeaver 7.50",
    "nw_740": "NetWeaver 7.40",
    "nw_731": "NetWeaver 7.31",
    "nw_702": "NetWeaver 7.02 / 7.03",
    "unsure": "Not confirmed yet",
    "custom": "Other",
    "other": "Other",
}


def normalize_sap_system_version(text: str | None) -> str:
    """공백 제거 후 영문 소문자만 대문자로 변환."""
    raw = (text or "").strip()
    if not raw:
        return ""
    return "".join(ch.upper() if "a" <= ch <= "z" else ch for ch in raw)


def normalize_sap_system_version_note(note: str | None) -> str:
    return (note or "").strip()[:NOTE_MAX_LEN]


def sap_system_version_missing_labels(
    code: str | None,
    note: str | None,
    *,
    required: bool,
) -> list[str]:
    del note  # 자유 입력 단일 필드; note 컬럼은 레거시·부가용
    c = normalize_sap_system_version(code)
    if not required:
        return []
    if not c:
        return ["SAP 시스템 버전"]
    if len(c) > VERSION_MAX_LEN:
        return ["SAP 시스템 버전(120자 이내)"]
    return []


def apply_sap_system_version_to_row(
    row,
    code: str | None,
    note: str | None,
    *,
    required: bool,
) -> str | None:
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
        return "sap_system_version_invalid"
    row.sap_system_version = c
    row.sap_system_version_note = n or None
    return None


def _display_base(code: str, *, lang: str) -> str:
    key = (code or "").strip().lower()
    if lang == "en":
        return _LEGACY_LABEL_EN.get(key) or code
    return _LEGACY_LABEL_KO.get(key) or code


def display_label_ko(code: str | None, note: str | None = None) -> str:
    c = (code or "").strip()
    if not c:
        return "—"
    base = _display_base(c, lang="ko")
    n = normalize_sap_system_version_note(note)
    if n and n.lower() != base.lower():
        return f"{base} ({n})"
    return base


def display_label_en(code: str | None, note: str | None = None) -> str:
    c = (code or "").strip()
    if not c:
        return "—"
    base = _display_base(c, lang="en")
    n = normalize_sap_system_version_note(note)
    if n and n.lower() != base.lower():
        return f"{base} ({n})"
    return base


def _abap_hint_family(code: str) -> str:
    u = (code or "").upper()
    if not u:
        return ""
    if "S/4" in u or u.startswith("S4") or "S/4HANA" in u or u == "S4HANA":
        return "s4"
    if "750" in u or "NW 7.50" in u:
        return "nw750"
    if "740" in u or "EHP8" in u:
        return "nw740"
    if "731" in u or "EHP7" in u or "EHP6" in u or "702" in u or "703" in u:
        return "nw731"
    if u in ("UNSURE",) or "확인" in code:
        return "unsure"
    return "generic"


def agent_prompt_lines(rfp_data: dict) -> str:
    code = normalize_sap_system_version(rfp_data.get("sap_system_version"))
    note = normalize_sap_system_version_note(rfp_data.get("sap_system_version_note"))
    label = display_label_ko(code, note) if code else "(미입력 — 고객에게 확인)"
    lines = [f"- SAP 시스템(대상 환경): {label}"]
    family = _abap_hint_family(code) if code else ""
    if family == "s4":
        lines.append(
            "- ABAP·설계는 **S/4HANA** 환경을 전제로 한다. "
            "ECC 7.40 전용·구식 패턴만 있는 코드는 지양하고, FS 범위에 있을 때만 RAP/CDS 등 S/4 기능을 쓴다."
        )
    elif family == "nw740":
        lines.append(
            "- ABAP·설계는 **NetWeaver 7.40 / ECC EHP8** 호환 문법·API를 우선한다. "
            "S/4 전용 RAP 등은 FS에 명시되지 않으면 넣지 않는다."
        )
    elif family == "nw731":
        lines.append(
            "- ABAP·설계는 **NetWeaver 7.31 전후(구 ECC)** 호환을 우선한다. "
            "7.40+ 전용 구문·신규 API는 FS에 명시되지 않으면 사용하지 않는다."
        )
    elif family == "nw750":
        lines.append(
            "- ABAP·설계는 **NetWeaver 7.50** 계열을 전제로 한다(7.40과 다른 신구문 여부는 FS·표준에 맞게 판단)."
        )
    elif family == "unsure":
        lines.append(
            "- 대상 SAP 버전이 **미확정**이다. 보수적으로 작성하고, 버전 의존 API는 FS·인터뷰에서 확정 후 반영한다."
        )
    elif family == "generic" and code:
        lines.append(f"- 고객 지정 SAP 환경: **{label}** — 이 환경에 맞는 ABAP·API만 사용한다.")
    return "\n".join(lines) + "\n"
