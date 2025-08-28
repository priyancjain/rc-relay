from flask import Flask, request, Response, jsonify
import os, requests, logging, json, time
from dotenv import load_dotenv
from collections import OrderedDict

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

ZOHO_URL = os.getenv("ZOHO_CRM_FUNCTION_URL")
VERIFY_TOKEN = os.getenv("RC_VERIFICATION_TOKEN")

TTL_SECONDS = 300
_seen = OrderedDict()

def seen_uuid(u: str) -> bool:
    if not u:
        return False
    now = time.time()
    to_delete = []
    for k, exp in _seen.items():
        if exp < now:
            to_delete.append(k)
        else:
            break
    for k in to_delete:
        _seen.pop(k, None)
    if u in _seen:
        return True
    _seen[u] = now + TTL_SECONDS
    if len(_seen) > 2000:
        _seen.popitem(last=False)
    return False

# --- Health/landing: allow GET/HEAD/OPTIONS so Render/browser don't 405 ---
@app.route("/", methods=["GET", "OPTIONS"])
def root_health():
    if request.method == "OPTIONS":
        resp = app.make_response(("", 204))
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        return resp
    return "OK", 200

# --- Webhook endpoint(s): POST only ---
@app.post("/rc")
def rc_webhook_root():
    return handle_rc_webhook("rc")

@app.post("/rc/<path:path>")
def rc_webhook_any(path):
    return handle_rc_webhook(f"rc/{path}")

def handle_rc_webhook(path):
    # 1) RingCentral validation handshake
    vt = request.headers.get("Validation-Token")
    if vt:
        app.logger.info("RC validation ping on /%s", path)
        # Must echo header back with 200 and (ideally) no body
        return Response(status=200, headers={"Validation-Token": vt})

    # 2) Optional shared secret (soft check to avoid RC retries)
    if VERIFY_TOKEN:
        incoming = request.headers.get("Verification-Token")
        if incoming != VERIFY_TOKEN:
            app.logger.warning("Verification-Token mismatch: got=%r expected=%r", incoming, VERIFY_TOKEN)

    # 3) Parse JSON and drop dupes by uuid (if present)
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    u = payload.get("uuid") or payload.get("eventId")  # some RC events use eventId
    if u and seen_uuid(u):
        app.logger.info("Duplicate notification dropped (id=%s)", u)
        return Response(status=200)

    # 4) Forward to Zoho (best-effort)
    try:
        r = requests.post(
            ZOHO_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10,
        )
        app.logger.info("Forwarded to Zoho: %s %s", r.status_code, r.text[:200])
    except Exception:
        app.logger.exception("Forward error")

    # Always 200 so RC doesn't retry
    return Response(status=200)

@app.get("/health")
def health():
    return jsonify(ok=True), 200
