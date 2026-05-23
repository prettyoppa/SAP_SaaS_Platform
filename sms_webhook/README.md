# SMS Webhook (Railway)

SAP 메인 앱(`SMS_WEBHOOK_URL`)이 호출하는 전용 서비스입니다.

## Railway 설정

1. 같은 프로젝트에 **새 서비스** 추가 (또는 기존 `sms-webhook` 서비스 재배포)
2. **Root Directory**: `sms_webhook`
3. **Variables** (SENS / Twilio 키는 여기만):
   - `NCP_SENS_ACCESS_KEY`, `NCP_SENS_SECRET_KEY`, `NCP_SENS_SERVICE_ID`, `NCP_SENS_SENDER`
   - (해외) `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`
4. 도메인 생성 후 메인 `web` 서비스에:
   - `SMS_WEBHOOK_URL=https://<이 서비스 도메인>/sms/send`

## 확인

- `GET /health` → `{"ok":true,"sens_configured":true,...}`
- 배포 로그에 `Application failed to respond` 가 없어야 함

## 계약

`POST /sms/send` JSON:

```json
{
  "to": "+821012345678",
  "text": "본문",
  "type": "new_offer",
  "route_hint": "domestic_kr_sens",
  "country_hint": "KR"
}
```
