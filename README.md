# Ubuntu Line

SMS AI for feature phones, built with Flask, Twilio-compatible SMS webhooks, SQLite, and the Google Gemini API. Canned commands work without an LLM key; free-form questions are cached by language and normalized text.

## Setup

Requires Python 3.10+ and a Gemini API key (free from aistudio.google.com) for AI answers.

```bash
python -m venv .venv
source .venv/bin/activate
pip install Flask
export GEMINI_API_KEY="your-key"
export LLM_MODEL="gemini-3.5-flash-lite"
python app.py
```

Open `http://127.0.0.1:5000` for the phone simulator and live usage log. SQLite data is stored in `ubuntu_line.db` beside `app.py`; set `DB_PATH` to change it. The model defaults to `gemini-3.5-flash-lite` and can be overridden with `LLM_MODEL`.

## Test the six SMS scenarios

```bash
python simulate.py
```

The simulator uses a temporary database and checks first-contact language selection, HELP, the SRD appeal flow, job-ad scam flags, an AI/fallback question, and a repeated cached question with zero tokens.

## Twilio and ngrok

1. Start the Flask server: `python app.py`.
2. In another terminal, expose it: `ngrok http 5000`.
3. In the Twilio phone number's **Messaging** configuration, set **A message comes in** to `https://YOUR-NGROK-DOMAIN/incoming` with method **HTTP POST**.
4. Send an SMS to the Twilio number. The `/incoming` route reads Twilio's `From` and `Body` fields and returns TwiML.

`POST /sim` accepts JSON `{ "phone": "+27...", "body": "..." }` or form fields `phone` and `body`, and returns `{ "reply": "..." }`. `GET /log` returns recent exchanges and token/zero-token totals for the dashboard.
