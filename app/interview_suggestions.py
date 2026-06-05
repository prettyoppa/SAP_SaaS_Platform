"""인터뷰 선지 — suggestion_groups(exclusive/multi) 파싱·저장·검증."""

from __future__ import annotations

import os
import re
from typing import Any

MAX_SUGGESTIONS = 5
MAX_GROUPS = 3


def interview_suggestion_groups_enabled() -> bool:
    v = (os.environ.get("INTERVIEW_SUGGESTION_GROUPS") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _norm_lang(lang: str | None) -> str:
    return "en" if (lang or "").strip().lower() == "en" else "ko"


def exclusive_group_prompt(lang: str | None) -> str:
    if _norm_lang(lang) == "en":
        return "Pick one option below"
    return "아래 중 하나를 선택하세요"


def multi_group_prompt(lang: str | None) -> str:
    if _norm_lang(lang) == "en":
        return "Select all that apply (optional)"
    return "해당하는 항목을 선택하세요 (복수 가능, 선택 사항)"


def _cap_options(options: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in options:
        t = str(x).strip()
        if not t or len(t) > 500:
            continue
        k = t.lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


def flat_to_exclusive_group(flat: list[str], *, lang: str | None = "ko") -> list[dict[str, Any]]:
    opts = _cap_options(flat)
    if len(opts) < 2:
        return []
    return [
        {
            "id": "policy",
            "mode": "exclusive",
            "prompt": exclusive_group_prompt(lang),
            "options": opts,
        }
    ]


def normalize_suggestion_groups(raw: Any, *, lang: str | None = "ko") -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    lg = _norm_lang(lang)
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw[:MAX_GROUPS]):
        if not isinstance(item, dict):
            continue
        mode = (item.get("mode") or "exclusive").strip().lower()
        if mode not in ("exclusive", "multi"):
            mode = "exclusive"
        opts = _cap_options(item.get("options") if isinstance(item.get("options"), list) else [])
        if len(opts) < 2:
            continue
        gid = (item.get("id") or f"g{i + 1}").strip()[:32] or f"g{i + 1}"
        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            prompt = multi_group_prompt(lg) if mode == "multi" else exclusive_group_prompt(lg)
        out.append({"id": gid, "mode": mode, "prompt": prompt[:200], "options": opts})
    return out


def flatten_groups(groups: list[dict[str, Any]]) -> list[str]:
    flat: list[str] = []
    seen: set[str] = set()
    for g in groups:
        for opt in g.get("options") or []:
            t = str(opt).strip()
            if not t:
                continue
            k = t.lower()[:80]
            if k in seen:
                continue
            seen.add(k)
            flat.append(t)
    return flat[:MAX_SUGGESTIONS]


def finalize_suggestion_payload(
    flat: list[str],
    groups: list[dict[str, Any]] | None,
    *,
    lang: str | None = "ko",
) -> dict[str, Any]:
    """LLM 출력 → 저장·UI용 flat + groups."""
    flat_norm = _cap_options(flat)
    if not interview_suggestion_groups_enabled():
        return {"suggested_answers": flat_norm, "suggestion_groups": []}

    norm_groups = normalize_suggestion_groups(groups, lang=lang)
    if norm_groups:
        flat_out = flatten_groups(norm_groups)
        return {"suggested_answers": flat_out, "suggestion_groups": norm_groups}

    if len(flat_norm) >= 2:
        ex = flat_to_exclusive_group(flat_norm, lang=lang)
        return {"suggested_answers": flat_norm, "suggestion_groups": ex}

    return {"suggested_answers": flat_norm, "suggestion_groups": []}


def parse_suggestions_from_llm_json(j: dict[str, Any], *, lang: str | None = "ko") -> dict[str, Any]:
    flat_raw: list[str] = []
    sa = j.get("suggested_answers")
    if isinstance(sa, list):
        flat_raw = [str(x).strip() for x in sa if str(x).strip()]
    groups_raw = j.get("suggestion_groups")
    groups: list[dict[str, Any]] | None = None
    if isinstance(groups_raw, list):
        groups = groups_raw  # type: ignore[assignment]
    return finalize_suggestion_payload(flat_raw, groups, lang=lang)


def apply_suggestions_to_intra(intra: dict[str, Any], payload: dict[str, Any]) -> None:
    flat = _cap_options(list(payload.get("suggested_answers") or []))
    intra["current_suggestions"] = flat
    groups = payload.get("suggestion_groups")
    if interview_suggestion_groups_enabled() and isinstance(groups, list) and groups:
        intra["current_suggestion_groups"] = groups
    else:
        intra.pop("current_suggestion_groups", None)


def resolve_groups_for_display(
    intra: dict[str, Any] | None,
    *,
    lang: str | None = "ko",
) -> list[dict[str, Any]]:
    intra = intra or {}
    flat = _cap_options(list(intra.get("current_suggestions") or []))
    stored = intra.get("current_suggestion_groups")
    if interview_suggestion_groups_enabled() and isinstance(stored, list) and stored:
        norm = normalize_suggestion_groups(stored, lang=lang)
        if norm:
            return norm
    if interview_suggestion_groups_enabled() and len(flat) >= 2:
        return flat_to_exclusive_group(flat, lang=lang)
    return []


def wizard_suggestion_context(intra: dict[str, Any] | None, *, lang: str | None = "ko") -> dict[str, Any]:
    intra = intra or {}
    flat = _cap_options(list(intra.get("current_suggestions") or []))
    groups = resolve_groups_for_display(intra, lang=lang)
    return {
        "answer_suggestions": flat,
        "answer_suggestion_groups": groups,
        "interview_suggestion_groups_enabled": interview_suggestion_groups_enabled(),
    }


def _likes_in_group(payload: dict[str, Any], group: dict[str, Any]) -> list[str]:
    likes = {str(x).strip() for x in (payload.get("like") or []) if str(x).strip()}
    opts = {str(x).strip() for x in (group.get("options") or []) if str(x).strip()}
    return sorted(likes & opts)


def validate_step_payload_with_groups(
    payload: dict[str, Any],
    groups: list[dict[str, Any]] | None,
) -> str | None:
    """
    None = OK. Otherwise error code: empty | exclusive_none | exclusive_multi
    """
    from .interview_answer_payload import format_parsed_step_answer

    like = payload.get("like") or []
    dislike = payload.get("dislike") or []
    free = (payload.get("free") or "").strip()
    if not like and not dislike and len(free) < 2:
        return "empty"

    formatted = format_parsed_step_answer(payload).strip()
    if len(formatted.replace(" ", "").replace("\n", "")) < 2:
        return "empty"

    if not interview_suggestion_groups_enabled() or not groups:
        return None

    for g in groups:
        if (g.get("mode") or "").strip().lower() != "exclusive":
            continue
        picked = _likes_in_group(payload, g)
        if len(picked) > 1:
            return "exclusive_multi"
        if len(picked) == 1:
            continue
        if len(free) >= 2:
            continue
        if len(_cap_options(list(g.get("options") or []))) >= 2:
            return "exclusive_none"
    return None


def merge_crew_result_suggestions(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    result["suggested_answers"] = payload.get("suggested_answers") or []
    result["suggestion_groups"] = payload.get("suggestion_groups") or []
    return result
