"""AI 후속 질문 POST — JSON 응답(패널 유지·전체 새로고침 없음)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .templates_config import templates


def wants_ai_chat_json(request: Request) -> bool:
    return (request.headers.get("X-Abap-Ai-Chat") or "").strip() == "1"


def render_followup_log_html(request: Request, turns: list[Any]) -> str:
    tpl = templates.env.get_template("partials/abap_followup_messenger_log.html")
    return tpl.render(request=request, followup_turns=turns)


def ai_chat_json_ok(
    request: Request,
    *,
    turns: list[Any],
    limit_reached: bool = False,
) -> JSONResponse:
    log_html = render_followup_log_html(request, turns) if turns else ""
    return JSONResponse(
        {
            "ok": True,
            "log_html": log_html,
            "turn_count": len(turns),
            "limit_reached": limit_reached,
        }
    )


def ai_chat_json_error(message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)
