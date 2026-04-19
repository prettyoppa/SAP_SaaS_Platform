# Catchy Lab – SAP 개발 Hub

> **현재 상태**: 2단계 기능 개선 + 3단계 콘텐츠 기능 완료 (Phase 2 완료)

---

## 프로젝트 개요

SAP 개발 요청(RFP)을 받아 AI 에이전트가 인터뷰를 진행하고 Development Proposal을 자동 생성하는 SaaS 플랫폼입니다.

```
[Free Tier]  RFP 제출 → AI 인터뷰 (3라운드) → Development Proposal 생성
[Paid Tier]  상세 FS 작성 → ABAP 코드 생성 → QA 시나리오 (Phase 3 예정)
```

---

## 폴더 구조

```
SAP_AI_PROJECTS/
├── SAP_SaaS_Platform/          ← 메인 SaaS 플랫폼 (→ 추후 platform/ 으로 rename)
│   ├── app/
│   │   ├── agents/             ← CrewAI 에이전트 모듈
│   │   │   ├── free_crew.py    ← Free Tier: f_analyst, f_questioner, f_writer, f_reviewer
│   │   │   ├── paid_crew.py    ← Paid Tier: 스텁 (Phase 3)
│   │   │   └── agent_tools.py  ← 코드 라이브러리 조회 헬퍼
│   │   ├── routers/
│   │   │   ├── auth_router.py       ← 로그인/회원가입 + 회사명 자동완성 API
│   │   │   ├── rfp_router.py        ← RFP 제출/수정/대시보드 (날짜검색·정렬)
│   │   │   ├── interview_router.py  ← 인터뷰 + 답변 편집 + Proposal 재생성
│   │   │   ├── codelib_router.py
│   │   │   ├── admin_router.py      ← 관리자 (모듈·개발유형·설정·공지·FAQ·후기)
│   │   │   └── review_router.py     ← 이용후기 회원 작성/삭제
│   │   ├── templates/          ← Jinja2 HTML 템플릿
│   │   ├── static/             ← CSS, JS
│   │   ├── models.py           ← SQLAlchemy DB 모델
│   │   ├── auth.py             ← JWT 인증 (Argon2 해싱)
│   │   ├── code_analyzer.py    ← ABAP 코드 분석 (Gemini 직접 호출, 레거시)
│   │   ├── database.py
│   │   ├── templates_config.py ← 공유 Jinja2Templates 인스턴스
│   │   └── main.py
│   ├── uploads/
│   ├── saas_platform.db        ← SQLite DB
│   ├── requirements.txt
│   └── .env                    ← GOOGLE_API_KEY 설정
└── sandbox/                    ← 실험/검증 환경 (구 SAP_AI_Agent)
```

---

## AI 에이전트 구조

### Free Tier 에이전트 (`free_crew.py`)

| 변수명 | 페르소나 | 역할 |
|---|---|---|
| `f_analyst` | Hannah | RFP 분석, 라운드 간 답변 분석, 코드 기술 분석 |
| `f_questioner` | Mia | 전 라운드 인터뷰 질문 생성, 코드 역추출 질문 생성 |
| `f_writer` | Jun | Development Proposal 작성 |
| `f_reviewer` | Sara | Proposal 품질 검토 및 최종 승인 |

### Paid Tier 에이전트 (`paid_crew.py`) – Phase 3 예정

| 변수명 | 페르소나 | 역할 |
|---|---|---|
| `p_architect` | David | 상세 FS 작성 |
| `p_coder` | Kevin | ABAP 코드 생성 |
| `p_inspector` | Young | 코드 리뷰 및 수정 지시 |
| `p_tester` | Brian | Unit Test 시나리오 작성 |

### 에이전트 활용 플로우

```
[코드 라이브러리 분석]
ABAP 업로드 → Hannah(기술분석) → Mia(범용 질문 추출) → DB 저장

[인터뷰 라운드 진행]
1라운드: 코드 라이브러리 매칭 있으면 DB 질문 사용, 없으면 Hannah→Mia 에이전트
2·3라운드: 항상 Hannah(답변 분석) → Mia(다음 질문 생성)

[Proposal 생성]
Hannah(최종 분석) → Jun(Proposal 작성) → Sara(품질 검토·승인)
→ BackgroundTask 비동기 실행 + 생성 중 로딩 화면 표시
```

---

## 주요 기능

### 회원 기능 (Free)
- 회원가입/로그인 (JWT 쿠키 인증, Argon2 패스워드 해싱)
- RFP 제출 (SAP 모듈 선택, 개발유형 선택, 파일 첨부, 자유 기술)
- AI 인터뷰 (3라운드 × 3질문, 코드 라이브러리 기반 1라운드 우선)
- Development Proposal 생성 및 다운로드 (Hannah·Jun·Sara 3에이전트)
- 인터뷰 재시작 기능 (대시보드 ↺ 버튼)

