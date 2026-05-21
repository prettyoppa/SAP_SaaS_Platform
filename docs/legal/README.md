# 법무 문서 (Markdown)

| 파일 | 용도 |
|------|------|
| `terms_of_service_ko.md` / `_en.md` | 이용약관 |
| `privacy_policy_ko.md` / `_en.md` | 개인정보처리방침 |

## 반영

1. `python scripts/sync_content_drafts_bundle.py` — `app/data/content_drafts/` (Docker 번들)
2. `python scripts/seed_legal_and_rebuild_user_guide.py` — DB + PDF
3. 배포 후 서버 기동 시 자동 동기화(비어 있거나 파일 해시 변경 시)

## 공개 URL

- `/terms` — 이용약관 (Markdown 렌더 + PDF 다운로드)
- `/privacy` — 개인정보처리방침

관리자 사이트 설정에서는 **편집 UI 없음**. 본문은 이 폴더의 `.md`만 수정하세요.
