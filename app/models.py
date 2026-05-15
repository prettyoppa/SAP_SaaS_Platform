from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    company = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    is_consultant = Column(Boolean, default=False)
    consultant_application_pending = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=True)  # 기존 행은 마이그레이션에서 true
    phone_number = Column(String(32), nullable=True)
    phone_verified = Column(Boolean, default=False)
    phone_verified_at = Column(DateTime, nullable=True)
    # 업무 알림(요청 진행/납품 등) 수신 동의
    ops_email_opt_in = Column(Boolean, default=False)
    ops_sms_opt_in = Column(Boolean, default=False)
    # 마케팅 수신 동의
    marketing_email_opt_in = Column(Boolean, default=False)
    marketing_sms_opt_in = Column(Boolean, default=False)
    consent_updated_at = Column(DateTime, nullable=True)
    # IANA tz database 이름(예: Asia/Seoul). Null이면 화면 시각은 브라우저 로컬 타임존 사용.
    timezone = Column(String(64), nullable=True)
    # 컨설턴트 가입 시 선택 첨부 프로필 파일 (R2 URI 또는 로컬 경로)
    consultant_profile_file_path = Column(Text, nullable=True)
    consultant_profile_file_name = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 회원 탈퇴: 유예 기간 후 영구 삭제 (소프트 단계에서는 로그인 불가, 이메일로 취소 가능)
    pending_account_deletion = Column(Boolean, default=False)
    deletion_requested_at = Column(DateTime, nullable=True)
    deletion_hard_scheduled_at = Column(DateTime, nullable=True)
    # 구독 플랜(일반/컨설턴트 각각 catalog의 code와 대응, 기본 experience)
    subscription_plan_code = Column(String(32), nullable=False, default="experience")
    subscription_plan_source = Column(String(20), nullable=False, default="default")  # default | admin | stripe
    subscription_plan_expires_at = Column(DateTime, nullable=True)
    # Experience 플랜 체험(UTC): 기간 중 entitlement는 consultant+junior와 동일. 이메일·휴대폰당 1회(해시 보관).
    experience_trial_ends_at = Column(DateTime, nullable=True)

    rfps = relationship("RFP", back_populates="owner")
    integration_requests = relationship("IntegrationRequest", back_populates="owner")
    abap_codes = relationship("ABAPCode", back_populates="uploader")
    abap_analysis_requests = relationship("AbapAnalysisRequest", back_populates="owner")


class EmailChangePending(Base):
    """로그인 회원의 이메일 변경 — 새 주소 인증 링크 확인 후 확정."""

    __tablename__ = "email_change_pending"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    new_email = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


class AccountPhoneOtp(Base):
    """로그인 회원 휴대폰 등록·변경·재인증용 OTP(인증할 번호 1건)."""

    __tablename__ = "account_phone_otps"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    target_phone = Column(String(32), nullable=False)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


class RFP(Base):
    __tablename__ = "rfps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    program_id = Column(String, nullable=True)         # 프로그램 ID (대문자, 영문+숫자)
    transaction_code = Column(String, nullable=True)   # 트랜잭션 코드
    title = Column(String, nullable=False)
    sap_modules = Column(String, nullable=True)        # comma-separated, 최대 3개
    dev_types = Column(String, nullable=True)          # comma-separated, 최대 3개
    description = Column(Text, nullable=True)
    description_format = Column(String(16), nullable=False, default="plain")
    requirement_screenshots_json = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    attachments_json = Column(Text, nullable=True)   # JSON [{path, filename, note}, ...] 최대 5
    # 회원 제출 ABAP 코드(본 RFP 전용, abap_codes 미등록). 에이전트 프롬프트용.
    reference_code_payload = Column(Text, nullable=True)
    status = Column(String, default="draft")           # draft | submitted | in_review | completed
    # direct: 일반 신규 개발 제출 | abap_analysis | integration — 워크플로 연결 시 인터뷰·제안서 톤 분기
    workflow_origin = Column(String, default="direct", nullable=False)
    interview_status = Column(String, default="pending")  # pending | in_progress | generating_proposal | completed
    proposal_text = Column(Text, nullable=True)
    proposal_generated_at = Column(DateTime, nullable=True)
    # 유료 개발 의뢰 — FS·납품 ABAP (조회: 회원·관리자 / 생성: 관리자만)
    paid_engagement_status = Column(String, default="none")  # none | checkout_pending | active | cancelled
    paid_activated_at = Column(DateTime, nullable=True)
    stripe_checkout_session_id = Column(String, nullable=True)
    fs_status = Column(String, default="none")  # none | generating | ready | failed
    fs_text = Column(Text, nullable=True)
    fs_generated_at = Column(DateTime, nullable=True)
    fs_error = Column(Text, nullable=True)
    # 관리자용: 생성 백그라운드 작업 진행 로그(텍스트, 단순 줄 단위 축적)
    fs_job_log = Column(Text, nullable=True)
    delivered_code_status = Column(String, default="none")  # none | generating | ready | failed
    delivered_code_text = Column(Text, nullable=True)
    # JSON: program_id, slots[], implementation_guide_md, test_scenarios_md (에이전트 납품 패키지)
    delivered_code_payload = Column(Text, nullable=True)
    delivered_code_generated_at = Column(DateTime, nullable=True)
    delivered_code_error = Column(Text, nullable=True)
    delivered_job_log = Column(Text, nullable=True)
    # ABAP 코드 생성 시 사용할 FS 보조파일(DB id). Null이면 에이전트 fs_text 사용.
    fs_codegen_supplement_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="rfps")
    messages = relationship("RFPMessage", back_populates="rfp", order_by="RFPMessage.round_number")
    followup_messages = relationship(
        "RfpFollowupMessage",
        back_populates="rfp",
        order_by="RfpFollowupMessage.created_at",
        cascade="all, delete-orphan",
    )
    fs_supplements = relationship(
        "RfpFsSupplement",
        foreign_keys="RfpFsSupplement.rfp_id",
        back_populates="rfp",
        cascade="all, delete-orphan",
        order_by="RfpFsSupplement.uploaded_at",
    )


