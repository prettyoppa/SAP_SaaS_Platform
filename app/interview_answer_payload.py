"""인터뷰 답변 폼 payload (좋아요/싫어요/보충) — 공통 파싱."""

from __future__ import annotations

import json


def parse_answer_payload_form(answer_payload: str, current_answer: str) -> dict:
    raw = (answer_payload or "").strip()
    if raw.startswith("{"):
        try:
            o = json.loads(raw)
            if isinstance(o, dict):
                like = o.get("like") if isinstance(o.get("like"), list) else []
                dis = o.get("dislike") if isinstance(o.get("dislike"), list) else []
                free_val = o.get("free", "")
                free = (
                    (str(free_val).strip() if free_val is not None else "")
                    if isinstance(free_val, (str, int, float))
                    else ""
                )
                return {
                    "v": 1,
                    "like": [str(x).strip() for x in like if str(x).strip()],
                    "dislike": [str(x).strip() for x in dis if str(x).strip()],
                    "free": free,
                }
        except Exception:
            pass
    fr = (current_answer or "").strip()
    return {"v": 1, "like": [], "dislike": [], "free": fr}


def format_parsed_step_answer(o: dict) -> str:
    like = o.get("like") or []
    if not isinstance(like, list):
        like = []
    like = [str(x).strip() for x in like if str(x).strip()]
    dis = o.get("dislike") or []
    if not isinstance(dis, list):
        dis = []
    dis = [str(x).strip() for x in dis if str(x).strip()]
    free = (o.get("free") or "").strip()
    parts = []
    if like:
        parts.append("**선택**\n" + "\n".join(f"- {x}" for x in like))
    if dis:
        parts.append("**제외한 답**\n" + "\n".join(f"- {x}" for x in dis))
    if free:
        parts.append("**보충**\n" + free)
    if parts:
        return "\n\n".join(parts)
    return free


def step_payload_valid(o: dict) -> bool:
    t = format_parsed_step_answer(o).strip()
    return len(t.replace(" ", "").replace("\n", "")) >= 2
