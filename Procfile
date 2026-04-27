# Railway가 Procfile을 쓸 때는 반드시 sh -c 로 $PORT 를 확장해야 함 (그대로 두면 --port '$PORT' 리터럴 오류)
web: sh -c "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