### 관리자 기능
- ABAP 코드 라이브러리 관리 (업로드·조회·재분석·삭제)
- 멀티섹션 ABAP 소스 입력 (SE80 구조 기준 섹션 분리 탭 표시)
- Hannah·Mia 에이전트 기반 역분석 (기술 분석 + 범용 인터뷰 질문 추출)

---

## 기술 스택

| 분류 | 기술 |
|---|---|
| Backend | FastAPI 0.135, SQLAlchemy 2.0, SQLite(로컬) / PostgreSQL(Railway 등) |
| Frontend | Jinja2, Bootstrap 5, Vanilla JS |
| AI 에이전트 | CrewAI 1.14, Google Gemini (기본 `gemini-2.5-flash`, `GEMINI_MODEL`로 변경) |
| 인증 | JWT (python-jose), Argon2 (passlib) |

---

## 로컬 실행

```bash
cd SAP_SaaS_Platform

# 가상환경 및 패키지 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에 GOOGLE_API_KEY=your_key 입력

# 서버 실행
python -m uvicorn app.main:app --reload --port 8000
```

브라우저에서 **http://127.0.0.1:8000** 접속

---

## 배포 환경 (Railway + PostgreSQL + R2)

프로덕션은 **Railway**에 웹 서비스를 두고, **PostgreSQL**을 DB로 쓰며, RFP 첨부 파일은 **Cloudflare R2**(S3 호환 API)에 올리도록 구성할 수 있다. 아래는 실제 세팅 시 겪은 이슈와 변수 정리다.

### Railway – 웹 서비스

- **빌드/실행**: `requirements.txt`, Nixpacks, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **PostgreSQL 드라이버**: `psycopg2-binary` 필수. 없으면 `ModuleNotFoundError: No module named 'psycopg2'` 로 기동 실패.

### Railway – PostgreSQL 연결 문자열

Postgres 플러그인이 주는 `DATABASE_URL`은 종종 호스트가 **`postgres.railway.internal`** 이다. 웹 컨테이너에서 사설 DNS가 풀리지 않으면 아래 오류가 난다.

`psycopg2.OperationalError: could not translate host name "postgres.railway.internal" to address: Name or service not known`

**대응 (웹 서비스 Variables)**

| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | Postgres가 발급한 **전체** URL(내부 호스트 포함)을 그대로 유지해도 된다. |
| `DATABASE_PUBLIC_URL` | **공개 TCP 프록시**용 URL. `*.proxy.rlwy.net` 등 **전체** `postgresql://user:pass@host:port/dbname` 형태를 넣는다. |

앱(`app/database.py`) 동작 요약:

- `DATABASE_PUBLIC_URL`이 있으면 **우선** 사용한다.
- 값이 **`postgresql://`로 시작하는 전체 URL**이면 그대로 쓰고, 공개 호스트(`.rlwy.net` 등)에는 **`sslmode=require`** 를 자동으로 붙인다.
- 값이 **`host:port`만**이면, 같은 서비스에 있는 **`DATABASE_URL`의 사용자·비밀번호·DB 경로**와 합쳐 한 줄 URL로 만든다. (이때 `DATABASE_URL`도 반드시 있어야 한다.)
- **`DATABASE_PUBLIC_URL`에 `host:port`만 넣고 전체 URL이 아닌 경우**, SQLAlchemy가 파싱하지 못해 `ArgumentError: Could not parse SQLAlchemy URL` 이 날 수 있으므로, **전체 `postgresql://...` 를 넣거나** 위 **host:port 병합** 규칙을 지킨다.

비밀번호 **regenerate** 후에는 Postgres와 웹 양쪽의 URL을 **다시 맞춘 뒤** 재배포한다.

### Cloudflare R2 – 객체 저장 (RFP 첨부)

앱은 `boto3`로 R2 S3 API에 붙는다 (`app/r2_storage.py`). Railway **웹** 서비스에 아래 네 변수를 넣는다.

| 변수 | 설명 |
|------|------|
| `R2_ACCOUNT_ID` | Cloudflare **Account ID** (R2/대시보드에서 확인) |
| `R2_ACCESS_KEY_ID` | R2 전용 **Access Key ID** |
| `R2_SECRET_ACCESS_KEY` | 위와 쌍인 **Secret Access Key** (생성 직후 한 번만 표시) |
| `R2_BUCKET_NAME` | R2 버킷 이름 |

