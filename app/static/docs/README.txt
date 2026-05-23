이용 가이드 PDF 배치 위치
========================

기본 URL: /static/docs/user-guide.pdf

운영 시 이 폴더에 user-guide.pdf 파일을 넣거나,
관리자가 홈 화면 편집 패널에서 user_guide_pdf_url 을 외부 URL로 바꿀 수 있습니다.

본문 초안(마크다운): docs/user_guide/user_guide_ko.md (영문: user_guide_en.md)
법무 초안: docs/legal/

PDF 수정 후 다시 만들려면 (Windows 에 맑은 고딕이 있는 경우):

  pip install fpdf2
  python scripts/build_user_guide_pdf.py

제안서 PDF 한글 폰트 (운영 Docker 빌드 시 자동 설치):

  python scripts/fetch_proposal_pdf_font.py

로컬에서도 위 스크립트를 실행하면 app/static/fonts/ 에 NotoSansCJKkr-Regular.otf 가 받아집니다.
