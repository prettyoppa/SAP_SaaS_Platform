"""납품 ABAP 구현 보완 — 작업용 패키지(JSON) · 슬롯 저장 · 수동 ZIP."""

from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .delivered_code_package import (
    build_abap_delivered_zip_bytes,
    build_integration_delivered_zip_bytes,
    delivered_package_has_body,
    integration_delivered_package_has_body,
    normalize_delivered_package,
    normalize_integration_delivered_package,
    parse_delivered_code_payload,
    parse_integration_delivered_payload,
)
from .delivery_fs_supplements import KIND_ANALYSIS, KIND_INTEGRATION, KIND_RFP

KIND_ALIASES = {
    "rfp": KIND_RFP,
    "analysis": KIND_ANALYSIS,
    "integration": KIND_INTEGRATION,
    KIND_RFP: KIND_RFP,
    KIND_ANALYSIS: KIND_ANALYSIS,
    KIND_INTEGRATION: KIND_INTEGRATION,
}

# 작업본 JSON 메타 — normalize_delivered_package 대상 아님(ZIP·슬롯 스키마 제외)
WORKSPACE_PENDING_KEY = "_workspace_pending"


def _read_pending_from_raw(raw: str | None) -> dict[str, Any] | None:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    pending = data.get(WORKSPACE_PENDING_KEY) if isinstance(data, dict) else None
    return pending if isinstance(pending, dict) else None


def get_pending_suggestion(pkg: dict[str, Any] | None, slot_index: int) -> dict[str, Any] | None:
    """슬롯별 마지막 AI 수정 제안(작업본 JSON에 저장)."""
    if not pkg or not isinstance(pkg, dict):
        return None
    pending = pkg.get(WORKSPACE_PENDING_KEY)
    if not isinstance(pending, dict):
        return None
    try:
        if int(pending.get("slot_index", -1)) != int(slot_index):
            return None
    except (TypeError, ValueError):
        return None
    return pending


def set_pending_suggestion(
    db: Session,
    row: Any,
    request_kind: str,
    slot_index: int,
    *,
    suggested_source: str,
    se38_error: str = "",
    fix_elsewhere_target: str | None = None,
    fix_elsewhere_reason: str | None = None,
    peer_count: int = 0,
) -> None:
    pkg = get_working_package(db, row, request_kind)
    if not pkg:
        raise ValueError("no_package")
    pkg[WORKSPACE_PENDING_KEY] = {
        "slot_index": int(slot_index),
        "suggested_source": (suggested_source or "")[:200_000],
        "se38_error": (se38_error or "")[:8_000],
        "fix_elsewhere_target": (fix_elsewhere_target or "").strip()[:500],
        "fix_elsewhere_reason": (fix_elsewhere_reason or "").strip()[:2_000],
        "peer_count": max(0, int(peer_count)),
    }
    save_working_package(db, row, pkg, request_kind)


def clear_pending_suggestion(db: Session, row: Any, request_kind: str) -> None:
    pkg = get_working_package(db, row, request_kind)
    if not pkg or WORKSPACE_PENDING_KEY not in pkg:
        return
    del pkg[WORKSPACE_PENDING_KEY]
    save_working_package(db, row, pkg, request_kind)


def normalize_request_kind(raw: str | None) -> str | None:
    k = (raw or "").strip().lower()
    return KIND_ALIASES.get(k)


def load_request_row(db: Session, *, request_kind: str, request_id: int) -> Any | None:
    kind = normalize_request_kind(request_kind)
    if not kind:
        return None
    rid = int(request_id)
    if kind == KIND_RFP:
        return db.query(models.RFP).filter(models.RFP.id == rid).first()
    if kind == KIND_ANALYSIS:
        return db.query(models.AbapAnalysisRequest).filter(models.AbapAnalysisRequest.id == rid).first()
    if kind == KIND_INTEGRATION:
        return (
            db.query(models.IntegrationRequest)
            .filter(models.IntegrationRequest.id == rid)
            .first()
        )
    return None


def parse_package(raw: str | None, request_kind: str) -> dict[str, Any] | None:
    kind = normalize_request_kind(request_kind) or ""
    if kind == KIND_INTEGRATION:
        return parse_integration_delivered_payload(raw)
    return parse_delivered_code_payload(raw)


def package_has_slots(pkg: dict[str, Any] | None, request_kind: str) -> bool:
    kind = normalize_request_kind(request_kind) or ""
    if kind == KIND_INTEGRATION:
        return integration_delivered_package_has_body(pkg)
    return delivered_package_has_body(pkg)


