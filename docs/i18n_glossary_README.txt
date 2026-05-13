i18n glossary (KO / EN)
=======================

File: i18n_glossary.tsv
  - UTF-8, tab-separated (열 구분: 탭). Excel에서 열 때 인코딩 UTF-8로 지정하세요.
  - 열: key | ko | en
  - key는 app/static/js/i18n.js 의 TRANSLATIONS 키와 동일합니다.

갱신 방법 (개발자)
  - 터미널에서 프로젝트 루트로 이동 후:
      python scripts/generate_i18n_glossary.py
  - i18n.js를 수정한 뒤 다시 생성하면 표가 최신으로 덮어써집니다.

번역 수정 후 반영
  - en 열만 수정한 뒤, 해당 key의 문자열을 i18n.js 의 en: { ... } 블록에 반영하거나,
  - 수정한 TSV 전체를 주시면 en 컬럼을 기준으로 i18n.js에 일괄 반영할 수 있습니다.

이 표에 없는 문자열
  - base.html 등에서 nav-ko / nav-en 쌍으로 직접 넣은 문구
  - 구독 플랜 비교표의 기능명 영문: app/subscription_catalog.py 의 METRIC_LABEL_EN
  - SiteSettings·DB·Markdown 본문(관리자 편집)은 이 파일 범위 밖입니다.
-----------------------------

요청 자체는 이해됐고, 핵심 방향(관리 화면 + 저장 반영 + AI 보조)은 타당합니다.
다만 **“사이트 전체 모든 한글을 기계적으로 한 번에 나열”**에는 구조적 한계가 있어, **키 기반(i18n.js + 점진적 키 확장)**으로 가져가는 게 오히려 유지보수에 유리합니다.
원하시면 다음 단계로 MVP 범위를 이렇게 잡는 걸 제안합니다:
Admin 타일 + i18n 키 목록(페이지/영역 그룹) + 영어 편집·저장·오버라이드 병합 + AI 제안 API.
그다음 필요할 때마다 템플릿의 중요 문구를 data-i18n으로 옮겨 목록에 자연스럽게 포함시키기.