"""SMS webhook — POST /sms/send (+82 → SENS, else Twilio)."""

from __future__ import annotations

import logging
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from vendor import deliver_sms, sens_configured, twilio_configured

_log = logging.getLogger("uvicorn.error")
app = FastAPI(title="SAP SMS Webhook", version="1.0.0")


class SmsPayload(BaseModel):
    to: str
    text: str
    type: str = "registration_otp"
    route_hint: str | None = None
    country_hint: str | None = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "sens_configured": sens_configured(),
        "twilio_configured": twilio_configured(),
    }


@app.post("/sms/send")
def sms_send(payload: SmsPayload):
    phone = (payload.to or "").strip()
    text = (payload.text or "").strip()
    if not phone.startswith("+") or len(phone) < 10:
        raise HTTPException(status_code=400, detail="invalid to (E.164 required)")
    if not text:
        raise HTTPException(status_code=400, detail="empty text")

    secret = (os.environ.get("SMS_WEBHOOK_SECRET") or "").strip()
    # Optional: SAP app can send Authorization: Bearer <secret> (see sms_sender)

    try:
        route = deliver_sms(phone, text)
    except RuntimeError as exc:
        _log.exception(
            "sms send failed type=%s to=%s…%s",
            payload.type,
            phone[:4],
            phone[-2:] if len(phone) > 6 else "",
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _log.info("sms sent type=%s route=%s to=…%s", payload.type, route, phone[-4:])
    return {"ok": True, "route": route, "type": payload.type}
