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
from .interview_suggestions import finalize_suggestion_payload, resolve_groups_for_display
from .interview_answer_payload import (
    format_parsed_step_answer,
    parse_answer_payload_form,
    step_payload_valid,
)
from .interview_locale import (
    normalize_interview_lang,
    section6_agent_backstory,
    section6_fallback_question,
    section6_fallback_question_alt,
    section6_fallback_suggestions,
    section6_interview_task_body,
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
    interview_lang: str = "ko",
) -> dict[str, Any]:
    """LLM: 기술적 §6 항목 → 이해하기 쉬운 질문 + suggested_answers."""
    ilang = normalize_interview_lang(interview_lang)
    llm = _get_llm()
    role, goal, backstory = section6_agent_backstory(ilang)
    agent = Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        verbose=False,
        llm=llm,
        allow_delegation=False,
    )
    prior_lines: list[str] = []
    for i, t in enumerate(prior_turns[:6], 1):
        if not isinstance(t, dict):
            continue
        if ilang == "en":
            prior_lines.append(
                f"[Prior {i}] item: {(t.get('open_item') or '')[:200]}\n"
                f"Q: {(t.get('question') or '')[:200]}\n"
                f"A: {(t.get('decision_text') or '')[:300]}"
            )
        else:
            prior_lines.append(
                f"[이전 {i}] 항목: {(t.get('open_item') or '')[:200]}\n"
                f"질문: {(t.get('question') or '')[:200]}\n"
                f"답: {(t.get('decision_text') or '')[:300]}"
            )
    prior_block = "\n".join(prior_lines) if prior_lines else ("(none)" if ilang == "en" else "(없음)")
    task = Task(
        description=section6_interview_task_body(
            ilang,
            request_title=request_title,
            item_index=item_index,
            total_items=total_items,
            open_item=open_item,
            prior_block=prior_block,
        ),
        agent=agent,
        expected_output="JSON",
    )
    try:
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        raw = str(crew.kickoff())
        q, flat_raw, groups_raw = _parse_question_and_suggestions(raw, interview_lang=ilang)
        if not q:
            q = section6_fallback_question(ilang)
        su = _normalize_suggested_answers(flat_raw)
        if len(su) < 2:
            more = generate_suggested_answers_for_question(
                {"title": request_title, "description": open_item},
                q,
                1,
                1,
                interview_lang=ilang,
            )
            su = _normalize_suggested_answers(list(su) + list(more))
        packed = finalize_suggestion_payload(su, groups_raw or None, lang=ilang)
        return {
            "question": q[:2000],
            "suggested_answers": packed.get("suggested_answers") or [],
            "suggestion_groups": packed.get("suggestion_groups") or [],
        }
    except Exception:
        return {
            "question": section6_fallback_question_alt(ilang),
            "suggested_answers": section6_fallback_suggestions(ilang),
        }


def start_section6_interview(
    *,
    open_items: list[str],
    request_title: str,
    interview_lang: str = "ko",
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
        interview_lang=interview_lang,
    )
    inv = payload["interview"]
    inv["status"] = "active"
    inv["current_index"] = 0
    inv["turns"] = [
        {
            "open_item": open_items[0],
            "question": turn["question"],
            "suggestions": turn.get("suggested_answers") or [],
            "suggestion_groups": turn.get("suggestion_groups") or [],
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
    interview_lang: str = "ko",
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
    groups = resolve_groups_for_display(
        {
            "current_suggestions": turns[idx].get("suggestions") or [],
            "current_suggestion_groups": turns[idx].get("suggestion_groups") or [],
        },
        lang=interview_lang,
    )
    if not step_payload_valid(o, groups if groups else None):
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
        interview_lang=interview_lang,
    )
    turns.append(
        {
            "open_item": open_items[next_idx],
            "question": turn["question"],
            "suggestions": turn.get("suggested_answers") or [],
            "suggestion_groups": turn.get("suggestion_groups") or [],
            "answer_payload": None,
            "decision_text": "",
        }
    )
    inv["turns"] = turns
    inv["current_index"] = next_idx
    inv["status"] = "active"
    payload["interview"] = inv
    return payload
