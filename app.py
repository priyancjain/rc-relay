from flask import Flask, request, Response
import os, requests, logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---- config (use env vars in prod) ----
ZOHO_URL = os.getenv("ZOHO_CRM_FUNCTION_URL") or "https://www.zohoapis.com/crm/v7/functions/XXXXX/actions/execute?auth_type=apikey&zapikey=YOUR_ZAPIKEY"
VERIFY_TOKEN = os.getenv("RC_VERIFICATION_TOKEN") or ""   # optional shared secret

@app.post("/")
def rc_webhook_root():
    return handle_rc_webhook("")

@app.post("/<path:path>")
def rc_webhook_any(path):
    return handle_rc_webhook(path)

def handle_rc_webhook(path):
    # 1) Validation handshake
    vt = request.headers.get("Validation-Token")
    if vt:
        app.logger.info("RC validation ping on /%s", path)
        return Response(status=200, headers={"Validation-Token": vt})

    # 2) Optional shared secret for normal events
    if VERIFY_TOKEN:
        incoming = request.headers.get("Verification-Token")
        if incoming != VERIFY_TOKEN:
            app.logger.warning("Forbidden: bad Verification-Token")
            return Response("Forbidden", status=403)

    # 3) Forward body to Zoho
    body = request.get_data(as_text=True) or "{}"
    try:
        r = requests.post(
            ZOHO_URL,
            headers={"Content-Type": "application/json"},
            data=body,
            timeout=8
        )
        app.logger.info("Forwarded to Zoho: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        app.logger.exception("Forward error")
        # Still return 200 so RC doesn’t retry forever
    return Response(status=200)

@app.get("/health")
def health():
    return {"ok": True}, 200
