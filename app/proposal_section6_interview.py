"""제안서 §6 확인 필요 사항 — 요청자용 추가 인터뷰(쉬운 질문·좋아요/싫어요 선지)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from crewai import Agent, Crew, Process, Task

from .agents.free_crew import (
    _get_llm,
    _normalize_suggested_answers,
    _parse_question_and_suggestions,
    generate_suggested_answers_for_question,
)
from .interview_answer_payload import (
    format_parsed_step_answer,
    parse_answer_payload_form,
    step_payload_valid,
)
_INTERVIEW_VERSION = 2


def _empty_interview_state(open_items: list[str]) -> dict[str, Any]:
    return {
        "version": _INTERVIEW_VERSION,
        "interview": {
            "status": "idle",
            "open_items": open_items,
            "current_index": 0,
            "turns": [],
            "additional": "",
        },
        "items": [],
        "additional": "",
    }


def load_section6_payload(raw: str | None) -> dict[str, Any]:
    if not (raw or "").strip():
        return _empty_interview_state([])
    try:
        data = json.loads(raw)
    except Exception:
        return _empty_interview_state([])
    if not isinstance(data, dict):
        return _empty_interview_state([])
    if data.get("version") == _INTERVIEW_VERSION and isinstance(data.get("interview"), dict):
        inv = data["interview"]
        inv.setdefault("status", "idle")
        inv.setdefault("open_items", [])
        inv.setdefault("current_index", 0)
        inv.setdefault("turns", [])
        inv.setdefault("additional", "")
        data.setdefault("items", [])
        data.setdefault("additional", inv.get("additional") or "")
        return data
    items = data.get("items")
    if isinstance(items, list):
        return {
            "version": 1,
            "interview": {
                "status": "complete" if items else "idle",
                "open_items": [],
                "current_index": 0,
                "turns": [],
                "additional": str(data.get("additional") or "").strip(),
            },
            "items": items,
            "additional": str(data.get("additional") or "").strip(),
        }
    return _empty_interview_state([])


def save_section6_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _items_from_turns(turns: list[dict]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        label = (t.get("open_item") or "").strip()
        dec = (t.get("decision_text") or "").strip()
        if label and dec:
            out.append({"label": label, "decision": dec})
    return out


def finalize_interview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    inv = payload.get("interview") or {}
    turns = inv.get("turns") or []
    inv["status"] = "complete"
    payload["items"] = _items_from_turns(turns)
    payload["additional"] = (inv.get("additional") or "").strip()
    payload["interview"] = inv
    return payload


def has_section6_decisions(payload: dict[str, Any]) -> bool:
    inv = payload.get("interview") or {}
    if (inv.get("status") or "").strip() == "complete":
        turns = inv.get("turns") or []
        if any((t.get("decision_text") or "").strip() for t in turns if isinstance(t, dict)):
            return True
    for row in payload.get("items") or []:
        if isinstance(row, dict) and (row.get("decision") or "").strip():
            return True
    return bool((payload.get("additional") or "").strip())


def format_section6_for_downstream(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    inv = payload.get("interview") or {}
    turns = inv.get("turns") or []
    if turns:
        for t in turns:
            if not isinstance(t, dict):
                continue
            label = (t.get("open_item") or "").strip()
            dec = (t.get("decision_text") or "").strip()
            if not dec:
                continue
            q = (t.get("question") or "").strip()
            if label:
                block = f"- **확인 항목:** {label}"
                if q:
                    block += f"\n  - **질문:** {q}"
                block += f"\n  - **요청자 최종 결정:** {dec}"
                parts.append(block)
            else:
                parts.append(f"- {dec}")
    else:
        for row in payload.get("items") or []:
            if not isinstance(row, dict):
                continue
            label = (row.get("label") or "").strip()
            dec = (row.get("decision") or "").strip()
            if not dec:
                continue
            if label:
                parts.append(
                    f"- **확인 항목:** {label}\n  - **요청자 최종 결정:** {dec}"
                )
            else:
                parts.append(f"- {dec}")
    add = (payload.get("additional") or inv.get("additional") or "").strip()
    if add:
        parts.append(f"\n**추가 최종 결정·메모:**\n{add}")
    return "\n".join(parts).strip()


def generate_section6_interview_turn(
    *,
    open_item: str,
    item_index: int,
    total_items: int,
    prior_turns: list[dict],
    request_title: str,
) -> dict[str, Any]:
    """LLM: 기술적 §6 항목 → 이해하기 쉬운 질문 + suggested_answers."""
    llm = _get_llm()
    agent = Agent(
        role="SAP 고객 확인 인터뷰 도우미",
        goal="비전문 요청자가 Development Proposal §6 항목에 답할 수 있게 쉬운 질문과 선택지를 만든다",
        backstory="SAP 컨설턴트이지만 고객 담당자(IT 비전문)에게 말한다. 전문 용어는 짧게 풀어 쓴다.",
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    prior_lines: list[str] = []
    for i, t in enumerate(prior_turns[:6], 1):
        if not isinstance(t, dict):
            continue
        prior_lines.append(
            f"[이전 {i}] 항목: {(t.get('open_item') or '')[:200]}\n"
            f"질문: {(t.get('question') or '')[:200]}\n"
            f"답: {(t.get('decision_text') or '')[:300]}"
        )
    prior_block = "\n".join(prior_lines) if prior_lines else "(없음)"
    task = Task(
        description=f"""개발 제안서 §6(확인 필요 사항) 중 **한 항목**에 대해 고객 인터뷰 질문을 만드세요.

