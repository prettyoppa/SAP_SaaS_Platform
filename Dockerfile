# Railway / Docker: Root Directory를 SAP_SaaS_Platform 으로 두세요.
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# apt-get 생략: Railway/BuildKit에서 bookworm InRelease GPG 오류가 자주 납니다.
# requirements는 대부분 manylinux wheel(psycopg2-binary, cryptography, argon2 등).
# pip에서 C 확장 빌드가 실패하면 베이스를 python:3.12-bookworm 로 바꾸세요(gcc 내장).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts/fetch_proposal_pdf_font.py ./scripts/fetch_proposal_pdf_font.py
RUN python scripts/fetch_proposal_pdf_font.py \
    && test -s app/static/fonts/NotoSansCJKkr-Regular.otf
COPY admins.txt ./admins.txt

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
