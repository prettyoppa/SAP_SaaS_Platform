@echo off
title Catchy Lab - SAP Dev Hub Server
color 0A
echo.
echo  ============================================
echo    Catchy Lab - SAP Dev Hub  (Port 8000)
echo  ============================================
echo.
echo  [로컬 접속]  http://127.0.0.1:8000
echo.

cd /d "%~dp0"

:: Cloudflare Tunnel 설치 여부 확인 후 자동 시작
where cloudflared >nul 2>&1
if %errorlevel% == 0 (
    echo  [Cloudflare Tunnel] cloudflared 감지됨. 터널을 시작합니다...
    echo  공개 URL 은 아래 터널 창에서 확인하세요.
    echo.
    start "Cloudflare Tunnel" cmd /k "cloudflared tunnel --url http://localhost:8000"
    timeout /t 3 /nobreak >nul
) else (
    echo  [Cloudflare Tunnel] cloudflared 미설치 - 로컬 전용 모드로 실행합니다.
    echo  외부 공유가 필요하면: winget install Cloudflare.cloudflared
    echo.
)

echo  종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo  ============================================
echo.

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

echo.
echo  서버가 종료되었습니다. 아무 키나 누르면 창이 닫힙니다.
pause > nul
