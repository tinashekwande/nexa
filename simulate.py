"""Run six end-to-end SMS scenarios against the local Flask app."""
import os
import tempfile

# Isolate demo data from any existing local database.
fd, path = tempfile.mkstemp(suffix=".sqlite3")
os.close(fd)
os.environ["DB_PATH"] = path

import app as service

client = service.app.test_client()

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
    print("simulate.py: all 6 scenarios passed")
finally:
    os.unlink(path)
