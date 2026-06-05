"""인터뷰 질문·선지 출력 언어 — 회원 preferred_lang(ko/en)."""

from __future__ import annotations

from typing import Any


def normalize_interview_lang(lang: str | None) -> str:
    return "en" if (lang or "").strip().lower() == "en" else "ko"


def interview_lang_for_user(user: Any | None) -> str:
    if not user:
        return "ko"
    return normalize_interview_lang(getattr(user, "preferred_lang", None))


def interview_output_language_block(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return """
[Output language — REQUIRED]
- Write **question** and every **suggested_answers** entry in **English** for a non-technical requester.
- Keep SAP terms (T-code, BAPI/FM names, field names) in standard SAP notation; add a short parenthetical once if needed.
- Do not mix Korean in customer-facing strings unless quoting the RFP verbatim.
"""
    return """
[출력 언어 — 필수]
- **question**과 **suggested_answers**의 모든 항목은 **한국어**로 작성한다 (IT 비전문 요청자용).
- SAP 용어(T-code, BAPI/FM명, 필드명)는 표기 관례대로 두고, 필요 시 괄호로 한 번만 풀어도 된다.
- RFP 인용이 아니면 영어 문장을 섞지 않는다.
"""


MIA_INTERVIEW_SCOPE_KO = """
[질문 범위 — 반드시 준수]
- RFP 본문·첨부·이전 인터뷰 답에 없는 편의 기능·부가 UX는 질문에 넣지 마라. (RFP에 명시된 경우만 예외.)
- **한 턴에 정하는 것은 '한 가지 질문'뿐이다.** '또한/그리고'로 Plant와 Sales Order Type처럼 **주제가 다른** 것을 한 질문에 섞지 마라 — 반드시 **질문을 나눈다.**
- 질문은 **짧고** (2~3문장 이하). **선지(suggested_answers)에 쓰일 나열·시나리오**를 질문에 **미리 중복**해서 길게 쓰지 마라.
- [전체 인터뷰 + 이번 라운드 Q&A]에 **이미 확답**한 주제는 **다시 묻지 마라.**

[RFP·애매한 표현]
- RFP에 뜻이 불명확한 표현이 있고 정의가 없을 때, 임의로 틀릴 수 있는 영어/SAP 풀어쓰기로 덮지 말고 RFP 표현을 인용한 뒤 **한 가지 확인 질문**으로 의미를 묻는다.

[suggested_answers]
- 2~5개. **각 항목은 위 질문 하나에 대한 응답만.** 한 행에 두 주제를 합치지 마라. 실무 톤으로 짧게.
- **상호배타(택1) 정책**은 suggested_answers에 나란히 넣지 말고 **suggestion_groups** 의 **exclusive** 그룹으로 낸다.
- “~한다” vs “~하지 않는다”, “무조건 변경” vs “변경 안 함”처럼 **같은 결정의 찬반**을 서로 다른 좋아요 후보 두 줄로 두지 마라.
- **multi** 그룹만 복수 선택 의미(동시에 참일 수 있는 서로 다른 측면).

[suggestion_groups]
- 1~2개 권장. **mode=exclusive**: options 2~4개, **하나만** 고르게(택1). **mode=multi**: 복수 OK.
- 질문 전제가 하나면 exclusive options도 **그 전제 안**에서만. 다른 전제(Old Value 있음/없음)는 **질문을 나눈다**.

[출력 JSON — suggestion_groups 사용 시]
{{"question": "...", "suggestion_groups": [{{"id": "main", "mode": "exclusive", "options": ["...", "..."]}}]}}
또는 multi 보조 그룹: {{"id": "extras", "mode": "multi", "options": ["..."]}}
(suggested_answers 단독 출력은 하위호환용 — 가능하면 suggestion_groups 우선)
- JSON에서 ** … ** 별표 감싸기 금지.
"""

MIA_INTERVIEW_SCOPE_EN = """
[Question scope — mandatory]
- Do not ask about convenience UX not in the RFP, attachments, or prior answers (unless explicitly in the RFP).
- **One decision per turn.** Do not combine unrelated topics (e.g. Plant and Sales Order Type) in one question.
- Keep the question **short** (≤2–3 sentences). Do not paste long scenarios meant for suggested_answers into the question.
- Do not repeat topics already answered in prior rounds or this round.

[Ambiguous RFP wording]
- If the RFP uses unclear terms without definition, do not guess with misleading English/SAP glosses — quote the RFP phrase and ask **one** clarifying question.

[suggested_answers]
- 2–5 items. **Each line answers only the question above.** One idea per line. Practical tone.
- Do **not** put mutually exclusive policies side by side in suggested_answers — use **suggestion_groups** with **mode=exclusive**.
- Never offer “do X” and “do not X” as two separate like candidates for the same decision.
- Only **multi** groups allow multiple selections (independent facets).

[suggestion_groups]
- Prefer 1–2 groups. **exclusive**: 2–4 options, pick exactly one. **multi**: optional extras.
- One question premise → exclusive options must match that premise only.

[JSON with suggestion_groups]
{{"question": "...", "suggestion_groups": [{{"id": "main", "mode": "exclusive", "options": ["...", "..."]}}]}}

[Output format]
- No markdown bold (** … **) inside JSON strings.
"""

SAP_INTERVIEW_CREDIBILITY_KO = """
[SAP 사실·질문 품질 — 반드시 준수]
- BAPI/트랜잭션 필수 키를 "자동/수동 선택하시죠"식 **템플릿**으로만 묻지 마라.
- RFP·이전 답이 충분하면 followup JSON에서 **round_complete: true** (억지로 3문항을 채우지 않는다).
"""

SAP_INTERVIEW_CREDIBILITY_EN = """
[SAP quality — mandatory]
- Avoid generic template questions about BAPI/transaction keys when policy is already in the RFP or prior answers.
- If the RFP and answers are sufficient, return **round_complete: true** (do not pad to three questions).
"""

_DEFAULT_QUESTIONS_KO = [
    "이 개발의 주요 사용자는 누구인가요? (예: 영업팀, 물류팀, 경영진)",
    "조회 결과를 엑셀로 다운로드하거나 인쇄하는 기능이 필요한가요?",
    "기존에 유사한 프로그램이 있나요? 있다면 어떤 점을 개선하고 싶으신가요?",
]

_DEFAULT_QUESTIONS_EN = [
    "Who are the primary users of this development? (e.g. sales, logistics, management)",
    "Do you need Excel export or print for the report output?",
    "Is there a similar program today? If yes, what should improve?",
]


def mia_interview_prompt_bundle(lang: str) -> str:
    lg = normalize_interview_lang(lang)
    scope = MIA_INTERVIEW_SCOPE_EN if lg == "en" else MIA_INTERVIEW_SCOPE_KO
    cred = SAP_INTERVIEW_CREDIBILITY_EN if lg == "en" else SAP_INTERVIEW_CREDIBILITY_KO
    return scope + cred + interview_output_language_block(lg)


def default_interview_questions(lang: str) -> list[str]:
    return list(
        _DEFAULT_QUESTIONS_EN
        if normalize_interview_lang(lang) == "en"
        else _DEFAULT_QUESTIONS_KO
    )


def default_interview_question(lang: str, index: int) -> str:
    qs = default_interview_questions(lang)
    if not qs:
        return ""
    i = max(0, min(int(index), len(qs) - 1))
    return qs[i]


def interview_followup_anti_dup_block(lang: str, done_brief: str) -> str:
    lg = normalize_interview_lang(lang)
    if lg == "en":
        return f"""[This round Q&A so far — do not repeat]
{done_brief}
- Do not re-ask policies the user already stated (Plant, order type, rollback rules, etc.).
- Do not rephrase the same intent in English/Korean. If nothing remains, set round_complete: true."""
    return f"""[이번 라운드·이미 오간 Q&A(반복 금지 — **답 내용**까지 읽을 것)]
{done_brief}
- 위에서 사용자가 **이미 끊어 말한** 정책을 **또 묻지 마라.**
- 같은 취지를 영어/한글 **표현만 바꿔** 다시 쓰는 것도 금지.
- 남는 것이 없으면 round_complete: true."""


def interview_gate_issues_label(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return "If fail: fixes for the question author (English). If pass: empty string."
    return "불합이면 질문 작성자가 고칠 점(한국어). 합격이면 빈 문자열."


def interview_reviewer_language_line(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return "- Readable **English** for a non-technical customer; follow SAP term rules above."
    return "- 고객(IT 비전문가)이 읽을 수 있는 **한국어**, SAP 용어는 앞서 규칙 따름"


def section6_fallback_question(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return "How would you like to proceed on this open item?"
    return "이 항목에 대해 어떻게 진행할지 알려 주시겠어요?"


def section6_fallback_suggestions(lang: str) -> list[str]:
    if normalize_interview_lang(lang) == "en":
        return [
            "Proceed with the default scope in the proposal",
            "Reduce scope (exclude some items)",
            "Follow the consultant's recommendation",
        ]
    return [
        "제안서 기본 범위대로 진행해 주세요",
        "범위를 줄여(일부 제외) 진행해 주세요",
        "컨설턴트 권장안을 따르겠습니다",
    ]


def section6_fallback_question_alt(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return "Please tell us your preferred direction for this open item."
    return "아래 확인 사항에 대해 선호하시는 방향을 알려 주세요."


def suggested_answers_task_preamble(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return (
            "Below is an SAP custom development RFP interview question. "
            "Create short tap-to-select answer options for **this one question** only."
        )
    return (
        "다음은 SAP 맞춤개발 RFP 인터뷰 질문입니다. "
        "비전문가가 버튼만 눌러 한 질문에 답하도록, 짧은 답안 후보만 만드세요."
    )


def interview_in_round_empty_label(lang: str) -> str:
    if normalize_interview_lang(lang) == "en":
        return "(first question this round — no answers yet)"
    return "(이번 라운드 첫 질문 — 아직 답 없음)"


def section6_agent_backstory(lang: str) -> tuple[str, str, str]:
    """role, goal, backstory for §6 interview agent."""
    if normalize_interview_lang(lang) == "en":
        return (
            "SAP customer confirmation interview assistant",
            "Turn §6 open items into short questions and decision-style choices the requester can pick immediately",
            (
                "You speak to non-technical SAP customers. "
                "Ask briefly about scope include/exclude; each choice is one-line decision text."
            ),
        )
    return (
        "SAP 고객 확인 인터뷰 도우미",
        "§6 확인 필요 사항을 요청자가 바로 선택할 수 있는 짧은 질문과 결정형 선택지로 만든다",
        (
            "SAP 컨설턴트이지만 IT 비전문 요청자에게 말한다. "
            "장황한 설명 없이 범위·포함/제외를 묻고, 선택지는 한 줄 결정문으로 제시한다."
        ),
    )


def section6_interview_task_body(
    lang: str,
    *,
    request_title: str,
    item_index: int,
    total_items: int,
    open_item: str,
    prior_block: str,
) -> str:
    lg = normalize_interview_lang(lang)
    title = request_title or ("Development request" if lg == "en" else "개발 요청")
    if lg == "en":
        return f"""Create a **customer interview question** for **one** §6 (open items) row in a development proposal.

[Request title] {title}
[Progress] {item_index + 1} / {total_items}
[§6 source text (technical)]
{open_item[:4000]}

[Prior §6 interviews already done]
{prior_block}

Rules:
- Question: **1–2 sentences**, direct. No long preamble or training text.
- Avoid meta phrases like "time and effort". If trade-offs exist, mention **performance/speed** only briefly.
- Ask about include/exclude or analysis depth from the §6 text. SAP/ABAP terms: parenthetical gloss **once** if needed.
- suggested_answers: 2–4 **one-line decisions** (legacy — prefer **suggestion_groups**).
- Use **suggestion_groups** with **mode=exclusive** for pick-one policies; **multi** only for independent add-ons.
- No markdown bold (**) inside JSON strings.
{interview_output_language_block(lg)}

Output JSON only (prefer suggestion_groups):
{{"question": "...", "suggestion_groups": [{{"id": "main", "mode": "exclusive", "options": ["...", "..."]}}]}}"""
    return f"""개발 제안서 §6(확인 필요 사항) 중 **한 항목**에 대해 고객 인터뷰 질문을 만드세요.

[요청 제목] {title}
[진행] {item_index + 1} / {total_items}
[이번 §6 원문(기술적)]
{open_item[:4000]}

[이미 끝낸 다른 §6 인터뷰]
{prior_block}

규칙:
- 질문은 **1~2문장**, 짧고 직접적으로. 배경·교육 설명·장황한 서두 금지.
- "시간과 노력", "협의가 필요" 같은 메타 표현 금지. 부담이 있으면 **성능·처리 속도**만 짧게(예: 분석 범위를 넓히면 프로그램 실행·화면 응답이 느려질 수 있음).
- §6 원문의 핵심(포함/제외, 분석 깊이)을 묻는다. SAP·ABAP 용어는 괄호로 **한 번만** 짧게 풀어도 된다.
- suggested_answers 2~4개(하위호환) — 가능하면 **suggestion_groups** 사용.
- **exclusive**: 택1 정책. **multi**: 동시에 참일 수 있는 보조 항목만.
- JSON 출력에 별표 강조(**) 사용 금지.
{interview_output_language_block(lg)}

반드시 JSON 한 블록만 (suggestion_groups 권장):
{{"question": "...", "suggestion_groups": [{{"id": "main", "mode": "exclusive", "options": ["...", "..."]}}]}}"""
