"""인터뷰 suggestion_groups 파싱·검증."""

from __future__ import annotations

from app.interview_suggestions import (
    flat_to_exclusive_group,
    finalize_suggestion_payload,
    validate_step_payload_with_groups,
)


def test_flat_to_exclusive_group():
    g = flat_to_exclusive_group(["A policy", "B policy"], lang="ko")
    assert len(g) == 1
    assert g[0]["mode"] == "exclusive"
    assert len(g[0]["options"]) == 2


def test_finalize_prefers_groups():
    payload = finalize_suggestion_payload(
        [],
        [{"id": "m", "mode": "exclusive", "options": ["X", "Y"]}],
        lang="ko",
    )
    assert payload["suggestion_groups"][0]["mode"] == "exclusive"
    assert payload["suggested_answers"] == ["X", "Y"]


def test_finalize_fallback_flat_to_exclusive():
    payload = finalize_suggestion_payload(
        ["옵션 A", "옵션 B", "옵션 C"],
        None,
        lang="ko",
    )
    assert len(payload["suggestion_groups"]) == 1
    assert payload["suggestion_groups"][0]["mode"] == "exclusive"


def test_validate_exclusive_one_like():
    groups = [{"id": "p", "mode": "exclusive", "options": ["A", "B"]}]
    err = validate_step_payload_with_groups({"v": 1, "like": ["A"], "dislike": [], "free": ""}, groups)
    assert err is None


def test_validate_exclusive_rejects_double_like():
    groups = [{"id": "p", "mode": "exclusive", "options": ["A", "B"]}]
    err = validate_step_payload_with_groups(
        {"v": 1, "like": ["A", "B"], "dislike": [], "free": ""},
        groups,
    )
    assert err == "exclusive_multi"


def test_validate_exclusive_allows_free_text():
    groups = [{"id": "p", "mode": "exclusive", "options": ["A", "B"]}]
    err = validate_step_payload_with_groups(
        {"v": 1, "like": [], "dislike": [], "free": "필드별로 다르게 처리"},
        groups,
    )
    assert err is None


def test_validate_exclusive_none_without_pick_or_free():
    groups = [{"id": "p", "mode": "exclusive", "options": ["A", "B"]}]
    err = validate_step_payload_with_groups({"v": 1, "like": [], "dislike": ["A"], "free": ""}, groups)
    assert err == "exclusive_none"
