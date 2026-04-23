/* ─────────────────────────────────────────────────
   SAP Dev Hub – Internationalisation (EN / KO)
───────────────────────────────────────────────── */
const TRANSLATIONS = {
  en: {
    /* Brand */
    "brand.name": "Catchy Lab - SAP Dev Hub",
    /* Nav */
    "nav.home": "Home", "nav.dashboard": "Dashboard", "nav.newRfp": "New Request",
    "nav.codelib": "Code Library", "nav.admin": "Admin",
    "nav.login": "Login", "nav.signup": "Sign Up", "nav.logout": "Logout",
    /* Footer */
    "footer.tagline": "AI-Powered SAP Development Automation Platform",
    "footer.copy": "© 2026 SAP Dev Hub. All rights reserved.",
    /* Hero */
    "hero.badge": "AI-Assisted SAP Development",
    "hero.title1": "Transform Your", "hero.title2": "SAP Development", "hero.title3": "with AI Power",
    "hero.subtitle": "Submit your SAP development requirements and receive a professional Development Proposal automatically. Expert consultants then deliver production-ready ABAP code.",
    "hero.cta.start": "Start Free", "hero.cta.how": "How it Works",
    "hero.stat1": "Development Proposal", "hero.stat2": "Turnaround", "hero.stat3": "Certified Experts",
    /* How */
    "how.title": "How It Works", "how.subtitle": "From requirement to delivery in 3 simple steps",
    "how.step1.title": "Submit Your RFP",
    "how.step1.desc": "Select SAP modules and development types, describe your requirements in plain language, and attach any reference files.",
    "how.step1.tag": "FREE",
    "how.step2.title": "Receive AI Proposal",
    "how.step2.desc": "Our AI instantly generates a structured Development Proposal covering overview, screen flow, features, and expert checkpoints.",
    "how.step2.tag": "FREE",
    "how.step3.title": "Get Final FS & Code",
    "how.step3.desc": "Expert consultants review and refine the proposal, deliver production-ready ABAP code, and provide on-site implementation support.",
    "how.step3.tag": "PAID",
    /* Modules */
    "modules.title": "SAP Modules Supported",
    /* Home tabs */
    "home.tab.notice": "Notices", "home.tab.review": "Reviews",
    "home.notice.empty": "No notices yet.", "home.faq.empty": "No FAQs yet.",
    "home.review.empty": "Be the first to leave a review.",
    "home.review.write": "Write a Review", "home.review.login": "Login to Write",
    /* Hero (logged-in) */
    "hero.cta.new": "New Request", "hero.cta.dashboard": "My Dashboard",
    /* How-it-works flow */
    "how.step1.a": "Select SAP Module & Dev Type",
    "how.step1.b": "Describe requirements freely",
    "how.step1.c": "Attach reference files (optional)",
    "how.step2.a": "Hannah – RFP Analysis",
    "how.step2.b": "Mia – 3-Round In-depth Interview",
    "how.step2.c": "Jun – Development Proposal Draft",
    "how.step2.d": "Sara – Proposal Quality Review",
    "how.step3.a": "David – Detailed Functional Spec",
    "how.step3.b": "Kevin – ABAP Code Generation",
    "how.step3.c": "Young – Code Review & Refinement",
    "how.step3.d": "Brian – Unit Test Scenarios",
    /* CTA */
    "cta.title": "Ready to automate your SAP development?",
    "cta.sub": "Create your free account and submit your first requirement today.",
    "cta.btn": "Get Started Free", "cta.btn.loggedin": "New Request",
    /* Login */
    "login.title": "Welcome Back", "login.sub": "Sign in to your SAP Dev Hub account",
    "login.email": "Email", "login.password": "Password", "login.btn": "Sign In",
    "login.error": "Invalid email or password.",
    "login.noAccount": "Don't have an account?", "login.signupLink": "Sign up free",
    /* Register */
    "register.title": "Create Account", "register.sub": "Start automating your SAP development today",
    "register.name": "Full Name", "register.email": "Email", "register.company": "Company",
    "register.optional": "(Optional)", "register.password": "Password",
    "register.terms": "I agree to the", "register.termsLink": " Terms of Service",
    "register.and": " and ", "register.privacyLink": "Privacy Policy",
    "register.btn": "Create Account",
    "register.errorDuplicate": "This email is already registered.",
    "register.hasAccount": "Already have an account?", "register.loginLink": "Sign in",
    /* RFP Form */
    "rfp.back": "Back to Dashboard", "rfp.title": "New Development Request",
    "rfp.sub": "Tell us what you need. Our AI will generate a free Development Proposal for you.",
    "rfp.prog1": "Modules & Type", "rfp.prog2": "Description", "rfp.prog3": "Attachment",
    "rfp.prog4": "Ref. code", "rfp.prog5": "Review",
    "rfp.s1.title": "Request Title & SAP Module",
    "rfp.s1.sub": "Select SAP modules and dev types first, then program ID and title.",
    "rfp.titleLabel": "Request Title", "rfp.titlePlaceholder": "",
    "rfp.moduleLabel": "SAP Modules", "rfp.devTypeLabel": "Development Type",
    "rfp.devTypeSub": "Select the type(s) of ABAP development required.",
    "rfp.s2.title": "Describe Your Requirements",
    "rfp.s2.sub": "Write as much detail as you can. The more context, the better the proposal.",
    "rfp.descPlaceholder": "Example: We need a program to upload Sales Orders from an Excel file...",
    "rfp.descHint": "Describe business context, expected inputs/outputs, constraints, edge cases, etc.",
    "rfp.chars": "chars",
    "rfp.tipTitle": "Tips for a great proposal",
    "rfp.tip1": "Mention the SAP T-Code or process this relates to (e.g., VA01, ME21N)",
    "rfp.tip2": "Describe where data comes from and where it should go",
    "rfp.tip3": "List any validation rules or error handling expectations",
    "rfp.tip4": "Mention output format (ALV, PDF form, file export, etc.)",
    "rfp.s3.title": "Attach Reference Files",
    "rfp.s3.sub": "Excel templates, existing reports, screen captures, or any relevant documents.",
    "rfp.dropTitle": "Click or drag a file here",
    "rfp.dropSub": "PDF, Excel, Word, images, TXT · Max 20MB",
    "rfp.changeFile": "Click to change file",
    "rfp.s4.title": "Review & Submit",
    "rfp.s4.sub": "Your request will be reviewed and a free Development Proposal will be generated.",
    "rfp.reviewModules": "Selected Modules:", "rfp.reviewTypes": "Development Types:",
    "rfp.reviewFile": "Attachment:", "rfp.none": "None selected", "rfp.noFile": "No file attached",
    "rfp.freeNote": "Development Proposal generation is <strong>completely free</strong>. You'll receive it within 24 hours.",
    "rfp.cancel": "Cancel", "rfp.submit": "Submit Request",
    "rfp.errorFile": "Invalid file type. Allowed: PDF, Excel, Word, images, TXT.",
    /* Modules */
    "mod.SD": "Sales & Distribution", "mod.MM": "Materials Management",
    "mod.FI": "Financial Accounting", "mod.CO": "Controlling",
    "mod.PP": "Production Planning", "mod.QM": "Quality Management",
    "mod.PM": "Plant Maintenance", "mod.HCM": "Human Capital Mgmt",
    "mod.WM": "Warehouse Mgmt", "mod.PS": "Project System",
    "mod.EWM": "Ext. Warehouse Mgmt", "mod.Basis": "Basis / Technical",
    /* Dev Types */
    "dt.report": "Report / ALV", "dt.dialog": "Dialog Program",
    "dt.fm": "Function Module", "dt.enh": "BAdI / User Exit",
    "dt.bapi": "BAPI Call", "dt.upload": "Data Upload (BDC/LSMW)",
    "dt.interface": "Interface (IDoc/RFC)", "dt.form": "Form (SmartForms/ADS)",
    "dt.workflow": "Workflow", "dt.fiori": "Fiori / Web Dynpro",
    /* Dashboard */
    "dash.welcome": "Welcome back,",
    "dash.newRequest": "New Request", "dash.totalRequests": "Total",
    "dash.completed": "Completed", "dash.inReview": "In Review", "dash.submitted": "Submitted",
    "dash.myRequests": "My Development Requests",
    "dash.emptyTitle": "No requests yet",
    "dash.emptyDesc": "Submit your first development request and receive a free AI-generated proposal.",
    "dash.emptyBtn": "Create First Request",
    "dash.editRfp": "Edit RFP", "dash.createdAt": "Submitted", "dash.proposalAt": "Proposal",
    /* Status */
    "status.draft": "Draft", "status.submitted": "Submitted",
    "status.in_review": "In Review", "status.completed": "Completed",
    /* Success */
    "success.title": "Request Submitted!", "success.sub": "Your development request has been received. Our AI is analyzing your requirements.",
    "success.title2": "Request Title", "success.modules": "SAP Modules",
    "success.types": "Dev Types", "success.status": "Status",
    "success.nextTitle": "What happens next?",
    "success.next1.title": "AI Analysis", "success.next1.desc": "Our AI parses your requirements and generates a structured Development Proposal.",
    "success.next2.title": "Expert Review", "success.next2.desc": "An SAP consultant reviews and enriches the proposal with professional insights.",
    "success.next3.title": "Proposal Delivered", "success.next3.desc": "You'll receive your free Development Proposal within 24 hours via email.",
    "success.newRequest": "New Request", "success.dashboard": "Go to Dashboard",
  },

  ko: {
    /* Brand */
    "brand.name": "Catchy Lab - SAP 개발 Hub",
    /* Nav */
    "nav.home": "홈", "nav.dashboard": "대시보드", "nav.newRfp": "신규 요청",
    "nav.codelib": "코드 라이브러리", "nav.admin": "관리자 메뉴",
    "nav.login": "로그인", "nav.signup": "회원가입", "nav.logout": "로그아웃",
    /* Footer */
    "footer.tagline": "AI 기반 SAP 개발 자동화 플랫폼",
    "footer.copy": "© 2026 SAP Dev Hub. All rights reserved.",
    /* Hero */
    "hero.badge": "AI 기반 SAP 개발 자동화",
    "hero.title1": "SAP 개발을", "hero.title2": "AI로 혁신하세요", "hero.title3": "",
    "hero.subtitle": "개발 요구사항을 제출하면 전문 수준의 개발 제안서(Proposal)를 자동으로 받아보세요. SAP 전문 컨설턴트가 실제 운영 가능한 ABAP 코드를 납품해 드립니다.",
    "hero.cta.start": "무료로 시작하기", "hero.cta.how": "이용 방법 보기",
    "hero.stat1": "개발 제안서 무료", "hero.stat2": "납품 기간", "hero.stat3": "SAP 전문가",
    /* How */
    "how.title": "이용 방법", "how.subtitle": "요구사항 접수부터 납품까지 3단계",
    "how.step1.title": "RFP 제출",
    "how.step1.desc": "SAP 모듈과 개발 유형을 선택하고, 요구사항을 자유롭게 입력하고 참고 파일을 첨부하세요.",
    "how.step1.tag": "무료",
    "how.step2.title": "AI 제안서 수신",
    "how.step2.desc": "AI가 즉시 구조화된 개발 제안서를 생성합니다. 개요, 화면 흐름, 기능 명세, 전문가 체크포인트가 포함됩니다.",
    "how.step2.tag": "무료",
    "how.step3.title": "최종 FS & 코드 수령",
    "how.step3.desc": "전문 컨설턴트가 제안서를 검토·보완하고, 검증된 ABAP 코드와 현장 이행 서비스를 제공합니다.",
    "how.step3.tag": "유료",
    /* Modules */
    "modules.title": "지원 SAP 모듈",
    /* Home tabs */
    "home.tab.notice": "공지사항", "home.tab.review": "이용후기",
    "home.notice.empty": "등록된 공지사항이 없습니다.", "home.faq.empty": "등록된 FAQ가 없습니다.",
    "home.review.empty": "이용후기를 남겨주세요.",
    "home.review.write": "후기 작성", "home.review.login": "로그인 후 작성",
    /* Hero (logged-in) */
    "hero.cta.new": "신규 요청하기", "hero.cta.dashboard": "내 대시보드",
    /* How-it-works flow */
    "how.step1.a": "SAP 모듈 & 개발 유형 선택",
    "how.step1.b": "요구사항 자유 기술",
    "how.step1.c": "참고 파일 첨부 (선택)",
    "how.step2.a": "Hannah – RFP 분석",
    "how.step2.b": "Mia – 3라운드 심층 인터뷰",
    "how.step2.c": "Jun – 개발 제안서 초안",
    "how.step2.d": "Sara – 제안서 품질 검토",
    "how.step3.a": "David – 상세 기능 명세서 작성",
    "how.step3.b": "Kevin – ABAP 코드 생성",
    "how.step3.c": "Young – 코드 리뷰 & 완성도 향상",
    "how.step3.d": "Brian – 단위 테스트 시나리오",
    /* CTA */
    "cta.title": "SAP 개발 자동화를 시작할 준비가 되셨나요?",
    "cta.sub": "무료 계정을 만들고 첫 번째 요구사항을 오늘 바로 제출해 보세요.",
    "cta.btn": "무료로 시작하기", "cta.btn.loggedin": "신규 요청하기",
    /* Login */
    "login.title": "다시 오셨군요!", "login.sub": "SAP Dev Hub 계정으로 로그인하세요",
    "login.email": "이메일", "login.password": "비밀번호", "login.btn": "로그인",
    "login.error": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "login.noAccount": "계정이 없으신가요?", "login.signupLink": "무료 회원가입",
    /* Register */
    "register.title": "계정 만들기", "register.sub": "SAP 개발 자동화를 지금 시작하세요",
    "register.name": "이름", "register.email": "이메일", "register.company": "회사명",
    "register.optional": "(선택)", "register.password": "비밀번호",
    "register.terms": "다음에 동의합니다:", "register.termsLink": "이용약관",
    "register.and": " 및 ", "register.privacyLink": "개인정보처리방침",
    "register.btn": "계정 만들기",
    "register.errorDuplicate": "이미 가입된 이메일 주소입니다.",
    "register.hasAccount": "이미 계정이 있으신가요?", "register.loginLink": "로그인",
    /* RFP Form */
    "rfp.back": "대시보드로 돌아가기", "rfp.title": "새 개발 요청",
    "rfp.sub": "요구사항을 입력하면 무료 개발 제안서(Proposal)를 자동 생성해 드립니다.",
    "rfp.prog1": "모듈 & 유형", "rfp.prog2": "요구사항", "rfp.prog3": "파일첨부",
    "rfp.prog4": "참고 코드", "rfp.prog5": "최종확인",
    "rfp.s1.title": "요청 제목 & SAP 모듈",
    "rfp.s1.sub": "먼저 SAP 모듈·개발 유형을 선택한 뒤 프로그램 ID와 제목을 입력해 주세요.",
    "rfp.titleLabel": "요청 제목", "rfp.titlePlaceholder": "",
    "rfp.moduleLabel": "SAP 모듈", "rfp.devTypeLabel": "개발 유형",
    "rfp.devTypeSub": "필요한 ABAP 개발 유형을 선택하세요. 복수 선택 가능합니다.",
    "rfp.s2.title": "요구사항 상세 기술",
    "rfp.s2.sub": "최대한 자세히 작성할수록 더 정확한 제안서가 생성됩니다.",
    "rfp.descPlaceholder": "",
    "rfp.descHint": "비즈니스 배경, 입출력 데이터, 제약 사항, 예외 처리 등을 기술해 주세요.",
    "rfp.chars": "자",
    "rfp.tipTitle": "더 좋은 제안서를 위한 작성 팁",
    "rfp.tip1": "관련 SAP T-Code 또는 프로세스를 언급해 주세요 (예: VA01, ME21N)",
    "rfp.tip2": "데이터의 출처와 목적지를 설명해 주세요",
    "rfp.tip3": "유효성 검사 규칙이나 오류 처리 기대 사항을 명시해 주세요",
    "rfp.tip4": "출력 형태를 알려주세요 (ALV, PDF Form, 파일 Export 등)",
    "rfp.s3.title": "참고 파일 첨부",
    "rfp.s3.sub": "엑셀 양식, 기존 리포트, 화면 캡처, 관련 문서 등을 첨부하세요.",
    "rfp.dropTitle": "클릭하거나 파일을 여기에 끌어다 놓으세요",
    "rfp.dropSub": "PDF, Excel, Word, 이미지, TXT · 최대 20MB",
    "rfp.changeFile": "클릭하여 파일 변경",
    "rfp.s4.title": "검토 후 제출",
    "rfp.s4.sub": "요청이 검토되고 무료 개발 제안서가 생성됩니다.",
    "rfp.reviewModules": "선택 모듈:", "rfp.reviewTypes": "개발 유형:",
    "rfp.reviewFile": "첨부 파일:", "rfp.none": "선택 없음", "rfp.noFile": "파일 없음",
    "rfp.freeNote": "개발 제안서 생성은 <strong>완전 무료</strong>입니다. 24시간 내에 이메일로 받아보실 수 있습니다.",
    "rfp.cancel": "취소", "rfp.submit": "요청 제출",
    "rfp.errorFile": "허용되지 않는 파일 형식입니다. 허용: PDF, Excel, Word, 이미지, TXT.",
    /* Modules */
    "mod.SD": "영업 및 유통", "mod.MM": "자재 관리",
    "mod.FI": "재무 회계", "mod.CO": "관리 회계",
    "mod.PP": "생산 계획", "mod.QM": "품질 관리",
    "mod.PM": "설비 관리", "mod.HCM": "인사 관리",
    "mod.WM": "창고 관리", "mod.PS": "프로젝트 시스템",
    "mod.EWM": "확장 창고 관리", "mod.Basis": "Basis / 기술",
    /* Dev Types */
    "dt.report": "Report / ALV", "dt.dialog": "다이얼로그 프로그램",
    "dt.fm": "함수 모듈", "dt.enh": "BAdI / User Exit",
    "dt.bapi": "BAPI 호출", "dt.upload": "데이터 업로드 (BDC/LSMW)",
    "dt.interface": "인터페이스 (IDoc/RFC)", "dt.form": "서식 (SmartForms/ADS)",
    "dt.workflow": "워크플로우", "dt.fiori": "Fiori / Web Dynpro",
    /* Dashboard */
    "dash.welcome": "환영합니다,",
    "dash.newRequest": "신규 요청", "dash.totalRequests": "전체",
    "dash.completed": "완료", "dash.inReview": "검토 중", "dash.submitted": "제출됨",
    "dash.myRequests": "나의 개발 요청 목록",
    "dash.emptyTitle": "아직 요청이 없습니다",
    "dash.emptyDesc": "첫 번째 개발 요청을 제출하고 무료 AI 개발 제안서를 받아보세요.",
    "dash.emptyBtn": "첫 번째 요청 만들기",
    "dash.editRfp": "RFP 수정", "dash.createdAt": "제출일", "dash.proposalAt": "제안서",
    /* Status */
    "status.draft": "초안", "status.submitted": "제출됨",
    "status.in_review": "검토 중", "status.completed": "완료",
    /* Success */
    "success.title": "요청이 접수되었습니다!", "success.sub": "개발 요청이 정상적으로 접수되었습니다. AI가 요구사항을 분석하고 있습니다.",
    "success.title2": "요청 제목", "success.modules": "SAP 모듈",
    "success.types": "개발 유형", "success.status": "상태",
    "success.nextTitle": "다음 단계는 무엇인가요?",
    "success.next1.title": "AI 분석", "success.next1.desc": "AI가 요구사항을 분석하여 구조화된 개발 제안서를 생성합니다.",
    "success.next2.title": "전문가 검토", "success.next2.desc": "SAP 컨설턴트가 제안서를 검토하고 전문적인 인사이트를 추가합니다.",
    "success.next3.title": "제안서 발송", "success.next3.desc": "무료 개발 제안서가 24시간 이내에 이메일로 발송됩니다.",
    "success.newRequest": "새 요청 만들기", "success.dashboard": "대시보드로",
  }
};

let currentLang = localStorage.getItem('lang') || 'ko';

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem('lang', lang);

  // .nav-ko/.nav-en, .brand-ko/.brand-en 직접 토글
  const isKo = (lang === 'ko');
  document.querySelectorAll('.nav-ko, .brand-ko').forEach(el => el.style.display = isKo ? '' : 'none');
  document.querySelectorAll('.nav-en, .brand-en').forEach(el => el.style.display = isKo ? 'none' : '');

  applyTranslations();

  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('btn-' + lang);
  if (btn) btn.classList.add('active');
  document.documentElement.setAttribute('data-lang', lang);
}

function t(key) {
  return (TRANSLATIONS[currentLang] && TRANSLATIONS[currentLang][key]) ||
         (TRANSLATIONS['en'] && TRANSLATIONS['en'][key]) || null;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const val = t(key);
    if (val !== null) el.innerHTML = val;
    // 번역 없으면 HTML에 작성된 기본값 그대로 유지
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    const val = t(key);
    if (val !== null) el.placeholder = val;
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setLang(currentLang);
});
