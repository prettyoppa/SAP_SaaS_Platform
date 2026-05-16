"""입금 신청 API 오류 코드·상태 라벨 (UI에서 KO/EN 매핑)."""

from __future__ import annotations

ERR_INVALID_COUNTRY = "invalid_country"
ERR_PLAN_REQUIRED = "plan_required"
ERR_PLAN_NOT_FOUND = "plan_not_found"
ERR_KRW_AMOUNT_MISSING = "krw_amount_missing"
ERR_USD_AMOUNT_MISSING = "usd_amount_missing"
ERR_AMOUNT_MISMATCH = "amount_mismatch"
ERR_PENDING_CLAIM_EXISTS = "pending_claim_exists"
ERR_DEPOSITOR_REQUIRED = "depositor_required"
ERR_CLAIM_NOT_FOUND = "claim_not_found"
ERR_CLAIM_NOT_PENDING = "claim_not_pending"

STATUS_LABEL_KO: dict[str, str] = {
    "pending": "확인 대기",
    "confirmed": "활성화 완료",
    "rejected": "반려",
    "cancelled": "취소",
}

STATUS_LABEL_EN: dict[str, str] = {
    "pending": "Pending review",
    "confirmed": "Activated",
    "rejected": "Rejected",
    "cancelled": "Cancelled",
}