def normalize_package(pkg: dict[str, Any], request_kind: str) -> dict[str, Any] | None:
    kind = normalize_request_kind(request_kind) or ""
    if kind == KIND_INTEGRATION:
        return normalize_integration_delivered_package(pkg)
    return normalize_delivered_package(pkg)


def get_official_package(row: Any, request_kind: str) -> dict[str, Any] | None:
    return parse_package(getattr(row, "delivered_code_payload", None), request_kind)


def get_working_package(db: Session, row: Any, request_kind: str) -> dict[str, Any] | None:
    """작업 복사본 반환. 없으면 공식 납품에서 fork(공식 payload는 변경하지 않음)."""
    kind = normalize_request_kind(request_kind)
    if not kind:
        return None
    raw_work = getattr(row, "delivered_code_working_payload", None)
    pending = _read_pending_from_raw(raw_work)
    pkg = parse_package(raw_work, kind)
    if pkg and package_has_slots(pkg, kind):
        if pending is not None:
            pkg[WORKSPACE_PENDING_KEY] = pending
        return pkg
    official = get_official_package(row, kind)
    if not official:
        return None
    working = copy.deepcopy(official)
    normalized = normalize_package(working, kind)
    if not normalized:
        return None
    save_working_package(db, row, normalized, kind)
    return normalized


def save_working_package(
    db: Session, row: Any, pkg: dict[str, Any], request_kind: str
) -> None:
    kind = normalize_request_kind(request_kind) or ""
    pending = pkg.get(WORKSPACE_PENDING_KEY) if isinstance(pkg.get(WORKSPACE_PENDING_KEY), dict) else None
    pkg_for_norm = {k: v for k, v in pkg.items() if k != WORKSPACE_PENDING_KEY}
    normalized = normalize_package(pkg_for_norm, kind)
    if not normalized:
        raise ValueError("invalid_package")
    if pending is not None:
        normalized[WORKSPACE_PENDING_KEY] = pending
    row.delivered_code_working_payload = json.dumps(normalized, ensure_ascii=False)
    db.add(row)
    db.flush()


def apply_slot_source(
    db: Session,
    row: Any,
    request_kind: str,
    slot_index: int,
    new_source: str,
) -> dict[str, Any] | None:
    pkg = get_working_package(db, row, request_kind)
    if not pkg:
        return None
    slots = pkg.get("slots")
    if not isinstance(slots, list) or slot_index < 0 or slot_index >= len(slots):
        raise IndexError("slot_index")
    if not isinstance(slots[slot_index], dict):
        raise IndexError("slot_index")
    from .delivered_code_package import normalize_slot_source_text

    slots[slot_index]["source"] = normalize_slot_source_text(new_source)
    pkg["slots"] = slots
    normalized = normalize_package(pkg, request_kind)
    if not normalized:
        raise ValueError("invalid_package")
    save_working_package(db, row, normalized, request_kind)
    return normalized


def build_workspace_zip_bytes(row: Any, pkg: dict[str, Any], request_kind: str) -> bytes:
    kind = normalize_request_kind(request_kind) or ""
    if kind == KIND_INTEGRATION:
        impl_codes = [
            x.strip()
            for x in (getattr(row, "impl_types", None) or "").split(",")
            if x.strip()
        ]
        return build_integration_delivered_zip_bytes(pkg, impl_codes=impl_codes)
    return build_abap_delivered_zip_bytes(pkg)


def slots_for_ui(pkg: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for i, sl in enumerate(pkg.get("slots") or []):
        if not isinstance(sl, dict):
            continue
        out.append(
            {
                "index": str(i),
                "filename": (sl.get("filename") or f"slot_{i + 1}.abap").strip(),
                "role": (sl.get("role") or "other").strip(),
                "title_ko": (sl.get("title_ko") or sl.get("title") or "").strip(),
            }
        )
    return out


def slots_detail_for_ui(pkg: dict[str, Any]) -> list[dict[str, Any]]:
    """작업실 UI: 슬롯별 소스 포함(클라이언트 탭 전환용)."""
    out: list[dict[str, Any]] = []
    for i, sl in enumerate(pkg.get("slots") or []):
        if not isinstance(sl, dict):
            continue
        out.append(
            {
                "index": i,
                "filename": (sl.get("filename") or f"slot_{i + 1}.abap").strip(),
                "role": (sl.get("role") or "other").strip(),
                "source": (sl.get("source") or "").strip(),
            }
        )
    return out
