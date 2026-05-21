# 법무·안내 문서 초안 (검토용)

이 폴더의 문서는 **법률 자문을 대체하지 않는** 운영·검토용 초안입니다. 상호·주소·연락처·시행일·보관 기간 등은 실제 사업자 정보에 맞게 수정한 뒤 게시하세요.

## 파일

| 파일 | 용도 |
|------|------|
| `terms_of_service_ko.txt` / `_en.txt` | 이용약관 (한국어 / English) |
| `privacy_policy_ko.txt` / `_en.txt` | 개인정보처리방침 (한국어 / English) |

## 관리자 사이트 설정에 반영

KO 초안(`*_ko.txt`)은 앱 기동 시 `SiteSettings`에 자동 동기화됩니다(`app/site_legal_seed.py`, revision `legal_content_revision`).

배포 번들 갱신(필수 — Docker는 `app/data/content_drafts/` 만 포함):

```bash
python scripts/sync_content_drafts_bundle.py
```

수동 반영·PDF 재생성:

```bash
python scripts/seed_legal_and_rebuild_user_guide.py
```

본문을 수정한 뒤 DB에 다시 넣으려면 `app/site_legal_seed.py`의 `LEGAL_CONTENT_REVISION` 값을 올리고 위 스크립트를 실행하거나 서버를 재기동하세요.

회원가입 화면은 **단일** `terms_of_service`, `privacy_policy` 필드(plain text)를 사용합니다. 영문은 `*_en.txt` 참고·별도 필드 추가 전까지 KO만 게시됩니다.

경로: **관리자 → 사이트 설정 → 이용약관 / 개인정보처리방침**

## 사용 안내서 (PDF)

- `../user_guide/user_guide_ko.md`, `user_guide_en.md` — 본문 초안
- PDF 재생성: `python scripts/build_user_guide_pdf.py` (한글 폰트 필요, `app/static/docs/README.txt` 참고)
