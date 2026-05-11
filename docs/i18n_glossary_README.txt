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
