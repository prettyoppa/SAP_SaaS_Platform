"""
Paid Tier — FS·납품 ABAP (1차: Markdown 스텁, 추후 Crew/LLM 연동).
"""

from __future__ import annotations

from typing import Any


def generate_fs_markdown(rfp_summary: dict[str, Any], proposal_text: str) -> str:
    """기능명세서 형태의 Markdown (스텁)."""
    title = rfp_summary.get("title") or "(제목 없음)"
    mods = ", ".join(rfp_summary.get("sap_modules") or []) or "—"
    dtypes = ", ".join(rfp_summary.get("dev_types") or []) or "—"
    prop = (proposal_text or "").strip()
    excerpt = prop[:6000] + ("\n\n…(Proposal 발췌 종료)" if len(prop) > 6000 else "")
    return f"""# Functional Specification (초안·스텁)

> **RFP**: {title}
> **모듈**: {mods}
> **개발 유형**: {dtypes}

## 1. 개요

유료 단계 FS 자동 생성 파이프라인이 연결되기 전까지는 **스텁 문서**가 저장됩니다.
관리자 화면에서 재생성할 수 있습니다.

## 2. Proposal 기반 발췌

{excerpt}

## 3. 추후 보강 항목

- 인터뷰·요구사항 상세 반영
- 인터페이스·데이터 대상·권한·예외 시나리오
- 단위 테스트·이행 체크리스트

---
*generated_by=paid_crew_stub*
"""


def generate_delivered_abap_markdown(rfp_summary: dict[str, Any], fs_text: str) -> str:
    """납품 ABAP를 Markdown 코드 블록으로 (스텁)."""
    title = rfp_summary.get("title") or ""
    prog = rfp_summary.get("program_id") or "Z_STUB_REPORT"
    fs_excerpt = (fs_text or "").strip()[:4000]
    return f"""# Delivered ABAP (스텁)

RFP **{title}** — 프로그램 ID 예시: `{prog}`

## ABAP 소스 (스텁)

```abap
*&---------------------------------------------------------------------*
*& 유료 단계 코드 생성 에이전트 연결 전 스텁
*& 실제 과제에서는 FS·Proposal·인터뷰 내용을 반영한 프로그램이 생성됩니다.
REPORT {prog}.

WRITE: / 'Stub delivery for Catchy Lab RFP'.

" TODO: 목록/선택 화면, 권한, 예외 처리 등
*&---------------------------------------------------------------------*
```

## FS 발췌 (참조)

{fs_excerpt}

---
*generated_by=paid_crew_stub*
"""
