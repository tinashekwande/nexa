"""Run six end-to-end SMS scenarios against the local Flask app."""
import os
import tempfile

# Isolate demo data from any existing local database.
fd, path = tempfile.mkstemp(suffix=".sqlite3")
os.close(fd)
os.environ["DB_PATH"] = path

import app as service

client = service.app.test_client()

# Without an API key, stub the LLM so the cache path is still tested.
if not os.environ.get("GEMINI_API_KEY"):
    service.ask_llm = lambda phone, q, lang: ("Visit your nearest labour centre.", 42)

def send(phone, body):
    response = client.post("/sim", json={"phone": phone, "body": body})
    assert response.status_code == 200, response.data
    return response.get_json()["reply"]

try:
    # 1. First contact shows the language menu; selecting English saves it.
    assert "1 English" in send("+27001", "hello")
    assert "Welcome" in send("+27001", "1")
    # 2. Canned help does not call the LLM.
    assert "Ubuntu Line" in send("+27001", "HELP")
    # 3. SRD appeal flow provides menu and actionable steps.
    assert "SRD decline reason" in send("+27001", "GRANT")
    assert "Appeal" in send("+27001", "1")
    # 4. Job scam rules flag a fee and urgency.
    assert send("+27001", "JOB Pay a fee for training, urgent!").startswith("SCAM:")
    # 5. A plain question uses the LLM only when configured; absent key is a safe fallback.
    first = send("+27001", "How do I find work?")
    assert first
    # 6. Repeating that question is served from cache and uses zero tokens.
    second = send("+27001", "  HOW DO I FIND WORK?  ")
    assert second == first
    with service.db() as conn:
        rows = conn.execute("SELECT route,tokens FROM msgs WHERE body LIKE '%FIND WORK%' OR body LIKE '%find work%' ORDER BY rowid DESC LIMIT 2").fetchall()
    assert len(rows) == 2 and rows[0]["route"] == "cache" and rows[0]["tokens"] == 0
    assert client.get("/log").status_code == 200
    # 7. STOP opts out (no reply), START opts back in.
    send("+27001", "STOP")
    assert send("+27001", "hello") == ""
    assert "Welcome" in send("+27001", "START")
    # 8. SMS-gateway webhook accepts a received SMS.
    sent = []
    service.send_via_gateway = lambda phone, text: sent.append((phone, text))
    r = client.post("/sms-gate", json={"event": "sms:received", "payload": {"phoneNumber": "+27002", "message": "hi"}})
    assert r.status_code == 200
    import time; time.sleep(0.5)
    assert sent and "1 English" in sent[0][1]
    # 9. Africa's Talking inbox callback accepts a received SMS.
    at_sent = []
    service.send_via_at = lambda phone, text, link_id=None: at_sent.append((phone, text))
    r = client.post("/at-sms", data={"from": "+27003", "text": "hi", "to": "12345"})
    assert r.status_code == 200
    time.sleep(0.5)
    assert at_sent and "1 English" in at_sent[0][1]
    print("simulate.py: all 9 scenarios passed")
finally:
    os.unlink(path)
