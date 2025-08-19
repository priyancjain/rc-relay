

from flask import Flask, request, Response
import os, requests, logging, json, time
from dotenv import load_dotenv
from collections import OrderedDict

# Load environment variables from .env file
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
load_dotenv()
# ---- config ----
ZOHO_URL = os.getenv("ZOHO_CRM_FUNCTION_URL") 
VERIFY_TOKEN = os.getenv("RC_VERIFICATION_TOKEN")    # optional shared secret

# ---- simple in-memory de-dup cache (uuid -> expiry) ----
TTL_SECONDS = 300  # keep seen uuids for 5 minutes
_seen = OrderedDict()

def seen_uuid(u: str) -> bool:
    """Return True if we've already processed this uuid recently."""
    if not u:
        return False
    now = time.time()
    # purge expired
    to_delete = []
    for k, exp in _seen.items():
        if exp < now:
            to_delete.append(k)
        else:
            break  # Ordered by insertion; stop at first non-expired
    for k in to_delete:
        _seen.pop(k, None)

    if u in _seen:
        return True
    _seen[u] = now + TTL_SECONDS
    # cap size just in case
    if len(_seen) > 2000:
        _seen.popitem(last=False)
    return False

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

    # 2) Optional shared secret for normal events (SOFT CHECK)
    if VERIFY_TOKEN:
        incoming = request.headers.get("Verification-Token")
        if incoming != VERIFY_TOKEN:
            # Don't 403 — that causes RC to retry the same event many times
            app.logger.warning("Verification-Token mismatch: got=%r expected=%r", incoming, VERIFY_TOKEN)

    # 3) Parse JSON (if any) and drop duplicates by uuid
    try:
        payload = request.get_json(force=False, silent=True) or {}
    except Exception:
        payload = {}

    u = payload.get("uuid")
    if u and seen_uuid(u):
        app.logger.info("Duplicate notification dropped (uuid=%s)", u)
        return Response(status=200)

    # 4) Forward to Zoho (even if payload is empty; RC sometimes sends pings)
    try:
        r = requests.post(
            ZOHO_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=8
        )
        app.logger.info("Forwarded to Zoho: %s %s", r.status_code, r.text[:200])
    except Exception:
        app.logger.exception("Forward error")

    # Always 200 so RC doesn't retry
    return Response(status=200)

@app.get("/health")
def health():
    return {"ok": True}, 200
