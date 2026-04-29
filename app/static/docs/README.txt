이용 가이드 PDF 배치 위치
========================

기본 URL: /static/docs/user-guide.pdf

운영 시 이 폴더에 user-guide.pdf 파일을 넣거나,
관리자가 홈 화면 편집 패널에서 user_guide_pdf_url 을 외부 URL로 바꿀 수 있습니다.

현재 저장소의 user-guide.pdf 는 테스트용 안내 문서입니다. 수정 후 다시 만들려면
(Windows 에 맑은 고딕이 있는 경우):

  pip install fpdf2
  python scripts/build_user_guide_pdf.py

한글 폰트가 없으면 app/static/fonts/ 에 NotoSansKR-Regular.ttf 를 두거나 위 스크립트의 폰트 경로를 조정하세요.
