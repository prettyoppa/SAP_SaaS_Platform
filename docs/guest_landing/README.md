# 비로그인·서비스 소개 Markdown 초안

Admin **사이트 설정**에 붙여 넣을 초안입니다. 파일 내용을 복사해 해당 필드에 저장하세요.

## 적용 위치

| 파일 | Admin 필드 | 표시 위치 |
|------|------------|-----------|
| `service_abap_intro_ko.md` | 신규 개발 첫 페이지 소개 | `/services/abap` 상단 |
| `service_abap_intro_en.md` | (EN은 KO 저장 후 자동 번역 또는 수동) | 동일 |
| `service_analysis_intro_ko.md` | 분석·개선 첫 페이지 소개 | `/abap-analysis` 상단 |
| `service_analysis_intro_en.md` | | 동일 |
| `service_integration_intro_ko.md` | 연동 개발 첫 페이지 소개 | `/integration` 상단 |
| `service_integration_intro_en.md` | | 동일 |

**Admin 경로:** `/admin/settings`

- **비로그인 홈 가이드** (5단계·FAQ 등): `app/templates/partials/ia_guest_guide.html` — 채팅으로 수정 요청
- **메뉴별 소개:** 카드 「신규 개발 첫 페이지 소개」등 (KO만 textarea가 보이지만, 상단 KO/EN 전환으로 EN hidden 필드도 편집 가능)

## 코드 기준 메뉴·URL

| 메뉴 | 공개 소개·목록 | 로그인 후 요청 작성 |
|------|----------------|---------------------|
| 신규 개발 | `/services/abap` | `/rfp/new` |
| 분석·개선 | `/abap-analysis` | `/abap-analysis/new` |
| 연동 개발 | `/integration` | `/integration/new` |

## 참고

- Markdown 규칙은 서비스 소개 페이지와 동일 (`##` 제목, `-` 목록, `**굵게**`).
- 수정 후 저장하면 즉시 반영(재배포 불필요).