[요청 제목] {request_title or '개발 요청'}
[진행] {item_index + 1} / {total_items}
[이번 §6 원문(기술적)]
{open_item[:4000]}

[이미 끝낸 다른 §6 인터뷰]
{prior_block}

규칙:
- 고객(IT 비전문)이 읽을 **한 가지** 질문만. 2~4문장 이하.
- SAP·ABAP 용어는 괄호로 짧게 풀어 설명.
- 개발자만 아는 세부(테이블명·메소드 내부 구현)는 질문에 넣지 말고 **비즈니스 선택**으로 바꿔 물어본다.
- suggested_answers 2~4개: 각각 **한 줄** 완결 답(복수 선택 가능한 대안). 과장된 존댓말 금지.
- JSON 출력에 **별표 강조(**) 사용 금지.

반드시 JSON 한 블록만:
{{"question": "...", "suggested_answers": ["...", "..."]}}""",
        agent=agent,
        expected_output="JSON",
    )
    try:
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        raw = str(crew.kickoff())
        q, su = _parse_question_and_suggestions(raw)
        if not q:
            q = "이 항목에 대해 어떻게 진행할지 알려 주시겠어요?"
        su = _normalize_suggested_answers(su)
        if len(su) < 2:
            more = generate_suggested_answers_for_question(
                {"title": request_title, "description": open_item},
                q,
                1,
                1,
            )
            su = _normalize_suggested_answers(list(su) + list(more))
        return {"question": q[:2000], "suggested_answers": su[:5]}
    except Exception:
        q = "아래 확인 사항에 대해 선호하시는 방향을 알려 주세요."
        return {
            "question": q,
            "suggested_answers": [
                "표준 방식으로 진행해 주세요",
                "가능한 범위만 단순하게 진행해 주세요",
                "잘 모르겠으니 컨설턴트 제안을 따르겠습니다",
            ],
        }


def start_section6_interview(
    *,
    open_items: list[str],
    request_title: str,
) -> dict[str, Any]:
    payload = _empty_interview_state(open_items)
    if not open_items:
        inv = payload["interview"]
        inv["status"] = "complete"
        return payload
    turn = generate_section6_interview_turn(
        open_item=open_items[0],
        item_index=0,
        total_items=len(open_items),
        prior_turns=[],
        request_title=request_title,
    )
    inv = payload["interview"]
    inv["status"] = "active"
    inv["current_index"] = 0
    inv["turns"] = [
        {
            "open_item": open_items[0],
            "question": turn["question"],
            "suggestions": turn.get("suggested_answers") or [],
            "answer_payload": None,
            "decision_text": "",
        }
    ]
    return payload


def advance_section6_interview(
    payload: dict[str, Any],
    *,
    answer_payload: dict,
    current_answer: str,
    request_title: str,
) -> dict[str, Any]:
    inv = payload.setdefault("interview", {})
    open_items = list(inv.get("open_items") or [])
    turns: list[dict] = list(inv.get("turns") or [])
    idx = int(inv.get("current_index") or 0)
    if idx >= len(turns) or idx >= len(open_items):
        return finalize_interview_payload(payload)

    if isinstance(answer_payload, dict):
        o = answer_payload
    else:
        o = parse_answer_payload_form(
            json.dumps(answer_payload) if answer_payload else str(answer_payload or ""),
            current_answer,
        )
    if not step_payload_valid(o):
        raise ValueError("answer_invalid")

    decision_text = format_parsed_step_answer(o)
    turns[idx] = {
        **turns[idx],
        "answer_payload": o,
        "decision_text": decision_text,
    }
    inv["turns"] = turns

    next_idx = idx + 1
    if next_idx >= len(open_items):
        inv["status"] = "complete"
        inv["current_index"] = next_idx
        return finalize_interview_payload(payload)

    prior = [t for t in turns if (t.get("decision_text") or "").strip()]
    turn = generate_section6_interview_turn(
        open_item=open_items[next_idx],
        item_index=next_idx,
        total_items=len(open_items),
        prior_turns=prior,
        request_title=request_title,
    )
    turns.append(
        {
            "open_item": open_items[next_idx],
            "question": turn["question"],
            "suggestions": turn.get("suggested_answers") or [],
            "answer_payload": None,
            "decision_text": "",
        }
    )
    inv["turns"] = turns
    inv["current_index"] = next_idx
    inv["status"] = "active"
    payload["interview"] = inv
    return payload
