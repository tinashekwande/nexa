import hashlib
import json
import os
import re
import threading
import base64
import urllib.parse
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Flask, jsonify, request, send_from_directory

from content import LANGUAGES, TEXT

# Load KEY=value lines from .env (gitignored) so secrets never go in code.
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).with_name("ubuntu_line.db")))
MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LANG_MENU = "1 English 2 isiXhosa 3 isiZulu 4 Afrikaans"
LANG_CODES = {"1": "en", "2": "xh", "3": "zu", "4": "af"}


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY, lang TEXT, state TEXT DEFAULT 'language');
            CREATE TABLE IF NOT EXISTS msgs(phone TEXT, body TEXT, reply TEXT, route TEXT, tokens INTEGER DEFAULT 0, ts TEXT);
            CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, answer TEXT);
        """)


def clean_sms(text):
    # Keep output in the GSM-7 basic ASCII range and under the requested SMS limit.
    text = str(text or "").encode("ascii", "replace").decode("ascii")
    text = re.sub(r"[^\x20-\x7e\n]", " ", text)
    return text[:306]


def lang_menu():
    return LANG_MENU


def cached_answer(question, lang):
    normal = " ".join(question.lower().split())
    key = hashlib.sha256((lang + "\0" + normal).encode()).hexdigest()
    with db() as conn:
        row = conn.execute("SELECT answer FROM cache WHERE key=?", (key,)).fetchone()
    return key, row["answer"] if row else None


def ask_llm(phone, question, lang):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return TEXT[lang]["unavailable"], 0

    with db() as conn:
        history = conn.execute(
            "SELECT body, reply FROM msgs WHERE phone=? ORDER BY rowid DESC LIMIT 2", (phone,)
        ).fetchall()
    contents = []
    for row in reversed(history):
        contents.extend(({"role": "user", "parts": [{"text": row["body"]}]},
                         {"role": "model", "parts": [{"text": row["reply"]}]}))
    contents.append({"role": "user", "parts": [{"text": question}]})
    payload = json.dumps({
        "systemInstruction": {"parts": [{"text":
            f"SMS assistant, Africa. Reply in {LANGUAGES[lang]}, plain text, max 300 chars. Emergencies 10177."}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 120, "temperature": 0.3},
    }).encode()
    req = urllib.request.Request(GEMINI_URL.format(model=MODEL), data=payload, headers={
        "content-type": "application/json", "x-goog-api-key": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as response:  # Twilio webhooks time out at 15s
            data = json.loads(response.read())
        parts = data["candidates"][0]["content"].get("parts", [])
        answer = "".join(part.get("text", "") for part in parts)
        # totalTokenCount includes prompt, reply and any thinking tokens.
        tokens = int(data.get("usageMetadata", {}).get("totalTokenCount", 0))
        return clean_sms(answer) or TEXT[lang]["unavailable"], tokens
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError):
        app.logger.exception("Gemini request failed")
        return TEXT[lang]["unavailable"], 0


def job_reply(body, lang):
    ad = re.sub(r"^JOB\s*", "", body, flags=re.I)
    flags = []
    if re.search(r"\b(fee|pay|payment|deposit|charge|cost)\b.{0,35}\b(uniform|training|job|work|placement)\b|\b(uniform|training)\b.{0,35}\b(fee|pay|payment|deposit|charge|cost)\b", ad, re.I):
        flags.append("fee")
    if re.search(r"\b(whatsapp|whats\s*app)\b", ad, re.I) and re.search(r"\b(only|exclusively|no calls)\b", ad, re.I):
        flags.append("whatsapp")
    if re.search(r"\b(urgent|immediately|act now|today only|limited time)\b", ad, re.I):
        flags.append("urgent")
    level = "SCAM" if "fee" in flags or "whatsapp" in flags else "CAREFUL" if flags else "OK"
    reasons = ", ".join(TEXT[lang]["flag_" + flag] for flag in flags) or TEXT[lang]["no_flags"]
    return f"{level}: {reasons}. {TEXT[lang]['job_tip']}"


def handle_sms(phone, body):
    phone = str(phone or "unknown")[:64]
    body = clean_sms(body).strip()
    upper = body.upper()
    init_db()
    with db() as conn:
        user = conn.execute("SELECT lang,state FROM users WHERE phone=?", (phone,)).fetchone()
        if user is None:
            conn.execute("INSERT INTO users(phone,lang,state) VALUES(?,NULL,'language')", (phone,))
            lang, state = None, "language"
        else:
            lang, state = user["lang"], user["state"]

    tokens, route = 0, "canned"
    if not lang:
        selected = LANG_CODES.get(body)
        if selected:
            lang, state = selected, "ready"
            with db() as conn:
                conn.execute("UPDATE users SET lang=?,state=? WHERE phone=?", (lang, state, phone))
            reply = TEXT[lang]["welcome"]
        else:
            reply = lang_menu()
    else:
        if state == "stopped" and upper != "START":
            return ""  # opted out: send nothing
        if upper == "START":
            reply = TEXT[lang]["welcome"]
            with db() as conn:
                conn.execute("UPDATE users SET state='ready' WHERE phone=?", (phone,))
        elif upper == "HELP":
            reply = TEXT[lang]["help"]
        elif upper == "STOP":
            reply = TEXT[lang]["stop"]
            with db() as conn:
                conn.execute("UPDATE users SET state='stopped' WHERE phone=?", (phone,))
        elif state == "grant_reason":
            if body in {"1", "2", "3", "4"}:
                reply = TEXT[lang]["grant_" + body]
                with db() as conn:
                    conn.execute("UPDATE users SET state='ready' WHERE phone=?", (phone,))
            else:
                reply = TEXT[lang]["grant_menu"]
        elif upper == "GRANT":
            reply = TEXT[lang]["grant_menu"]
            with db() as conn:
                conn.execute("UPDATE users SET state='grant_reason' WHERE phone=?", (phone,))
        elif upper.startswith("JOB "):
            reply = job_reply(body, lang)
        else:
            key, answer = cached_answer(body, lang)
            if answer is not None:
                reply, route = answer, "cache"
            else:
                reply, tokens = ask_llm(phone, body, lang)
                route = "llm" if tokens else "llm_no_tokens"
                if tokens:
                    with db() as conn:
                        conn.execute("INSERT OR REPLACE INTO cache(key,answer) VALUES(?,?)", (key, reply))

    reply = clean_sms(reply)
    with db() as conn:
        conn.execute("INSERT INTO msgs(phone,body,reply,route,tokens,ts) VALUES(?,?,?,?,?,?)",
                     (phone, body, reply, route, tokens, datetime.now(timezone.utc).isoformat()))
    return reply


@app.get("/")
def home():
    return send_from_directory(Path(__file__).parent, "index.html")


@app.post("/incoming")
def incoming():
    phone = request.form.get("From", "unknown")
    body = request.form.get("Body", "")
    reply = handle_sms(phone, body)
    if not reply:
        return '<?xml version="1.0" encoding="UTF-8"?><Response/>', 200, {"Content-Type": "application/xml"}
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(reply)}</Message></Response>', 200, {"Content-Type": "application/xml"}


@app.post("/sim")
def simulate():
    data = request.get_json(silent=True) or request.form
    phone = data.get("phone", "simulator")
    body = data.get("body", "")
    return jsonify(reply=handle_sms(phone, body))


# --- Real phone number via "SMS Gateway for Android" (sms-gate.app) ---
# An Android phone with a normal SA SIM receives the SMS, posts it here,
# and we send the reply back out through that same phone.
SMSGATE_URL = os.environ.get("SMSGATE_URL", "https://api.sms-gate.app/3rdparty/v1")


def send_via_gateway(phone, text):
    user, pwd = os.environ.get("SMSGATE_USER"), os.environ.get("SMSGATE_PASS")
    if not (user and pwd):
        app.logger.error("SMSGATE_USER/SMSGATE_PASS not set; reply not sent")
        return
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    req = urllib.request.Request(SMSGATE_URL + "/messages", data=json.dumps({
        "textMessage": {"text": text}, "phoneNumbers": [phone],
    }).encode(), headers={"content-type": "application/json", "authorization": "Basic " + auth})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.URLError, TimeoutError):
        app.logger.exception("SMS gateway send failed")


@app.post("/sms-gate")
def sms_gate():
    data = request.get_json(silent=True) or {}
    if data.get("event") != "sms:received":
        return jsonify(ok=True)
    payload = data.get("payload", {})
    phone, body = payload.get("phoneNumber", "unknown"), payload.get("message", "")

    def work():  # reply in the background so the phone's webhook call returns fast
        reply = handle_sms(phone, body)
        if reply:
            send_via_gateway(phone, reply)
    threading.Thread(target=work, daemon=True).start()
    return jsonify(ok=True)


# --- Africa's Talking two-way SMS (sandbox or live shortcode) ---
# Set AT_USERNAME=sandbox to use the free simulator at simulator.africastalking.com.
def send_via_at(phone, text, link_id=None):
    user, key = os.environ.get("AT_USERNAME"), os.environ.get("AT_API_KEY")
    if not (user and key):
        app.logger.error("AT_USERNAME/AT_API_KEY not set; reply not sent")
        return
    host = "api.sandbox.africastalking.com" if user == "sandbox" else "api.africastalking.com"
    fields = {"username": user, "to": phone, "message": text}
    if os.environ.get("AT_SHORTCODE"):
        fields["from"] = os.environ["AT_SHORTCODE"]
    if link_id:
        fields["linkId"] = link_id
    req = urllib.request.Request(f"https://{host}/version1/messaging",
                                 data=urllib.parse.urlencode(fields).encode(),
                                 headers={"apiKey": key, "Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.URLError, TimeoutError):
        app.logger.exception("Africa's Talking send failed")


@app.post("/at-sms")
def at_sms():
    phone, body = request.form.get("from", "unknown"), request.form.get("text", "")
    link_id = request.form.get("linkId")

    def work():
        reply = handle_sms(phone, body)
        if reply:
            send_via_at(phone, reply, link_id)
    threading.Thread(target=work, daemon=True).start()
    return "", 200


def mask(phone):
    return phone if len(phone) < 8 else phone[:5] + "***" + phone[-3:]


@app.get("/log")
def log():
    init_db()
    with db() as conn:
        rows = conn.execute("SELECT phone,body,reply,route,tokens,ts FROM msgs ORDER BY rowid DESC LIMIT 30").fetchall()
        total, zero, count = conn.execute(
            "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(CASE WHEN tokens=0 THEN 1 ELSE 0 END),0), COUNT(*) FROM msgs"
        ).fetchone()
    return jsonify(total_tokens=total, zero_percent=round(100 * zero / count, 1) if count else 0,
                   messages=[{**dict(row), "phone": mask(row["phone"])} for row in rows])


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
