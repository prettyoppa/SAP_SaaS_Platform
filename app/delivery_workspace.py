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
    pkg = parse_package(raw_work, kind)
    if pkg and package_has_slots(pkg, kind):
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
    normalized = normalize_package(pkg, kind)
    if not normalized:
        raise ValueError("invalid_package")
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
