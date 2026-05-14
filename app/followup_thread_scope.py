"""AI 문의 후속 메시지를 참가자(요청 소유자 vs 매칭 컨설턴트)별로 분리해 조회한다."""

from __future__ import annotations

from typing import Any


def filter_followup_messages_for_viewer(
    msgs: list[Any],
    *,
    request_owner_id: int,
    viewer_user_id: int,
    viewer_is_admin: bool = False,
) -> list[Any]:
    """thread_user_id가 NULL이면 레거시(요청 소유자 스레드)로 본다.

    관리자는 소유자·컨설턴트 스레드를 구분하지 않고 전체를 본다.
    """
    if viewer_is_admin:
        return sorted(
            list(msgs or []),
            key=lambda x: (
                getattr(x, "created_at", None) or 0,
                getattr(x, "id", 0) or 0,
            ),
        )
    oid = int(request_owner_id)
    vid = int(viewer_user_id)
    out: list[Any] = []
    for m in msgs or []:
        raw = getattr(m, "thread_user_id", None)
        tid = int(raw) if raw is not None else None
        if vid == oid:
            if tid is None or tid == oid:
                out.append(m)
        else:
            if tid is not None and tid == vid:
                out.append(m)
    return sorted(
        out,
        key=lambda x: (
            getattr(x, "created_at", None) or 0,
            getattr(x, "id", 0) or 0,
        ),
    )
