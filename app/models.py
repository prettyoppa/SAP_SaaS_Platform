from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
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
    email_verified = Column(Boolean, default=True)  # 기존 행은 마이그레이션에서 true
    created_at = Column(DateTime, default=datetime.utcnow)

    rfps = relationship("RFP", back_populates="owner")
    abap_codes = relationship("ABAPCode", back_populates="uploader")


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
    file_path = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    attachments_json = Column(Text, nullable=True)   # JSON [{path, filename, note}, ...] 최대 5
    status = Column(String, default="draft")           # draft | submitted | in_review | completed
    interview_status = Column(String, default="pending")  # pending | in_progress | generating_proposal | completed
    proposal_text = Column(Text, nullable=True)
    proposal_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="rfps")
    messages = relationship("RFPMessage", back_populates="rfp", order_by="RFPMessage.round_number")


class RFPMessage(Base):
    __tablename__ = "rfp_messages"

    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey("rfps.id"))
    round_number = Column(Integer, nullable=False)
    questions_json = Column(Text, nullable=False)
    answers_text = Column(Text, nullable=True)
    source_label = Column(String, nullable=True)
    is_answered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    rfp = relationship("RFP", back_populates="messages")


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
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FAQ(Base):
    """자주 묻는 질문"""
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String, nullable=False)
    answer = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Review(Base):
    """이용후기"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    rating = Column(Integer, default=5)          # 1~5점
    is_public = Column(Boolean, default=False)   # Admin이 공개 승인
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = relationship("User", foreign_keys=[user_id])
    comments = relationship("ReviewComment", back_populates="review", order_by="ReviewComment.created_at")


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