**주의:** **My Profile → Account API Tokens** 에서 만든 **일반 API 토큰(문자열 한 줄)** 은 이 경로에 쓰이지 않는다. 반드시 **R2** 화면의 **Create Account API Token**(또는 **Manage R2 API Tokens** 등 S3 호환 키 발급 UI)에서 **Access Key ID + Secret** 쌍을 발급한다.

토큰 생성 시:

- **권한**: 업로드·다운로드·삭제가 필요하면 **`Object Read & Write`** (가능하면 특정 버킷만). 처음엔 넓게 **`Admin Read & Write`** 로 시작해도 된다.
- **Client IP 필터**: Railway 출구 IP가 고정이 아니므로 **비우는 것**을 권장한다.
- **TTL**: `Forever` 로 시작 가능. 운영 시에는 주기적 갱신을 검토.

R2 구독/결제 수단 연결은 Cloudflare 정책에 따라 활성화 단계에서 요구될 수 있다(무료 한도 내 사용은 요금 페이지 기준).

### 동작 확인 체크리스트

1. Railway 웹 서비스가 **시간이 지나도 Crashed로 바뀌지 않는지**
2. RFP에 파일 첨부 후 제출 → Cloudflare R2 버킷에 **`rfp_attachments/...`** 객체가 생기는지
3. (별도) AI 인터뷰·Proposal: Railway에 **`GOOGLE_API_KEY`** 등이 설정되어 있는지 — R2와 무관하지만 기능상 필요하다.

### 참고 파일

- `app/database.py` — DB URL 해석, `DATABASE_PUBLIC_URL` 병합, 공개 호스트 SSL
- `app/r2_storage.py` — R2 업로드·presigned URL·`r2://` 키 접두사
- `app/routers/rfp_router.py` — 첨부 저장 시 R2 또는 로컬/`/tmp`
- `.env.example` — 변수 이름 요약

---

## 개발 이력

| 단계 | 내용 |
|---|---|
| Phase 1 | FastAPI 웹앱 기초 (회원가입/로그인/RFP 수집) |
| Phase 1.5 | Gemini 직접 호출 인터뷰 엔진 + Proposal 생성 |
| Phase 1.7 | ABAP 코드 라이브러리 (역분석 질문 DB화) |
| Phase 2 | **CrewAI 에이전트 통합** (Hannah·Mia·Jun·Sara) |
| Phase 2 Stage 1 | Admin 시스템, DB 스키마 확장, UI/UX 기초 개선 |
| Phase 2 Stage 2 | 인터뷰 답변 편집, Proposal 재생성, 대시보드 날짜검색/정렬, 회원가입 개선 |
| Phase 2 Stage 3 | Admin 사이트 설정, 공지사항/FAQ/이용후기 관리, 이용약관/개인정보처리방침 연동 |
| Phase 3 | Paid Tier 에이전트 (David·Kevin·Young·Brian) – 예정 |

---

## Stage 2 신규 기능 (2026-04-12)

### 2단계 – 기능 개선
| 기능 | 설명 |
|---|---|
| 인터뷰 답변 편집 | Proposal 화면에서 "답변 수정" 버튼으로 기존 답변 인라인 편집 |
| Proposal 재생성 | 답변 수정 후 "Proposal 재생성" 버튼으로 새 제안서 생성 |
| 대시보드 날짜 검색 | 시작일/종료일 필터링으로 기간별 요청 조회 |
| 대시보드 정렬 | 최신순/오래된순/상태순 정렬 기능 |
| 회원가입 이메일 유효성 | 프론트엔드 실시간 이메일 형식 검사 |
| 회사명 자동완성 | 기존 회원 회사명 AJAX 자동완성 드롭다운 |
| 비밀번호 보기/숨기기 | 회원가입·로그인 폼의 password 토글 버튼 |

### 3단계 – 콘텐츠 기능
| 기능 | 설명 |
|---|---|
| Admin 사이트 설정 | 홈 헤드라인·부제목, 개발요청 작성팁, 이용약관, 개인정보처리방침 설정 |
| 공지사항 관리 | Admin CRUD + 홈 화면 공지사항 탭에 실시간 표시 |
| FAQ 관리 | Admin CRUD + 홈 화면 FAQ 탭에 아코디언 표시 |
| 이용후기 관리 | 회원 작성 → Admin 공개 승인 → 홈 화면 이용후기 탭에 표시 |
| 이용약관 연동 | Admin에서 설정한 이용약관/개인정보처리방침을 회원가입 모달로 표시 |

---

## 다음 과제

- [ ] 인터뷰 질문 품질 개선 (Mia 프롬프트 튜닝)
- [ ] Proposal 생성 중 로딩 화면 개선 (실시간 진행 상황 표시)
- [ ] Paid Tier 에이전트 구현 (Phase 3)
- [ ] 결제 연동