class RFPMessage(Base):
    __tablename__ = "rfp_messages"

    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey("rfps.id"))
    round_number = Column(Integer, nullable=False)
    questions_json = Column(Text, nullable=False)
    answers_text = Column(Text, nullable=True)
    # 순차 인터뷰(JSON): answers_so_far, library_pool 등(레거시 메시지는 null)
    intra_state_json = Column(Text, nullable=True)
    source_label = Column(String, nullable=True)
    is_answered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    rfp = relationship("RFP", back_populates="messages")


class RfpFollowupMessage(Base):
    """신규 개발(RFP) 허브 — 요청·인터뷰·제안 맥락에서 회원 질문·AI 응답."""

    __tablename__ = "rfp_followup_messages"

    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey("rfps.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 대화 스레드 소유(요청자 user_id 또는 매칭 컨설턴트 id). NULL은 마이그레이션 전 레거시(요청자 스레드).
    thread_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    rfp = relationship("RFP", back_populates="followup_messages")


class RfpFsSupplement(Base):
    """컨설턴트가 업로드한 수정 FS(.md). R2 또는 로컬 uploads 경로에 저장."""

    __tablename__ = "rfp_fs_supplements"

    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey("rfps.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_path = Column(Text, nullable=False)
    filename = Column(String(512), nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    rfp = relationship("RFP", foreign_keys=[rfp_id], back_populates="fs_supplements")


class IntegrationRequest(Base):
    """SAP 연동 개발 요청 (비 ABAP 중심: VBA, Python, 배치, API 등)."""

    __tablename__ = "integration_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=False)
    # comma-separated codes — 옵션은 DevType(usage=integration|both)에서 관리
    impl_types = Column(String, nullable=True)
    sap_touchpoints = Column(Text, nullable=True)
    environment_notes = Column(Text, nullable=True)
    security_notes = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    description_format = Column(String(16), nullable=False, default="plain")
    requirement_screenshots_json = Column(Text, nullable=True)
    attachments_json = Column(Text, nullable=True)
    reference_code_payload = Column(Text, nullable=True)
    status = Column(String, default="submitted")
    interview_status = Column(String, default="pending")
    proposal_text = Column(Text, nullable=True)
    proposal_generated_at = Column(DateTime, nullable=True)
    # 연동 전용: 기능명세(FS)·구현 산출(비-ABAP, 마크다운)
    fs_status = Column(String, default="none")  # none | generating | ready | failed
    fs_text = Column(Text, nullable=True)
    fs_generated_at = Column(DateTime, nullable=True)
    fs_error = Column(Text, nullable=True)
    fs_job_log = Column(Text, nullable=True)
    delivered_code_status = Column(String, default="none")  # none | generating | ready | failed
    delivered_code_text = Column(Text, nullable=True)
    delivered_code_payload = Column(Text, nullable=True)  # JSON: 파일 슬롯 + 가이드·테스트 (연동 납품)
    delivered_code_generated_at = Column(DateTime, nullable=True)
    delivered_code_error = Column(Text, nullable=True)
    delivered_job_log = Column(Text, nullable=True)
    # 분석·연동 → 신규 개발(RFP) 제안·FS·납품 파이프라인 연결
    workflow_rfp_id = Column(Integer, ForeignKey("rfps.id"), nullable=True)
    improvement_request_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="integration_requests")
    workflow_rfp = relationship("RFP", foreign_keys=[workflow_rfp_id])
    interview_messages = relationship(
        "IntegrationInterviewMessage",
        back_populates="request",
        order_by="IntegrationInterviewMessage.round_number, IntegrationInterviewMessage.id",
        cascade="all, delete-orphan",
    )
    followup_messages = relationship(
        "IntegrationFollowupMessage",
        back_populates="request",
        order_by="IntegrationFollowupMessage.created_at",
        cascade="all, delete-orphan",
    )


class IntegrationInterviewMessage(Base):
    """연동 개발 — AI 인터뷰 라운드(RFPMessage와 동일 스키마)."""

    __tablename__ = "integration_interview_messages"

    id = Column(Integer, primary_key=True, index=True)
    integration_request_id = Column(
        Integer,
        ForeignKey("integration_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number = Column(Integer, nullable=False)
    questions_json = Column(Text, nullable=False)
    answers_text = Column(Text, nullable=True)
    intra_state_json = Column(Text, nullable=True)
    source_label = Column(String, nullable=True)
    is_answered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    request = relationship("IntegrationRequest", back_populates="interview_messages")


class IntegrationFollowupMessage(Base):
    """연동 개발 상세 — 후속 질문·응답(분석·개선 인터뷰와 동일 역할)."""

    __tablename__ = "integration_followup_messages"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("integration_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    thread_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    request = relationship("IntegrationRequest", back_populates="followup_messages")


class ABAPCode(Base):
    __tablename__ = "abap_codes"

    id = Column(Integer, primary_key=True, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    program_id = Column(String, nullable=True)         # SAP 프로그램 ID
    transaction_code = Column(String, nullable=True)   # 트랜잭션 코드
    title = Column(String, nullable=False)             # 프로그램 설명 (필수)
    sap_modules = Column(String, nullable=False)       # comma-separated
    dev_types = Column(String, nullable=False)         # comma-separated
    source_code = Column(Text, nullable=False)
    analysis_json = Column(Text, nullable=True)        # Hannah 분석 결과 JSON
    is_analyzed = Column(Boolean, default=False)
    is_draft = Column(Boolean, default=False)          # 임시 저장 여부
    created_at = Column(DateTime, default=datetime.utcnow)

    uploader = relationship("User", back_populates="abap_codes")


class AbapAnalysisRequest(Base):
    """회원 전용 ABAP 정밀 분석(abap_codes와 별도 저장)."""

    __tablename__ = "abap_analysis_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(512), nullable=False, default="")
    program_id = Column(String, nullable=True)
    transaction_code = Column(String, nullable=True)
    sap_modules = Column(String, nullable=True)
    dev_types = Column(String, nullable=True)
    requirement_text = Column(Text, nullable=False, default="")
    # plain | html — html이면 requirement_text에 서식·인라인 이미지 HTML
    requirement_text_format = Column(String(16), nullable=False, default="plain")
    # [{path, filename, size, inline_id?}] — 인라인·레거시 갤러리 이미지
    requirement_screenshots_json = Column(Text, nullable=True)
    # RFP와 동일 JSON 스키마(슬롯·섹션)
    reference_code_payload = Column(Text, nullable=True)
    source_code = Column(Text, nullable=False, default="")
    attachments_json = Column(Text, nullable=True)
    analysis_json = Column(Text, nullable=True)
    is_analyzed = Column(Boolean, default=False)
    is_draft = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    workflow_rfp_id = Column(Integer, ForeignKey("rfps.id"), nullable=True)
    improvement_request_text = Column(Text, nullable=True)

    owner = relationship("User", back_populates="abap_analysis_requests")
    workflow_rfp = relationship("RFP", foreign_keys=[workflow_rfp_id])
    followup_messages = relationship(
        "AbapAnalysisFollowupMessage",
        back_populates="request",
        order_by="AbapAnalysisFollowupMessage.created_at",
        cascade="all, delete-orphan",
    )


class AbapAnalysisFollowupMessage(Base):
    """SAP ABAP 분석 상세 — 동일 코드·분석 맥락에서 이어지는 회원 질문·응답."""

    __tablename__ = "abap_analysis_followup_messages"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("abap_analysis_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    request = relationship("AbapAnalysisRequest", back_populates="followup_messages")


# ── Admin 관리 테이블 ──────────────────────────────────

class SAPModule(Base):
    """Admin이 관리하는 SAP 모듈 목록"""
    __tablename__ = "sap_modules"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)   # SD, MM, FI ...
    label_ko = Column(String, nullable=False)            # 한국어 라벨
    label_en = Column(String, nullable=False)            # 영문 라벨
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class DevType(Base):
    """Admin이 관리하는 개발 유형 목록"""
    __tablename__ = "dev_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)   # Report_ALV, Dialog ...
    label_ko = Column(String, nullable=False)
    label_en = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    # abap: 신규·분석·코드갤러리 칩 / integration: 연동 요청 구현 형태 / both: 양쪽
    usage = Column(String(16), nullable=False, default="abap")


class SiteSettings(Base):
    """Admin이 관리하는 사이트 설정 (key-value)"""
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notice(Base):
    """공지사항"""
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(Text, nullable=False)
    # EN 모드 표시용(비우면 title/content 로 폴백)
    title_en = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FAQ(Base):
    """자주 묻는 질문"""
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    question_en = Column(Text, nullable=True)
    answer = Column(Text, nullable=False)
    answer_en = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Review(Base):
    """문의/리뷰 커뮤니티 글(회원 작성, 댓글 스레드)."""

    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    # 0 = 저자 평점 없음(표시는 review_ratings 집계만). 과거 행은 마이그레이션 전까지 기존 값 유지 가능.
    rating = Column(Integer, default=0, nullable=False)
    # 화면 표시용 이름(비우면 익명). 기본값은 작성 시 계정 이름으로 채움.
    display_name = Column(String(200), nullable=True)
    # 회원이 선택한 공개 여부. False면 작성자·관리자만 열람.
    is_public = Column(Boolean, default=True, nullable=False)
    # True면 회원이 공개로 올렸어도 목록·홈에서 숨김(작성자·관리자만 열람).
    admin_suppressed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = relationship("User", foreign_keys=[user_id])
    comments = relationship(
        "ReviewComment",
        back_populates="review",
        order_by="ReviewComment.created_at",
        cascade="all, delete-orphan",
    )
    ratings = relationship(
        "ReviewRating",
        back_populates="review",
        cascade="all, delete-orphan",
    )


class ReviewRating(Base):
    """다른 회원이 글에 매기는 별점(글 작성자 본인은 제외, 회원당 1회)."""

    __tablename__ = "review_ratings"
    __table_args__ = (UniqueConstraint("review_id", "user_id", name="uq_review_rating_user"),)

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stars = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    review = relationship("Review", back_populates="ratings")
    rater = relationship("User", foreign_keys=[user_id])


class ReviewComment(Base):
    """이용후기 댓글"""
    __tablename__ = "review_comments"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("reviews.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    review = relationship("Review", back_populates="comments")
    author = relationship("User", foreign_keys=[user_id])


class EmailRegistrationCode(Base):
    """회원가입 6자리 인증 코드 (이메일 OTP). 링크 인증 대신 사용."""

    __tablename__ = "email_registration_codes"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PhoneRegistrationCode(Base):
    """회원가입 휴대폰 OTP 인증 코드."""

    __tablename__ = "phone_registration_codes"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(32), unique=True, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PhoneEmailHintCode(Base):
    """로그인 이메일 찾기 — 인증된 휴대폰으로 OTP 발송 후 마스킹된 이메일 표시."""

    __tablename__ = "phone_email_hint_codes"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(32), unique=True, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    """비밀번호 재설정 링크(일회용). 토큰 평문은 저장하지 않고 SHA-256 해시만 보관."""

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True)


class RequestOffer(Base):
    """컨설턴트가 요청건(RFP/ABAP 분석/연동)에 제출한 오퍼."""

    __tablename__ = "request_offers"

    id = Column(Integer, primary_key=True, index=True)
    request_kind = Column(String(16), nullable=False, index=True)  # rfp | analysis | integration
    request_id = Column(Integer, nullable=False, index=True)
    consultant_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="offered", index=True)  # offered | matched
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    matched_at = Column(DateTime, nullable=True)
    # 컨설턴트가 요청 Console에서 매칭 탭을 열기 전까지 표시할 빨간점용
    match_notice_pending = Column(Boolean, default=False, nullable=False)

    consultant = relationship("User", foreign_keys=[consultant_user_id])
    inquiries = relationship(
        "RequestOfferInquiry",
        back_populates="request_offer",
        order_by="RequestOfferInquiry.created_at",
        cascade="all, delete-orphan",
    )


class RequestOfferInquiry(Base):
    """요청 소유자가 오퍼한 컨설턴트에게 보낸 문의(이력)."""

    __tablename__ = "request_offer_inquiries"

    id = Column(Integer, primary_key=True, index=True)
    request_offer_id = Column(
        Integer, ForeignKey("request_offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_inquiry_id = Column(Integer, ForeignKey("request_offer_inquiries.id", ondelete="SET NULL"), nullable=True)
    body = Column(Text, nullable=False)
    email_sent = Column(Boolean, default=False, nullable=False)
    sms_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    request_offer = relationship("RequestOffer", back_populates="inquiries")
    author = relationship("User", foreign_keys=[author_user_id])


class SubscriptionPlan(Base):
    """구독 플랜 정의(일반 회원 / 컨설턴트 별 catalog)."""

    __tablename__ = "subscription_plans"
    __table_args__ = (UniqueConstraint("account_kind", "code", name="uq_subscription_plan_kind_code"),)

    id = Column(Integer, primary_key=True, index=True)
    account_kind = Column(String(16), nullable=False, index=True)  # member | consultant
    code = Column(String(32), nullable=False, index=True)
    display_name_ko = Column(String(128), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    # 월 정액 표시용(결제 연동 전). NULL이면 subscription_catalog 기본가 사용.
    price_monthly_krw = Column(Integer, nullable=True)
    price_monthly_usd_cents = Column(Integer, nullable=True)

    entitlements = relationship(
        "PlanEntitlement",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanEntitlement.metric_key",
    )


class PlanEntitlement(Base):
    """플랜별 기능 한도(period_type + limit_value)."""

    __tablename__ = "plan_entitlements"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_key = Column(String(64), nullable=False, index=True)
    # monthly | per_request | unlimited | disabled
    period_type = Column(String(20), nullable=False)
    # monthly/per_request: 상한 숫자. unlimited/disabled 에서는 무시(저장은 NULL 허용)
    limit_value = Column(Integer, nullable=True)

    plan = relationship("SubscriptionPlan", back_populates="entitlements")

    __table_args__ = (UniqueConstraint("plan_id", "metric_key", name="uq_plan_entitlement_metric"),)


class SubscriptionUsageMonthly(Base):
    """월 단위 사용량(추후 dev_request 등)."""

    __tablename__ = "subscription_usage_monthly"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_key = Column(String(64), nullable=False, index=True)
    year_month = Column(String(7), nullable=False, index=True)  # YYYY-MM (UTC 기준)
    used = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "metric_key", "year_month", name="uq_sub_usage_monthly"),
    )


class SubscriptionUsagePerRequest(Base):
    """요청 건당 사용량(선택적; AI 문의 등은 메시지 카운트와 병행 가능)."""

    __tablename__ = "subscription_usage_per_request"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_key = Column(String(64), nullable=False, index=True)
    request_kind = Column(String(20), nullable=False)  # rfp | analysis | integration
    request_id = Column(Integer, nullable=False, index=True)
    used = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "metric_key", "request_kind", "request_id", name="uq_sub_usage_per_request"
        ),
    )


class AgentPlaybookEntry(Base):
    """테스트·운영 피드백을 누적해 에이전트 프롬프트에 주입하는 플레이북 항목."""

    __tablename__ = "agent_playbook_entries"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    active = Column(Boolean, default=True, nullable=False)
    priority = Column(Integer, default=0, nullable=False)
    title = Column(String(512), nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    # any | rfp | abap_analysis | integration
    match_entity = Column(String(32), nullable=False, default="any")
    # any | direct | abap_analysis | integration | integration_native
    match_workflow_origin = Column(String(64), nullable=False, default="any")
    # JSON 배열 문자열, 예: ["interview","proposal"] — 비어 있으면 매칭 안 함
    match_stages_json = Column(Text, nullable=False, default="[]")

    creator = relationship("User", foreign_keys=[created_by_user_id])


class TrialEligibilityConsumed(Base):
    """체험판(Experience→Junior 권한) 중복 방지: 이메일/휴대폰 식별자 해시."""

    __tablename__ = "trial_eligibility_consumed"
    __table_args__ = (UniqueConstraint("kind", "identity_hash", name="uq_trial_eligibility_kind_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(16), nullable=False, index=True)  # email | phone
    identity_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UiI18nEnOverride(Base):
    """data-i18n 키별 EN 문구 오버라이드(관리자 UI에서 편집). 빈 값이면 행 삭제로 기본 i18n.js 값 사용."""

    __tablename__ = "ui_i18n_en_overrides"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(256), nullable=False, unique=True, index=True)
    en_text = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
