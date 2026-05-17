"""계좌이체·환불 정책 SiteSettings 키."""

BANK_TRANSFER_SETTING_KEYS: tuple[str, ...] = (
    "bank_transfer_notice_md_ko",
    "bank_transfer_notice_md_en",
    "bank_transfer_notice_usd_md_ko",
    "bank_transfer_notice_usd_md_en",
    "bank_transfer_activation_sla_ko",
    "bank_transfer_activation_sla_en",
    "usd_krw_rate",
)

REFUND_POLICY_SETTING_KEYS: tuple[str, ...] = (
    "refund_policy_md_ko",
    "refund_policy_md_en",
)

ALL_BANK_BILLING_SETTING_KEYS: tuple[str, ...] = (
    *BANK_TRANSFER_SETTING_KEYS,
    *REFUND_POLICY_SETTING_KEYS,
)

DEFAULT_BANK_TRANSFER_NOTICE_KO = """### 계좌이체 (원화, KRW)

- **은행·계좌·예금주**: (Admin에서 이 문구를 수정하세요)
- **입금자명**: 회원가입 이름과 동일하게
- 입금 후 **사용량 확인** 화면에서 충전 신청을 제출해 주세요.

"""

DEFAULT_BANK_TRANSFER_NOTICE_USD_KO = """### Bank transfer (USD)

- **Account details**: (Edit in Admin)
- After transfer, submit a claim under **Account → Subscription & payment**.

"""
