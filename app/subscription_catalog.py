"""구독 플랜·metric_key 정의 및 DB 시드(초기 entitlement 표)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import models

# ── metric_key (플랜 표 기능과 1:1) ─────────────────────────────
METRIC_INQUIRY_REVIEW = "inquiry_review"
METRIC_DEV_REQUEST = "dev_request"
METRIC_REQUEST_DUPLICATE = "request_duplicate"
METRIC_AI_INQUIRY = "ai_inquiry"
METRIC_DEV_PROPOSAL = "dev_proposal"
METRIC_DEV_PROPOSAL_REGEN = "dev_proposal_regenerate"
METRIC_OFFER = "offer"
METRIC_FS = "functional_spec"
METRIC_FS_REGEN = "fs_regenerate"
METRIC_DEV_CODE = "dev_code"
METRIC_DEV_CODE_REGEN = "dev_code_regenerate"

METRIC_ORDER: tuple[str, ...] = (
    METRIC_INQUIRY_REVIEW,
    METRIC_DEV_REQUEST,
    METRIC_REQUEST_DUPLICATE,
    METRIC_AI_INQUIRY,
    METRIC_DEV_PROPOSAL,
    METRIC_DEV_PROPOSAL_REGEN,
    METRIC_OFFER,
    METRIC_FS,
    METRIC_FS_REGEN,
    METRIC_DEV_CODE,
    METRIC_DEV_CODE_REGEN,
)

METRIC_LABEL_KO: dict[str, str] = {
    METRIC_INQUIRY_REVIEW: "문의/리뷰 작성·조회·댓글",
    METRIC_DEV_REQUEST: "개발 요청",
    METRIC_REQUEST_DUPLICATE: "요청 복사 생성",
    METRIC_AI_INQUIRY: "AI 문의",
    METRIC_DEV_PROPOSAL: "개발 제안",
    METRIC_DEV_PROPOSAL_REGEN: "개발 제안 재생성",
    METRIC_OFFER: "오퍼",
    METRIC_FS: "FS",
    METRIC_FS_REGEN: "FS 재생성",
    METRIC_DEV_CODE: "개발 코드",
    METRIC_DEV_CODE_REGEN: "개발 코드 재생성",
}

# SiteSettings 키: subscription_metric_help_<metric_key> — 구독 플랜 페이지 기능 설명(툴팁)
SUBSCRIPTION_METRIC_HELP_KEY_PREFIX = "subscription_metric_help_"


def _e(
    db: Session,
    plan_id: int,
    metric: str,
    period: str,
    limit_value: int | None = None,
) -> None:
    db.add(
        models.PlanEntitlement(
            plan_id=plan_id,
            metric_key=metric,
            period_type=period,
            limit_value=limit_value,
        )
    )


def _member_experience(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        else:
            _e(db, plan_id, m, "disabled", None)


def _member_end_user(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL):
            _e(db, plan_id, m, "monthly", 3)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 30)
        else:
            _e(db, plan_id, m, "disabled", None)


def _member_power_user(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL):
            _e(db, plan_id, m, "monthly", 10)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 60)
        elif m == METRIC_DEV_PROPOSAL_REGEN:
            _e(db, plan_id, m, "per_request", 1)
        else:
            _e(db, plan_id, m, "disabled", None)


def _member_process_innovator(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL):
            _e(db, plan_id, m, "monthly", 30)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 60)
        elif m == METRIC_DEV_PROPOSAL_REGEN:
            _e(db, plan_id, m, "per_request", 3)
        else:
            _e(db, plan_id, m, "disabled", None)


def _consultant_experience(db: Session, plan_id: int) -> None:
    _member_experience(db, plan_id)


def _consultant_junior(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL, METRIC_OFFER, METRIC_FS, METRIC_DEV_CODE):
            _e(db, plan_id, m, "monthly", 3)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 30)
        elif m in (METRIC_DEV_PROPOSAL_REGEN, METRIC_FS_REGEN, METRIC_DEV_CODE_REGEN):
            _e(db, plan_id, m, "per_request", 1)
        else:
            _e(db, plan_id, m, "disabled", None)


def _consultant_senior(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL, METRIC_OFFER, METRIC_FS, METRIC_DEV_CODE):
            _e(db, plan_id, m, "monthly", 10)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 60)
        elif m in (METRIC_DEV_PROPOSAL_REGEN, METRIC_FS_REGEN, METRIC_DEV_CODE_REGEN):
            _e(db, plan_id, m, "per_request", 1)
        else:
            _e(db, plan_id, m, "disabled", None)


def _consultant_superior(db: Session, plan_id: int) -> None:
    for m in METRIC_ORDER:
        if m == METRIC_INQUIRY_REVIEW:
            _e(db, plan_id, m, "unlimited", None)
        elif m in (METRIC_DEV_REQUEST, METRIC_REQUEST_DUPLICATE, METRIC_DEV_PROPOSAL, METRIC_OFFER, METRIC_FS, METRIC_DEV_CODE):
            _e(db, plan_id, m, "monthly", 30)
        elif m == METRIC_AI_INQUIRY:
            _e(db, plan_id, m, "per_request", 60)
        elif m in (METRIC_DEV_PROPOSAL_REGEN, METRIC_FS_REGEN, METRIC_DEV_CODE_REGEN):
            _e(db, plan_id, m, "per_request", 3)
        else:
            _e(db, plan_id, m, "disabled", None)


def seed_subscription_catalog(db: Session) -> None:
    """subscription_plans 비어 있을 때만 플랜·entitlement 전체 시드."""
    if db.query(models.SubscriptionPlan).count() > 0:
        return

    specs: list[tuple[str, str, str, int, callable]] = [
        ("member", "experience", "Experience (일반)", 0, _member_experience),
        ("member", "end_user", "End User", 1, _member_end_user),
        ("member", "power_user", "Power User", 2, _member_power_user),
        ("member", "process_innovator", "Process Innovator", 3, _member_process_innovator),
        ("consultant", "experience", "Experience (컨설턴트)", 0, _consultant_experience),
        ("consultant", "junior", "Junior", 1, _consultant_junior),
        ("consultant", "senior", "Senior", 2, _consultant_senior),
        ("consultant", "superior", "Superior", 3, _consultant_superior),
    ]

    for account_kind, code, name_ko, sort_order, fill_fn in specs:
        p = models.SubscriptionPlan(
            account_kind=account_kind,
            code=code,
            display_name_ko=name_ko,
            sort_order=sort_order,
            is_active=True,
        )
        db.add(p)
        db.flush()
        fill_fn(db, p.id)

    db.commit()
